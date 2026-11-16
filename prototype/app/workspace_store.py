"""Persistent, single-user local collaboration workspace.

Names and system examples are display labels, not authenticated identities.
Uploads and attachment versions never imply CAD reconstruction or validation.
The existing verified CAD demonstration is copied read-only as one logical part.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
import threading
import urllib.parse
import uuid
import zipfile


ROOT = Path(__file__).resolve().parent.parent
STORE_ROOT = ROOT / "data" / "workspace"
MAX_FILE_BYTES = 20 * 1024 * 1024
LOCK = threading.RLock()
_SEED_ENABLED = True
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_STATUSES = {"draft", "in_review", "ready", "blocked", "done"}
_NAMESPACE = uuid.UUID("8af8d337-d049-451e-a6fb-b22e6971fd52")
_DEMO_PROJECT = "3e021549-36ac-45b6-87d2-2df611ec475b"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(value):
    if not isinstance(value, str) or not _UUID.fullmatch(value) or str(uuid.UUID(value)) != value:
        raise ValueError("올바른 항목 식별자가 필요합니다.")
    return value


def _new_id():
    return str(uuid.uuid4())


def _stable_id(name):
    return str(uuid.uuid5(_NAMESPACE, name))


def _text(value, label, maximum=4000, empty=False):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label}을 확인해 주세요.")
    value = value.strip()
    if not value and not empty:
        raise ValueError(f"{label}을 입력해 주세요.")
    return value


def _object(data, allowed, required=()):
    if type(data) is not dict or not set(required) <= set(data) or not set(data) <= set(allowed):
        raise ValueError("요청 항목을 확인해 주세요.")


def _is_link(path):
    if path.is_symlink():
        return True
    if path.exists():
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    return False


def _path(relative):
    base = Path(STORE_ROOT)
    if _is_link(base):
        raise ValueError("작업 공간 저장 경로를 사용할 수 없습니다.")
    root = base.resolve()
    name = Path(relative)
    if name.is_absolute() or any(p in ("..", "") for p in name.parts):
        raise ValueError("허용되지 않은 파일 경로입니다.")
    current = base
    for part in name.parts:
        current = current / part
        if _is_link(current):
            raise ValueError("연결된 파일 경로는 사용할 수 없습니다.")
    target = current.resolve()
    if not target.is_relative_to(root):
        raise ValueError("작업 공간 밖의 파일은 사용할 수 없습니다.")
    return target


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".workspace-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _empty():
    return {"schema": "cadbridge.workspace.v1", "scope": "local_single_user", "revision": 0,
            "created_at": _now(), "updated_at": _now(), "seeded": False,
            "channels": {}, "messages": {}, "files": {}, "shapes": {}, "pins": {}}


def _commit(state):
    state["revision"] += 1
    state["updated_at"] = _now()
    _atomic_json(_path("index.json"), state)


def _load():
    path = _path("index.json")
    if not path.exists():
        Path(STORE_ROOT).mkdir(parents=True, exist_ok=True)
        state = _empty()
        if _SEED_ENABLED:
            _seed(state)
        _commit(state)
        return state
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("작업 공간 색인이 너무 큽니다.")
    state = json.loads(path.read_text(encoding="utf-8"))
    if (type(state) is not dict or state.get("schema") != "cadbridge.workspace.v1"
            or type(state.get("revision")) is not int):
        raise ValueError("작업 공간 색인이 손상되었습니다.")
    for key in ("channels", "messages", "files", "shapes", "pins"):
        if type(state.get(key)) is not dict:
            raise ValueError("작업 공간 색인을 읽을 수 없습니다.")
        for identifier, item in state[key].items():
            _id(identifier)
            if type(item) is not dict or item.get("id") != identifier:
                raise ValueError("작업 공간 식별자가 일치하지 않습니다.")
    return state


def configure(root_path, seed=False):
    """Select a storage directory, useful for isolated tests and local copies."""
    global STORE_ROOT, _SEED_ENABLED
    with LOCK:
        if _is_link(Path(root_path)):
            raise ValueError("연결된 작업 공간 경로는 사용할 수 없습니다.")
        STORE_ROOT = Path(root_path).resolve()
        _SEED_ENABLED = bool(seed)
        _load()
        return snapshot()


def _get(state, collection, identifier):
    identifier = _id(identifier)
    if identifier not in state[collection]:
        raise ValueError("항목을 찾을 수 없습니다.")
    return state[collection][identifier]


def _filename(filename):
    if isinstance(filename, str) and filename != filename.rstrip(" ."):
        raise ValueError("파일 이름 끝에 점이나 공백을 넣을 수 없습니다.")
    name = _text(filename, "파일 이름", 180)
    if name in (".", "..") or any(c in name for c in '\\/:<>"|?*') or any(ord(c) < 32 for c in name):
        raise ValueError("파일 이름에 경로를 넣을 수 없습니다.")
    stem = name.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", stem):
        raise ValueError("Windows 예약 이름은 파일 이름으로 사용할 수 없습니다.")
    return name


def _file_public(item):
    value = deepcopy(item)
    value.pop("blob", None)
    value["download_url"] = "/api/workspace/file?id=" + value["id"]
    return value


def _pinned(state, kind, identifier):
    return any(p["kind"] == kind and p["target_id"] == identifier for p in state["pins"].values())


def _public(state, kind, item):
    value = _file_public(item) if kind == "file" else deepcopy(item)
    value["pinned"] = _pinned(state, kind, item["id"])
    return value


def snapshot():
    with LOCK:
        state = _load()
        return {"schema": state["schema"], "scope": "local_single_user", "revision": state["revision"],
                "updated_at": state["updated_at"], "seeded": state["seeded"],
                "channels": sorted(deepcopy(list(state["channels"].values())), key=lambda x: x["created_at"]),
                "messages": sorted((_public(state, "message", m) for m in state["messages"].values()), key=lambda x: x["created_at"]),
                "files": sorted((_public(state, "file", f) for f in state["files"].values()), key=lambda x: x["created_at"]),
                "shapes": sorted((_public(state, "shape", s) for s in state["shapes"].values()), key=lambda x: x["created_at"]),
                "pins": deepcopy(list(state["pins"].values())),
                "notice": "이 PC의 단일 사용자 작업 공간입니다. 표시 이름은 인증된 팀원 신원이 아닙니다."}


def create_channel(data):
    _object(data, {"name", "description"}, {"name"})
    name = _text(data["name"], "채널 이름", 60).lstrip("#").strip()
    if not name:
        raise ValueError("채널 이름을 입력해 주세요.")
    description = _text(data.get("description", ""), "채널 설명", 1000, empty=True)
    with LOCK:
        state = _load()
        if any(c["name"].casefold() == name.casefold() for c in state["channels"].values()):
            raise ValueError("같은 이름의 채널이 있습니다.")
        value = {"id": _new_id(), "name": name, "description": description, "created_at": _now(), "updated_at": _now()}
        state["channels"][value["id"]] = value; _commit(state)
        return deepcopy(value)


def _target(state, data, channel_id=None):
    if data is None:
        return None
    _object(data, {"kind", "id", "version_id", "feature"}, {"kind", "id"})
    kind = data["kind"]
    if kind not in ("file", "shape", "message", "channel"):
        raise ValueError("지원하지 않는 연결 대상입니다.")
    item = _get(state, {"file": "files", "shape": "shapes", "message": "messages", "channel": "channels"}[kind], data["id"])
    item_channel = item["id"] if kind == "channel" else item["channel_id"]
    if channel_id is not None and item_channel != channel_id:
        raise ValueError("같은 채널의 대상에만 의견을 연결할 수 있습니다.")
    target = {"kind": kind, "id": item["id"]}
    version = None
    if data.get("version_id") is not None:
        if kind != "shape":
            raise ValueError("부품에만 버전을 지정할 수 있습니다.")
        version_id = _id(data["version_id"])
        version = next((v for v in item["versions"] if v["id"] == version_id), None)
        if version is None:
            raise ValueError("해당 부품의 버전을 찾을 수 없습니다.")
        target["version_id"] = version_id
    if data.get("feature") is not None:
        if kind != "shape":
            raise ValueError("부품에만 특징을 지정할 수 있습니다.")
        if version is None:
            version = next((v for v in item["versions"] if v["id"] == item.get("active_version_id")), None)
        feature = data["feature"]
        if feature not in ("body", "pocket", "holes") or version is None or feature not in {f["id"] for f in version.get("features", [])}:
            raise ValueError("이 버전에서 확인된 특징을 선택해 주세요.")
        target["version_id"] = version["id"]; target["feature"] = feature
    return target


def post_message(data):
    _object(data, {"channel_id", "text", "parent_id", "target"}, {"channel_id", "text"})
    text = _text(data["text"], "메시지", 12000)
    with LOCK:
        state = _load(); channel = _get(state, "channels", data["channel_id"])
        parent = None
        if data.get("parent_id") is not None:
            parent = _get(state, "messages", data["parent_id"])
            if parent["channel_id"] != channel["id"]:
                raise ValueError("다른 채널의 메시지에 답글을 달 수 없습니다.")
            if parent["parent_id"] is not None:
                raise ValueError("스레드의 첫 메시지에 답글을 달아 주세요.")
        raw_target = data.get("target", parent.get("target") if parent else None)
        target = _target(state, raw_target, channel["id"])
        if target and target["kind"] not in ("file", "shape"):
            raise ValueError("메시지 의견의 대상은 파일 또는 부품이어야 합니다.")
        if parent and target != parent.get("target"):
            raise ValueError("스레드의 연결 대상과 같은 대상으로 답글을 달아 주세요.")
        value = {"id": _new_id(), "channel_id": channel["id"], "text": text,
                 "parent_id": parent["id"] if parent else None, "target": target,
                 "author": "나", "is_system_example": False, "created_at": _now()}
        state["messages"][value["id"]] = value; channel["updated_at"] = value["created_at"]; _commit(state)
        return _public(state, "message", value)


def _store_bytes(state, filename, content, channel_id, shape_id=None, version_id=None, identifier=None):
    filename = _filename(filename)
    if not isinstance(content, (bytes, bytearray)) or not 0 < len(content) <= MAX_FILE_BYTES:
        raise ValueError("0바이트보다 크고 20 MB 이하인 파일을 선택해 주세요.")
    explicit_identifier = identifier is not None
    identifier = _id(identifier) if explicit_identifier else _new_id()
    if identifier in state["files"]:
        raise ValueError("이미 등록된 파일 식별자입니다.")
    path = _path("blobs/" + identifier + ".bin"); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if (not explicit_identifier or path.stat().st_size != len(content)
                or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(content).digest()):
            raise ValueError("이미 사용 중이거나 다른 내용의 파일 경로입니다.")
    else:
        with path.open("xb") as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
    media = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    value = {"id": identifier, "name": filename, "channel_id": channel_id, "shape_id": shape_id,
             "version_id": version_id, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
             "media_type": media, "created_at": _now(), "blob": "blobs/" + identifier + ".bin"}
    state["files"][identifier] = value
    return value


def add_file(filename, content, channel_id, shape_id=None):
    with LOCK:
        state = _load(); channel = _get(state, "channels", channel_id)
        shape = _get(state, "shapes", shape_id) if shape_id else None
        if shape and shape["channel_id"] != channel["id"]:
            raise ValueError("부품과 같은 채널에 파일을 올려 주세요.")
        value = _store_bytes(state, filename, content, channel["id"], shape_id)
        if shape:
            shape["file_ids"].append(value["id"]); shape["updated_at"] = _now()
            if filename.lower().endswith(".stl") and not shape["versions"]:
                shape["preview_file_id"] = value["id"]
                shape["representation_status"] = "attachment_preview_only"
        _commit(state)
        return _public(state, "file", value)


def _link_files(state, shape, identifiers):
    if type(identifiers) is not list or len(identifiers) > 100:
        raise ValueError("중복 없는 파일 목록을 지정해 주세요.")
    for identifier in identifiers:
        _id(identifier)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("중복 없는 파일 목록을 지정해 주세요.")
    values = []
    for identifier in identifiers:
        value = _get(state, "files", identifier)
        if value["channel_id"] != shape["channel_id"] or value.get("shape_id") not in (None, shape["id"]):
            raise ValueError("같은 채널의 연결되지 않은 파일을 선택해 주세요.")
        _checked_file(value)
        values.append(value)
    for value in values:
        value["shape_id"] = shape["id"]
        if value["id"] not in shape["file_ids"]:
            shape["file_ids"].append(value["id"])
    return values


def create_shape(data):
    _object(data, {"name", "channel_id", "description", "file_ids", "status"}, {"name", "channel_id"})
    name = _text(data["name"], "부품 이름", 120)
    description = _text(data.get("description", ""), "부품 설명", 4000, empty=True)
    status = data.get("status", "draft")
    if type(status) is not str or status not in _STATUSES:
        raise ValueError("부품 상태를 확인해 주세요.")
    with LOCK:
        state = _load(); channel = _get(state, "channels", data["channel_id"])
        value = {"id": _new_id(), "name": name, "channel_id": channel["id"], "description": description,
                 "status": status, "file_ids": [], "versions": [], "active_version_id": None,
                 "preview_file_id": None, "source_project_id": None, "source_kind": "user_metadata",
                 "representation_status": "metadata_only", "created_at": _now(), "updated_at": _now()}
        files = _link_files(state, value, data.get("file_ids", []))
        previews = [f["id"] for f in files if f["name"].lower().endswith(".stl")]
        if previews:
            value.update(preview_file_id=previews[-1], representation_status="attachment_preview_only")
        state["shapes"][value["id"]] = value; _commit(state)
        return _public(state, "shape", value)


def update_shape(identifier, data):
    _object(data, {"name", "description", "status", "file_ids"})
    with LOCK:
        state = _load(); value = _get(state, "shapes", identifier)
        if "name" in data:
            value["name"] = _text(data["name"], "부품 이름", 120)
        if "description" in data:
            value["description"] = _text(data["description"], "부품 설명", 4000, empty=True)
        if "status" in data:
            if type(data["status"]) is not str or data["status"] not in _STATUSES:
                raise ValueError("부품 상태를 확인해 주세요.")
            value["status"] = data["status"]
        if "file_ids" in data:
            files = _link_files(state, value, data["file_ids"])
            if not value["versions"]:
                previews = [f["id"] for f in files if f["name"].lower().endswith(".stl")]
                if previews:
                    value.update(preview_file_id=previews[-1], representation_status="attachment_preview_only")
        value["updated_at"] = _now(); _commit(state)
        return _public(state, "shape", value)


def add_shape_version(shape_id, data):
    _object(data, {"file_ids", "label", "note"}, {"file_ids"})
    if not data["file_ids"]:
        raise ValueError("새 버전에 포함할 파일을 선택해 주세요.")
    label = _text(data.get("label", "첨부 파일 버전"), "버전 이름", 120)
    note = _text(data.get("note", ""), "버전 설명", 4000, empty=True)
    with LOCK:
        state = _load(); shape = _get(state, "shapes", shape_id)
        files = _link_files(state, shape, data["file_ids"])
        previews = [f["id"] for f in files if f["name"].lower().endswith(".stl")]
        native = [f["id"] for f in files if f["name"].lower().endswith(".fcstd")]
        step = [f["id"] for f in files if f["name"].lower().endswith((".step", ".stp"))]
        value = {"id": _new_id(), "name": f"v{len(shape['versions'])+1:03d}", "label": label, "note": note,
                 "file_ids": [f["id"] for f in files], "preview_file_id": previews[-1] if previews else None,
                 "native_file_id": native[-1] if native else None, "step_file_id": step[-1] if step else None,
                 "plan": None, "features": [], "verification": "unverified_attachment_version",
                 "source_project_id": None, "source_version_id": None, "created_at": _now()}
        shape["versions"].append(value)
        shape.update(active_version_id=value["id"], preview_file_id=value["preview_file_id"],
                     representation_status="attachment_preview_only" if previews else "attachment_metadata_only", updated_at=_now())
        _commit(state)
        return deepcopy(value)


def _checked_file(value):
    identifier = _id(value["id"])
    if (value.get("blob") != "blobs/" + identifier + ".bin"
            or not isinstance(value.get("sha256"), str) or not _HASH.fullmatch(value["sha256"])):
        raise ValueError("파일 저장 정보가 손상되었습니다.")
    path = _path(value["blob"])
    if not path.is_file() or path.stat().st_size != value["size"]:
        raise ValueError("파일 크기가 바뀌었거나 파일을 찾을 수 없습니다.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != value["sha256"]:
        raise ValueError("저장된 파일의 무결성을 확인할 수 없습니다.")
    return path


def file_path(identifier):
    with LOCK:
        return _checked_file(_get(_load(), "files", identifier))


def get_file(identifier):
    with LOCK:
        state = _load(); value = _get(state, "files", identifier)
        _checked_file(value)
        return _public(state, "file", value)


def search(query, channel_id=None):
    query = _text(query, "검색어", 300).casefold()
    with LOCK:
        state = _load()
        if channel_id is not None:
            _get(state, "channels", channel_id)
        result = {}
        for kind, plural, fields in (("message", "messages", ("text",)), ("file", "files", ("name",)),
                                     ("shape", "shapes", ("name", "description", "status"))):
            result[plural] = [_public(state, kind, value) for value in state[plural].values()
                              if (channel_id is None or value["channel_id"] == channel_id)
                              and any(query in value.get(f, "").casefold() for f in fields)]
        return result


def set_pin(data):
    _object(data, {"kind", "id", "pinned"}, {"kind", "id", "pinned"})
    if data["kind"] not in ("message", "file", "shape") or type(data["pinned"]) is not bool:
        raise ValueError("고정할 항목을 확인해 주세요.")
    with LOCK:
        state = _load(); target = _target(state, {"kind": data["kind"], "id": data["id"]})
        key = _stable_id("pin:" + target["kind"] + ":" + target["id"])
        pin = state["pins"].get(key)
        if data["pinned"] and pin is None:
            entity = _get(state, {"message": "messages", "file": "files", "shape": "shapes"}[target["kind"]], target["id"])
            pin = {"id": key, "kind": target["kind"], "target_id": target["id"],
                   "channel_id": entity["channel_id"], "created_at": _now()}
            state["pins"][key] = pin; _commit(state)
        elif not data["pinned"] and pin is not None:
            del state["pins"][key]; _commit(state); pin = None
        return {"pinned": data["pinned"], "pin": deepcopy(pin)}


def context(data):
    with LOCK:
        state = _load(); target = _target(state, data)
        plural = {"channel": "channels", "file": "files", "shape": "shapes", "message": "messages"}[target["kind"]]
        entity = _get(state, plural, target["id"])
        result = {"target": target, "entity": deepcopy(entity) if target["kind"] == "channel" else _public(state, target["kind"], entity),
                  "comments": [], "related_files": [], "shape": None, "version": None, "feature": None}
        shape = entity if target["kind"] == "shape" else state["shapes"].get(entity.get("shape_id"))
        if shape:
            result["shape"] = _public(state, "shape", shape)
            if target["kind"] == "file":
                # Files are immutable and can be reused in several explicit
                # attachment versions. Keep a seeded source-version binding;
                # otherwise choose the most recently registered containing
                # version, never an unrelated active version.
                if entity.get("version_id"):
                    version = next((v for v in shape["versions"] if v["id"] == entity["version_id"]), None)
                    if version is None or entity["id"] not in version["file_ids"]:
                        raise ValueError("파일과 부품 버전의 연결 정보가 일치하지 않습니다.")
                    result["version_selection"] = "file_explicit_source_version"
                else:
                    version = next((v for v in reversed(shape["versions"]) if entity["id"] in v["file_ids"]), None)
                    result["version_selection"] = "latest_version_containing_file" if version else "shape_attachment_without_version"
            else:
                version_id = target.get("version_id") or shape.get("active_version_id")
                version = next((v for v in shape["versions"] if v["id"] == version_id), None)
                result["version_selection"] = "requested_shape_version" if target.get("version_id") else "shape_active_version"
            result["version"] = deepcopy(version)
            if target.get("feature") and version:
                result["feature"] = deepcopy(next(f for f in version["features"] if f["id"] == target["feature"]))
            identifiers = version["file_ids"] if version else shape["file_ids"]
            result["related_files"] = [_public(state, "file", _get(state, "files", i)) for i in identifiers]
        elif target["kind"] == "file":
            result["related_files"] = [_public(state, "file", entity)]
        if target["kind"] in ("file", "shape"):
            for message in state["messages"].values():
                match = message.get("target") or {}
                if match.get("kind") != target["kind"] or match.get("id") != target["id"]:
                    continue
                if target.get("version_id") and match.get("version_id") != target["version_id"]:
                    continue
                if target.get("feature") and match.get("feature") != target["feature"]:
                    continue
                result["comments"].append(_public(state, "message", message))
        elif target["kind"] == "message":
            root = entity.get("parent_id") or entity["id"]
            result["comments"] = [_public(state, "message", m) for m in state["messages"].values()
                                   if m["id"] == root or m.get("parent_id") == root]
        result["comments"].sort(key=lambda m: m["created_at"])
        result["context_url"] = "/workspace?" + urllib.parse.urlencode(target)
        return result


def export_bundle():
    with LOCK:
        state = _load()
        checked = [(value, _checked_file(value)) for value in state["files"].values()]
        output = _path("exports/" + _new_id() + ".zip"); output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".workspace-export-", suffix=".tmp", dir=output.parent)
        os.close(descriptor); temporary = Path(name)
        try:
            manifest = {"schema": "cadbridge.workspace-export.v1", "exported_at": _now(),
                        "scope": "local_single_user", "revision": state["revision"], "files": [],
                        "notice": "System examples are examples. User attachments are not verified CAD. No existing project directory or credentials are included automatically."}
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("workspace-index.json", json.dumps(snapshot(), ensure_ascii=False, indent=2))
                for value, path in checked:
                    member = "attachments/" + value["id"] + "/" + _filename(value["name"])
                    archive.write(path, member)
                    manifest["files"].append({"id": value["id"], "path": member, "size": value["size"], "sha256": value["sha256"]})
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise ValueError("내보낸 묶음의 무결성을 확인할 수 없습니다.")
                for record in manifest["files"]:
                    raw = archive.read(record["path"])
                    if len(raw) != record["size"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
                        raise ValueError("내보낸 파일이 원본과 일치하지 않습니다.")
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()
        return output


def _seed(state):
    """Copy only named verified demo assets, never its source project in bulk."""
    now = _now()
    for name, description in (("프로젝트-공지", "시스템 예제와 프로젝트 맥락"),
                              ("설계-검토", "파일·부품·특징을 연결한 검토 의견"),
                              ("파일-자료", "첨부 자료와 논리 부품 관리")):
        identifier = _stable_id("channel:" + name)
        state["channels"][identifier] = {"id": identifier, "name": name, "description": description,
                                           "created_at": now, "updated_at": now}
    channel_id = _stable_id("channel:설계-검토")
    shape_id = _stable_id("shape:verified-demo-cbp01")
    project_path = ROOT / "data" / "projects" / _DEMO_PROJECT
    project_file = project_path / "project.json"
    validation_file = ROOT / "evidence" / "validation.json"
    if not project_file.is_file() or not validation_file.is_file():
        state["seeded"] = True
        _seed_message(state, _stable_id("channel:프로젝트-공지"), "시스템 예제: 채널·파일·부품을 이 PC에서 연결하는 로컬 작업 공간입니다. 검증 예제 파일이 없어 부품 시드는 생략했습니다.")
        return
    project = json.loads(project_file.read_text(encoding="utf-8"))
    validation = json.loads(validation_file.read_text(encoding="utf-8"))
    if validation.get("status") != "passed" or validation.get("project_id") != _DEMO_PROJECT or project.get("id") != _DEMO_PROJECT:
        raise ValueError("검증 예제의 연결 근거가 일치하지 않습니다.")
    shape = {"id": shape_id, "name": "CB-P01 플레이트", "channel_id": channel_id,
             "description": "검증에 사용한 합성 부품 하나의 실제 v001·v002입니다. 원본 재구성과 편집본을 서로 다른 부품으로 표시하지 않습니다.",
             "status": "in_review", "file_ids": [], "versions": [], "active_version_id": None,
             "preview_file_id": None, "source_project_id": _DEMO_PROJECT, "source_kind": "synthetic_demo_fixture",
             "representation_status": "verified_demo_native", "created_at": now, "updated_at": now}
    state["shapes"][shape_id] = shape
    for version_name in ("v001", "v002"):
        source = project_path / "versions" / version_name
        session = json.loads((source / "session.json").read_text(encoding="utf-8"))
        version_id = _id(session["version_id"])
        version = {"id": version_id, "name": version_name,
                   "label": "원본 형상 재구성" if version_name == "v001" else "두께·지름·X 간격 편집",
                   "note": "시스템 예제: 같은 합성 부품의 실제 저장 버전입니다.",
                   "plan": deepcopy(session["plan"]), "file_ids": [], "features": [
                       {"id": "body", "name": "판재", "type": "PartDesign::Pad"},
                       {"id": "pocket", "name": "중앙 포켓", "type": "PartDesign::Pocket"},
                       {"id": "holes", "name": "관통 홀 4개", "type": "PartDesign::Pocket ThroughAll"}],
                   "preview_file_id": None, "native_file_id": None, "step_file_id": None,
                   "verification": "verified_demo_native", "source_project_id": _DEMO_PROJECT,
                   "source_version_id": version_id, "source_version_name": version_name, "created_at": now}
        roles = {"model.FCStd": "native_file_id", "result.step": "step_file_id", "preview.stl": "preview_file_id"}
        for filename in ("model.FCStd", "result.step", "preview.stl", "geometry-check.json", "inspect-report.json"):
            raw = (source / filename).read_bytes()
            expected = session.get("assets", {}).get(filename)
            if expected is None or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("검증 예제 파일의 해시가 일치하지 않습니다: " + filename)
            value = _store_bytes(state, "CB-P01_" + version_name + "_" + filename, raw, channel_id,
                                 shape_id, version_id, _stable_id("file:cbp01:" + version_name + ":" + filename))
            version["file_ids"].append(value["id"]); shape["file_ids"].append(value["id"])
            if filename in roles:
                version[roles[filename]] = value["id"]
        shape["versions"].append(version)
    shape["active_version_id"] = shape["versions"][-1]["id"]
    shape["preview_file_id"] = shape["versions"][-1]["preview_file_id"]
    _seed_message(state, _stable_id("channel:프로젝트-공지"), "시스템 예제: 이 작업 공간은 한 PC의 단일 사용자용 시제품입니다. 실제 팀원의 대화나 인증된 다인 협업을 재현한 자료가 아닙니다.")
    message = _seed_message(state, channel_id, "시스템 예제: CB-P01 플레이트 하나의 실제 두 저장 버전을 연결했습니다. v001은 재구성본, v002는 두께 15 mm·홀 Ø10 mm·X 간격 70 mm 편집본입니다.", {"kind": "shape", "id": shape_id})
    _seed_message(state, channel_id, "시스템 예제 답글: 실제 검증 결과와 남은 검토 의견을 이 스레드에 연결할 수 있습니다. 이 문장은 실제 팀 대화가 아닙니다.", {"kind": "shape", "id": shape_id}, message["id"])
    _seed_message(state, channel_id, "시스템 예제: 이 버전의 관통 홀은 동일 지름과 중심 대칭을 유지하도록 연결되어 있습니다. 추가 검토 의견은 해당 버전·특징에 남깁니다.", {"kind": "shape", "id": shape_id, "version_id": shape["active_version_id"], "feature": "holes"})
    pin_id = _stable_id("pin:shape:" + shape_id)
    state["pins"][pin_id] = {"id": pin_id, "kind": "shape", "target_id": shape_id, "channel_id": channel_id, "created_at": now}
    state["seeded"] = True


def _seed_message(state, channel_id, text, target=None, parent_id=None):
    value = {"id": _new_id(), "channel_id": channel_id, "text": text, "target": target,
             "parent_id": parent_id, "author": "시스템 예제", "is_system_example": True, "created_at": _now()}
    state["messages"][value["id"]] = value
    return value

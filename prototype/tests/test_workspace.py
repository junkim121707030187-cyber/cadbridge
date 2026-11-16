"""Workspace persistence and trust-boundary regressions; no CAD execution."""
from __future__ import annotations

import hashlib
import http.client
import importlib
import json
from pathlib import Path, PurePosixPath
import sys
import shutil
import subprocess
import tempfile
import threading
import unittest
import uuid
import zipfile
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
store = importlib.import_module("workspace_store")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workspace-guards-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        store.configure(self.root / "workspace", seed=False)
        self.channel = store.create_channel({"name": "설계 검토", "description": "독립 회귀 작업"})
        self.other_channel = store.create_channel({"name": "다른 채널"})

    def file(self, name="plate.step", data=b"ISO-10303-21; TEST FIXTURE;", channel=None, shape=None):
        return store.add_file(name, data, channel or self.channel["id"], shape_id=shape)

    def shape(self, files=None):
        return store.create_shape({"name": "판재 부품", "channel_id": self.channel["id"],
                                   "file_ids": files or [], "description": "관계 검토용", "status": "draft"})

    def test_channels_messages_and_replies_survive_reload(self):
        top = store.post_message({"channel_id": self.channel["id"], "text": "두께 변경을 검토합니다."})
        reply = store.post_message({"channel_id": self.channel["id"], "text": "포켓 깊이는 유지합니다.", "parent_id": top["id"]})
        before = store.snapshot()
        store.configure(self.root / "workspace", seed=False)
        after = store.snapshot()
        self.assertEqual(before, after)
        messages = {m["id"]: m for m in after["messages"]}
        self.assertEqual(messages[reply["id"]]["parent_id"], top["id"])
        with self.assertRaises(ValueError):
            store.post_message({"channel_id": self.other_channel["id"], "text": "다른 채널의 답글", "parent_id": top["id"]})

    def test_repeated_uploads_are_immutable_and_hash_verified(self):
        first = self.file(data=b"first bytes")
        second = self.file(data=b"second bytes")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(store.file_path(first["id"]).read_bytes(), b"first bytes")
        self.assertEqual(store.file_path(second["id"]).read_bytes(), b"second bytes")
        self.assertEqual(first["sha256"], hashlib.sha256(b"first bytes").hexdigest())
        store.file_path(first["id"]).write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            store.file_path(first["id"])
        with self.assertRaises(ValueError):
            store.export_bundle()

    def test_shape_attachment_versions_are_distinct_and_do_not_claim_cad_validation(self):
        part = self.shape()
        first = self.file(shape=part["id"], data=b"version one")
        version1 = store.add_shape_version(part["id"], {"file_ids": [first["id"]], "label": "처음 받은 모델"})
        second = self.file(shape=part["id"], data=b"version two")
        version2 = store.add_shape_version(part["id"], {"file_ids": [second["id"]], "note": "수정본"})
        snapshot = store.snapshot()
        saved = next(s for s in snapshot["shapes"] if s["id"] == part["id"])
        self.assertEqual([v["name"] for v in saved["versions"]], ["v001", "v002"])
        self.assertNotEqual(saved["versions"][0]["id"], saved["versions"][1]["id"])
        for version in saved["versions"]:
            self.assertEqual(version["verification"], "unverified_attachment_version")
            self.assertIsNone(version["plan"])
            self.assertEqual(version["features"], [])
        self.assertEqual(store.file_path(first["id"]).read_bytes(), b"version one")
        self.assertEqual(store.file_path(second["id"]).read_bytes(), b"version two")

    def test_file_and_shape_targets_keep_discussions_separate(self):
        file = self.file()
        part = self.shape([file["id"]])
        file_target = {"kind": "file", "id": file["id"]}
        shape_target = {"kind": "shape", "id": part["id"]}
        store.post_message({"channel_id": self.channel["id"], "text": "파일 형식 확인", "target": file_target})
        store.post_message({"channel_id": self.channel["id"], "text": "부품 의도 확인", "target": shape_target})
        file_context = json.dumps(store.context(file_target), ensure_ascii=False)
        shape_context = json.dumps(store.context(shape_target), ensure_ascii=False)
        self.assertIn("파일 형식 확인", file_context)
        self.assertNotIn("부품 의도 확인", file_context)
        self.assertIn("부품 의도 확인", shape_context)
        self.assertNotIn("파일 형식 확인", shape_context)
        with self.assertRaises(ValueError):
            store.post_message({"channel_id": self.other_channel["id"], "text": "교차 채널", "target": shape_target})

    def test_unknown_ids_and_unregistered_version_feature_are_rejected(self):
        part = self.shape()
        for bad in ("../index.json", "..\\index.json", str(uuid.uuid4()).upper(), "not-an-id"):
            with self.subTest(id=bad), self.assertRaises(ValueError):
                store.get_file(bad)
        for target in ({"kind": "shape", "id": part["id"], "version_id": str(uuid.uuid4())},
                       {"kind": "shape", "id": part["id"], "feature": "body"},
                       {"kind": "shape", "id": part["id"], "feature": "../secret"}):
            with self.subTest(target=target), self.assertRaises(ValueError):
                store.post_message({"channel_id": self.channel["id"], "text": "잘못된 참조", "target": target})

    def test_unsafe_upload_names_do_not_escape_the_store(self):
        before = store.snapshot()
        for name in ("../outside.step", "..\\outside.step", "/absolute.step", "C:\\absolute.step", "", ".", "..",
                     "CON.step", "AUX.txt", "COM1.step", "file.", "file "):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.file(name=name)
        self.assertEqual(before, store.snapshot())

    def test_search_and_pins_persist_and_respect_channel(self):
        file = self.file(name="홀간격_검토.step")
        part = self.shape([file["id"]])
        message = store.post_message({"channel_id": self.channel["id"], "text": "홀간격 70 mm 검토"})
        store.post_message({"channel_id": self.other_channel["id"], "text": "홀간격 다른 채널"})
        store.set_pin({"kind": "message", "id": message["id"], "pinned": True})
        store.set_pin({"kind": "file", "id": file["id"], "pinned": True})
        results = store.search("홀간격", self.channel["id"])
        self.assertIn(message["id"], {m["id"] for m in results["messages"]})
        self.assertNotIn("다른 채널", json.dumps(results, ensure_ascii=False))
        self.assertIn(file["id"], {f["id"] for f in results["files"]})
        before = store.snapshot()
        store.configure(self.root / "workspace", seed=False)
        self.assertEqual(before["pins"], store.snapshot()["pins"])

    def test_zip_contains_saved_index_and_original_bytes_with_safe_names(self):
        original = b"transferred attachment contents"
        file = self.file(name="팀_전달.step", data=original)
        part = self.shape([file["id"]])
        store.post_message({"channel_id": self.channel["id"], "text": "전달 시 보존할 대화"})
        archive = store.export_bundle()
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            self.assertIn("workspace-index.json", names)
            for name in names:
                self.assertFalse(PurePosixPath(name).is_absolute())
                self.assertNotIn("..", PurePosixPath(name).parts)
                self.assertNotIn("\\", name)
            self.assertTrue(any(bundle.read(n) == original for n in names if not n.endswith("/")))
            exported = json.loads(bundle.read("workspace-index.json"))
            self.assertIn("전달 시 보존할 대화", json.dumps(exported, ensure_ascii=False))

    def test_message_markup_is_preserved_as_plain_data(self):
        text = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
        message = store.post_message({"channel_id": self.channel["id"], "text": text})
        saved = next(m for m in store.snapshot()["messages"] if m["id"] == message["id"])
        self.assertEqual(saved["text"], text)
        # Rendering of this plain string is separately checked in the real UI.

    def test_version_feature_comments_are_bound_to_the_exact_shape_and_version(self):
        part = self.shape()
        first = self.file(shape=part["id"], data=b"first")
        v1 = store.add_shape_version(part["id"], {"file_ids": [first["id"]]})
        second = self.file(shape=part["id"], data=b"second")
        v2 = store.add_shape_version(part["id"], {"file_ids": [second["id"]]})
        # Fixture metadata only: no CAD is generated or claimed by this test.
        index = Path(store.STORE_ROOT) / "index.json"
        data = json.loads(index.read_text(encoding="utf-8"))
        versions = data["shapes"][part["id"]]["versions"]
        versions[0]["features"] = [{"id": name, "name": name} for name in ("body", "pocket", "holes")]
        versions[1]["features"] = [{"id": name, "name": name} for name in ("body", "holes")]
        index.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        target1 = {"kind": "shape", "id": part["id"], "version_id": v1["id"], "feature": "pocket"}
        target2 = {"kind": "shape", "id": part["id"], "version_id": v2["id"], "feature": "body"}
        top = store.post_message({"channel_id": self.channel["id"], "text": "v1 포켓 검토", "target": target1})
        reply = store.post_message({"channel_id": self.channel["id"], "text": "같은 포켓의 답글", "parent_id": top["id"]})
        store.post_message({"channel_id": self.channel["id"], "text": "v2 판재 검토", "target": target2})
        self.assertEqual(reply["target"], target1)
        self.assertEqual(len(store.context(target1)["comments"]), 2)
        self.assertEqual(len(store.context(target2)["comments"]), 1)
        for target in ({**target1, "version_id": v2["id"]},
                       {**target2, "id": self.shape()["id"]}):
            with self.subTest(target=target), self.assertRaises(ValueError):
                store.post_message({"channel_id": self.channel["id"], "text": "잘못된 특징/버전", "target": target})
        with self.assertRaises(ValueError):
            store.post_message({"channel_id": self.channel["id"], "text": "스레드 대상을 바꾸면 안 됨",
                                "parent_id": top["id"], "target": target2})

    def test_old_attachment_context_keeps_its_own_shape_version(self):
        part = self.shape()
        first = self.file(shape=part["id"], data=b"first")
        v1 = store.add_shape_version(part["id"], {"file_ids": [first["id"]]})
        second = self.file(shape=part["id"], data=b"second")
        store.add_shape_version(part["id"], {"file_ids": [second["id"]]})
        context = store.context({"kind": "file", "id": first["id"]})
        self.assertEqual(context["version"]["id"], v1["id"])
        self.assertEqual({f["id"] for f in context["related_files"]}, {first["id"]})

    def test_failed_atomic_commit_keeps_the_previous_index_and_allows_retry(self):
        before = (Path(store.STORE_ROOT) / "index.json").read_bytes()
        with patch.object(store.os, "replace", side_effect=OSError("injected commit failure")):
            with self.assertRaisesRegex(OSError, "injected"):
                store.post_message({"channel_id": self.channel["id"], "text": "저장 실패 사례"})
        self.assertEqual((Path(store.STORE_ROOT) / "index.json").read_bytes(), before)
        saved = store.post_message({"channel_id": self.channel["id"], "text": "재시도 성공"})
        self.assertIn(saved["id"], {m["id"] for m in store.snapshot()["messages"]})

    def test_concurrent_message_commits_do_not_lose_records(self):
        errors = []
        def post(index):
            try:
                store.post_message({"channel_id": self.channel["id"], "text": f"동시 저장 {index}"})
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=post, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(store.snapshot()["messages"]), 12)

    def test_zip_manifest_hashes_match_every_exported_attachment(self):
        first = self.file(data=b"A")
        second = self.file(name="표면.stl", data=b"B")
        with zipfile.ZipFile(store.export_bundle()) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertEqual({f["id"] for f in manifest["files"]}, {first["id"], second["id"]})
            for record in manifest["files"]:
                raw = bundle.read(record["path"])
                self.assertEqual(record["size"], len(raw))
                self.assertEqual(record["sha256"], hashlib.sha256(raw).hexdigest())

    def http_server(self):
        prototype = importlib.import_module("prototype")
        server = prototype.ThreadingHTTPServer(("127.0.0.1", 0), prototype.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown()
            server.server_close()
            thread.join(5)
        self.addCleanup(stop)
        return prototype, server.server_address[1]

    def test_http_rejects_mutations_without_token_and_serves_markup_attachment_as_download(self):
        prototype, port = self.http_server()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(connection.close)
        before = store.snapshot()
        connection.request("POST", "/api/workspace/message", json.dumps({"channel_id": self.channel["id"], "text": "unauthorized"}),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 400)
        self.assertEqual(before, store.snapshot())
        file = self.file(name="notes.html", data=b"<script>throw 'untrusted'</script>")
        connection.request("GET", "/api/workspace/file?id=" + file["id"])
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/octet-stream")
        self.assertIn("attachment", response.getheader("Content-Disposition"))
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.read(), b"<script>throw 'untrusted'</script>")

    def test_http_message_json_and_search_preserve_plain_data(self):
        prototype, port = self.http_server()
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(connection.close)
        text = '<img src=x onerror="window.pwned=true"> 검토'
        payload = json.dumps({"channel_id": self.channel["id"], "text": text}).encode()
        connection.request("POST", "/api/workspace/message", payload,
                           {"Content-Type": "application/json", "X-CADBridge-Token": prototype.TOKEN})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertTrue(response.getheader("Content-Type").startswith("application/json"))
        message = json.loads(response.read())
        self.assertEqual(message["text"], text)
        connection.request("GET", "/api/workspace/search?q=onerror&channel_id=" + self.channel["id"])
        response = connection.getresponse()
        self.assertEqual(json.loads(response.read())["messages"][0]["id"], message["id"])

    def test_real_ui_escape_function_makes_message_markup_inert(self):
        executable = shutil.which("node")
        if executable is None:
            self.skipTest("Node is needed to execute the actual UI escaping function")
        source = (APP / "workspace.html").read_text(encoding="utf-8")
        line = next(line for line in source.splitlines() if "const $=" in line and "esc=" in line)
        script = "const vm=require('vm');const x=JSON.parse(process.argv[1]);process.stdout.write(JSON.stringify(vm.runInNewContext(x.line+';esc(payload)',{payload:x.payload})));"
        payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>&'
        result = subprocess.run([executable, "-e", script, json.dumps({"line": line, "payload": payload})],
                                capture_output=True, text=True, timeout=10, check=True)
        escaped = json.loads(result.stdout)
        self.assertNotIn("<", escaped)
        self.assertNotIn('"', escaped)
        self.assertIn("&lt;img", escaped)
        self.assertIn("esc(m.text||m.body||'')", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

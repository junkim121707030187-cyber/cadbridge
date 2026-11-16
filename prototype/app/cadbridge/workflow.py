"""Local single-user workflow. Plan hashes bind versions, not user identities."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
import uuid

from .model import BridgeError, apply_edit, plan_sha256, validate_plan
from .policy import require_selection

VOLUME_TOLERANCE_MM3 = 1e-5
INFORMATION_GROUPS = {"known_plan_fixture", "step_observed_agent_plan"}
DEFAULT_PLAN = {
    "schema": "cadbridge.plan.v1", "units": "mm",
    "plate": {"width": 100, "height": 80, "thickness": 10},
    "pocket": {"width": 30, "height": 20, "depth": 5},
    "holes": [{"x": x, "y": y, "diameter": 8} for x, y in
              [(-30, -20), (30, -20), (30, 20), (-30, 20)]],
    "hole_relation": "equal_diameter",
}


def read_json(path):
    def reject_constant(value):
        raise ValueError("Nonfinite JSON number")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Nonfinite JSON number")
        return number

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          parse_constant=reject_constant, parse_float=finite_float)
    except (OSError, UnicodeError, ValueError) as exc:
        raise BridgeError("invalid_json", f"Cannot read JSON: {Path(path).name}") from exc


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provenance_sha256(provenance):
    return hashlib.sha256(json.dumps(provenance, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validate_provenance(value, source_sha256):
    """Validate declared session-agent evidence, without treating hashes as identity."""
    if value is None:
        return None
    fields = {"input_information_group", "source_step_sha256", "observation_sha256",
              "request_sha256", "response_sha256", "agent", "evidence", "assumptions",
              "user_constraints", "session_agent_calls", "external_llm_calls"}
    if not isinstance(value, dict) or set(value) != fields:
        raise BridgeError("invalid_provenance", "Agent provenance fields are missing or unsupported")
    if value["input_information_group"] != "step_observed_agent_plan":
        raise BridgeError("invalid_provenance", "Unsupported agent information group")
    for field in ("source_step_sha256", "observation_sha256", "request_sha256", "response_sha256"):
        if not isinstance(value[field], str) or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None:
            raise BridgeError("invalid_provenance", "Invalid evidence SHA256: " + field)
    if value["source_step_sha256"] != source_sha256:
        raise BridgeError("provenance_source_mismatch", "Agent evidence belongs to a different STEP input")
    agent = value["agent"]
    if (not isinstance(agent, dict) or set(agent) != {"name", "model"}
            or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in agent.values())):
        raise BridgeError("invalid_provenance", "Agent name and model must be explicitly recorded")
    for field in ("evidence", "assumptions", "user_constraints"):
        lines = value[field]
        if (not isinstance(lines, list) or len(lines) > 100
                or any(not isinstance(v, str) or not v.strip() or len(v) > 4000 for v in lines)):
            raise BridgeError("invalid_provenance", "Invalid provenance statements: " + field)
    if not value["evidence"]:
        raise BridgeError("invalid_provenance", "Observed evidence is required for an agent plan")
    if (type(value["session_agent_calls"]) is not int or not 0 <= value["session_agent_calls"] <= 100
            or type(value["external_llm_calls"]) is not int or value["external_llm_calls"] != 0):
        raise BridgeError("invalid_provenance", "Session agent calls and external API calls must be distinguished")
    return copy.deepcopy(value)


def freecad_executable(explicit=None):
    value = explicit or os.environ.get("CADBRIDGE_FREECADCMD")
    resolved = shutil.which(value) if value else next(
        (shutil.which(name) for name in ("freecadcmd", "FreeCADCmd", "FreeCADCmd.exe")
         if shutil.which(name)), None)
    if not resolved:
        raise BridgeError("freecad_missing", "Set CADBRIDGE_FREECADCMD to the FreeCAD console executable")
    return resolved


def run_worker(request, executable=None):
    command = freecad_executable(executable)
    worker = Path(__file__).with_name("freecad_worker.py").resolve()
    with tempfile.TemporaryDirectory(prefix="cadbridge-worker-") as temporary:
        request = copy.deepcopy(request)
        request["report_path"] = str(Path(temporary) / "report.json")
        request["volume_tolerance_mm3"] = VOLUME_TOLERANCE_MM3
        request_file = Path(temporary) / "request.json"
        write_json(request_file, request)
        environment = os.environ.copy()
        portable_profile = Path(temporary) / "freecad-profile"
        portable_profile.mkdir()
        environment.update(CADBRIDGE_REQUEST=str(request_file), QT_QPA_PLATFORM="offscreen",
                           PYTHONDONTWRITEBYTECODE="1", FREECAD_USER_HOME=str(portable_profile))
        try:
            process = subprocess.run([command, str(worker)], env=environment,
                                     capture_output=True, text=True, errors="replace", timeout=120,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise BridgeError("cad_timeout", "FreeCAD operation exceeded 120 seconds") from exc
        report_file = Path(request["report_path"])
        if not report_file.is_file():
            raise BridgeError("cad_report_missing", "FreeCAD did not produce an operation report: " + (process.stderr or process.stdout)[-1600:])
        report = read_json(report_file)
        if process.returncode or report.get("status") != "ok":
            raise BridgeError(report.get("code", "cad_failed"), report.get("message", "FreeCAD operation failed"))
        return report


def _protected(plan, fields):
    if not isinstance(fields, list) or any(not isinstance(x, str) for x in fields):
        raise BridgeError("invalid_protected_field", "Protected fields must be a list of numeric plan paths")
    allowed = {f"plate.{key}" for key in plan["plate"]}
    if plan["pocket"]:
        allowed.update(f"pocket.{key}" for key in plan["pocket"])
    allowed.update(f"holes.{i}.{key}" for i, hole in enumerate(plan["holes"]) for key in hole)
    if any(x not in allowed for x in fields):
        raise BridgeError("invalid_protected_field", "Unknown protected field")
    return sorted(set(fields))


def _portable(value, stage):
    if isinstance(value, dict):
        return {k: _portable(v, stage) for k, v in value.items()}
    if isinstance(value, list):
        return [_portable(v, stage) for v in value]
    if isinstance(value, str):
        return value.replace(str(stage), ".")
    return value


def _publish(stage, output):
    """Reserve a new destination exclusively; never replace an existing folder."""
    try:
        output.mkdir()
    except FileExistsError as exc:
        raise BridgeError("output_exists", "Output already exists") from exc
    # Completion marker moves last. A partial transfer cannot be loaded as a session.
    markers = {"session.json", "demo-report.json"}
    children = sorted(stage.iterdir(), key=lambda p: (p.name in markers, p.name))
    for child in children:
        shutil.move(str(child), str(output / child.name))
    stage.rmdir()


def _output_stage(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise BridgeError("output_exists", "Use a new output directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".cadbridge-staging-", dir=output.parent))
    return output, stage


def load_session(project):
    root = Path(project).resolve()
    session = read_json(root / "session.json")
    if not isinstance(session, dict) or session.get("schema") != "cadbridge.session.v1":
        raise BridgeError("invalid_session", "Unsupported session")
    for field in ("project_id", "version_id"):
        if not isinstance(session.get(field), str) or not session[field].strip():
            raise BridgeError("invalid_session", f"Missing or invalid {field}")
    parent = session.get("parent_version_id")
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        raise BridgeError("invalid_session", "Invalid parent version")
    history = session.get("history")
    if not isinstance(history, list) or not history or any(
        not isinstance(event, dict)
        or event.get("operation") not in ("reconstruct", "edit")
        or not isinstance(event.get("changes"), dict)
        or not isinstance(event.get("at"), str)
        or not isinstance(event.get("plan_sha256"), str)
        for event in history
    ):
        raise BridgeError("invalid_session", "Invalid version history")
    plan = validate_plan(session.get("plan"))
    if session.get("plan_sha256") != plan_sha256(plan):
        raise BridgeError("session_conflict", "Stored plan fingerprint changed")
    protected = _protected(plan, session.get("protected_fields"))
    selection = session.get("selection")
    context = session.get("context")
    profile = session.get("validation_profile")
    if (not isinstance(selection, dict) or selection.get("plan_sha256") != session["plan_sha256"]
            or selection.get("mode") != "explicit_plan_version"
            or selection.get("identity_authenticated") is not False):
        raise BridgeError("session_conflict", "Selection metadata disagrees with this local plan version")
    if (not isinstance(context, dict) or context.get("constraints") != protected
            or type(context.get("external_llm_calls")) is not int or context["external_llm_calls"] != 0
            or session.get("protected_fields") != protected):
        raise BridgeError("session_conflict", "Context and protection metadata disagree")
    group = session.get("input_information_group")
    if (not isinstance(group, str) or group not in INFORMATION_GROUPS
            or session.get("product_acceptance") != "not_assessed"
            or not isinstance(profile, dict) or profile.get("kind") != "engineering_exploration"
            or profile.get("volume_tolerance_mm3") != VOLUME_TOLERANCE_MM3
            or history[-1].get("plan_sha256") != session["plan_sha256"]):
        raise BridgeError("invalid_session", "Unsupported scope, validation profile or history link")
    assets = session.get("assets")
    if not isinstance(assets, dict) or not {"model.FCStd", "result.step", "source.step"} <= assets.keys():
        raise BridgeError("invalid_session", "Required assets are missing")
    for name, expected in assets.items():
        if not isinstance(name, str) or Path(name).name != name or name in (".", "..") or "\\" in name:
            raise BridgeError("invalid_session", "Unsafe asset path")
        path = root / name
        if path.is_symlink() or not path.is_file() or file_sha256(path) != expected:
            raise BridgeError("session_conflict", f"Asset changed: {name}")
    provenance = validate_provenance(session.get("provenance"), file_sha256(root / "source.step"))
    if group == "step_observed_agent_plan":
        if (provenance is None or session.get("provenance_sha256") != provenance_sha256(provenance)
                or context.get("provenance") != provenance
                or context.get("session_agent_calls") != provenance["session_agent_calls"]
                or context.get("assumptions") != provenance["assumptions"]
                or context.get("user_constraints") != provenance["user_constraints"]):
            raise BridgeError("session_conflict", "Agent evidence and context disagree")
    elif provenance is not None or session.get("provenance_sha256") is not None or context.get("session_agent_calls", 0) != 0:
        raise BridgeError("session_conflict", "Fixture scope cannot claim session-agent evidence")
    return session


def _build_project(input_step, plan, output, selected_sha, protected_fields,
                   executable=None, previous=None, previous_root=None, changes=None, provenance=None):
    plan = validate_plan(plan)
    require_selection(plan, selected_sha)
    protected_fields = _protected(plan, protected_fields)
    input_step = Path(input_step).resolve()
    if not input_step.is_file() or input_step.suffix.lower() not in (".step", ".stp"):
        raise BridgeError("invalid_step", "Provide a readable STEP file")
    input_hash = file_sha256(input_step)
    provenance = validate_provenance(previous.get("provenance") if previous else provenance, input_hash)
    group = provenance["input_information_group"] if provenance else "known_plan_fixture"
    provenance_hash = provenance_sha256(provenance) if provenance else None
    output, stage = _output_stage(output)
    try:
        shutil.copyfile(input_step, stage / "source.step")
        if file_sha256(stage / "source.step") != input_hash:
            raise BridgeError("input_changed", "Input changed during copy")
        request = {"action": "edit" if previous else "reconstruct", "plan": plan,
                   "input_step": str(stage / "source.step"),
                   "output_native": str(stage / "model.FCStd"),
                   "output_step": str(stage / "result.step"),
                   "output_stl": str(stage / "preview.stl"),
                   "input_information_group": group, "provenance_sha256": provenance_hash}
        if previous:
            request.update(input_native=str(Path(previous_root) / "model.FCStd"),
                           previous_plan=previous["plan"])
        report = run_worker(request, executable)
        native_hash = file_sha256(stage / "model.FCStd")
        inspected = run_worker({"action": "inspect", "plan": plan,
                                "input_native": str(stage / "model.FCStd"),
                                "input_information_group": group, "provenance_sha256": provenance_hash}, executable)
        if (report.get("input_information_group") != group or inspected.get("input_information_group") != group
                or report.get("provenance_sha256") != provenance_hash
                or inspected.get("provenance_sha256") != provenance_hash):
            raise BridgeError("native_provenance_mismatch", "Native evidence scope differs from the selected plan")
        if file_sha256(stage / "model.FCStd") != native_hash:
            raise BridgeError("inspection_changed_native", "Read-only inspection changed the native file")
        if plan_sha256(validate_plan(inspected.get("plan"))) != plan_sha256(plan):
            raise BridgeError("native_plan_mismatch", "Native plan differs after a new process reopened it")
        if file_sha256(input_step) != input_hash:
            raise BridgeError("input_changed", "Input changed during operation")
        if previous:
            # Recheck the source version after CAD execution, before publication.
            current = load_session(previous_root)
            if current != previous:
                raise BridgeError("session_conflict", "Source version changed during editing")
        write_json(stage / "build-report.json", _portable(report, stage))
        write_json(stage / "inspect-report.json", _portable(inspected, stage))
        version = str(uuid.uuid4())
        event = {"operation": request["action"], "plan_sha256": plan_sha256(plan),
                 "changes": changes or {}, "at": datetime.now(timezone.utc).isoformat()}
        session = {"schema": "cadbridge.session.v1", "project_id": previous["project_id"] if previous else str(uuid.uuid4()),
                   "version_id": version, "parent_version_id": previous["version_id"] if previous else None,
                   "plan": plan, "plan_sha256": plan_sha256(plan), "protected_fields": protected_fields,
                   "selection": {"mode": "explicit_plan_version", "plan_sha256": selected_sha,
                                 "identity_authenticated": False},
                   "input_information_group": group, "product_acceptance": "not_assessed",
                   "validation_profile": {"kind": "engineering_exploration", "volume_tolerance_mm3": VOLUME_TOLERANCE_MM3},
                   "source": {"filename": input_step.name, "sha256": input_hash},
                   "history": (previous["history"] if previous else []) + [event],
                   "context": {"origin": "explicit plan and measured STEP geometry", "external_llm_calls": 0,
                               "assumptions": ["Plan intent is supplied, not inferred from STEP"],
                               "constraints": protected_fields, "separate_process_reopen": True},
                   "assets": {p.name: file_sha256(p) for p in stage.iterdir() if p.is_file()}}
        if provenance is not None:
            session.update(provenance=provenance, provenance_sha256=provenance_hash)
            session["context"].update(origin="measured STEP observations and session-agent proposed plan",
                                      provenance=provenance, assumptions=provenance["assumptions"],
                                      user_constraints=provenance["user_constraints"],
                                      session_agent_calls=provenance["session_agent_calls"])
        write_json(stage / "session.json", session)
        _publish(stage, output)
        return session
    except Exception as exc:
        if stage.exists():
            failure = {"status": "error", "code": getattr(exc, "code", "workflow_failed"),
                       "message": str(exc), "product_acceptance": "not_assessed"}
            if not (stage / "failure.json").exists():
                write_json(stage / "failure.json", failure)
        raise


def reconstruct(input_step, plan, output, selected_sha, protected_fields=None, executable=None, provenance=None):
    return _build_project(input_step, plan, output, selected_sha,
                          [] if protected_fields is None else protected_fields, executable, provenance=provenance)


def edit_project(project, changes, output, expected_version, executable=None):
    previous = load_session(project)
    if not expected_version or expected_version != previous.get("version_id"):
        raise BridgeError("stale_version", "Explicit expected version does not match this session")
    updated = apply_edit(previous["plan"], changes, previous["protected_fields"])
    return _build_project(Path(project) / "source.step", updated, output, plan_sha256(updated),
                          previous["protected_fields"], executable, previous=previous,
                          previous_root=Path(project).resolve(), changes=changes)


def demo(output, executable=None):
    plan = validate_plan(DEFAULT_PLAN)
    output, stage = _output_stage(output)
    try:
        run_worker({"action": "fixture", "plan": plan, "output_step": str(stage / "fixture.step")}, executable)
        write_json(stage / "fixture-plan.json", plan)
        initial = reconstruct(stage / "fixture.step", plan, stage / "initial", plan_sha256(plan),
                              ["plate.width", "plate.height"] + [f"holes.{i}.{v}" for i in range(4) for v in ("x", "y")], executable)
        edited = edit_project(stage / "initial", {"plate.thickness": 15, "holes.0.diameter": 10},
                              stage / "edited", initial["version_id"], executable)
        summary = {"status": "ok", "input_information_group": "known_plan_fixture",
                   "product_acceptance": "not_assessed", "external_llm_calls": 0,
                   "initial_version": initial["version_id"], "edited_version": edited["version_id"],
                   "initial_plan_sha256": initial["plan_sha256"], "edited_plan_sha256": edited["plan_sha256"],
                   "thickness_change_mm": [initial["plan"]["plate"]["thickness"], edited["plan"]["plate"]["thickness"]],
                   "edited_hole_diameters_mm": [h["diameter"] for h in edited["plan"]["holes"]],
                   "separate_process_reopen": True}
        write_json(stage / "demo-report.json", summary)
        _publish(stage, output)
        return summary
    except Exception:
        # Retain our unique staging folder and its diagnostic reports.
        raise

"""Application guard regressions. Mocked CAD/observer transport is not CAD evidence."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
prototype = importlib.import_module("prototype")
workflow = importlib.import_module("cadbridge.workflow")
from cadbridge.model import BridgeError


class PrototypeGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cadbridge-app-guards-", dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        self.fail_verify = 0
        self.native_semantics = {
            "parameter_driven": True, "symmetric_four_hole_pattern": True,
            "equal_hole_diameter": True, "through_all_holes": True,
            "pocket_depth_independent_of_thickness": True,
        }
        self.proof = True
        self.worker_requests = []
        for target, replacement in (
            ("PROJECTS", self.projects), ("DATA", self.root), ("JOBS", {}),
        ):
            mock = patch.object(prototype, target, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        mocks = [patch.object(prototype, "legacy", side_effect=self.fake_legacy),
                 patch.object(prototype, "config", return_value={"freecadcmd": "fake-native-no-process"}),
                 patch.object(workflow, "run_worker", side_effect=self.fake_worker)]
        for mock in mocks:
            mock.start()
            self.addCleanup(mock.stop)

    def fake_worker(self, request, executable=None):
        self.worker_requests.append(copy.deepcopy(request))
        for field in ("output_native", "output_step", "output_stl"):
            if field in request:
                Path(request[field]).write_bytes(("MOCK transport: " + field).encode())
        return {"status": "ok", "plan": request["plan"],
                "input_information_group": request["input_information_group"],
                "provenance_sha256": request["provenance_sha256"],
                "native_semantics": copy.deepcopy(self.native_semantics)}

    def fake_legacy(self, *args):
        action = args[0]
        if action == "convert":
            target = Path(args[3])
            prototype.write(target, copy.deepcopy(workflow.DEFAULT_PLAN))
            prototype.write(target.with_name(target.stem + ".bridge.json"), {
                "limits": ["mocked conversion for application-state guard tests"],
                "semantics_required": {"symmetric_2x2_proof": {"explicit_ir_2x2": self.proof}},
            })
        elif action == "verify":
            if self.fail_verify:
                self.fail_verify -= 1
                raise ValueError("injected_geometry_verification_failure")
            prototype.write(Path(args[3]), {"status": "ok", "scope": "mocked verification transport"})
        else:
            raise AssertionError("Unexpected legacy action: " + str(action))
        return "mocked"

    def seed(self):
        identifier = str(uuid.uuid4())
        folder = self.projects / identifier
        folder.mkdir()
        (folder / "source.step").write_bytes(b"MOCK STEP input, not CAD evidence")
        prototype.write(folder / "project.json", {
            "id": identifier, "name": "guard.step", "status": "observed", "origin": "guard_test",
            "created_at": prototype.now(), "updated_at": prototype.now(),
            "constraints": prototype.DEFAULT_CONSTRAINTS,
            "source_sha256": prototype.digest(folder / "source.step"), "versions": [],
            "agent": None, "selected": False, "scope": "guard-test state only",
        })
        prototype.write(folder / "observation-request.json", {"observation": {"sha256": "a" * 64}})
        prototype.write(folder / "agent-request.json", {"model": "gpt-6.1-terra", "guard_test": True})
        prototype.write(folder / "agent-response.schema.json", {
            "type": "object", "additionalProperties": False,
            "required": ["summary", "assumptions", "warnings", "ir"],
            "properties": {"summary": {"type": "string"},
                           "assumptions": {"type": "array", "items": {"type": "string"}},
                           "warnings": {"type": "array", "items": {"type": "string"}},
                           "ir": {"type": "object"}},
        })
        response = {"summary": "Measured STEP hypothesis for guard testing",
                    "assumptions": ["Mock conversion is not CAD evidence"], "warnings": [],
                    "ir": {"source": {"observation_sha256": "a" * 64}}}
        return identifier, folder, response

    def candidate(self, transport="session_agent"):
        identifier, folder, response = self.seed()
        prototype.import_response(identifier, response, transport=transport, agent_name="Guard test agent")
        return identifier, folder

    def test_failed_verify_preserves_diagnostics_and_allows_successful_retry(self):
        identifier, folder = self.candidate()
        original = (folder / "source.step").read_bytes()
        self.fail_verify = 1
        with self.assertRaisesRegex(ValueError, "injected_geometry"):
            prototype.build(identifier)
        self.assertEqual(prototype.state(identifier)["status"], "candidate")
        self.assertEqual(prototype.state(identifier)["versions"], [])
        self.assertFalse((folder / "versions" / "v001").exists())
        retained = list(folder.glob("builds/*/native/session.json"))
        self.assertEqual(len(retained), 1)
        failed_native = retained[0].parent
        ready = prototype.build(identifier)
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["active_version"], "v001")
        self.assertEqual(len(ready["versions"]), 1)
        self.assertTrue((failed_native / "session.json").is_file())
        self.assertEqual((folder / "source.step").read_bytes(), original)
        workflow.load_session(folder / "versions" / "v001")

    def test_missing_explicit_ir_symmetry_is_rejected_before_native_execution(self):
        self.proof = False
        identifier, folder = self.candidate()
        with self.assertRaisesRegex(ValueError, "대칭 관계"):
            prototype.build(identifier)
        self.assertEqual(self.worker_requests, [])
        self.assertFalse((folder / "versions" / "v001").exists())

    def test_native_relation_failure_is_not_published(self):
        identifier, folder = self.candidate()
        self.native_semantics["symmetric_four_hole_pattern"] = False
        with self.assertRaisesRegex(ValueError, "설계 관계"):
            prototype.build(identifier)
        self.assertEqual(prototype.state(identifier)["status"], "candidate")
        self.assertFalse((folder / "versions" / "v001").exists())

    def test_stale_or_missing_display_version_rejected_before_edit(self):
        identifier, folder = self.candidate()
        ready = prototype.build(identifier)
        before = (folder / "versions" / "v001" / "session.json").read_bytes()
        self.worker_requests.clear()
        for expected in (None, "v000", "v999"):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, "버전"):
                prototype.edit(identifier, {"thickness": 15}, expected_version=expected)
        self.assertEqual(self.worker_requests, [])
        self.assertEqual((folder / "versions" / "v001" / "session.json").read_bytes(), before)
        self.assertEqual(prototype.state(identifier)["versions"], ready["versions"])

    def test_imported_response_does_not_claim_verified_model_or_agent_call(self):
        identifier, folder = self.candidate(transport="imported_agent_response")
        agent = prototype.state(identifier)["agent"]
        self.assertFalse(agent["execution_verified"])
        self.assertEqual(agent["model"], "unverified_import")
        prototype.build(identifier)
        session = workflow.load_session(folder / "versions" / "v001")
        self.assertEqual(session["provenance"]["session_agent_calls"], 0)
        self.assertEqual(session["provenance"]["external_llm_calls"], 0)
        self.assertEqual(session["provenance"]["agent"]["model"], "unverified_import")

    def test_running_agent_blocks_manual_import_and_build(self):
        identifier, folder = self.candidate()
        before = (folder / "project.json").read_bytes()
        prototype.JOBS[identifier] = {"id": "run-1", "status": "running"}
        response = {"summary": "other", "assumptions": [], "warnings": [], "ir": {}}
        with self.assertRaisesRegex(ValueError, "진행 중"):
            prototype.import_response(identifier, response)
        with self.assertRaisesRegex(ValueError, "진행 중"):
            prototype.build(identifier)
        self.assertEqual((folder / "project.json").read_bytes(), before)
        self.assertEqual(self.worker_requests, [])

    def test_semantic_evidence_is_hashed_and_tampering_is_rejected(self):
        identifier, folder = self.candidate()
        prototype.build(identifier)
        version = folder / "versions" / "v001"
        session = workflow.load_session(version)
        for name in ("agent-request.json", "observation-request.json", "agent-response.json",
                     "candidate.ir.json", "native-plan.bridge.json", "geometry-check.json"):
            self.assertIn(name, session["assets"])
            target = version / name
            original = target.read_bytes()
            target.write_bytes(original + b"\n")
            try:
                with self.subTest(name=name), self.assertRaises(BridgeError) as error:
                    workflow.load_session(version)
                self.assertEqual(error.exception.code, "session_conflict")
            finally:
                target.write_bytes(original)
        workflow.load_session(version)

    def test_failed_edit_verify_preserves_active_version_then_retry_keeps_provenance(self):
        identifier, folder = self.candidate()
        prototype.build(identifier)
        initial = folder / "versions" / "v001"
        original_session = (initial / "session.json").read_bytes()
        original_provenance = workflow.load_session(initial)["provenance"]
        self.fail_verify = 1
        with self.assertRaisesRegex(ValueError, "injected_geometry"):
            prototype.edit(identifier, {"thickness": 15}, expected_version="v001")
        self.assertEqual(prototype.state(identifier)["active_version"], "v001")
        self.assertEqual(len(prototype.state(identifier)["versions"]), 1)
        self.assertFalse((folder / "versions" / "v002").exists())
        self.assertEqual((initial / "session.json").read_bytes(), original_session)
        ready = prototype.edit(identifier, {"thickness": 15}, expected_version="v001")
        self.assertEqual(ready["active_version"], "v002")
        edited = workflow.load_session(folder / "versions" / "v002")
        self.assertEqual(edited["plan"]["plate"]["thickness"], 15)
        self.assertEqual(edited["provenance"], original_provenance)
        self.assertEqual(edited["context"]["session_agent_calls"], 1)
        self.assertEqual(edited["history"][-1]["operation"], "edit")
        self.assertIn("agent-response.json", edited["assets"])
        self.assertEqual((initial / "session.json").read_bytes(), original_session)

    def test_impossible_thickness_is_rejected_without_native_execution(self):
        identifier, folder = self.candidate()
        prototype.build(identifier)
        original_state = (folder / "project.json").read_bytes()
        self.worker_requests.clear()
        with self.assertRaises(BridgeError):
            prototype.edit(identifier, {"thickness": 4}, expected_version="v001")
        self.assertEqual(self.worker_requests, [])
        self.assertEqual((folder / "project.json").read_bytes(), original_state)
        self.assertFalse((folder / "versions" / "v002").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

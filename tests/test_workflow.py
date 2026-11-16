import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cadbridge.model import BridgeError, plan_sha256, validate_plan
from cadbridge.workflow import DEFAULT_PLAN, _publish, edit_project, file_sha256, load_session, read_json, reconstruct


class WorkflowGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.step = self.root / "input.step"
        self.step.write_text("not a real STEP: guard tests must not invoke CAD")
        self.plan = validate_plan(DEFAULT_PLAN)

    def make_session(self):
        folder = self.root / "project"
        folder.mkdir()
        for name in ("model.FCStd", "result.step", "source.step"):
            (folder / name).write_text("guard-test asset, not CAD evidence")
        data = {"schema": "cadbridge.session.v1", "project_id": "guard-test-project",
                "version_id": "v1", "parent_version_id": None, "plan": self.plan,
                "plan_sha256": plan_sha256(self.plan), "protected_fields": ["plate.width"],
                "history": [{"operation": "reconstruct", "changes": {}, "at": "2026-11-16T00:00:00+00:00",
                             "plan_sha256": plan_sha256(self.plan)}],
                "selection": {"mode": "explicit_plan_version", "plan_sha256": plan_sha256(self.plan),
                              "identity_authenticated": False},
                "context": {"constraints": ["plate.width"], "external_llm_calls": 0},
                "input_information_group": "known_plan_fixture", "product_acceptance": "not_assessed",
                "validation_profile": {"kind": "engineering_exploration", "volume_tolerance_mm3": 1e-5},
                "assets": {p.name: file_sha256(p) for p in folder.iterdir()}}
        (folder / "session.json").write_text(json.dumps(data), encoding="utf-8")
        return folder, data

    @patch("cadbridge.workflow.run_worker")
    def test_unselected_plan_never_creates_output_or_runs_cad(self, worker):
        out = self.root / "new"
        with self.assertRaises(BridgeError):
            reconstruct(self.step, self.plan, out, None)
        self.assertFalse(out.exists())
        worker.assert_not_called()

    def test_nonfinite_json_literals_and_overflow_are_rejected(self):
        path = self.root / "nonfinite.json"
        for number in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(number=number):
                path.write_text('{"nested":{"value":' + number + '}}')
                with self.assertRaises(BridgeError) as error:
                    read_json(path)
                self.assertEqual(error.exception.code, "invalid_json")

    @patch("cadbridge.workflow.run_worker")
    def test_conflicting_selection_and_protection_metadata_rejected(self, worker):
        folder, original = self.make_session()
        variants = [lambda d: d["selection"].update(plan_sha256="stale"),
                    lambda d: d.update(protected_fields=[]),
                    lambda d: d["context"].update(constraints=[])]
        for mutate in variants:
            data = copy.deepcopy(original)
            mutate(data)
            (folder / "session.json").write_text(json.dumps(data))
            with self.assertRaises(BridgeError):
                edit_project(folder, {"plate.width": 110}, self.root / "out", "v1")
        worker.assert_not_called()

    def test_unsupported_success_and_input_scope_cannot_be_replayed(self):
        folder, original = self.make_session()
        for field, value in (("product_acceptance", "passed"), ("input_information_group", "step_only")):
            data = copy.deepcopy(original)
            data[field] = value
            (folder / "session.json").write_text(json.dumps(data))
            with self.assertRaises(BridgeError) as error:
                load_session(folder)
            self.assertEqual(error.exception.code, "invalid_session")

    def test_failed_demo_publication_does_not_expose_success_marker(self):
        import shutil
        stage = self.root / "stage"
        stage.mkdir()
        (stage / "initial").mkdir()
        (stage / "edited").mkdir()
        (stage / "demo-report.json").write_text('{"status":"ok"}')
        real_move = shutil.move

        def fail_during_data_move(source, destination):
            if Path(source).name == "edited":
                raise OSError("simulated publish failure")
            return real_move(source, destination)

        output = self.root / "published"
        with patch("cadbridge.workflow.shutil.move", side_effect=fail_during_data_move):
            with self.assertRaises(OSError):
                _publish(stage, output)
        self.assertFalse((output / "demo-report.json").exists())
        self.assertTrue((stage / "demo-report.json").exists())

    @patch("cadbridge.workflow.run_worker")
    def test_existing_output_is_preserved(self, worker):
        out = self.root / "existing"
        out.mkdir()
        marker = out / "user.txt"
        marker.write_text("keep")
        with self.assertRaises(BridgeError) as error:
            reconstruct(self.step, self.plan, out, plan_sha256(self.plan))
        self.assertEqual(error.exception.code, "output_exists")
        self.assertEqual(marker.read_text(), "keep")
        worker.assert_not_called()

    @patch("cadbridge.workflow.run_worker")
    def test_invalid_protected_path_fails_before_cad(self, worker):
        with self.assertRaises(BridgeError):
            reconstruct(self.step, self.plan, self.root / "out", plan_sha256(self.plan), ["plate.typo"])
        worker.assert_not_called()

    @patch("cadbridge.workflow.run_worker")
    def test_falsy_malformed_protection_is_not_treated_as_empty(self, worker):
        for fields in ({}, False, ""):
            with self.subTest(fields=fields), self.assertRaises(BridgeError):
                reconstruct(self.step, self.plan, self.root / "out", plan_sha256(self.plan), fields)
        worker.assert_not_called()

    def test_tampered_native_asset_is_detected(self):
        folder, _ = self.make_session()
        (folder / "model.FCStd").write_text("changed")
        with self.assertRaises(BridgeError) as error:
            load_session(folder)
        self.assertEqual(error.exception.code, "session_conflict")

    def test_tampered_plan_is_detected(self):
        folder, data = self.make_session()
        data["plan"]["plate"]["thickness"] = 11
        (folder / "session.json").write_text(json.dumps(data))
        with self.assertRaises(BridgeError) as error:
            load_session(folder)
        self.assertEqual(error.exception.code, "session_conflict")

    @patch("cadbridge.workflow.run_worker")
    def test_malformed_session_envelope_rejected_before_cad(self, worker):
        folder, original = self.make_session()
        variants = [("project_id", None), ("project_id", ""), ("version_id", 12),
                    ("parent_version_id", []), ("history", "bad"), ("history", [12]),
                    ("history", [{"operation": "edit"}])]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                data = copy.deepcopy(original)
                data[field] = value
                (folder / "session.json").write_text(json.dumps(data))
                with self.assertRaises(BridgeError) as error:
                    edit_project(folder, {"plate.thickness": 15}, self.root / "out", "v1")
                self.assertEqual(error.exception.code, "invalid_session")
        worker.assert_not_called()

    @patch("cadbridge.workflow.run_worker")
    def test_stale_version_rejected_before_cad(self, worker):
        folder, _ = self.make_session()
        with self.assertRaises(BridgeError) as error:
            edit_project(folder, {"plate.thickness": 15}, self.root / "out", "old")
        self.assertEqual(error.exception.code, "stale_version")
        worker.assert_not_called()

    @patch("cadbridge.workflow.run_worker")
    def test_protected_edit_keeps_source_session_unchanged(self, worker):
        folder, _ = self.make_session()
        before = (folder / "session.json").read_bytes()
        with self.assertRaises(BridgeError):
            edit_project(folder, {"plate.width": 110}, self.root / "out", "v1")
        self.assertEqual((folder / "session.json").read_bytes(), before)
        worker.assert_not_called()

    @patch("cadbridge.workflow.run_worker", side_effect=BridgeError("shape_mismatch", "rejected"))
    def test_failed_build_does_not_publish_success(self, worker):
        before = self.step.read_bytes()
        output = self.root / "out"
        with self.assertRaises(BridgeError):
            reconstruct(self.step, self.plan, output, plan_sha256(self.plan))
        self.assertFalse(output.exists())
        self.assertEqual(self.step.read_bytes(), before)
        diagnostics = list(self.root.glob(".cadbridge-staging-*/failure.json"))
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(json.loads(diagnostics[0].read_text())["code"], "shape_mismatch")


if __name__ == "__main__":
    unittest.main()

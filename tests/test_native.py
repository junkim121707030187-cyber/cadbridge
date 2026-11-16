"""Real FreeCAD subprocess integration tests; no mock native-CAD pass."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


FREECAD = shutil.which("freecadcmd") or shutil.which("FreeCADCmd")
WORKER = Path(__file__).resolve().parents[1] / "cadbridge" / "freecad_worker.py"
PLAN = {
    "schema": "cadbridge.plan.v1", "units": "mm",
    "plate": {"width": 100.0, "height": 80.0, "thickness": 10.0},
    "pocket": {"width": 30.0, "height": 20.0, "depth": 5.0},
    "holes": [{"x": x, "y": y, "diameter": 8.0}
              for x, y in ((-30.0, -20.0), (30.0, -20.0), (30.0, 20.0), (-30.0, 20.0))],
    "hole_relation": "equal_diameter",
}


@unittest.skipUnless(FREECAD, "FreeCAD executable absent: real native integration requires freecadcmd")
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="cadbridge-native-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.sequence = 0
        cls.source = cls.directory / "source.step"
        cls.native = cls.directory / "source.FCStd"
        cls.fixture_report = cls.worker(action="fixture", plan=PLAN, output_step=str(cls.source))
        cls.require_ok(cls.fixture_report)
        cls.reconstruct_report = cls.worker(action="reconstruct", plan=PLAN, input_step=str(cls.source),
                                            output_native=str(cls.native))
        cls.require_ok(cls.reconstruct_report)

    @classmethod
    def worker(cls, **request):
        cls.sequence += 1
        stem = cls.directory / ("request-%03d" % cls.sequence)
        report_path = stem.with_suffix(".report.json")
        request["report_path"] = str(report_path)
        request_path = stem.with_suffix(".json")
        request_path.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
        environment = os.environ.copy()
        environment["CADBRIDGE_REQUEST"] = str(request_path)
        result = subprocess.run([FREECAD, str(WORKER)], env=environment, cwd=cls.directory,
                                capture_output=True, text=True, timeout=90)
        if not report_path.is_file():
            raise AssertionError("Worker produced no report; exit=%s\n%s\n%s" %
                                 (result.returncode, result.stdout, result.stderr))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["_process_returncode"] = result.returncode
        report["_process_output"] = result.stdout + result.stderr
        return report

    @staticmethod
    def require_ok(report):
        if report.get("status") != "ok":
            raise AssertionError(json.dumps(report, indent=2))
        if report["_process_returncode"] != 0:
            raise AssertionError(report["_process_output"])

    def assert_native(self, report, plan):
        self.require_ok(report)
        self.assertTrue(report["reopened"])
        self.assertTrue(report["shape_valid"])
        self.assertEqual(report["solid_count"], 1)
        self.assertEqual(report["input_information_group"], "known_plan_fixture")
        self.assertEqual(report["product_acceptance"], "not_assessed")
        self.assertEqual(report["plan"], plan)
        self.assertLessEqual(report["symmetric_difference_mm3"], 1e-5)
        self.assertTrue(all(report["sketch_fully_constrained"].values()))
        self.assertTrue(all(count > 0 for count in report["sketch_constraints"].values()))
        plate, pocket = plan["plate"], plan["pocket"]
        expected = plate["width"] * plate["height"] * plate["thickness"]
        if pocket:
            expected -= pocket["width"] * pocket["height"] * pocket["depth"]
        expected -= sum(math.pi * (hole["diameter"] / 2) ** 2 * plate["thickness"]
                        for hole in plan["holes"])
        self.assertAlmostEqual(report["volume_mm3"], expected, places=6)

    def test_reconstruction_uses_real_sketcher_and_partdesign_features(self):
        report = self.reconstruct_report
        self.assert_native(report, PLAN)
        features = {feature["name"]: feature["type"] for feature in report["native_features"]}
        self.assertEqual(features, {"Body": "PartDesign::Body", "PlateSketch": "Sketcher::SketchObject",
                                    "Pad": "PartDesign::Pad", "PocketSketch": "Sketcher::SketchObject",
                                    "Pocket": "PartDesign::Pocket", "HolesSketch": "Sketcher::SketchObject",
                                    "Holes": "PartDesign::Pocket"})
        self.assertEqual(report["sketch_constraints"], {"PlateSketch": 12, "PocketSketch": 12,
                                                       "HolesSketch": 12})

    def test_inspect_in_separate_process_observes_persistent_native(self):
        report = self.worker(action="inspect", input_native=str(self.native))
        self.assert_native(report, PLAN)
        self.assertEqual(report["native_parameters"]["Pad"]["length_mm"], 10.0)
        self.assertEqual(report["native_parameters"]["HolesSketch"]["Hole0Diameter"], 8.0)

    def test_edit_changes_existing_dimensions_and_keeps_original(self):
        original_hash = hashlib.sha256(self.native.read_bytes()).hexdigest()
        plan = copy.deepcopy(PLAN)
        plan["plate"]["thickness"] = 15.0
        for hole in plan["holes"]:
            hole["diameter"] = 10.0
        output = self.directory / "edited.FCStd"
        step = self.directory / "edited.step"
        report = self.worker(action="edit", previous_plan=PLAN, plan=plan,
                             input_native=str(self.native), output_native=str(output), output_step=str(step))
        self.assert_native(report, plan)
        self.assertEqual(report["native_features"], self.reconstruct_report["native_features"])
        self.assertEqual(report["sketch_constraints"], self.reconstruct_report["sketch_constraints"])
        self.assertEqual(report["native_parameters"]["Pad"]["length_mm"], 15.0)
        self.assertEqual(report["native_parameters"]["HolesSketch"]["Hole0Diameter"], 10.0)
        self.assertEqual(hashlib.sha256(self.native.read_bytes()).hexdigest(), original_hash)
        self.assertTrue(step.is_file())
        # This is a fresh worker process, after the editing process has exited.
        reopened = self.worker(action="inspect", input_native=str(output), plan=plan)
        self.assert_native(reopened, plan)
        self.assertEqual(reopened["native_parameters"], report["native_parameters"])

    def test_edit_rectangle_pocket_and_hole_positions(self):
        plan = copy.deepcopy(PLAN)
        plan["plate"].update(width=120.0, height=90.0)
        plan["pocket"].update(width=32.0, height=22.0, depth=6.0)
        for hole in plan["holes"]:
            hole["x"] *= 1.1
            hole["y"] *= 1.1
        report = self.worker(action="edit", previous_plan=PLAN, plan=plan,
                             input_native=str(self.native), output_native=str(self.directory / "moved.FCStd"))
        self.assert_native(report, plan)
        self.assertEqual(report["native_parameters"]["PlateSketch"]["Width"], 120.0)
        self.assertEqual(report["native_parameters"]["Pocket"]["length_mm"], 6.0)
        self.assertEqual(report["native_parameters"]["HolesSketch"]["Hole0X"], -33.0)

    def test_mismatching_step_is_rejected_before_outputs_are_written(self):
        plan = copy.deepcopy(PLAN)
        plan["plate"]["thickness"] = 12.0
        output = self.directory / "mismatch.FCStd"
        step = self.directory / "mismatch.step"
        report = self.worker(action="reconstruct", plan=plan, input_step=str(self.source),
                             output_native=str(output), output_step=str(step))
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["code"], "shape_mismatch")
        self.assertFalse(output.exists())
        self.assertFalse(step.exists())

    def test_existing_output_is_preserved(self):
        output = self.directory / "occupied.FCStd"
        output.write_bytes(b"preserve existing output")
        report = self.worker(action="reconstruct", plan=PLAN, input_step=str(self.source),
                             output_native=str(output))
        self.assertEqual(report["code"], "output_exists")
        self.assertEqual(output.read_bytes(), b"preserve existing output")

    def test_report_hard_link_cannot_truncate_native_input(self):
        original_hash = hashlib.sha256(self.native.read_bytes()).hexdigest()
        alias = self.directory / "unsafe-report.json"
        os.link(self.native, alias)
        request = self.directory / "unsafe-request.json"
        request.write_text(json.dumps({"action": "inspect", "input_native": str(self.native),
                                       "report_path": str(alias)}), encoding="utf-8")
        environment = os.environ.copy()
        environment["CADBRIDGE_REQUEST"] = str(request)
        result = subprocess.run([FREECAD, str(WORKER)], env=environment, capture_output=True,
                                text=True, timeout=90, cwd=self.directory)
        self.assertIn('"code": "invalid_request"', result.stdout)
        self.assertEqual(hashlib.sha256(self.native.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(alias.read_bytes(), self.native.read_bytes())

    def test_previous_plan_must_match_native_metadata(self):
        previous = copy.deepcopy(PLAN)
        previous["plate"]["thickness"] = 11.0
        output = self.directory / "stale.FCStd"
        report = self.worker(action="edit", previous_plan=previous, plan=PLAN,
                             input_native=str(self.native), output_native=str(output))
        self.assertEqual(report["code"], "previous_plan_mismatch")
        self.assertFalse(output.exists())

    def test_structural_edit_is_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["holes"] = []
        output = self.directory / "structural.FCStd"
        report = self.worker(action="edit", previous_plan=PLAN, plan=plan,
                             input_native=str(self.native), output_native=str(output))
        self.assertEqual(report["code"], "unsupported_edit")
        self.assertFalse(output.exists())

    def test_corrupt_step_is_rejected(self):
        source = self.directory / "corrupt.step"
        source.write_text("not a STEP file", encoding="utf-8")
        output = self.directory / "corrupt.FCStd"
        report = self.worker(action="reconstruct", plan=PLAN, input_step=str(source), output_native=str(output))
        self.assertEqual(report["code"], "invalid_step")
        self.assertFalse(output.exists())

    def test_multiple_solids_are_rejected(self):
        source = self.directory / "multiple.step"
        helper = self.directory / "make_multiple.py"
        helper.write_text("import Part\nPart.makeCompound([Part.makeBox(1,1,1), "
                          "Part.makeBox(2,2,2)]).exportStep(" + repr(str(source)) + ")\n", encoding="utf-8")
        result = subprocess.run([FREECAD, str(helper)], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = self.directory / "multiple.FCStd"
        report = self.worker(action="reconstruct", plan=PLAN, input_step=str(source), output_native=str(output))
        self.assertEqual(report["code"], "invalid_step")
        self.assertFalse(output.exists())

    def test_no_pocket_and_zero_coordinate_independent_holes(self):
        plan = copy.deepcopy(PLAN)
        plan["pocket"] = None
        plan["holes"] = [{"x": 0.0, "y": 20.0, "diameter": 4.0},
                         {"x": 20.0, "y": 0.0, "diameter": 6.0}]
        plan["hole_relation"] = "independent"
        source = self.directory / "independent.step"
        output = self.directory / "independent.FCStd"
        self.require_ok(self.worker(action="fixture", plan=plan, output_step=str(source)))
        report = self.worker(action="reconstruct", plan=plan, input_step=str(source), output_native=str(output))
        self.assert_native(report, plan)
        self.assertEqual(report["native_parameters"]["HolesSketch"]["Hole1Diameter"], 6.0)
        self.assertNotIn("Pocket", {feature["name"] for feature in report["native_features"]})

    def test_plate_without_pockets_or_holes(self):
        plan = copy.deepcopy(PLAN)
        plan.update(pocket=None, holes=[])
        source = self.directory / "plate.step"
        output = self.directory / "plate.FCStd"
        self.require_ok(self.worker(action="fixture", plan=plan, output_step=str(source)))
        report = self.worker(action="reconstruct", plan=plan, input_step=str(source), output_native=str(output))
        self.assert_native(report, plan)
        self.assertEqual(report["sketch_constraints"], {"PlateSketch": 12})


if __name__ == "__main__":
    unittest.main()

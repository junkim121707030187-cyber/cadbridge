"""Core contract checks; these tests do not establish native CAD success."""

from copy import deepcopy
import hashlib
import json
import math
import unittest

from cadbridge.model import BridgeError, apply_edit, plan_sha256, validate_plan
from cadbridge.policy import require_selection


def plan_fixture():
    return {"schema": "cadbridge.plan.v1", "units": "mm",
            "plate": {"width": 100, "height": 80, "thickness": 10},
            "pocket": {"width": 20, "height": 10, "depth": 3},
            "holes": [{"x": -30, "y": 0, "diameter": 8},
                      {"x": 30, "y": 0, "diameter": 8}],
            "hole_relation": "equal_diameter"}


class PlanValidationTests(unittest.TestCase):
    def assert_rejected(self, plan, code="invalid_plan"):
        before = deepcopy(plan)
        with self.assertRaises(BridgeError) as caught:
            validate_plan(plan)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(plan, before)

    def test_canonical_copy_converts_all_numeric_leaves_and_preserves_hole_order(self):
        plan = plan_fixture()
        canonical = validate_plan(plan)
        self.assertEqual(canonical, plan)
        for feature in [canonical["plate"], canonical["pocket"], *canonical["holes"]]:
            self.assertTrue(all(type(value) is float for value in feature.values()))
        canonical["holes"][0]["x"] = -31
        canonical["plate"]["width"] = 120
        self.assertEqual(plan, plan_fixture())

    def test_optional_pocket_and_empty_holes(self):
        plan = plan_fixture()
        plan["pocket"] = None
        plan["holes"] = []
        self.assertEqual(validate_plan(plan)["holes"], [])

    def test_rejects_malformed_schema_units_relation_and_feature_shapes(self):
        for field, values in {
            "schema": [None, "cadbridge.plan.v2", 1],
            "units": ["inch", "MM", None],
            "hole_relation": ["equal", None, False],
            "plate": [None, [], {}],
            "pocket": [[], {}, False],
            "holes": [None, {}, (), "holes"],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    plan = plan_fixture()
                    plan[field] = value
                    self.assert_rejected(plan)
        for plan in [None, [], "plan", False]:
            with self.subTest(plan=plan):
                self.assert_rejected(plan)

    def test_exact_key_sets_at_all_levels(self):
        for feature in (None, "plate", "pocket", "hole"):
            for operation in ("extra", "missing"):
                with self.subTest(feature=feature, operation=operation):
                    plan = plan_fixture()
                    target = (plan if feature is None else plan["holes"][0]
                              if feature == "hole" else plan[feature])
                    if operation == "extra":
                        target["unsupported"] = 1
                    else:
                        target.pop(next(iter(target)))
                    self.assert_rejected(plan)

    def test_non_numeric_bool_nonfinite_and_unrepresentable_values(self):
        for field in ("plate.width", "pocket.depth", "holes.0.x", "holes.0.diameter"):
            for value in (True, False, None, "8", math.inf, -math.inf, math.nan, 10 ** 400):
                with self.subTest(field=field, value=repr(value)[:30]):
                    plan = plan_fixture()
                    parts = field.split(".")
                    target = plan[parts[0]] if len(parts) == 2 else plan["holes"][0]
                    target[parts[-1]] = value
                    with self.assertRaises(BridgeError) as caught:
                        validate_plan(plan)
                    self.assertEqual(caught.exception.code, "invalid_plan")

    def test_dimensions_and_diameters_must_be_positive(self):
        for feature, key in (("plate", "width"), ("plate", "height"), ("plate", "thickness"),
                             ("pocket", "width"), ("pocket", "height"), ("pocket", "depth"),
                             ("hole", "diameter")):
            for value in (0, -1):
                with self.subTest(feature=feature, key=key, value=value):
                    plan = plan_fixture()
                    target = plan["holes"][0] if feature == "hole" else plan[feature]
                    target[key] = value
                    self.assert_rejected(plan)

    def test_pocket_must_be_strictly_inside_plate(self):
        for key, plate_key in (("width", "width"), ("height", "height"), ("depth", "thickness")):
            for extra in (0, 1):
                with self.subTest(key=key, extra=extra):
                    plan = plan_fixture()
                    plan["pocket"][key] = plan["plate"][plate_key] + extra
                    self.assert_rejected(plan)

    def test_hole_boundary_touch_outside_and_overlap_are_rejected(self):
        for x, y in ((46, 0), (47, 0), (-46, 0), (0, 36), (0, -36), (200, 0)):
            with self.subTest(x=x, y=y):
                plan = plan_fixture()
                plan["pocket"] = None
                plan["holes"] = [{"x": x, "y": y, "diameter": 8}]
                self.assert_rejected(plan)

    def test_hole_pair_touch_overlap_and_diagonal_contact(self):
        for x, y in ((-22, 0), (-23, 0), (-30, 0), (-24, 8)):
            with self.subTest(x=x, y=y):
                plan = plan_fixture()
                plan["pocket"] = None
                diameter = 10 if (x, y) == (-24, 8) else 8
                plan["holes"] = [{"x": -30, "y": 0, "diameter": diameter},
                                  {"x": x, "y": y, "diameter": diameter}]
                self.assert_rejected(plan)

    def test_pocket_face_corner_and_inside_overlap(self):
        for x, y, diameter in ((14, 0, 8), (13, 0, 8), (0, 0, 8), (13, 9, 10)):
            with self.subTest(x=x, y=y):
                plan = plan_fixture()
                plan["holes"] = [{"x": x, "y": y, "diameter": diameter}]
                self.assert_rejected(plan)
        plan = plan_fixture()
        plan["holes"] = [{"x": 13, "y": 9.01, "diameter": 10}]
        validate_plan(plan)

    def test_limit_16_and_equal_diameter_consistency(self):
        plan = plan_fixture()
        plan["pocket"] = None
        plan["holes"] = [{"x": -37.5 + i * 5, "y": 0, "diameter": 2} for i in range(16)]
        self.assertEqual(len(validate_plan(plan)["holes"]), 16)
        plan["holes"].append({"x": 0, "y": 20, "diameter": 2})
        self.assert_rejected(plan)
        plan = plan_fixture()
        plan["holes"][1]["diameter"] = 9
        self.assert_rejected(plan)
        plan["hole_relation"] = "independent"
        validate_plan(plan)

    def test_geometry_predicates_avoid_distance_overflow_and_underflow(self):
        for scale in (1e-200, 1e200):
            with self.subTest(scale=scale):
                plan = plan_fixture()
                plan["pocket"] = None
                plan["plate"] = {"width": 100 * scale, "height": 80 * scale, "thickness": scale}
                plan["holes"] = [{"x": -10 * scale, "y": 0, "diameter": 2 * scale},
                                  {"x": 10 * scale, "y": 0, "diameter": 2 * scale}]
                validate_plan(plan)

    def test_subnormal_hole_and_pocket_contact_is_rejected(self):
        tiny = math.ulp(0.0)
        plan = plan_fixture()
        plan["pocket"] = None
        plan["holes"] = [{"x": 0, "y": 0, "diameter": tiny},
                          {"x": tiny, "y": 0, "diameter": tiny}]
        self.assert_rejected(plan)
        plan["holes"][1]["x"] = 2 * tiny
        validate_plan(plan)
        plan["holes"] = [{"x": tiny, "y": 0, "diameter": tiny}]
        plan["pocket"] = {"width": tiny, "height": tiny, "depth": tiny}
        self.assert_rejected(plan)

    def test_hash_is_canonical_and_order_sensitive_only_for_holes(self):
        plan = plan_fixture()
        canonical = validate_plan(plan)
        expected = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        self.assertEqual(plan_sha256(plan), expected)
        self.assertEqual(plan_sha256(dict(reversed(list(canonical.items())))), expected)
        canonical["holes"].reverse()
        self.assertNotEqual(plan_sha256(canonical), expected)
        plan["holes"][0]["y"] = -0.0
        self.assertEqual(plan_sha256(plan), expected)
        plan["units"] = "m"
        with self.assertRaises(BridgeError):
            plan_sha256(plan)


class PlanEditTests(unittest.TestCase):
    def assert_edit_rejected(self, changes, protected=(), code="invalid_edit", plan=None):
        plan = plan_fixture() if plan is None else plan
        before = deepcopy(plan)
        with self.assertRaises(BridgeError) as caught:
            apply_edit(plan, changes, list(protected))
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(plan, before)

    def test_edit_all_supported_numeric_feature_types_on_a_copy(self):
        plan = plan_fixture()
        changes = {"plate.width": 110, "plate.height": 90, "plate.thickness": 12,
                   "pocket.width": 22, "pocket.height": 12, "pocket.depth": 4,
                   "holes.0.x": -32, "holes.0.y": 1, "holes.1.diameter": 9}
        before = deepcopy(changes)
        edited = apply_edit(plan, changes, [])
        self.assertEqual(edited["plate"], {"width": 110.0, "height": 90.0, "thickness": 12.0})
        self.assertEqual(edited["pocket"], {"width": 22.0, "height": 12.0, "depth": 4.0})
        self.assertEqual(edited["holes"][0], {"x": -32.0, "y": 1.0, "diameter": 9.0})
        self.assertEqual(edited["holes"][1]["diameter"], 9.0)
        self.assertEqual(plan, plan_fixture())
        self.assertEqual(changes, before)

    def test_unknown_paths_structure_changes_and_empty_edits_rejected(self):
        for changes in ({}, [], None, {"schema": "cadbridge.plan.v2"}, {"plate": {}},
                        {"holes": []}, {"hole_relation": "independent"}, {"holes.0.z": 1},
                        {"holes.-1.x": 1}, {"holes.00.x": 1}, {"holes.2.x": 1},
                        {"holes.0.x.extra": 1}, {1: 2}):
            with self.subTest(changes=changes):
                self.assert_edit_rejected(changes)
        plan = plan_fixture()
        plan["pocket"] = None
        self.assert_edit_rejected({"pocket.depth": 2}, plan=plan)

    def test_non_numeric_bool_nonfinite_and_invalid_values_rejected(self):
        for value in (True, False, None, "10", math.nan, math.inf, -math.inf, 10 ** 400, 0, -1):
            with self.subTest(value=repr(value)[:30]):
                self.assert_edit_rejected({"plate.width": value})

    def test_post_edit_geometry_is_validated_and_original_is_preserved(self):
        for changes in ({"holes.0.x": -46}, {"holes.0.x": -14}, {"plate.width": 60},
                        {"pocket.depth": 10}, {"holes.0.diameter": 50}):
            with self.subTest(changes=changes):
                self.assert_edit_rejected(changes, code="invalid_plan")

    def test_protected_fields_reject_direct_and_propagated_changes(self):
        self.assert_edit_rejected({"plate.width": 120}, ["plate.width"], "protected_field")
        self.assert_edit_rejected({"holes.0.diameter": 10}, ["holes.1.diameter"], "protected_field")
        edited = apply_edit(plan_fixture(), {"holes.0.diameter": 8}, ["holes.1.diameter"])
        self.assertEqual(edited, plan_fixture())

    def test_protection_references_are_always_validated(self):
        for path in ("", "plate", "plate.width.extra", "plate.volume", "holes.*.diameter",
                     "holes.01.x", "holes.-1.x", "holes.2.x", None, 3):
            with self.subTest(path=path):
                self.assert_edit_rejected({"plate.width": 110}, [path], "invalid_protected_field")
        for protections in (None, (), "plate.width", {}):
            with self.subTest(protections=protections):
                with self.assertRaises(BridgeError) as caught:
                    apply_edit(plan_fixture(), {"plate.width": 110}, protections)
                self.assertEqual(caught.exception.code, "invalid_protected_field")
        plan = plan_fixture()
        plan["pocket"] = None
        self.assert_edit_rejected({"plate.width": 110}, ["pocket.depth"], "invalid_protected_field", plan)

    def test_contradictory_equal_diameter_edits_rejected_regardless_of_order(self):
        for changes in ({"holes.0.diameter": 8, "holes.1.diameter": 9},
                        {"holes.1.diameter": 9, "holes.0.diameter": 8}):
            self.assert_edit_rejected(changes)
        edited = apply_edit(plan_fixture(), {"holes.0.diameter": 9, "holes.1.diameter": 9}, [])
        self.assertEqual([hole["diameter"] for hole in edited["holes"]], [9.0, 9.0])

    def test_independent_diameters_are_not_propagated(self):
        plan = plan_fixture()
        plan["hole_relation"] = "independent"
        edited = apply_edit(plan, {"holes.0.diameter": 10}, ["holes.1.diameter"])
        self.assertEqual([hole["diameter"] for hole in edited["holes"]], [10.0, 8.0])


class SelectionPolicyTests(unittest.TestCase):
    def test_requires_an_explicit_current_plan_hash(self):
        plan = plan_fixture()
        digest = plan_sha256(plan)
        self.assertEqual(require_selection(plan, digest), digest)
        for selected in (None, "", False, 1, []):
            with self.subTest(selected=selected):
                with self.assertRaises(BridgeError) as caught:
                    require_selection(plan, selected)
                self.assertEqual(caught.exception.code, "selection_required")
        for selected in ("0" * 64, digest.upper(), "not-a-digest", "선택"):
            with self.subTest(selected=selected):
                with self.assertRaises(BridgeError) as caught:
                    require_selection(plan, selected)
                self.assertEqual(caught.exception.code, "stale_selection")

    def test_edit_invalidates_previous_selection(self):
        plan = plan_fixture()
        digest = require_selection(plan, plan_sha256(plan))
        edited = apply_edit(plan, {"plate.width": 110}, [])
        with self.assertRaises(BridgeError) as caught:
            require_selection(edited, digest)
        self.assertEqual(caught.exception.code, "stale_selection")
        self.assertEqual(require_selection(plan, digest), digest)

    def test_invalid_plan_is_never_selected(self):
        plan = plan_fixture()
        digest = plan_sha256(plan)
        plan["plate"]["width"] = math.nan
        with self.assertRaises(BridgeError) as caught:
            require_selection(plan, digest)
        self.assertEqual(caught.exception.code, "invalid_plan")


if __name__ == "__main__":
    unittest.main()

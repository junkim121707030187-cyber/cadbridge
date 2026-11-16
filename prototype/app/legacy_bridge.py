"""Isolated STEP observation and measured-IR to native-plan boundary.

Run this file in the M3 Python environment, never inside FreeCAD. No model is
called here. AI candidates are data and remain unapproved after validation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


APP = Path(__file__).resolve().parent
LEGACY = APP / "legacy" / "implementation"
NUMERICAL_EPSILON_MM = 1e-8
MAX_JSON_BYTES = 2_097_152


def _dependencies():
    if not (LEGACY / "cadbridge" / "cloud" / "observations.py").is_file():
        raise ValueError("legacy_implementation_missing")
    sys.path.insert(0, str(LEGACY))
    from cadbridge.cloud.observations import observe_step, ai_request, validate_observation
    from cadbridge.cloud.ir import validate_ir, to_legacy
    from cadbridge.cloud.providers import strict_json_object
    from cadbridge.cloud.solver import solve
    return observe_step, ai_request, validate_observation, validate_ir, to_legacy, strict_json_object, solve


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_new_json(path, value):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _read_json(path, loader):
    source = Path(path)
    if source.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("candidate_json_size_limit")
    raw = source.read_bytes()
    return loader(raw), hashlib.sha256(raw).hexdigest()


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("non_numeric_native_value")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non_finite_native_value")
    return number


def _zero(value, label):
    if abs(_finite(value)) > NUMERICAL_EPSILON_MM:
        raise ValueError("unsupported_native_offset:" + label)


def _internal_tolerances(shape):
    from OCP.BRep import BRep_Tool
    values = {}
    for label, method in (("faces", "Faces"), ("edges", "Edges"), ("vertices", "Vertices")):
        tolerances = [float(BRep_Tool.Tolerance_s(item.wrapped)) for item in getattr(shape, method)()]
        if not tolerances or any(not math.isfinite(t) or t < 0 for t in tolerances):
            raise ValueError("invalid_internal_tolerance_measurement")
        values[label] = {"count": len(tolerances), "max_mm": max(tolerances)}
    maximum = max(v["max_mm"] for v in values.values())
    return {"maximum_mm": maximum, "by_topology": values,
            "threshold_mm": 0.002, "comparison": "strictly_less_than",
            "passed": maximum < 0.002,
            "scope": "Stored OCCT BRep face/edge/vertex tolerance after STEP transfer, not a certificate of source manufacturing tolerance."}


def _input_tolerance_gate(source):
    from cadbridge import kernel
    measurements = _internal_tolerances(kernel.read_step(source))
    if not measurements["passed"]:
        raise ValueError("input_internal_tolerance_exceeds_policy")
    return measurements


def _hole_relation(ir, holes):
    entities = {e["id"]: e for s in ir["sketches"] for e in s["entities"]}
    features = {f["id"]: f for f in ir["features"]}
    parameter_ids = [entities[features[h["id"]]["entity"]]["parameters"]["diameter"] for h in holes]
    parents = {p: p for p in parameter_ids}

    def find(p):
        while parents[p] != p:
            parents[p] = parents[parents[p]]
            p = parents[p]
        return p

    def union(a, b):
        parents[find(a)] = find(b)

    diameter_ids = set(parameter_ids)
    for constraint in ir["constraints"]:
        refs = constraint["refs"]
        if not diameter_ids.intersection(refs):
            continue
        if constraint["type"] == "dimension":
            continue
        if constraint["type"] == "equal" and set(refs) <= diameter_ids:
            union(*refs)
        elif (constraint["type"] == "offset" and set(refs) <= diameter_ids
              and abs(constraint["value"]) <= NUMERICAL_EPSILON_MM):
            union(*refs)
        else:
            raise ValueError("unsupported_native_diameter_relation:" + constraint["id"])
    groups = [find(p) for p in parameter_ids]
    if len(parameter_ids) > 1 and len(set(groups)) == 1:
        return "equal_diameter"
    if len(groups) != len(set(groups)):
        raise ValueError("unsupported_native_partial_diameter_groups")
    return "independent"


def _validate_native_plan(plan):
    # Load by filename to avoid colliding with M3's cadbridge package.
    native_models = [APP / "native" / "cadbridge" / "model.py",
                     APP / "native" / "model.py", APP / "cadbridge" / "model.py"]
    for model_path in native_models:
        if model_path.is_file():
            spec = importlib.util.spec_from_file_location("cadbridge_native_plan_boundary", model_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.validate_plan(plan)
    raise ValueError("native_plan_validator_missing")


def _semantics(ir, legacy):
    entities = {e["id"]: e for s in ir["sketches"] for e in s["entities"]}
    features = {f["id"]: f for f in ir["features"]}
    native_to_ir = {}

    def bind(feature, mapping):
        f = features[feature["id"]]
        refs = {**entities[f["entity"]]["parameters"], **f["parameters"]}
        for native_field, original_field in mapping.items():
            native_to_ir[native_field] = refs[original_field]

    bind(legacy["base"], {"plate.width": "length", "plate.height": "width", "plate.thickness": "thickness"})
    if legacy["pockets"]:
        bind(legacy["pockets"][0], {"pocket.width": "length", "pocket.height": "width", "pocket.depth": "depth"})
    for i, h in enumerate(legacy["holes"]):
        bind(h, {f"holes.{i}.x": "cx", f"holes.{i}.y": "cy", f"holes.{i}.diameter": "diameter"})
    by_parameter = {}
    for field, parameter in native_to_ir.items():
        by_parameter.setdefault(parameter, []).append(field)
    return {"native_field_to_ir_parameter": native_to_ir,
            "ir_parameter_to_native_fields": by_parameter,
            "constraints": deepcopy(ir["constraints"]),
            "hole_feature_order": [h["id"] for h in legacy["holes"]],
            "coordinate_frame": deepcopy(ir["frame"]),
            "symmetric_2x2_proof": _symmetry_proof(ir, legacy),
            "unmapped_parameters": [p["id"] for p in ir["parameters"] if p["id"] not in by_parameter],
            "native_relational_acceptance": "Must be checked against these actual IR equations; identical measured numbers alone do not establish intended relations."}


def _symmetry_proof(ir, legacy):
    """Recognize explicit equal-row/column plus centered symmetry equations."""
    entities = {e["id"]: e for s in ir["sketches"] for e in s["entities"]}
    features = {f["id"]: f for f in ir["features"]}
    params = {p["id"]: p["id"] for p in ir["parameters"]}

    def find(p):
        while params[p] != p:
            params[p] = params[params[p]]
            p = params[p]
        return p

    for c in ir["constraints"]:
        if c["type"] == "equal":
            a, b = c["refs"]; params[find(a)] = find(b)
        elif c["type"] == "offset" and abs(c["value"]) <= NUMERICAL_EPSILON_MM:
            a, b = c["refs"]; params[find(a)] = find(b)
    base_refs = entities[features[legacy["base"]["id"]]["entity"]]["parameters"]
    proof = {"geometric_2x2": False, "explicit_ir_2x2": False, "axis_proofs": {}}
    holes = legacy["holes"]
    if len(holes) != 4:
        return proof
    xs = sorted({round(h["cx"], 8) for h in holes})
    ys = sorted({round(h["cy"], 8) for h in holes})
    corners = {(round(h["cx"], 8), round(h["cy"], 8)) for h in holes}
    if (len(xs) != 2 or len(ys) != 2 or len(corners) != 4
            or abs(xs[0] + xs[1]) > NUMERICAL_EPSILON_MM
            or abs(ys[0] + ys[1]) > NUMERICAL_EPSILON_MM):
        return proof
    proof["geometric_2x2"] = True
    for axis, coordinates in (("cx", xs), ("cy", ys)):
        groups = []
        for coordinate in coordinates:
            refs = [entities[features[h["id"]]["entity"]]["parameters"][axis]
                    for h in holes if abs(h[axis] - coordinate) <= NUMERICAL_EPSILON_MM]
            groups.append({find(p) for p in refs})
        if any(len(g) != 1 for g in groups):
            proof["axis_proofs"][axis] = {"passed": False, "reason": "missing_explicit_equal_row_or_column"}
            continue
        left, right = next(iter(groups[0])), next(iter(groups[1]))
        center = find(base_refs[axis])
        constraints = [c["id"] for c in ir["constraints"] if c["type"] == "symmetric"
                       and {find(c["refs"][0]), find(c["refs"][1])} == {left, right}
                       and find(c["refs"][2]) == center]
        proof["axis_proofs"][axis] = {"passed": bool(constraints), "symmetric_constraint_ids": constraints}
    proof["explicit_ir_2x2"] = all(proof["axis_proofs"][a]["passed"] for a in ("cx", "cy"))
    return proof


def _native_plan(ir, legacy):
    legacy = deepcopy(legacy)
    normalization = []
    observed = {p["id"]: p["value"] for p in ir["parameters"]}
    entities = {e["id"]: e for s in ir["sketches"] for e in s["entities"]}
    features = {f["id"]: f for f in ir["features"]}
    for feature in [legacy["base"]] + legacy["pockets"] + legacy["holes"]:
        f = features[feature["id"]]
        refs = {**entities[f["entity"]]["parameters"], **f["parameters"]}
        for field, parameter in refs.items():
            value, measured = feature[field], observed[parameter]
            if value != measured and abs(value - measured) <= NUMERICAL_EPSILON_MM:
                normalization.append({"field": feature["id"] + "." + field,
                                      "before": value, "after": measured,
                                      "reason": "SVD numerical roundoff; snap to the same cited observation within 1e-8 mm."})
                feature[field] = measured
    base = legacy["base"]
    for field in ("cx", "cy", "z"):
        _zero(base[field], "base." + field)
        if base[field] != 0:
            normalization.append({"field": "base." + field, "before": base[field], "after": 0.0,
                                  "reason": "Native origin has no offset field; discarded value is explicitly bounded by 1e-8 mm."})
    pockets = legacy["pockets"]
    if len(pockets) > 1:
        raise ValueError("unsupported_native_multiple_pockets")
    pocket = None
    if pockets:
        p = pockets[0]
        _zero(p["cx"], p["id"] + ".cx")
        _zero(p["cy"], p["id"] + ".cy")
        for field in ("cx", "cy"):
            if p[field] != 0:
                normalization.append({"field": p["id"] + "." + field, "before": p[field], "after": 0.0,
                                      "reason": "Native centered pocket has no offset field; discarded value is explicitly bounded by 1e-8 mm."})
        pocket = {"width": p["length"], "height": p["width"], "depth": p["depth"]}
    if len(legacy["holes"]) > 16:
        raise ValueError("unsupported_native_hole_count")
    relation = _hole_relation(ir, legacy["holes"])
    holes = [{"x": h["cx"], "y": h["cy"], "diameter": h["diameter"]} for h in legacy["holes"]]
    # SVD can leave equal diameters a few ulps apart. Their explicit equality
    # permits one shared diameter within this strictly numerical epsilon.
    for group in (pocket,):
        if group:
            for key in group:
                group[key] = _finite(group[key])
    if relation == "equal_diameter" and holes:
        diameter = holes[0]["diameter"]
        if any(abs(h["diameter"] - diameter) > NUMERICAL_EPSILON_MM for h in holes):
            raise ValueError("native_equal_diameter_solution_mismatch")
        for index, h in enumerate(holes):
            if h["diameter"] != diameter:
                normalization.append({"field": f"holes.{index}.diameter", "before": h["diameter"], "after": diameter})
            h["diameter"] = diameter
    plan = {"schema": "cadbridge.plan.v1", "units": "mm",
            "plate": {"width": base["length"], "height": base["width"], "thickness": base["thickness"]},
            "pocket": pocket, "holes": holes, "hole_relation": relation}
    return _validate_native_plan(plan), normalization


def observe(step, output):
    observe_step, ai_request, validate_observation, *_ = _dependencies()
    source = Path(step).resolve(strict=True)
    if Path(output).exists():
        raise ValueError("output_already_exists")
    if source.suffix.lower() not in (".step", ".stp"):
        raise ValueError("unsupported_input_format")
    before = _sha(source)
    _input_tolerance_gate(source)
    observation = observe_step(source)
    validate_observation(observation)
    if observation["source"]["sha256"] != before or _sha(source) != before:
        raise ValueError("source_changed_during_observation")
    request = ai_request(observation)
    _write_new_json(output, request)
    return {"status": "ok", "request_path": str(Path(output).resolve()), "source_sha256": before,
            "observation_sha256": observation["sha256"], "external_api_calls": 0}


def convert(step, candidate_path, output):
    observe_step, _, validate_observation, validate_ir, to_legacy, loader, solve = _dependencies()
    source = Path(step).resolve(strict=True)
    target = Path(output).resolve()
    evidence_target = target.with_name(target.stem + ".bridge.json")
    if target.exists() or evidence_target.exists():
        raise ValueError("output_already_exists")
    if source.suffix.lower() not in (".step", ".stp"):
        raise ValueError("unsupported_input_format")
    before = _sha(source)
    input_tolerances = _input_tolerance_gate(source)
    observation = observe_step(source)
    validate_observation(observation)
    if observation["source"]["sha256"] != before:
        raise ValueError("source_observation_hash_mismatch")
    candidate, candidate_sha256 = _read_json(candidate_path, loader)
    validate_ir(candidate, observation)
    solved = solve(candidate)
    if solved["status"] != "fully_constrained":
        raise ValueError("candidate_solver_" + solved["status"])
    legacy = to_legacy(candidate, solved["values"])
    native, normalization = _native_plan(candidate, legacy)
    if _sha(source) != before:
        raise ValueError("source_changed_during_conversion")
    flattened = [deepcopy(c) for c in candidate["constraints"] if c["type"] != "dimension"]
    evidence = {"schema": "cadbridge.legacy-native-bridge.v1", "status": "ok",
                "source_sha256": before, "observation_sha256": observation["sha256"],
                "candidate_sha256": candidate_sha256, "validated_ir": candidate,
                "solved": solved, "legacy_plan": legacy, "native_plan": native,
                "input_internal_tolerances": input_tolerances,
                "numerical_normalization": normalization,
                "semantics_required": _semantics(candidate, legacy),
                "relations_requiring_native_review": flattened,
                "limits": [
                    "This boundary validates a reconstruction hypothesis, not original authoring history.",
                    "Only a plate centered at global XY with base Z=0 and one centered pocket are representable; offsets are rejected.",
                    "The generic native v1 plan carries explicit all-hole equal diameter or independent diameter. The integrated adapter additionally requires the recorded explicit IR 2x2 symmetry proof before creating its Parameters-driven symmetric pattern.",
                    "Other cross-feature relations remain in the IR evidence and are not generically implemented in native CAD. The integrated app rejects unsupported patterns instead of claiming full relation transfer.",
                    "Native creation, geometry comparison and separate-process reopen/edit must still be checked by the native worker.",
                ], "external_api_calls": 0, "proposal_approval": candidate["proposal"]["approval"]}
    # Write evidence first. An interrupted conversion cannot leave a plan without
    # its bound evidence. Both paths are new and never overwrite user artifacts.
    _write_new_json(evidence_target, evidence)
    _write_new_json(target, native)
    return {"status": "ok", "plan_path": str(target), "evidence_path": str(evidence_target),
            "source_sha256": before, "external_api_calls": 0, "limits": evidence["limits"]}


def _legacy_from_native(plan):
    # For verification only: make the expected edited geometry, rather than
    # comparing an intentional edit against the unedited source part.
    base = {"id": "base", "cx": 0.0, "cy": 0.0, "z": 0.0,
            "length": plan["plate"]["width"], "width": plan["plate"]["height"],
            "thickness": plan["plate"]["thickness"]}
    pockets = []
    if plan["pocket"] is not None:
        p = plan["pocket"]
        pockets = [{"id": "pocket_1", "cx": 0.0, "cy": 0.0,
                    "length": p["width"], "width": p["height"], "depth": p["depth"]}]
    holes = [{"id": f"hole_{i+1}", "cx": h["x"], "cy": h["y"], "diameter": h["diameter"]}
             for i, h in enumerate(plan["holes"])]
    return {"schema_version": "0.1", "units": "mm", "base": base,
            "pockets": pockets, "holes": holes,
            "feature_order": ["base"] + [p["id"] for p in pockets] + [h["id"] for h in holes]}


def _measurement_delta(expected, actual):
    records = []
    for field in ("cx", "cy", "z", "length", "width", "thickness"):
        records.append({"field": "base." + field, "delta_mm": abs(expected["base"][field] - actual["base"][field])})
    for label, fields in (("pockets", ("cx", "cy", "length", "width", "depth")),
                          ("holes", ("cx", "cy", "diameter"))):
        if len(expected[label]) != len(actual[label]):
            raise ValueError("verification_feature_count_mismatch:" + label)
        left, right = expected[label], actual[label]
        distance = lambda a, b: max(abs(a[f] - b[f]) for f in fields)
        adjacency = {i: sorted((j for j in range(len(right)) if distance(a, right[j]) <= 0.01),
                               key=lambda j: distance(a, right[j])) for i, a in enumerate(left)}
        assigned = {}

        def match(i, visited):
            for j in adjacency[i]:
                if j in visited:
                    continue
                visited.add(j)
                if j not in assigned or match(assigned[j], visited):
                    assigned[j] = i
                    return True
            return False

        matched = all(match(i, set()) for i in range(len(left)))
        if matched:
            pairs = sorted(((i, j) for j, i in assigned.items()))
        else:
            # Retain an intelligible failed diagnostic when no tolerance-respecting
            # bijection exists. A valid match never relies on STEP face ordering.
            remaining = set(range(len(right))); pairs = []
            for i, a in enumerate(left):
                j = min(remaining, key=lambda k: distance(a, right[k]))
                remaining.remove(j); pairs.append((i, j))
        for index, (i, j) in enumerate(pairs):
            a, b = left[i], right[j]
            for field in fields:
                records.append({"field": f"{label}.{index}.{field}", "delta_mm": abs(a[field] - b[field])})
    maximum = max(r["delta_mm"] for r in records)
    return {"maximum_mm": maximum, "measurements": records,
            "feature_matching": "Tolerance-bounded geometric bipartite matching; STEP face IDs are not persistent feature identifiers.",
            "threshold_mm": 0.01, "passed": maximum <= 0.01}


def verify(input_step, candidate_step, output, reference_plan=None):
    observe_step, _, _, _, _, loader, _ = _dependencies()
    from cadbridge import kernel
    from cadbridge.geometry import build_shape, compare_shapes
    source = Path(input_step).resolve(strict=True)
    candidate = Path(candidate_step).resolve(strict=True)
    if Path(output).exists():
        raise ValueError("output_already_exists")
    before_source, before_candidate = _sha(source), _sha(candidate)
    input_shape = kernel.read_step(source)
    candidate_shape = kernel.read_step(candidate)
    internal = _internal_tolerances(input_shape)
    candidate_internal = _internal_tolerances(candidate_shape)
    if reference_plan:
        plan, plan_hash = _read_json(reference_plan, loader)
        expected = _legacy_from_native(_validate_native_plan(plan))
        reference_shape = build_shape(expected)
        reference = {"kind": "expected_edited_native_plan", "plan_sha256": plan_hash,
                     "native_plan": plan,
                     "compared_to_original_input_geometry": False}
    else:
        reference_shape = input_shape
        expected = observe_step(source)["geometry"]
        reference = {"kind": "original_input_step", "source_sha256": before_source,
                     "compared_to_original_input_geometry": True}
    comparison = compare_shapes(reference_shape, candidate_shape, tolerance=0.01)
    actual = observe_step(candidate)["geometry"]
    dimensions = _measurement_delta(expected, actual)
    distances_complete = all(key in comparison for key in
                             ("boundary_sample_max_mm", "bbox_max_delta_mm", "symdiff_volume_mm3"))
    geometry_passed = (distances_complete and not comparison["errors"]
                       and all(comparison["validity"].values())
                       and all(n == 1 for n in comparison["solid_counts"].values())
                       and comparison["boundary_sample_max_mm"] <= 0.01
                       and comparison["bbox_max_delta_mm"] <= 0.01 and dimensions["passed"])
    if _sha(source) != before_source or _sha(candidate) != before_candidate:
        raise ValueError("verification_input_changed")
    report = {"schema": "cadbridge.geometry-verification.v1",
              "status": "ok" if internal["passed"] and geometry_passed else "error",
              "input_sha256": before_source, "candidate_sha256": before_candidate,
              "reference": reference, "input_internal_tolerances": internal,
              "candidate_internal_tolerances_diagnostic": candidate_internal,
              "dimensions": dimensions, "comparison": comparison,
              "acceptance": {"input_internal_tolerance_strict_max_mm": 0.002,
                             "dimension_position_and_sample_distance_max_mm": 0.01,
                             "volume_difference": "diagnostic_only",
                             "legacy_comparison_status_used_for_acceptance": False},
              "limits": ["Distances are measured on finite bidirectional boundary samples, not a certified continuous Hausdorff distance.",
                         "Relative symmetric-difference volume is diagnostic only; the M3 comparison status includes its older 1e-6 rule and is not reused for product acceptance.",
                         "Both geometries are checked using the same OCCT kernel; this is not independent cross-kernel verification.",
                         "This report verifies saved geometry only; native lifecycle, native constraints and semantic edit behavior need separate tests."]}
    _write_new_json(output, report)
    return {"status": report["status"], "report_path": str(Path(output).resolve()),
            "maximum_sample_distance_mm": comparison.get("boundary_sample_max_mm"),
            "maximum_dimension_delta_mm": dimensions["maximum_mm"],
            "input_internal_max_mm": internal["maximum_mm"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    p = actions.add_parser("observe")
    p.add_argument("step"); p.add_argument("request_json")
    p = actions.add_parser("convert")
    p.add_argument("step"); p.add_argument("candidate_ir"); p.add_argument("native_plan_json")
    p = actions.add_parser("verify")
    p.add_argument("input_step"); p.add_argument("candidate_step"); p.add_argument("report_json")
    p.add_argument("--reference-plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "observe":
            result = observe(args.step, args.request_json)
        elif args.command == "convert":
            result = convert(args.step, args.candidate_ir, args.native_plan_json)
        else:
            result = verify(args.input_step, args.candidate_step, args.report_json, args.reference_plan)
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())

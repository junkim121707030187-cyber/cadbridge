"""Post-generation edit evaluation; hypothetical intent stays out of inference.

This module is intentionally separate from providers. Equal-diameter and
independent-diameter expectations are alternative test assumptions, not recovered
historical intent. The expected shape is constructed without the production IR
interpreter, but uses the same OCCT kernel; this is not a cross-kernel oracle.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from cadbridge import kernel
from cadbridge.extractor import extract_step
from cadbridge.geometry import build_shape, compare_shapes


def _dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _oracle_shape(measured: dict) -> kernel.Shape:
    """Independent bounded shape construction, not build_shape/to_legacy."""
    base = measured["base"]
    solid = BRepPrimAPI_MakeBox(
        gp_Pnt(base["cx"]-base["length"]/2, base["cy"]-base["width"]/2, base["z"]),
        base["length"], base["width"], base["thickness"]).Shape()
    # Deliberately separate control flow and order from the production builder.
    for hole in measured["holes"]:
        cutter = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(hole["cx"], hole["cy"], base["z"]-2), gp_Dir(0, 0, 1)),
            hole["diameter"]/2, base["thickness"]+4).Shape()
        cut = BRepAlgoAPI_Cut(solid, cutter)
        cut.Build()
        if not cut.IsDone():
            raise ValueError("Evaluator hole oracle Boolean failed")
        solid = cut.Shape()
    for pocket in measured["pockets"]:
        cutter = BRepPrimAPI_MakeBox(
            gp_Pnt(pocket["cx"]-pocket["length"]/2,
                   pocket["cy"]-pocket["width"]/2,
                   base["z"]+base["thickness"]-pocket["depth"]),
            pocket["length"], pocket["width"], pocket["depth"]+2).Shape()
        cut = BRepAlgoAPI_Cut(solid, cutter)
        cut.Build()
        if not cut.IsDone():
            raise ValueError("Evaluator pocket oracle Boolean failed")
        solid = cut.Shape()
    result = kernel.Shape(solid).clean()
    if not result.isValid() or len(result.Solids()) != 1:
        raise ValueError("Evaluator oracle did not produce one valid solid")
    return result


def _dimension_diagnostics(before: dict, after: dict, desired_diameter: float) -> dict:
    """Match observed features spatially rather than relying on face numbering."""
    tolerance = 1e-5
    checks: list[dict] = []
    diameters: list[dict] = []
    complete = True

    def check(label: str, a: float, b: float) -> None:
        checks.append({"dimension": label, "before_mm": a, "after_mm": b,
                       "delta_mm": b-a, "preserved": abs(b-a) <= tolerance})

    for key in ("cx", "cy", "z", "length", "width", "thickness"):
        check("base."+key, before["base"][key], after["base"][key])
    for group, non_targets in (("holes", ("cx", "cy")),
                               ("pockets", ("cx", "cy", "length", "width", "depth"))):
        unmatched = list(after[group])
        if len(before[group]) != len(unmatched):
            complete = False
        for source in before[group]:
            found = next((item for item in unmatched
                          if abs(source["cx"]-item["cx"]) <= tolerance
                          and abs(source["cy"]-item["cy"]) <= tolerance), None)
            if found is None:
                complete = False
                continue
            unmatched.remove(found)
            for key in non_targets:
                check(source["id"]+"."+key, source[key], found[key])
            if group == "holes":
                diameters.append({"feature": source["id"], "before_mm": source["diameter"],
                                  "after_mm": found["diameter"],
                                  "equal_task_expected_mm": desired_diameter,
                                  "independent_task_expected_mm": desired_diameter
                                  if source["id"] == "hole_1" else source["diameter"]})
        if unmatched:
            complete = False
    return {
        "matching_complete": complete, "tolerance_mm": tolerance,
        "non_target_dimensions": {"status": "PASS" if complete and all(
            item["preserved"] for item in checks) else "FAIL", "checks": checks},
        "hole_diameters": diameters,
        "equal_relation_preserved": complete and len(diameters) >= 2 and all(
            abs(item["after_mm"]-item["equal_task_expected_mm"]) <= tolerance
            for item in diameters),
        "independent_relation_preserved": complete and len(diameters) >= 2 and all(
            abs(item["after_mm"]-item["independent_task_expected_mm"]) <= tolerance
            for item in diameters),
    }


class EvaluationApplicabilityError(ValueError):
    """The bounded test cannot express its edit in this otherwise valid IR."""


def _diameter_driver(ir: dict) -> tuple[str, dict]:
    """Resolve semantic feature references, independent of arbitrary scalar IDs.

    Equalities may connect the observed hole diameter to a separately named
    driver. Only a unique dimension in this equality component is supported;
    general inverse editing through affine relations remains out of scope.
    """
    feature = next(f for f in ir["features"] if f["id"] == "hole_1")
    entity = next(e for sketch in ir["sketches"] for e in sketch["entities"]
                  if e["id"] == feature["entity"])
    parameter_id = entity["parameters"]["diameter"]
    component = {parameter_id}
    while True:
        expanded = component | {ref for c in ir["constraints"] if c["type"] == "equal"
                                and component.intersection(c["refs"]) for ref in c["refs"]}
        if expanded == component:
            break
        component = expanded
    dimensions = [c for c in ir["constraints"]
                  if c["type"] == "dimension" and c["refs"][0] in component]
    if len(dimensions) != 1:
        raise EvaluationApplicabilityError(
            "Unsupported evaluation edit: hole_1 diameter requires exactly one driving "
            "dimension in its equality component; general inverse affine editing is unsupported")
    return parameter_id, dimensions[0]


def evaluate_candidate(ir: dict, observation: dict, source_step: str | Path,
                       out_dir: str | Path) -> dict:
    """Execute a single driver edit and score two mutually exclusive assumptions.

    `status` scores the equal-diameter test task. `execution_status` separately
    reports whether validation, solving, CAD execution, STEP reopen and IR reload
    succeeded. An independent candidate can execute correctly and fail that task.
    """
    # Import here so no provider imports this module merely to assemble a request.
    from .ir import to_legacy, validate_ir
    from .solver import solve

    target = Path(out_dir)
    # Refuse before writing even a failure report, preserving previous evidence.
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("Evaluation output directory must be absent or empty")
    target.mkdir(parents=True, exist_ok=True)
    source = Path(source_step)
    report: dict[str, Any] = {
        "schema_version": "cadbridge.evaluation/1", "status": "FAIL",
        "execution_status": "FAIL", "errors": [], "artifacts": {},
        "interpretation": "Hypothetical post-generation edit tasks; not original design history.",
        "oracle_limitations": [
            "Expected B-rep is built by a separate evaluator implementation using the same OCCT kernel.",
            "Source measurements use the production restricted STEP extractor.",
            "Boundary samples are finite diagnostics, not a continuous Hausdorff proof.",
            "IR reload and STEP reopen do not establish any native CAD/version support.",
        ],
    }
    stage = "source_integrity"
    try:
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        report["source_sha256"] = source_hash
        if ir.get("source", {}).get("sha256") != source_hash:
            raise ValueError("Candidate source hash does not match evaluated STEP bytes")
        stage = "schema_validation"
        validate_ir(ir, observation)
        stage = "initial_solve"
        initial_solution = solve(ir)
        report["initial_solution"] = initial_solution
        if initial_solution["status"] != "fully_constrained":
            raise ValueError("Initial solver status: "+initial_solution["status"])
        _dump(target / "candidate.ir.json", ir)
        report["artifacts"]["candidate_ir"] = str(target / "candidate.ir.json")
        stage = "initial_geometry"
        initial_plan = to_legacy(ir, initial_solution["values"])
        initial_shape = build_shape(initial_plan)
        source_shape = kernel.read_step(source)
        report["baseline_geometry"] = compare_shapes(source_shape, initial_shape)
        kernel.write_step(initial_shape, target / "reconstructed.step")
        report["artifacts"]["reconstructed_step"] = str(target / "reconstructed.step")
        report["initial_step_reopen"] = compare_shapes(source_shape,
                                                       kernel.read_step(target / "reconstructed.step"))
        stage = "task_preconditions"
        measured = extract_step(source)
        holes = measured["holes"]
        if len(holes) < 2 or not all(abs(h["diameter"]-holes[0]["diameter"]) < 1e-5 for h in holes):
            raise ValueError("Evaluation task requires at least two initially equal-diameter holes")
        driver = next((h for h in holes if h["id"] == "hole_1"), None)
        if driver is None:
            raise ValueError("Evaluation requires measured feature hole_1")
        parameter_id, dimension = _diameter_driver(ir)
        report["task_applicability"] = "SUPPORTED"
        diameter = float(driver["diameter"])+2.0
        edits = {dimension["id"]: diameter}
        report["edit"] = {"dimension_edits": edits, "parameter": parameter_id,
                          "driving_parameter": dimension["refs"][0],
                          "from_mm": driver["diameter"], "to_mm": diameter,
                          "same_edit_for_all_policies": True}
        _dump(target / "edit.json", edits)
        report["artifacts"]["edit"] = str(target / "edit.json")
        stage = "edited_solve"
        edited_solution = solve(ir, edits)
        report["edited_solution"] = edited_solution
        if edited_solution["status"] != "fully_constrained":
            raise ValueError("Edited solver status: "+edited_solution["status"])
        stage = "edited_geometry"
        edited_plan = to_legacy(ir, edited_solution["values"])
        edited_shape = build_shape(edited_plan)
        kernel.write_step(edited_shape, target / "edited.step")
        report["artifacts"]["edited_step"] = str(target / "edited.step")
        reopened_edit = kernel.read_step(target / "edited.step")
        report["edited_step_reopen"] = compare_shapes(edited_shape, reopened_edit)
        stage = "ir_reload_regeneration"
        persisted_ir = json.loads((target / "candidate.ir.json").read_text(encoding="utf-8"))
        persisted_edits = json.loads((target / "edit.json").read_text(encoding="utf-8"))
        validate_ir(persisted_ir, observation)
        regenerated_solution = solve(persisted_ir, persisted_edits)
        if regenerated_solution["status"] != "fully_constrained":
            raise ValueError("Reloaded solver is not fully constrained")
        regenerated_shape = build_shape(to_legacy(persisted_ir, regenerated_solution["values"]))
        kernel.write_step(regenerated_shape, target / "regenerated.step")
        report["artifacts"]["regenerated_step"] = str(target / "regenerated.step")
        report["ir_reload_regeneration"] = compare_shapes(reopened_edit,
                                                          kernel.read_step(target / "regenerated.step"))
        stage = "independent_edit_oracles"
        equal_expected = deepcopy(measured)
        for hole in equal_expected["holes"]:
            hole["diameter"] = diameter
        independent_expected = deepcopy(measured)
        next(h for h in independent_expected["holes"] if h["id"] == "hole_1")["diameter"] = diameter
        equal_oracle = _oracle_shape(equal_expected)
        independent_oracle = _oracle_shape(independent_expected)
        kernel.write_step(equal_oracle, target / "equal-task-expected.step")
        kernel.write_step(independent_oracle, target / "independent-task-expected.step")
        report["artifacts"].update({
            "equal_task_oracle": str(target / "equal-task-expected.step"),
            "independent_task_oracle": str(target / "independent-task-expected.step")})
        equal_geometry = compare_shapes(equal_oracle, reopened_edit)
        independent_geometry = compare_shapes(independent_oracle, reopened_edit)
        actual_measured = extract_step(target / "edited.step")
        diagnostics = _dimension_diagnostics(measured, actual_measured, diameter)
        report.update(diagnostics)
        stage = "source_integrity_recheck"
        final_source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        report["final_source_sha256"] = final_source_hash
        report["source_stable"] = final_source_hash == source_hash
        if not report["source_stable"]:
            raise ValueError("Source STEP changed during evaluation; no task result may pass")
        successful_execution = all(report[key]["status"] == "PASS" for key in (
            "baseline_geometry", "initial_step_reopen", "edited_step_reopen", "ir_reload_regeneration"))
        report["execution_status"] = "PASS" if successful_execution else "FAIL"
        unchanged = report["non_target_dimensions"]["status"] == "PASS"
        report["tasks"] = {}
        for name, relation, comparison, description in (
            ("equal_diameter", diagnostics["equal_relation_preserved"], equal_geometry,
             "All initially equal holes should remain equal after editing one driving diameter."),
            ("independent_diameter", diagnostics["independent_relation_preserved"], independent_geometry,
             "Only the explicitly edited hole should change; other hole diameters should remain fixed.")):
            report["tasks"][name] = {
                "assumption": description, "not_original_history": True,
                "status": "PASS" if successful_execution and unchanged and relation
                and comparison["status"] == "PASS" else "FAIL",
                "relation_preserved": relation, "geometry": comparison,
            }
        report["status"] = report["tasks"]["equal_diameter"]["status"]
        report["geometry_error"] = equal_geometry
        stage = "complete"
    except Exception as exc:
        if isinstance(exc, EvaluationApplicabilityError):
            report["task_applicability"] = "UNSUPPORTED"
        report["errors"].append({"stage": stage, "type": type(exc).__name__, "message": str(exc)})
    report["completed_stage"] = stage
    report["artifacts"]["report"] = str(target / "evaluation.json")
    _dump(target / "evaluation.json", report)
    return report

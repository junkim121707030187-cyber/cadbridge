"""Local CLI: no installed commercial CAD and no cloud account are required."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import importlib.metadata

from .capabilities import capabilities
from .model import ContractError, analytic_volume, apply_edit, validate_plan, validate_edit_contract
from .planner import apply_candidate, request_for_ai


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(ContractError(f"Nonfinite JSON number: {value}")))


def _write(path, data):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"Refusing to replace existing artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2, allow_nan=False)


def _outdir(path):
    path = Path(path).resolve()
    if path.exists() and any(path.iterdir()):
        raise FileExistsError("Choose a new or empty output directory; existing results are preserved")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _engine():
    return {"python": platform.python_version(), "platform": platform.platform(),
            "backend": "OCCT direct via OCP (no CadQuery solver)",
            "ocp": importlib.metadata.version("cadquery-ocp"), "cadbridge": "0.1.0"}


def _load_shape(path):
    from .kernel import read_step
    return read_step(path)


def _mesh(shape):
    verts, triangles = shape.tessellate(0.15, 0.15)
    return {"vertices": [[v.x,v.y,v.z] for v in verts], "triangles": [list(t) for t in triangles]}


def _artifact_case(name, plan, expected_shape, directory, filename):
    from .geometry import build_shape, compare_shapes, export_step
    validate_plan(plan)
    shape = build_shape(plan)
    plan_file, step_file = directory / f"{filename}.json", directory / f"{filename}.step"
    _write(plan_file, plan)
    export_step(plan, step_file)
    persisted = _load_shape(step_file)
    geometry = compare_shapes(expected_shape, persisted)
    roundtrip = compare_shapes(shape, persisted)
    passed = geometry["status"] == "PASS" and roundtrip["status"] == "PASS"
    return {"name": name, "status": "PASS" if passed else "FAIL",
            "parameters": {"base": plan["base"], "pockets": plan["pockets"], "holes": plan["holes"]},
            "metrics": {"data_validation": "PASS", "regeneration": "PASS", "step_reread": "PASS",
                        "geometry": geometry, "roundtrip": roundtrip,
                        "verification_scope": "provided_reference_shape", "edit_task_verification": "UNVERIFIED",
                        "native_edit": "UNVERIFIED", "analytic_volume_mm3": analytic_volume(plan)},
            "artifacts": {"step": step_file.name, "plan": plan_file.name},
            "hashes": {"step_sha256": _hash(step_file), "plan_sha256": _hash(plan_file)},
            **_mesh(persisted)}


def _finish_report(directory, report):
    from .report import write_report
    report["capabilities"] = capabilities()
    report["engine"] = _engine()
    passed = bool(report["cases"]) and all(c["status"] == "PASS" for c in report["cases"]) and all(r.get("status") == "PASS" for r in report.get("rejections",[]))
    report["overall_status"] = "PASS" if passed else "FAIL"
    _write(directory / "report.json", report)
    write_report(report, directory / "report.html")
    print(json.dumps({"report": str(directory / "report.html"), "overall_status":report["overall_status"], "cases": [{"name":c["name"],"status":c["status"],"verification_scope":c.get("metrics",{}).get("verification_scope","UNVERIFIED"),"edit_task_verification":c.get("metrics",{}).get("edit_task_verification","UNVERIFIED")} for c in report["cases"]], "rejections":report.get("rejections",[]), "native": "UNVERIFIED"}, ensure_ascii=False))
    return 0 if passed else 2


def _limits():
    return ["공통 도구의 parameter JSON을 편집하여 STEP을 다시 생성합니다. 수신 CAD의 native 피처 편집 검증은 아닙니다.",
            "지원 범위: XY 정렬 사각 판재, 서로 겹치지 않는 상부 사각 포켓과 Z축 관통 홀.",
            "표면 거리는 유한 샘플 기반 진단이며 연속 Hausdorff 거리의 수학적 보증이 아닙니다.",
            "원래 피처 이력·설계 의도는 복원했다고 주장하지 않습니다. 같은 커널을 사용한 생성/검사에는 공통 오류 가능성이 있습니다."]


def inspect_file(args):
    from .extractor import extract_step
    plan = extract_step(args.input)
    validate_plan(plan)
    _write(args.out, plan)
    if args.ai_request:
        _write(args.ai_request, request_for_ai(plan))
    print(json.dumps({"plan":str(Path(args.out).resolve()),"features":len(plan["feature_order"]),"status":"PASS"},ensure_ascii=False))
    return 0


def reconstruct(args):
    if args.target != "occt":
        raise ContractError(f"{args.target}: native adapter is not implemented; use occt for the common-tool prototype")
    from .extractor import extract_step
    source = Path(args.input).resolve()
    source_hash = _hash(source)
    directory = _outdir(args.out)
    start = time.monotonic()
    plan = extract_step(source)
    if args.contract:
        plan["edit_contract"] = validate_edit_contract(_read(args.contract))
    if args.candidate:
        plan = apply_candidate(plan, _read(args.candidate))
    else:
        plan["planner"] = {"method":"deterministic_baseline"}
    case = _artifact_case("재구성",plan,_load_shape(source),directory,"reconstructed")
    case["metrics"]["verification_scope"] = "input_step_reconstruction"
    if _hash(source) != source_hash:
        raise ContractError("Source changed during reconstruction")
    report = {"title":"STEP 공통 파라미터 재구성", "summary":{"input":str(source),"input_sha256":source_hash,"source_preserved":True,"elapsed_seconds":time.monotonic()-start,"planner":plan["planner"]},
              "cases":[case],"rejections":[],"limitations":_limits()}
    return _finish_report(directory,report)


def edit_file(args):
    source = Path(args.plan).resolve()
    before = _hash(source)
    plan = _read(source)
    changes = {}
    for entry in args.set:
        key, sep, value = entry.partition("=")
        if not sep or key in changes:
            raise ContractError("Each edit must be a unique name=number")
        changes[key] = float(value)
    contract = _read(args.contract) if args.contract else None
    edited = apply_edit(plan,changes,contract)
    from .geometry import build_shape
    directory = _outdir(args.out)  # Invalid edits create no output directory.
    case = _artifact_case("편집 결과", edited, build_shape(edited), directory, "edited")
    # This command only has a plan-derived reference. Independent task truth is
    # available in the demo; do not call this independent task verification.
    case["metrics"]["edit_task_verification"] = "UNVERIFIED"
    case["metrics"]["verification_scope"] = "plan_roundtrip"
    if _hash(source) != before:
        raise ContractError("Source plan changed during edit")
    return _finish_report(directory,{"title":"공통 파라미터 편집", "summary":{"changes":changes,"source_preserved":True,"editing_surface":"parameter JSON in CADBridge"},"cases":[case],"rejections":[],"limitations":_limits()+["이 편집은 요청된 계획의 저장·재생성만 검사했습니다. 별도 사용자 과제의 독립 정답 검증은 미수행입니다."]})


def _fixture(thickness=10, diameter=8, pitch_x=60):
    """Independent test-fixture construction; never used as extractor input data."""
    from .kernel import Shape
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir
    part = BRepPrimAPI_MakeBox(gp_Pnt(-50,-40,0),100,80,thickness).Shape()
    cutters = [BRepPrimAPI_MakeBox(gp_Pnt(-15,-10,thickness-5),30,20,6).Shape()]
    for x in (-pitch_x/2,pitch_x/2):
        for y in (-20,20):
            cutters.append(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x,y,-1),gp_Dir(0,0,1)),diameter/2,thickness+2).Shape())
    for cutter in cutters:
        operation = BRepAlgoAPI_Cut(part,cutter)
        operation.Build()
        if not operation.IsDone():
            raise RuntimeError("Independent fixture Boolean failed")
        part = operation.Shape()
    return Shape(part)


def demo(args):
    from .extractor import extract_step
    from .kernel import write_step
    directory = _outdir(args.out)
    start = time.monotonic()
    source = directory / "input.step"
    write_step(_fixture(),source)
    before = _hash(source)
    plan = extract_step(source)
    validate_plan(plan)
    contract = {"provenance":"explicit_user_requirement","preserve_pocket_depth":True,"preserve_holes_through":True,"shared_hole_diameter":True,"symmetric_hole_pattern":True,"scope":"all_holes"}
    plan["edit_contract"] = contract
    plan["planner"] = {"method":"deterministic_baseline"}
    _write(directory/"ai-request.json",request_for_ai(plan))
    cases = [_artifact_case("원형 재구성",plan,_fixture(),directory,"base")]
    cases[0]["metrics"]["verification_scope"] = "independently_constructed_fixture"
    for name,changes,params,filename in (
        ("T1 · 두께 15 mm",{"plate_thickness":15},{"thickness":15},"T1-thickness"),
        ("T2 · 홀 Ø10 mm",{"hole_diameter":10},{"diameter":10},"T2-diameter"),
        ("T3 · X 간격 70 mm",{"hole_pitch_x":70},{"pitch_x":70},"T3-pitch"),
    ):
        edited = apply_edit(plan,changes)
        case = _artifact_case(name,edited,_fixture(**params),directory,filename)
        reread = extract_step(directory/f"{filename}.step")
        b = reread["base"]
        holes = reread["holes"]
        expected_t = params.get("thickness",10)
        expected_d = params.get("diameter",8)
        expected_x = params.get("pitch_x",60)/2
        independent = {
            "thickness": abs(b["thickness"]-expected_t)<1e-5,
            "hole_count": len(holes)==4,
            "diameters": all(abs(h["diameter"]-expected_d)<1e-5 for h in holes),
            "hole_centers": sorted((round(h["cx"],5),round(h["cy"],5)) for h in holes) == sorted((x,y) for x in (-expected_x,expected_x) for y in (-20,20)),
            "pocket_depth": len(reread["pockets"])==1 and abs(reread["pockets"][0]["depth"]-5)<1e-5,
        }
        case["metrics"]["independent_task_assertions"] = independent
        case["metrics"]["verification_scope"] = "independent_fixture_and_dimensional_assertions"
        case["metrics"]["edit_task_verification"] = "PASS" if all(independent.values()) and case["status"]=="PASS" else "FAIL"
        if case["metrics"]["edit_task_verification"] != "PASS":
            case["status"] = "FAIL"
        cases.append(case)
    saved = json.dumps(plan,sort_keys=True)
    try:
        apply_edit(plan,{"plate_thickness":4})
        rejection = {"task":"T4 두께4", "status":"FAIL", "reason":"Invalid blind-pocket edit was incorrectly accepted"}
    except ContractError as exc:
        rejection = {"task":"T4 두께4", "status":"PASS", "outcome":"REJECTED_BEFORE_CAD", "reason":str(exc)}
    if saved != json.dumps(plan,sort_keys=True) or _hash(source) != before:
        raise ContractError("Demo mutated its source")
    report = {"title":"STEP 공통 파라미터 재구성·편집 시연", "summary":{"input":"independently constructed synthetic STEP","input_sha256":before,"source_preserved":True,"elapsed_seconds":time.monotonic()-start,"planner":"deterministic baseline","reviewer":"Separate GPT-6 Astra / ultra task; no native CAD required"},"cases":cases,"rejections":[rejection],"limitations":_limits()+["이 데모는 범위 내 합성 부품 한 개입니다. 여러 CAD의 실제 수출·수입 호환성 또는 산업 성능을 입증하지 않습니다."]}
    return _finish_report(directory,report)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="cadbridge",description="Commercial-CAD-independent STEP reconstruction prototype")
    sub = parser.add_subparsers(dest="command",required=True)
    cap = sub.add_parser("capabilities")
    cap.set_defaults(run=lambda _:print(json.dumps(capabilities(),ensure_ascii=False,indent=2)) or 0)
    insp = sub.add_parser("inspect")
    insp.add_argument("input"); insp.add_argument("--out",required=True); insp.add_argument("--ai-request")
    insp.set_defaults(run=inspect_file)
    recon = sub.add_parser("reconstruct")
    recon.add_argument("input"); recon.add_argument("--out",required=True)
    recon.add_argument("--contract"); recon.add_argument("--candidate")
    recon.add_argument("--target",choices=["occt","catia","solidworks","nx"],default="occt")
    recon.set_defaults(run=reconstruct)
    edit = sub.add_parser("edit")
    edit.add_argument("plan"); edit.add_argument("--set",action="append",required=True)
    edit.add_argument("--out",required=True); edit.add_argument("--contract")
    edit.set_defaults(run=edit_file)
    dem = sub.add_parser("demo"); dem.add_argument("--out",required=True); dem.set_defaults(run=demo)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Exception as exc:
        print(json.dumps({"status":"FAIL","error":f"{type(exc).__name__}: {exc}","native_status":"UNVERIFIED"},ensure_ascii=False),file=sys.stderr)
        return 2

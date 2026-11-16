"""Developer CLI for the experimental known-plan native gate."""
import argparse
import json

from .model import BridgeError, plan_sha256, validate_plan
from .workflow import demo, edit_project, freecad_executable, load_session, read_json, reconstruct


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cadbridge")
    parser.add_argument("--freecadcmd", help="Path to a FreeCAD console executable")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("plan-inspect")
    p.add_argument("plan")
    p = sub.add_parser("demo")
    p.add_argument("--output", required=True)
    p = sub.add_parser("reconstruct")
    p.add_argument("--input", required=True)
    p.add_argument("--plan", required=True)
    p.add_argument("--selected-plan-sha", required=True)
    p.add_argument("--protect", action="append", default=[])
    p.add_argument("--output", required=True)
    p = sub.add_parser("edit")
    p.add_argument("--project", required=True)
    p.add_argument("--changes", required=True)
    p.add_argument("--expected-version", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("project")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = {"freecadcmd": freecad_executable(args.freecadcmd), "scope": "executable discovery only"}
        elif args.command == "plan-inspect":
            plan = validate_plan(read_json(args.plan))
            result = {"plan": plan, "plan_sha256": plan_sha256(plan), "selection_required": True}
        elif args.command == "demo":
            result = demo(args.output, args.freecadcmd)
        elif args.command == "reconstruct":
            result = reconstruct(args.input, read_json(args.plan), args.output, args.selected_plan_sha,
                                 args.protect, args.freecadcmd)
        elif args.command == "edit":
            result = edit_project(args.project, read_json(args.changes), args.output,
                                  args.expected_version, args.freecadcmd)
        else:
            result = load_session(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (BridgeError, OSError) as exc:
        print(json.dumps({"status": "error", "code": getattr(exc, "code", "io_error"), "message": str(exc)}, ensure_ascii=False))
        return 2

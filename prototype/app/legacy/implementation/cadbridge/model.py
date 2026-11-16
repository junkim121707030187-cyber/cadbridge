"""Backend-neutral measured model and explicit, immutable edit transactions."""
from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import math
import re


class ContractError(ValueError):
    pass


def validate_edit_contract(contract: dict) -> dict:
    """JSON booleans only: strings/numbers must never become consent."""
    flags = {"preserve_pocket_depth", "preserve_holes_through", "shared_hole_diameter", "symmetric_hole_pattern"}
    if not isinstance(contract, dict) or contract.get("provenance") != "explicit_user_requirement":
        raise ContractError("Explicit edit contract required; geometry does not prove design intent")
    if not set(contract) <= flags | {"provenance", "scope"}:
        raise ContractError("Unknown edit contract fields")
    for key in flags & set(contract):
        if type(contract[key]) is not bool:
            raise ContractError(f"{key}: JSON boolean required")
    if "scope" in contract and contract["scope"] != "all_holes":
        raise ContractError("Only scope=all_holes is implemented; partial-hole editing is unsupported")
    return contract


def _number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{label}: finite number required")
    if abs(value) > 10000 or (positive and value <= 1e-6):
        raise ContractError(f"{label}: outside supported dimension range")
    return float(value)


def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or plan.get("schema_version") != "0.1" or plan.get("units") != "mm":
        raise ContractError("Expected schema_version 0.1 and units mm")
    b = plan.get("base", {})
    required = {"id", "cx", "cy", "z", "length", "width", "thickness"}
    if set(b) != required or b["id"] != "base":
        raise ContractError("Invalid base fields")
    for key in required - {"id"}:
        _number(b[key], f"base.{key}", key in {"length", "width", "thickness"})
    pockets, holes = plan.get("pockets"), plan.get("holes")
    if not isinstance(pockets, list) or not isinstance(holes, list) or len(pockets) + len(holes) > 100:
        raise ContractError("At most 100 pockets/holes are supported")
    ids = ["base"]
    for kind, features, keys in (
        ("pocket", pockets, {"id", "cx", "cy", "length", "width", "depth"}),
        ("hole", holes, {"id", "cx", "cy", "diameter"}),
    ):
        for f in features:
            if set(f) != keys or not isinstance(f["id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", f["id"]):
                raise ContractError(f"Invalid {kind} fields or ID")
            ids.append(f["id"])
            for key in keys - {"id"}:
                _number(f[key], f"{f['id']}.{key}", key not in {"cx", "cy"})
            dx = f.get("length", f.get("diameter")) / 2
            dy = f.get("width", f.get("diameter")) / 2
            if abs(f["cx"] - b["cx"]) + dx >= b["length"] / 2 - 1e-6 or abs(f["cy"] - b["cy"]) + dy >= b["width"] / 2 - 1e-6:
                raise ContractError(f"{f['id']}: cut must remain strictly inside plate")
            if kind == "pocket" and f["depth"] >= b["thickness"] - 1e-6:
                raise ContractError("blind_pocket_depth_exceeds_or_equals_thickness")
    if len(set(ids)) != len(ids):
        raise ContractError("Duplicate feature IDs")
    order = plan.get("feature_order")
    if not isinstance(order, list) or not order or order[0] != "base" or len(order) != len(ids) or set(order) != set(ids):
        raise ContractError("Feature order must contain every feature once, base first")
    for a, c in combinations(holes, 2):
        if math.hypot(a["cx"] - c["cx"], a["cy"] - c["cy"]) <= (a["diameter"] + c["diameter"]) / 2 + 1e-6:
            raise ContractError("Intersecting/tangent holes are outside MVP")
    for a, c in combinations(pockets, 2):
        if abs(a["cx"]-c["cx"]) <= (a["length"]+c["length"])/2+1e-6 and abs(a["cy"]-c["cy"]) <= (a["width"]+c["width"])/2+1e-6:
            raise ContractError("Intersecting/tangent pockets are outside MVP")
    for h in holes:
        for p in pockets:
            dx = max(abs(h["cx"]-p["cx"]) - p["length"]/2, 0)
            dy = max(abs(h["cy"]-p["cy"]) - p["width"]/2, 0)
            if math.hypot(dx,dy) <= h["diameter"]/2 + 1e-6:
                raise ContractError("Intersecting/tangent hole and pocket are outside MVP")
    return plan


def apply_edit(plan: dict, changes: dict, contract: dict | None = None) -> dict:
    """Validate entirely before a CAD call or write. Never mutate the source."""
    validate_plan(plan)
    contract = plan.get("edit_contract", {}) if contract is None else contract
    validate_edit_contract(contract)
    allowed = {"plate_thickness", "hole_diameter", "hole_pitch_x"}
    if not changes or not set(changes) <= allowed:
        raise ContractError("Unsupported or empty edit")
    out = deepcopy(plan)
    for name, value in changes.items():
        _number(value, name, positive=True)
        if name == "plate_thickness":
            if out["pockets"] and contract.get("preserve_pocket_depth") is not True:
                raise ContractError("Pocket depth behavior must be specified")
            if out["holes"] and contract.get("preserve_holes_through") is not True:
                raise ContractError("Through-hole behavior must be specified")
            out["base"]["thickness"] = float(value)
        elif name == "hole_diameter":
            if contract.get("shared_hole_diameter") is not True or not out["holes"]:
                raise ContractError("Shared hole diameter must be explicitly requested")
            for hole in out["holes"]:
                hole["diameter"] = float(value)
        elif name == "hole_pitch_x":
            if contract.get("symmetric_hole_pattern") is not True or len(out["holes"]) != 4:
                raise ContractError("Explicit four-hole rectangular-pattern contract required")
            xs = sorted({round(h["cx"], 7) for h in out["holes"]})
            ys = sorted({round(h["cy"], 7) for h in out["holes"]})
            if len(xs) != 2 or len(ys) != 2 or {(round(h["cx"],7),round(h["cy"],7)) for h in out["holes"]} != {(x,y) for x in xs for y in ys}:
                raise ContractError("Holes do not form a rectangular pattern")
            cx = (xs[0] + xs[1]) / 2
            for h in out["holes"]:
                h["cx"] = cx + (-1 if h["cx"] < cx else 1) * float(value)/2
    validate_plan(out)
    out["edit_contract"] = deepcopy(contract)
    out.setdefault("edit_history", []).append({"changes": deepcopy(changes), "provenance": "explicit_user_requirement"})
    return out


def analytic_volume(plan: dict) -> float:
    validate_plan(plan)
    b = plan["base"]
    return b["length"] * b["width"] * b["thickness"] - sum(p["length"] * p["width"] * p["depth"] for p in plan["pockets"]) - sum(math.pi * (h["diameter"]/2)**2 * b["thickness"] for h in plan["holes"])

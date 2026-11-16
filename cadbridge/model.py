"""Strict, dependency-free plan validation and copy-on-edit operations.

The v1 model describes a centered rectangular plate, an optional centered top
pocket, and at most sixteen disjoint through holes. It carries a supplied plan;
it does not infer design intent from STEP geometry.
"""

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math


class BridgeError(ValueError):
    """An expected, fail-closed CADBridge rejection with a stable reason code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_PLAN_KEYS = {"schema", "units", "plate", "pocket", "holes", "hole_relation"}
_PLATE_KEYS = {"width", "height", "thickness"}
_POCKET_KEYS = {"width", "height", "depth"}
_HOLE_KEYS = {"x", "y", "diameter"}
_MAX_HOLES = 16


def _object(value, keys, label):
    if type(value) is not dict or set(value) != keys:
        raise BridgeError("invalid_plan", f"{label} must contain exactly {', '.join(sorted(keys))}")


def _number(value, label, *, positive=True, code="invalid_plan"):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError(code, f"{label} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise BridgeError(code, f"{label} must be a finite number") from None
    if not math.isfinite(result) or (positive and result <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise BridgeError(code, f"{label} must be a {qualifier} number")
    # One representation for zero, including input JSON -0.0 coordinates.
    return 0.0 if result == 0 else result


def validate_plan(data: dict) -> dict:
    """Return a detached, float-normalized plan, or reject unsupported input.

    Key sets are exact at every level. Geometry comparisons use strict
    separation: hole contacts with a boundary, another hole, or the pocket are
    invalid, as are holes which overlap any of those objects.
    """
    _object(data, _PLAN_KEYS, "plan")
    if data["schema"] != "cadbridge.plan.v1":
        raise BridgeError("invalid_plan", "unsupported plan schema")
    if data["units"] != "mm":
        raise BridgeError("invalid_plan", "unsupported plan units; v1 requires mm")
    if data["hole_relation"] not in ("equal_diameter", "independent"):
        raise BridgeError("invalid_plan", "unsupported hole relation")

    _object(data["plate"], _PLATE_KEYS, "plate")
    plate = {key: _number(data["plate"][key], f"plate.{key}")
             for key in ("width", "height", "thickness")}
    pocket = None
    if data["pocket"] is not None:
        _object(data["pocket"], _POCKET_KEYS, "pocket")
        pocket = {key: _number(data["pocket"][key], f"pocket.{key}")
                  for key in ("width", "height", "depth")}
        if (pocket["width"] >= plate["width"]
                or pocket["height"] >= plate["height"]
                or pocket["depth"] >= plate["thickness"]):
            raise BridgeError("invalid_plan", "pocket must be strictly smaller and shallower than plate")

    if type(data["holes"]) is not list or len(data["holes"]) > _MAX_HOLES:
        raise BridgeError("invalid_plan", "holes must be a list of at most 16 holes")
    holes = []
    hole_geometry = []
    # Exact predicates over normalized floats avoid losing a positive half
    # extent to underflow, or rounding a tangent pair into apparent separation.
    half_width = Fraction(plate["width"]) / 2
    half_height = Fraction(plate["height"]) / 2
    pocket_half_width = Fraction(pocket["width"]) / 2 if pocket else None
    pocket_half_height = Fraction(pocket["height"]) / 2 if pocket else None
    for index, item in enumerate(data["holes"]):
        _object(item, _HOLE_KEYS, f"holes.{index}")
        hole = {key: _number(item[key], f"holes.{index}.{key}",
                             positive=(key == "diameter"))
                for key in ("x", "y", "diameter")}
        x, y = Fraction(hole["x"]), Fraction(hole["y"])
        radius = Fraction(hole["diameter"]) / 2
        if abs(x) + radius >= half_width or abs(y) + radius >= half_height:
            raise BridgeError("invalid_plan", f"holes.{index} touches or crosses the plate boundary")
        if pocket is not None:
            dx = max(abs(x) - pocket_half_width, 0)
            dy = max(abs(y) - pocket_half_height, 0)
            if dx * dx + dy * dy <= radius * radius:
                raise BridgeError("invalid_plan", f"holes.{index} touches or overlaps the pocket")
        for previous_x, previous_y, previous_radius in hole_geometry:
            dx, dy = x - previous_x, y - previous_y
            radius_sum = radius + previous_radius
            if dx * dx + dy * dy <= radius_sum * radius_sum:
                raise BridgeError("invalid_plan", f"holes.{index} touches or overlaps another hole")
        holes.append(hole)
        hole_geometry.append((x, y, radius))

    if (data["hole_relation"] == "equal_diameter" and holes
            and any(hole["diameter"] != holes[0]["diameter"] for hole in holes[1:])):
        raise BridgeError("invalid_plan", "equal_diameter holes must have identical diameters")
    return {"schema": "cadbridge.plan.v1", "units": "mm", "plate": plate,
            "pocket": pocket, "holes": holes, "hole_relation": data["hole_relation"]}


def plan_sha256(plan: dict) -> str:
    """Hash canonical validated JSON; this binds a plan version, not a person."""
    normalized = validate_plan(plan)
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _editable_fields(plan):
    """Map exact editable dotted paths to their current leaf values."""
    fields = {f"plate.{key}": value for key, value in plan["plate"].items()}
    if plan["pocket"] is not None:
        fields.update({f"pocket.{key}": value for key, value in plan["pocket"].items()})
    for index, hole in enumerate(plan["holes"]):
        fields.update({f"holes.{index}.{key}": value for key, value in hole.items()})
    return fields


def _set_field(plan, path, value):
    parts = path.split(".")
    if parts[0] == "holes":
        plan["holes"][int(parts[1])][parts[2]] = value
    else:
        plan[parts[0]][parts[1]] = value


def apply_edit(plan, changes: dict, protected_fields: list[str]) -> dict:
    """Apply supported numeric edits to a copy, validating all consequences.

    Protection references must name existing editable leaves. In an
    equal-diameter plan every requested diameter must agree, and its change is
    propagated before checking protection. Only actual value changes trigger
    a protection rejection; a nonempty, explicit no-op edit is permitted.
    """
    original = validate_plan(plan)
    fields = _editable_fields(original)
    if type(protected_fields) is not list:
        raise BridgeError("invalid_protected_field", "protected_fields must be a list of existing dotted paths")
    for path in protected_fields:
        if type(path) is not str or path not in fields:
            raise BridgeError("invalid_protected_field", "protected field must name an existing editable numeric leaf")
    if type(changes) is not dict or not changes:
        raise BridgeError("invalid_edit", "changes must be a nonempty object of dotted numeric edits")

    proposed = {}
    for path, value in changes.items():
        if type(path) is not str or path not in fields:
            raise BridgeError("invalid_edit", "edit must name an existing editable numeric leaf")
        proposed[path] = _number(value, path, positive=not path.endswith((".x", ".y")),
                                 code="invalid_edit")

    if original["hole_relation"] == "equal_diameter":
        diameter_values = {value for path, value in proposed.items()
                           if path.startswith("holes.") and path.endswith(".diameter")}
        if len(diameter_values) > 1:
            raise BridgeError("invalid_edit", "contradictory diameter edits for equal_diameter holes")
        if diameter_values:
            diameter = next(iter(diameter_values))
            proposed.update({f"holes.{index}.diameter": diameter
                             for index in range(len(original["holes"]))})

    protected = set(protected_fields)
    for path, value in proposed.items():
        if path in protected and value != fields[path]:
            raise BridgeError("protected_field", f"edit would change protected field {path}")
    edited = deepcopy(original)
    for path, value in proposed.items():
        _set_field(edited, path, value)
    return validate_plan(edited)

"""Deterministic OpenCascade execution and geometric validation.

All dimensions are millimetres.  Shape agreement validates the present geometry;
it does not establish that a reconstructed feature tree was the author's tree.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import kernel
from .model import validate_plan
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass import BRepClass_FaceClassifier
from OCP.TopAbs import TopAbs_IN, TopAbs_ON
from OCP.gp import gp_Pnt2d


def _number(value: Any, label: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{label} must be {'positive and ' if positive else ''}finite")
    return result


def build_shape(plan: dict) -> kernel.Shape:
    """Execute a bounded declarative plan without executing generated code."""
    validate_plan(plan)
    if plan.get("schema_version") != "0.1" or plan.get("units") != "mm":
        raise ValueError("Only schema 0.1 with millimetre units is supported")
    base = plan["base"]
    cx, cy, z = (_number(base[k], f"base.{k}") for k in ("cx", "cy", "z"))
    length, width, thickness = (
        _number(base[k], f"base.{k}", True) for k in ("length", "width", "thickness")
    )
    shape = kernel.make_box(length, width, thickness, (cx-length/2, cy-width/2, z))
    entries = {base["id"]: ("base", base)}
    for kind in ("pockets", "holes"):
        for item in plan.get(kind, []):
            if item["id"] in entries:
                raise ValueError(f"Duplicate feature id: {item['id']}")
            entries[item["id"]] = (kind, item)
    order = plan["feature_order"]
    if len(order) != len(entries) or set(order) != set(entries) or order[0] != base["id"]:
        raise ValueError("feature_order must contain each feature once, with base first")
    for feature_id in order[1:]:
        kind, feature = entries[feature_id]
        x = _number(feature["cx"], f"{feature_id}.cx")
        y = _number(feature["cy"], f"{feature_id}.cy")
        if kind == "pockets":
            a, b, depth = (_number(feature[k], f"{feature_id}.{k}", True)
                           for k in ("length", "width", "depth"))
            if depth >= thickness:
                raise ValueError(f"{feature_id}: pocket must be blind")
            if abs(x-cx)+a/2 >= length/2 or abs(y-cy)+b/2 >= width/2:
                raise ValueError(f"{feature_id}: only internal rectangular pockets are supported")
            # Extra height avoids coincident faces at the open top.
            tool = kernel.make_box(a, b, depth+1, (x-a/2, y-b/2, z+thickness-depth))
        elif kind == "holes":
            diameter = _number(feature["diameter"], f"{feature_id}.diameter", True)
            if abs(x-cx)+diameter/2 >= length/2 or abs(y-cy)+diameter/2 >= width/2:
                raise ValueError(f"{feature_id}: only internal vertical holes are supported")
            tool = kernel.make_cylinder(diameter/2, thickness+2, (x, y, z-1), (0, 0, 1))
        else:
            raise ValueError(f"Unsupported feature: {kind}")
        old_volume = shape.Volume()
        shape = shape.cut(tool).clean()
        if not shape.isValid() or len(shape.Solids()) != 1:
            raise ValueError(f"{feature_id}: operation did not produce one valid solid")
        if old_volume - shape.Volume() <= 1e-9:
            raise ValueError(f"{feature_id}: operation removes no material")
    return shape


def export_step(plan: dict, path: str | Path) -> None:
    """Export a reconstructed solid. STEP is geometry exchange, not a feature tree."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    kernel.write_step(build_shape(plan), target)


def _bbox(shape: kernel.Shape) -> tuple[float, ...]:
    box = shape.BoundingBox()
    return box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax


def _boundary_samples(shape: kernel.Shape) -> list[tuple[float, float, float]]:
    """Exact surface samples including mesh vertices and trimmed UV interior grid.

    This is a finite sample diagnostic, not a proven continuous Hausdorff bound.
    UV points are classified against the trimmed face before evaluating them.
    """
    points: dict[tuple[float, float, float], tuple[float, float, float]] = {}
    for face in shape.Faces():
        vertices, _ = face.tessellate(0.05, 0.15)
        candidates = [(v.x, v.y, v.z) for v in vertices]
        surface = BRepAdaptor_Surface(face.wrapped, True)
        u0, u1 = surface.FirstUParameter(), surface.LastUParameter()
        v0, v1 = surface.FirstVParameter(), surface.LastVParameter()
        if not all(math.isfinite(x) for x in (u0, u1, v0, v1)):
            raise ValueError("Cannot sample a face with unbounded UV domain")
        for i in range(9):
            u = u0 + (u1-u0)*i/8
            for j in range(9):
                v = v0 + (v1-v0)*j/8
                state = BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(u, v), 1e-7).State()
                if state in (TopAbs_IN, TopAbs_ON):
                    point = surface.Value(u, v)
                    candidates.append((point.X(), point.Y(), point.Z()))
        for point in candidates:
            points[tuple(round(x, 9) for x in point)] = point
    if not points:
        raise ValueError("Boundary sampler returned no points")
    if len(points) > 100000:
        raise ValueError("Boundary sample budget exceeded")
    return list(points.values())


def _directed_sample_distance(source: kernel.Shape, target: kernel.Shape) -> tuple[float, int]:
    # A face compound measures distance to the boundary, not to solid material.
    boundary = kernel.compound(target.Faces())
    points = _boundary_samples(source)
    maximum = max(kernel.make_vertex(*p).distance(boundary) for p in points)
    if not math.isfinite(maximum):
        raise ValueError("Nonfinite boundary distance")
    return maximum, len(points)


def compare_shapes(reference: kernel.Shape, candidate: kernel.Shape, tolerance: float = 0.01) -> dict:
    """Fail closed on invalid geometry, Boolean failure, or incomplete diagnostics."""
    tolerance = _number(tolerance, "tolerance", True)
    result: dict[str, Any] = {
        "status": "FAIL", "tolerance_mm": tolerance,
        "validity": {"reference": False, "candidate": False},
        "errors": [],
        "boundary_sampling_note": "Finite samples; not a certified Hausdorff bound.",
    }
    try:
        result["validity"] = {"reference": bool(reference.isValid()),
                              "candidate": bool(candidate.isValid())}
        counts = {"reference": len(reference.Solids()), "candidate": len(candidate.Solids())}
        result["solid_counts"] = counts
        if not all(result["validity"].values()) or any(n != 1 for n in counts.values()):
            raise ValueError("Both inputs must contain exactly one valid solid")
        for label, shape in (("reference", reference), ("candidate", candidate)):
            solid = shape.Solids()[0]
            if any(len(getattr(shape, method)()) != len(getattr(solid, method)())
                   for method in ("Faces", "Edges", "Vertices")):
                raise ValueError(f"{label} contains loose non-solid topology")
        ref_volume, candidate_volume = reference.Volume(), candidate.Volume()
        if not all(math.isfinite(v) and v > 0 for v in (ref_volume, candidate_volume)):
            raise ValueError("Nonpositive or nonfinite input volume")
        missing = reference.cut(candidate)
        extra = candidate.cut(reference)
        if not missing.isValid() or not extra.isValid():
            raise ValueError("Symmetric difference Boolean returned invalid geometry")
        symdiff = abs(missing.Volume()) + abs(extra.Volume())
        if not math.isfinite(symdiff):
            raise ValueError("Nonfinite symmetric difference volume")
        ref_box, candidate_box = _bbox(reference), _bbox(candidate)
        bbox_delta = max(abs(a-b) for a, b in zip(ref_box, candidate_box))
        forward, forward_count = _directed_sample_distance(reference, candidate)
        backward, backward_count = _directed_sample_distance(candidate, reference)
        # This first prototype uses a strict volume fraction in addition to mm
        # tolerance. A matching volume alone must never pass shifted features.
        relative_limit = 1e-6
        result.update({
            "reference_volume_mm3": ref_volume,
            "candidate_volume_mm3": candidate_volume,
            "symdiff_volume_mm3": symdiff,
            "symdiff_relative": symdiff/ref_volume,
            "symdiff_relative_limit": relative_limit,
            "bbox_max_delta_mm": bbox_delta,
            "boundary_reference_to_candidate_mm": forward,
            "boundary_candidate_to_reference_mm": backward,
            "boundary_sample_max_mm": max(forward, backward),
            "boundary_sample_counts": {"reference": forward_count, "candidate": backward_count},
        })
        result["status"] = "PASS" if (symdiff/ref_volume <= relative_limit
                                              and bbox_delta <= tolerance
                                              and max(forward, backward) <= tolerance) else "FAIL"
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    return result

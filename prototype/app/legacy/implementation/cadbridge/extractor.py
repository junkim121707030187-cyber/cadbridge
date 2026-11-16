"""Recognize a deliberately restricted part family from STEP B-rep geometry."""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import kernel
from OCP.BRepAdaptor import BRepAdaptor_Surface

from .geometry import build_shape, compare_shapes

EPS = 1e-5


def _near(a: float, b: float) -> bool:
    return abs(a-b) <= EPS


def _rectangle(face: kernel.Face) -> tuple[float, float, float, float]:
    wire = face.outerWire()
    edges, vertices = wire.Edges(), wire.Vertices()
    if len(edges) != 4 or len(vertices) != 4 or any(e.geomType() != "LINE" for e in edges):
        raise ValueError("Pocket floor must have a four-line rectangular outer boundary")
    box = wire.BoundingBox()
    corners = {(round(x, 5), round(y, 5)) for x in (box.xmin, box.xmax)
               for y in (box.ymin, box.ymax)}
    observed = {(round(v.Center().x, 5), round(v.Center().y, 5)) for v in vertices}
    if corners != observed or box.xlen <= EPS or box.ylen <= EPS:
        raise ValueError("Pocket floor must be aligned with the global XY axes")
    return (box.xmin+box.xmax)/2, (box.ymin+box.ymax)/2, box.xlen, box.ylen


def extract_step(path: str | Path) -> dict:
    """Extract measured dimensions, then reject unexplained source geometry.

    STEP import normalizes supported source length units to OpenCascade's mm.
    No filename, original feature names, or supplied dimensional metadata is used.
    """
    source = Path(path)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    imported = kernel.read_step(source)
    if not imported.isValid() or len(imported.Solids()) != 1:
        raise ValueError("Only one valid solid is supported; assemblies and multi-body files are rejected")
    shape = imported.Solids()[0]
    if any(len(getattr(imported, method)()) != len(getattr(shape, method)())
           for method in ("Faces", "Edges", "Vertices")):
        raise ValueError("Loose surface, edge, or vertex topology alongside a solid is unsupported")
    box = shape.BoundingBox()
    if min(box.xlen, box.ylen, box.zlen) <= EPS:
        raise ValueError("Degenerate base bounding box")
    base = {"id": "base", "cx": (box.xmin+box.xmax)/2, "cy": (box.ymin+box.ymax)/2,
            "z": box.zmin, "length": box.xlen, "width": box.ylen, "thickness": box.zlen}
    measurement: dict = {}
    faces = shape.Faces()
    face_ids = [f"face_{i+1}" for i in range(len(faces))]
    for key in ("cx", "cy", "z", "length", "width", "thickness"):
        measurement[f"base.{key}"] = {"value": base[key], "unit": "mm", "evidence": face_ids,
                                      "method": "axis-aligned solid bounding box"}
    pockets: list[dict] = []
    cylinder_groups: list[dict] = []
    face_inventory: list[dict] = []
    for i, face in enumerate(faces):
        face_id = face_ids[i]
        kind = face.geomType()
        fb = face.BoundingBox()
        face_inventory.append({"id": face_id, "surface_type": kind, "area_mm2": face.Area()})
        if kind == "PLANE":
            normal = face.normalAt()
            components = (abs(normal.x), abs(normal.y), abs(normal.z))
            if max(components) < 1-EPS or sum(v > EPS for v in components) != 1:
                raise ValueError(f"{face_id}: inclined planar faces are unsupported")
            if abs(normal.z) > 1-EPS and box.zmin+EPS < fb.zmin < box.zmax-EPS:
                if normal.z < 0:
                    raise ValueError(f"{face_id}: a downward internal face is not a top-open pocket")
                if all(e.geomType() == "CIRCLE" for e in face.outerWire().Edges()):
                    raise ValueError(f"{face_id}: Blind cylindrical holes are unsupported")
                x, y, a, b = _rectangle(face)
                feature_id = f"pocket_{len(pockets)+1}"
                feature = {"id": feature_id, "cx": x, "cy": y,
                           "length": a, "width": b, "depth": box.zmax-fb.zmin}
                pockets.append(feature)
                for key in ("cx", "cy", "length", "width", "depth"):
                    measurement[f"{feature_id}.{key}"] = {
                        "value": feature[key], "unit": "mm", "evidence": [face_id],
                        "method": "rectangular floor boundary and base top elevation"}
        elif kind == "CYLINDER":
            cylinder = BRepAdaptor_Surface(face.wrapped, True).Cylinder()
            direction = cylinder.Axis().Direction()
            if abs(direction.Z()) < 1-EPS:
                raise ValueError(f"{face_id}: only vertical cylindrical holes are supported")
            location = cylinder.Location()
            key = (location.X(), location.Y(), cylinder.Radius())
            matched = next((g for g in cylinder_groups
                            if all(_near(a, b) for a, b in zip(g["key"], key))), None)
            if matched is None:
                matched = {"key": key, "faces": [], "zmin": fb.zmin, "zmax": fb.zmax}
                cylinder_groups.append(matched)
            matched["faces"].append(face_id)
            matched["zmin"] = min(matched["zmin"], fb.zmin)
            matched["zmax"] = max(matched["zmax"], fb.zmax)
        else:
            raise ValueError(f"{face_id}: unsupported surface type {kind}; fillets/freeform faces are out of scope")
    holes: list[dict] = []
    for group in cylinder_groups:
        if not _near(group["zmin"], box.zmin):
            raise ValueError("Blind or raised cylindrical features are unsupported")
        x, y, radius = group["key"]
        feature_id = f"hole_{len(holes)+1}"
        feature = {"id": feature_id, "cx": x, "cy": y, "diameter": 2*radius}
        holes.append(feature)
        for key in ("cx", "cy", "diameter"):
            measurement[f"{feature_id}.{key}"] = {
                "value": feature[key], "unit": "mm", "evidence": group["faces"],
                "method": "analytic cylinder axis and radius"}
    plan = {"schema_version": "0.1", "units": "mm", "base": base, "pockets": pockets,
            "holes": holes, "feature_order": ["base"]+[p["id"] for p in pockets]+[h["id"] for h in holes],
            "provenance": {"source_sha256": source_hash,
                           "measurements": measurement, "faces": face_inventory},
            "assumptions": [
                "Single axis-aligned XY rectangular base with internal top-open rectangular blind pockets and vertical holes only.",
                "Pocket-before-hole order is a reconstruction choice; original construction history is not recovered.",
                "Holes are through the current solid. Their future through-all behavior is an explicit edit assumption, not recovered design intent.",
                "Input length units are normalized to mm by the STEP reader.",
            ]}
    reconstructed = build_shape(plan)
    report = compare_shapes(shape, reconstructed)
    if report["status"] != "PASS":
        raise ValueError(f"Unsupported or unexplained source geometry: reconstruction check failed: {report}")
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise ValueError("Source STEP changed during extraction; retry against a stable file")
    plan["provenance"]["extraction_validation"] = report
    return plan

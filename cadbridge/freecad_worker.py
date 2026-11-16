"""Fixed FreeCAD command-line worker for the known-plan fixture slice.

Run with freecadcmd, not system Python. CADBRIDGE_REQUEST names a JSON file;
the result is written to its report_path even when an operation fails.
"""

import copy
import json
import math
import os
from pathlib import Path


class WorkerError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _fail(code, message):
    raise WorkerError(code, message)


def _number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("invalid_plan", "Plan dimensions must be finite numbers")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        _fail("invalid_plan", "Plan dimensions must be finite and positive")
    return value


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        _fail("invalid_plan", "Unexpected or missing plan fields")


def _plan(value):
    """Check the boundary independently; do not import the orchestration core."""
    _keys(value, ("schema", "units", "plate", "pocket", "holes", "hole_relation"))
    if value["schema"] != "cadbridge.plan.v1" or value["units"] != "mm":
        _fail("invalid_plan", "Only cadbridge.plan.v1 in mm is supported")
    result = copy.deepcopy(value)
    _keys(result["plate"], ("width", "height", "thickness"))
    for key in result["plate"]:
        result["plate"][key] = _number(result["plate"][key], True)
    plate = result["plate"]
    pocket = result["pocket"]
    if pocket is not None:
        _keys(pocket, ("width", "height", "depth"))
        for key in pocket:
            pocket[key] = _number(pocket[key], True)
        if any(pocket[a] >= plate[b] for a, b in
               (("width", "width"), ("height", "height"), ("depth", "thickness"))):
            _fail("invalid_plan", "Pocket must lie strictly inside the plate")
    holes = result["holes"]
    if not isinstance(holes, list) or len(holes) > 16:
        _fail("invalid_plan", "At most 16 holes are supported")
    if result["hole_relation"] not in ("independent", "equal_diameter"):
        _fail("invalid_plan", "Unsupported hole relation")
    for index, hole in enumerate(holes):
        _keys(hole, ("x", "y", "diameter"))
        for key in hole:
            hole[key] = _number(hole[key], key == "diameter")
        radius = hole["diameter"] / 2
        if abs(hole["x"]) + radius >= plate["width"] / 2 or \
                abs(hole["y"]) + radius >= plate["height"] / 2:
            _fail("invalid_plan", "Holes must lie strictly inside the plate")
        if pocket:
            dx = max(abs(hole["x"]) - pocket["width"] / 2, 0)
            dy = max(abs(hole["y"]) - pocket["height"] / 2, 0)
            if math.hypot(dx, dy) <= radius:
                _fail("invalid_plan", "Holes must not touch the pocket")
        for other in holes[:index]:
            if math.hypot(hole["x"] - other["x"], hole["y"] - other["y"]) <= \
                    (hole["diameter"] + other["diameter"]) / 2:
                _fail("invalid_plan", "Holes must not touch each other")
        if result["hole_relation"] == "equal_diameter" and \
                hole["diameter"] != holes[0]["diameter"]:
            _fail("invalid_plan", "Equal-diameter holes have inconsistent diameters")
    return result


def _canonical(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _path(request, field):
    value = request.get(field)
    if not isinstance(value, str) or not Path(value).is_absolute():
        _fail("invalid_request", field + " must be an absolute path")
    return value


def _same_path(first, second):
    if os.path.realpath(first) == os.path.realpath(second):
        return True
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False


def _output_paths(request):
    result = []
    for field in ("output_native", "output_step"):
        if field in request:
            path = _path(request, field)
            if os.path.lexists(path):
                _fail("output_exists", "Refusing to overwrite " + field)
            if not Path(path).parent.is_dir():
                _fail("invalid_request", "Output directory does not exist")
            result.append(path)
    inputs = [os.path.realpath(request[field]) for field in ("input_step", "input_native")
              if isinstance(request.get(field), str)]
    resolved = [os.path.realpath(path) for path in result]
    if len(set(resolved)) != len(resolved) or any(path in inputs for path in resolved):
        _fail("invalid_request", "Outputs must be distinct from each other and inputs")
    report = os.path.realpath(_path(request, "report_path"))
    if report in resolved or report in inputs:
        _fail("invalid_request", "Report must be distinct from CAD files")


def _solid(shape, code):
    if shape.isNull() or not shape.isValid() or len(shape.Solids) != 1:
        _fail(code, "Expected one valid solid")
    # STEP readers often wrap a solid in a compound. Reject loose extra geometry.
    def only_solids(item):
        if item.ShapeType == "Solid":
            return True
        if item.ShapeType not in ("Compound", "CompSolid"):
            return False
        children = item.childShapes()
        return bool(children) and all(only_solids(child) for child in children)
    if not only_solids(shape) or not math.isfinite(shape.Volume) or shape.Volume <= 0:
        _fail(code, "Expected a single solid without loose geometry")
    return shape.Solids[0]


def _reference(plan):
    """Independent Part-kernel construction; never used as the native feature."""
    plate = plan["plate"]
    width, height, thickness = (plate[key] for key in ("width", "height", "thickness"))
    shape = Part.makeBox(width, height, thickness, App.Vector(-width / 2, -height / 2, 0))
    pocket = plan["pocket"]
    if pocket:
        tool = Part.makeBox(pocket["width"], pocket["height"], pocket["depth"],
                            App.Vector(-pocket["width"] / 2, -pocket["height"] / 2,
                                       thickness - pocket["depth"]))
        shape = shape.cut(tool)
    for hole in plan["holes"]:
        shape = shape.cut(Part.makeCylinder(hole["diameter"] / 2, thickness,
                                           App.Vector(hole["x"], hole["y"], 0)))
    return _solid(shape, "invalid_plan")


def _difference(actual, expected, tolerance):
    volumes = (actual.cut(expected).Volume, expected.cut(actual).Volume)
    difference = sum(abs(value) for value in volumes)
    if not all(math.isfinite(value) for value in volumes) or difference > tolerance:
        _fail("shape_mismatch", "Symmetric difference %.12g mm3 exceeds %.12g mm3" %
              (difference, tolerance))
    return difference


def _constraint(sketch, name, *arguments):
    index = sketch.addConstraint(Sketcher.Constraint(*arguments))
    sketch.renameConstraint(index, name)
    return index


def _rectangle(body, name, width, height, z):
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.Placement.Base = App.Vector(0, 0, z)
    points = [(-width / 2, -height / 2), (width / 2, -height / 2),
              (width / 2, height / 2), (-width / 2, height / 2)]
    for index in range(4):
        start, end = points[index], points[(index + 1) % 4]
        sketch.addGeometry(Part.LineSegment(App.Vector(*start, 0), App.Vector(*end, 0)), False)
    for index in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", index, 2, (index + 1) % 4, 1))
        sketch.addConstraint(Sketcher.Constraint("Horizontal" if index % 2 == 0 else "Vertical", index))
    _constraint(sketch, "Width", "Distance", 0, width)
    _constraint(sketch, "Height", "Distance", 1, height)
    _constraint(sketch, "OriginX", "DistanceX", 0, 1, -width / 2)
    _constraint(sketch, "OriginY", "DistanceY", 0, 1, -height / 2)
    return sketch


def _holes(body, plan):
    sketch = body.newObject("Sketcher::SketchObject", "HolesSketch")
    sketch.Placement.Base = App.Vector(0, 0, plan["plate"]["thickness"])
    for index, hole in enumerate(plan["holes"]):
        sketch.addGeometry(Part.Circle(App.Vector(hole["x"], hole["y"], 0),
                                       App.Vector(0, 0, 1), hole["diameter"] / 2), False)
        _constraint(sketch, "Hole%dX" % index, "DistanceX", index, 3, hole["x"])
        _constraint(sketch, "Hole%dY" % index, "DistanceY", index, 3, hole["y"])
        if plan["hole_relation"] == "equal_diameter" and index:
            _constraint(sketch, "Hole%dEqual" % index, "Equal", 0, index)
        else:
            _constraint(sketch, "Hole%dDiameter" % index, "Diameter", index, hole["diameter"])
    return sketch


def _metadata(body, plan):
    if "CADBridgePlanJSON" not in body.PropertiesList:
        body.addProperty("App::PropertyString", "CADBridgePlanJSON", "CADBridge")
        body.addProperty("App::PropertyString", "CADBridgeInformationGroup", "CADBridge")
    body.CADBridgePlanJSON = _canonical(plan)
    body.CADBridgeInformationGroup = "known_plan_fixture"


def _build(plan):
    doc = App.newDocument("CADBridge")
    body = doc.addObject("PartDesign::Body", "Body")
    plate = plan["plate"]
    sketch = _rectangle(body, "PlateSketch", plate["width"], plate["height"], 0)
    doc.recompute()
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Length = plate["thickness"]
    doc.recompute()
    sketch.Visibility = False
    if plan["pocket"]:
        pocket = plan["pocket"]
        sketch = _rectangle(body, "PocketSketch", pocket["width"], pocket["height"], plate["thickness"])
        doc.recompute()
        feature = body.newObject("PartDesign::Pocket", "Pocket")
        feature.Profile = sketch
        feature.Length = pocket["depth"]
        doc.recompute()
        sketch.Visibility = False
        pad.Visibility = False
    if plan["holes"]:
        sketch = _holes(body, plan)
        doc.recompute()
        feature = body.newObject("PartDesign::Pocket", "Holes")
        feature.Profile = sketch
        feature.Type = 1  # Through all; remains through when plate thickness changes.
        doc.recompute()
        sketch.Visibility = False
    _metadata(body, plan)
    doc.recompute()
    return doc


def _expected_types(plan):
    result = {"Body": "PartDesign::Body", "PlateSketch": "Sketcher::SketchObject",
              "Pad": "PartDesign::Pad"}
    if plan["pocket"]:
        result.update(PocketSketch="Sketcher::SketchObject", Pocket="PartDesign::Pocket")
    if plan["holes"]:
        result.update(HolesSketch="Sketcher::SketchObject", Holes="PartDesign::Pocket")
    return result


def _dimensions(plan):
    result = {}
    for name, dimensions in (("PlateSketch", plan["plate"]), ("PocketSketch", plan["pocket"])):
        if dimensions is not None:
            result[name] = {"Width": dimensions["width"], "Height": dimensions["height"],
                            "OriginX": -dimensions["width"] / 2,
                            "OriginY": -dimensions["height"] / 2}
    if plan["holes"]:
        result["HolesSketch"] = {}
        for index, hole in enumerate(plan["holes"]):
            result["HolesSketch"].update({"Hole%dX" % index: hole["x"], "Hole%dY" % index: hole["y"]})
            if plan["hole_relation"] == "independent" or index == 0:
                result["HolesSketch"]["Hole%dDiameter" % index] = hole["diameter"]
    return result


def _observe(doc, expected_plan=None):
    body = doc.getObject("Body")
    if body is None or "CADBridgePlanJSON" not in body.PropertiesList:
        _fail("invalid_native", "Missing CADBridge body metadata")
    try:
        plan = _plan(json.loads(body.CADBridgePlanJSON))
    except (ValueError, TypeError) as error:
        _fail("invalid_native", "Invalid CADBridge metadata: " + str(error))
    if expected_plan is not None and plan != expected_plan:
        _fail("previous_plan_mismatch", "Native metadata does not match the expected plan")
    expected_types = _expected_types(plan)
    origin_types = {"Origin": "App::Origin", "X_Axis": "App::Line", "Y_Axis": "App::Line",
                    "Z_Axis": "App::Line", "XY_Plane": "App::Plane", "XZ_Plane": "App::Plane",
                    "YZ_Plane": "App::Plane"}
    actual_types = {obj.Name: obj.TypeId for obj in doc.Objects}
    if actual_types != dict(expected_types, **origin_types):
        _fail("invalid_native", "Unexpected native objects or feature types: " + str(actual_types))
    if body.CADBridgeInformationGroup != "known_plan_fixture":
        _fail("invalid_native", "Unexpected input information group")
    if body.Placement.Base.Length > 1e-8 or abs(body.Placement.Rotation.Angle) > 1e-8:
        _fail("invalid_native", "Unexpected body placement")
    constraints, constrained, parameters = {}, {}, {}
    dimensions = _dimensions(plan)
    for name, type_id in expected_types.items():
        obj = doc.getObject(name)
        if obj is not body and obj not in body.Group:
            _fail("invalid_native", "Feature is outside its PartDesign body")
        if type_id == "Sketcher::SketchObject":
            if obj.solve() != 0 or not obj.FullyConstrained:
                _fail("invalid_native", "Sketch is not fully constrained: " + name)
            constraints[name] = obj.ConstraintCount
            constrained[name] = bool(obj.FullyConstrained)
            parameters[name] = {constraint.Name: obj.getDatum(i).Value
                                for i, constraint in enumerate(obj.Constraints)
                                if constraint.Name and constraint.Name.endswith(
                                    ("Width", "Height", "OriginX", "OriginY", "X", "Y", "Diameter"))}
            if set(parameters[name]) != set(dimensions[name]) or any(
                    not math.isclose(parameters[name][key], value, rel_tol=0, abs_tol=1e-8)
                    for key, value in dimensions[name].items()):
                _fail("invalid_native", "Native sketch dimensions differ from metadata: " + name)
            expected_z = 0 if name == "PlateSketch" else plan["plate"]["thickness"]
            if (obj.Placement.Base - App.Vector(0, 0, expected_z)).Length > 1e-8 or \
                    abs(obj.Placement.Rotation.Angle) > 1e-8:
                _fail("invalid_native", "Unexpected sketch placement: " + name)
            if name == "HolesSketch":
                if obj.GeometryCount != len(plan["holes"]) or obj.ConstraintCount != 3 * len(plan["holes"]):
                    _fail("invalid_native", "Unexpected hole geometry or constraint count")
                equal = [(constraint.First, constraint.Second) for constraint in obj.Constraints
                         if constraint.Type == "Equal"]
                expected_equal = [(0, index) for index in range(1, len(plan["holes"]))] \
                    if plan["hole_relation"] == "equal_diameter" else []
                if equal != expected_equal:
                    _fail("invalid_native", "Native equal-diameter relation differs from metadata")
                for index, hole in enumerate(plan["holes"]):
                    circle = obj.Geometry[index]
                    if not isinstance(circle, Part.Circle) or \
                            abs(circle.Radius * 2 - hole["diameter"]) > 1e-8:
                        _fail("invalid_native", "Native hole diameters differ from metadata")
            elif obj.GeometryCount != 4 or obj.ConstraintCount != 12:
                _fail("invalid_native", "Unexpected rectangle geometry or constraint count")
        elif type_id in ("PartDesign::Pad", "PartDesign::Pocket"):
            _solid(obj.Shape, "invalid_native")
            if "Invalid" in obj.State or "Error" in obj.State:
                _fail("invalid_native", "Native feature is in error: " + name)
            parameters[name] = {"length_mm": obj.Length.Value}
            expected_profile = "PlateSketch" if name == "Pad" else "PocketSketch" if name == "Pocket" else "HolesSketch"
            profile = obj.Profile[0] if isinstance(obj.Profile, (tuple, list)) else obj.Profile
            if profile is not doc.getObject(expected_profile):
                _fail("invalid_native", "Unexpected sketch profile: " + name)
            expected_length = plan["plate"]["thickness"] if name == "Pad" else \
                plan["pocket"]["depth"] if name == "Pocket" else None
            if expected_length is not None and abs(obj.Length.Value - expected_length) > 1e-8:
                _fail("invalid_native", "Native feature length differs from metadata: " + name)
            if type_id == "PartDesign::Pocket":
                parameters[name]["type"] = str(obj.Type)
                expected_type_index = 1 if name == "Holes" else 0
                if obj.getEnumerationsOfProperty("Type").index(str(obj.Type)) != expected_type_index:
                    _fail("invalid_native", "Unexpected pocket termination mode")
    expected_tip = "Holes" if plan["holes"] else "Pocket" if plan["pocket"] else "Pad"
    if body.Tip is not doc.getObject(expected_tip):
        _fail("invalid_native", "Unexpected PartDesign body tip")
    shape = _solid(body.Shape, "invalid_native")
    return {"plan": plan, "volume_mm3": shape.Volume,
            "native_features": [{"name": obj.Name, "type": obj.TypeId} for obj in doc.Objects
                                if obj.Name in expected_types],
            "sketch_constraints": constraints, "sketch_fully_constrained": constrained,
            "native_parameters": parameters, "solid_count": 1, "shape_valid": True}


def _set(sketch, name, value):
    indices = [index for index, constraint in enumerate(sketch.Constraints) if constraint.Name == name]
    if len(indices) != 1:
        _fail("invalid_native", "Missing or duplicate dimensional constraint: " + name)
    sketch.setDatum(indices[0], App.Units.Quantity(value))


def _edit(doc, previous, plan):
    if previous == plan:
        _fail("unsupported_edit", "Edit must change at least one existing parameter")
    if (previous["pocket"] is None) != (plan["pocket"] is None) or \
            len(previous["holes"]) != len(plan["holes"]) or \
            previous["hole_relation"] != plan["hole_relation"]:
        _fail("unsupported_edit", "Edits cannot change native feature structure or hole relations")
    for name, dimensions in (("PlateSketch", plan["plate"]), ("PocketSketch", plan["pocket"])):
        if dimensions is None:
            continue
        sketch = doc.getObject(name)
        # Set center offsets as well as dimensions to keep the rectangle centered.
        for key, value in (("Width", dimensions["width"]), ("Height", dimensions["height"]),
                           ("OriginX", -dimensions["width"] / 2),
                           ("OriginY", -dimensions["height"] / 2)):
            _set(sketch, key, value)
    doc.Pad.Length = plan["plate"]["thickness"]
    if plan["pocket"]:
        doc.PocketSketch.Placement.Base = App.Vector(0, 0, plan["plate"]["thickness"])
        doc.Pocket.Length = plan["pocket"]["depth"]
    if plan["holes"]:
        doc.HolesSketch.Placement.Base = App.Vector(0, 0, plan["plate"]["thickness"])
        for index, hole in enumerate(plan["holes"]):
            _set(doc.HolesSketch, "Hole%dX" % index, hole["x"])
            _set(doc.HolesSketch, "Hole%dY" % index, hole["y"])
            if plan["hole_relation"] == "independent" or index == 0:
                _set(doc.HolesSketch, "Hole%dDiameter" % index, hole["diameter"])
    _metadata(doc.Body, plan)
    doc.recompute()


def _save_reopen(doc, output, plan):
    doc.recompute()
    doc.saveAs(output)
    App.closeDocument(doc.Name)
    reopened = App.openDocument(output)
    reopened.recompute()
    return reopened, _observe(reopened, plan)


def _run(request):
    action = request.get("action")
    if action not in ("fixture", "reconstruct", "edit", "inspect"):
        _fail("invalid_request", "Unsupported worker action")
    _output_paths(request)
    tolerance = request.get("volume_tolerance_mm3", 1e-5)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or \
            not math.isfinite(tolerance) or tolerance < 0:
        _fail("invalid_request", "Invalid volume comparison tolerance")
    report = {"status": "ok", "action": action, "freecad_version": ".".join(App.Version()[:3]),
              "input_information_group": "known_plan_fixture", "product_acceptance": "not_assessed"}
    if action == "inspect":
        doc = App.openDocument(_path(request, "input_native"))
        doc.recompute()
        plan = _plan(request["plan"]) if "plan" in request else None
        report.update(_observe(doc, plan))
        report["symmetric_difference_mm3"] = _difference(doc.Body.Shape, _reference(report["plan"]), tolerance)
        report["reopened"] = True
        App.closeDocument(doc.Name)
        return report
    plan = _plan(request.get("plan"))
    reference = _reference(plan)
    if action == "fixture":
        reference.exportStep(_path(request, "output_step"))
        report.update(plan=plan, volume_mm3=reference.Volume, native_features=[], sketch_constraints={},
                      reopened=False, fixture_builder="Part kernel")
        return report
    output = _path(request, "output_native")
    if action == "reconstruct":
        try:
            source = _solid(Part.read(_path(request, "input_step")), "invalid_step")
        except WorkerError:
            raise
        except Exception as error:
            _fail("invalid_step", "Cannot read STEP: " + str(error))
        # Reject mismatching input before constructing or saving a native document.
        _difference(source, reference, tolerance)
        doc = _build(plan)
        _observe(doc, plan)
        difference = _difference(doc.Body.Shape, source, tolerance)
    else:
        previous = _plan(request.get("previous_plan"))
        doc = App.openDocument(_path(request, "input_native"))
        doc.recompute()
        _observe(doc, previous)
        _difference(doc.Body.Shape, _reference(previous), tolerance)
        names_before = [(obj.Name, obj.TypeId) for obj in doc.Objects]
        _edit(doc, previous, plan)
        _observe(doc, plan)
        if names_before != [(obj.Name, obj.TypeId) for obj in doc.Objects]:
            _fail("invalid_native", "Edit replaced the native feature structure")
        difference = _difference(doc.Body.Shape, reference, tolerance)
    doc, observation = _save_reopen(doc, output, plan)
    # Verify the actual serialized solid, not only the in-memory model.
    difference = _difference(doc.Body.Shape, source if action == "reconstruct" else reference, tolerance)
    if "output_step" in request:
        doc.Body.Shape.exportStep(_path(request, "output_step"))
    report.update(observation)
    report.update(symmetric_difference_mm3=difference, reopened=True)
    App.closeDocument(doc.Name)
    return report


def main():
    request = None
    report_path = None
    try:
        request_path = os.environ["CADBRIDGE_REQUEST"]
        with open(request_path, encoding="utf-8") as handle:
            request = json.load(handle)
        if not isinstance(request, dict):
            _fail("invalid_request", "Request must be an object")
        candidate = _path(request, "report_path")
        # A bad report target must never truncate a CAD input, output, or request.
        reserved = [request_path] + [request[field] for field in
                    ("input_step", "input_native", "output_native", "output_step")
                    if isinstance(request.get(field), str)]
        if any(_same_path(candidate, path) for path in reserved):
            _fail("invalid_request", "Report must be distinct from CAD files and request")
        report_path = candidate
        global App, Part, Sketcher
        import FreeCAD as App
        import Part
        import Sketcher
        result = _run(request)
    except Exception as error:
        result = {"status": "error", "action": request.get("action") if isinstance(request, dict) else None,
                  "code": getattr(error, "code", "freecad_error"), "message": str(error),
                  "input_information_group": "known_plan_fixture", "product_acceptance": "not_assessed"}
    if report_path is not None:
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
    else:
        print(json.dumps(result, ensure_ascii=False))


# FreeCAD executes command-line .py files as imported modules, so __name__ is
# not reliably __main__. The request environment variable is the fixed entry.
if __name__ == "__main__" or "CADBRIDGE_REQUEST" in os.environ:
    main()

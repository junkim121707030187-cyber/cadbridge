"""Small, real OpenCascade backend for this prototype's bounded geometry.

Uses OCP directly; no CAD application, CadQuery sketch solver, NLP solver, or
general VTK rendering pipeline is required. This is not a native CAD feature tree.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import re

if sys.platform == "win32":
    # Initialize the installed VTK data-model types used by the OCP wheel.
    import vtkmodules.vtkCommonDataModel  # noqa: F401

from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepTools import BRepTools
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.Message import Message, Message_Fail
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.gp import gp_Pnt, gp_Dir, gp_Ax2, gp_Vec, gp_Trsf

for _printer in Message.DefaultMessenger_s().Printers():
    _printer.SetTraceLevel(Message_Fail)


@dataclass(frozen=True)
class Vector:
    x: float
    y: float
    z: float

    def toTuple(self):
        return self.x, self.y, self.z


@dataclass(frozen=True)
class BoundBox:
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def xlen(self): return self.xmax-self.xmin

    @property
    def ylen(self): return self.ymax-self.ymin

    @property
    def zlen(self): return self.zmax-self.zmin


class Shape:
    def __init__(self, wrapped):
        if wrapped.IsNull():
            raise ValueError("Null OpenCascade shape")
        self.wrapped = wrapped

    def _children(self, kind, cls, caster):
        shapes = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(self.wrapped, kind, shapes)
        return [cls(caster(shapes.FindKey(i))) for i in range(1, shapes.Extent()+1)]

    def Solids(self): return self._children(TopAbs_SOLID, Shape, TopoDS.Solid_s)

    def Faces(self): return self._children(TopAbs_FACE, Face, TopoDS.Face_s)

    def Edges(self): return self._children(TopAbs_EDGE, Edge, TopoDS.Edge_s)

    def Vertices(self): return self._children(TopAbs_VERTEX, Vertex, TopoDS.Vertex_s)

    def isValid(self): return bool(BRepCheck_Analyzer(self.wrapped).IsValid())

    def Volume(self):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(self.wrapped, props)
        return props.Mass()

    def Area(self):
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(self.wrapped, props)
        return props.Mass()

    def BoundingBox(self):
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(self.wrapped, box, False, False)
        if box.IsVoid():
            raise ValueError("Empty shape bounding box")
        return BoundBox(*box.Get())

    def cut(self, other):
        operation = BRepAlgoAPI_Cut(self.wrapped, other.wrapped)
        operation.Build()
        if not operation.IsDone():
            raise ValueError("OpenCascade Boolean cut failed")
        return Shape(operation.Shape())

    def clean(self):
        operation = ShapeUpgrade_UnifySameDomain(self.wrapped, True, True, True)
        operation.Build()
        return Shape(operation.Shape())

    def translate(self, delta):
        transform = gp_Trsf()
        transform.SetTranslation(gp_Vec(*delta))
        return Shape(BRepBuilderAPI_Transform(self.wrapped, transform, True).Shape())

    def distance(self, other):
        operation = BRepExtrema_DistShapeShape(self.wrapped, other.wrapped)
        if not operation.IsDone():
            raise ValueError("OpenCascade boundary distance failed")
        return operation.Value()

    def tessellate(self, tolerance=0.05, angularTolerance=0.15):
        mesh = BRepMesh_IncrementalMesh(self.wrapped, tolerance, False, angularTolerance, False)
        if not mesh.IsDone():
            raise ValueError("OpenCascade tessellation failed")
        vertices, triangles = [], []
        for face in self.Faces():
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face.wrapped, location)
            if triangulation is None:
                raise ValueError("OpenCascade face has no triangulation")
            offset = len(vertices)
            for i in range(1, triangulation.NbNodes()+1):
                p = triangulation.Node(i).Transformed(location.Transformation())
                vertices.append(Vector(p.X(), p.Y(), p.Z()))
            reverse = face.wrapped.Orientation() == TopAbs_REVERSED
            for i in range(1, triangulation.NbTriangles()+1):
                tri = triangulation.Triangle(i)
                indices = [tri.Value(j)+offset-1 for j in (1, 2, 3)]
                if reverse:
                    indices[1], indices[2] = indices[2], indices[1]
                triangles.append(tuple(indices))
        return vertices, triangles


class Face(Shape):
    def geomType(self):
        return str(BRepAdaptor_Surface(self.wrapped, True).GetType()).split("GeomAbs_")[-1].upper()

    def normalAt(self):
        u0, u1, v0, v1 = BRepTools.UVBounds_s(self.wrapped)
        p, n = gp_Pnt(), gp_Vec()
        BRepGProp_Face(self.wrapped).Normal((u0+u1)/2, (v0+v1)/2, p, n)
        n.Normalize()
        return Vector(n.X(), n.Y(), n.Z())

    def outerWire(self):
        return Shape(BRepTools.OuterWire_s(self.wrapped))


class Edge(Shape):
    def geomType(self):
        return str(BRepAdaptor_Curve(self.wrapped).GetType()).split("GeomAbs_")[-1].upper()


class Vertex(Shape):
    def Center(self):
        p = BRep_Tool.Pnt_s(self.wrapped)
        return Vector(p.X(), p.Y(), p.Z())


def make_box(length, width, height, origin=(0, 0, 0)) -> Shape:
    return Shape(BRepPrimAPI_MakeBox(gp_Pnt(*origin), length, width, height).Shape())


def make_cylinder(radius, height, origin=(0, 0, 0), direction=(0, 0, 1)) -> Shape:
    axis = gp_Ax2(gp_Pnt(*origin), gp_Dir(*direction))
    return Shape(BRepPrimAPI_MakeCylinder(axis, radius, height).Shape())


def make_vertex(x, y, z) -> Vertex:
    return Vertex(BRepBuilderAPI_MakeVertex(gp_Pnt(x, y, z)).Vertex())


def compound(shapes) -> Shape:
    output, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(output)
    for shape in shapes:
        builder.Add(output, shape.wrapped)
    return Shape(output)


def _step_failure_messages(checks) -> list[str]:
    """Return reported failures; ordinary STEP warnings do not reject input."""
    if checks.IsEmpty(True):
        return []
    messages = []
    checks.Start()
    while checks.More() and len(messages) < 5:
        check = checks.Value()
        for index in range(1, check.NbFails()+1):
            messages.append(check.CFail(index))
            if len(messages) == 5:
                break
        checks.Next()
    return messages or ["OpenCascade reported an unspecified failure"]


def _validate_step_envelope(path: str | Path) -> None:
    """Reject ignored trailing exchanges/payload in the supported Part 21 file.

    OCCT may stop at the first END-ISO marker. Strip quoted strings and block
    comments for this envelope check so marker-like labels remain valid data.
    This is a boundary check, not a replacement for OCCT's STEP parser.
    """
    data = Path(path).read_bytes()
    # Escaped apostrophes in Part 21 strings are represented by doubled quotes.
    tokens = re.compile(rb"'(?:[^']|'')*'|/\*.*?\*/", re.DOTALL)
    structural = tokens.sub(b' ', data).strip()
    if structural.startswith(b'\xef\xbb\xbf'):
        structural = structural[3:].lstrip()
    start, end = b'ISO-10303-21;', b'END-ISO-10303-21;'
    markers = re.findall(rb'(?<![A-Z0-9_-])(?:END-)?ISO-10303-21;', structural)
    if not structural.startswith(start) or not structural.endswith(end) or markers != [start, end]:
        raise ValueError('STEP requires one complete Part 21 exchange with no trailing payload')


def read_step(path: str | Path) -> Shape:
    _validate_step_envelope(path)
    reader = STEPControl_Reader()
    read_status = reader.ReadFile(str(path))
    if read_status != IFSelect_RetDone:
        raise ValueError(f"STEP file could not be loaded (read status: {read_status})")
    load_failures = _step_failure_messages(reader.WS().ModelCheckList(True))
    if load_failures:
        raise ValueError("STEP load validation failed: " + "; ".join(load_failures))
    reader.SetSystemLengthUnit(1.0)  # mm, including inch-labelled source files
    candidates = reader.NbRootsForTransfer()
    if candidates <= 0:
        raise ValueError("STEP file contains no transferable shape roots")
    # TransferRoots returns successful translations, not candidate count.
    # Accepting any nonzero count could silently discard a failed assembly part.
    transferred = reader.TransferRoots()
    if transferred != candidates:
        raise ValueError(f"Incomplete STEP transfer: translated {transferred} of {candidates} candidate roots")
    transfer_failures = _step_failure_messages(reader.WS().TransferReader().LastCheckList())
    if transfer_failures:
        raise ValueError("STEP transfer validation failed: " + "; ".join(transfer_failures))
    if reader.NbShapes() <= 0:
        raise ValueError("STEP transfer produced no shapes")
    return compound([Shape(reader.Shape(i)) for i in range(1, reader.NbShapes()+1)])


def write_step(shape: Shape, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = STEPControl_Writer()
    # The focused backend always executes and exports millimetre models.
    if not Interface_Static.SetCVal_s("write.step.unit", "MM"):
        raise ValueError("Could not configure STEP millimetre export")
    writer.Model().SetLocalLengthUnit(1.0)
    writer.Model().SetWriteLengthUnit(1.0)
    if writer.Transfer(shape.wrapped, STEPControl_AsIs) != IFSelect_RetDone:
        raise ValueError("STEP transfer failed")
    if writer.Write(str(target)) != IFSelect_RetDone:
        raise ValueError("STEP write failed")

"""Trusted GUI initialization; CADBRIDGE_OPEN_REQUEST is set by the launcher."""
import hashlib
import json
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui

request = json.loads(Path(CADBRIDGE_OPEN_REQUEST).read_text(encoding="utf-8"))
source = Path(request["source"])
working = Path(request["working_copy"])
try:
    if hashlib.sha256(source.read_bytes()).hexdigest() != request["source_sha256"]:
        raise ValueError("Source version changed")
    doc = App.openDocument(str(working))
    body = doc.getObject("Body")
    if body is None or body.Tip is None:
        raise ValueError("Native body and feature tip are required")
    for obj in doc.Objects:
        if obj.ViewObject is not None:
            obj.ViewObject.Visibility = obj is body or obj is body.Tip
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.activeDocument().activeView().fitAll()
    Gui.activeDocument().activeView().redraw()
    doc.recompute()
    doc.save()
    if hashlib.sha256(source.read_bytes()).hexdigest() != request["source_sha256"]:
        raise ValueError("Opening changed the preserved source")
    report = {"status": "ok", "working_copy": str(working), "source_preserved": True,
              "body_visible": bool(body.ViewObject.Visibility),
              "tip_visible": bool(body.Tip.ViewObject.Visibility), "freecad_version": ".".join(App.Version()[:3])}
except Exception as error:
    report = {"status": "error", "message": str(error)}
Path(request["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

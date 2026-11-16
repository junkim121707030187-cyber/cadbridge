"""Declare implemented support separately from software detection."""
import importlib.util
import os


def _registered(progid):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid):
            return True
    except (ImportError, OSError):
        return False


def capabilities():
    return {
        "common_ir": "cadbridge-0.1 / millimeters / global XY / one plate solid",
        "occt": {"implemented": True, "detected": importlib.util.find_spec("OCP") is not None, "output": "STEP + editable parameter JSON", "native_feature_tree": False, "runtime_status": "UNVERIFIED until per-run evidence", "geometry_validation_status": "UNVERIFIED until per-run evidence"},
        "catia": {"implemented": False, "detected": _registered("CATIA.Application"), "planned_output": "CATPart + STEP via installed CATIA V5", "runtime_status": "UNVERIFIED", "native_validation_status": "UNVERIFIED", "validation_status": "UNSUPPORTED", "note": "Adapter is not yet connected; software registration does not prove native generation."},
        "solidworks": {"implemented": False, "detected": _registered("SldWorks.Application"), "planned_mapping": {"base": "Boss-Extrude", "pocket": "Cut-Extrude", "hole": "Cut-Extrude"}, "validation_status": "UNSUPPORTED"},
        "nx": {"implemented": False, "detected": bool(os.environ.get("UGII_BASE_DIR")), "planned_mapping": {"base": "Extrude", "pocket": "Extrude/Subtract", "hole": "Extrude/Subtract"}, "validation_status": "UNSUPPORTED"},
        "policy": "Neutral STEP input may originate in any exporter, but cross-tool/version compatibility is only proven by recorded execution. Planned mappings are not adapters.",
    }

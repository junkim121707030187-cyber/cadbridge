"""Executed common-engine target and explicit unsupported native boundaries.

Adapters bind the candidate to an observation and source file, preserve
provenance, solve before geometry, and persist save/reopen/regenerate evidence.
STEP output transports geometry; the separate CADBridge IR preserves our
editable reconstruction hypothesis, never a vendor-native feature history.
"""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from .observations import observe_step, validate_observation


class FormatReader(Protocol):
    format_name: str

    def read(self, path: str | Path) -> dict: ...


class TargetAdapter(Protocol):
    name: str
    version: str

    def execute(self, ir: dict, out_dir: str | Path, *, observation: dict,
                source_step: str | Path, edits: dict | None = None) -> dict: ...


class RestrictedStepReader:
    format_name = "STEP"

    def read(self, path):
        return observe_step(path)


class OCCTStepAdapter:
    name = "occt-step"

    @property
    def version(self):
        try:
            return version("cadquery-ocp")
        except PackageNotFoundError:
            return "unavailable"

    def execute(self, ir, out_dir, *, observation, source_step, edits=None):
        # Import locally: pipeline may resolve this adapter without import cycles.
        from .pipeline import execute_candidate, dump

        validate_observation(observation)
        out = Path(out_dir)
        if out.exists():
            raise ValueError("output_already_exists")
        result = execute_candidate(ir, observation, source_step, out, edits)
        target = {"schema_version": "cadbridge.target-execution/1",
                  "name": self.name, "engine_distribution": "cadquery-ocp",
                  "engine_version": self.version, "status": result["status"],
                  "native_application_executed": False,
                  "native_editable_history": False,
                  "editable_representation": "cadbridge.ir/1",
                  "exchange_format": "STEP", "units": "mm",
                  "checks": {key: result.get(key, {}).get("status", "NOT_RUN")
                             for key in ("source_geometry", "roundtrip_geometry",
                                         "ir_reload_regeneration")},
                  "edit_transaction_applied": edits is not None,
                  "validation": "validation.json"}
        dump(out / "target.json", target)
        result["target"] = target
        return result


READERS = {"step": RestrictedStepReader(), "stp": RestrictedStepReader()}
TARGETS = {"occt-step": OCCTStepAdapter()}


def read_input(path, format_name=None):
    fmt = (format_name or Path(path).suffix.lstrip(".")).lower()
    if fmt not in READERS:
        raise ValueError("unsupported_input_format:" + fmt)
    return READERS[fmt].read(path)


def require_target(target):
    if not isinstance(target, str) or target not in TARGETS:
        raise ValueError("unsupported_native_target:" + str(target) +
                         "; creation/save/close/reopen/edit/regenerate not verified")
    return TARGETS[target]


def target_status():
    return {"available_targets": [{"name": item.name, "version": item.version,
                                    "native_application": False}
                                   for item in TARGETS.values()],
            "native_targets": "UNIMPLEMENTED_UNVERIFIED"}


SUPPORT_MATRIX = {
    "STEP": {"reader": "restricted_verified", "target": "geometry_exchange_verified",
             "target_adapter": "occt-step", "native_editable_history": False,
             "editable_sidecar": "cadbridge.ir/1"},
    **{name: {"reader": "unimplemented", "target": "unimplemented",
              "native_version_validation": []}
       for name in ["JT", "Parasolid", "CATIA", "SOLIDWORKS", "NX"]}
}

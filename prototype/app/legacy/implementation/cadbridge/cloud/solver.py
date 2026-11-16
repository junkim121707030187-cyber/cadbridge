"""Executable affine constraints for the explicitly limited CADBridge IR.

This is a scalar, linear constraint solver, not a general nonlinear sketch solver.
Parameter ``value`` fields are observations/initial guesses, never implicit locks.
Dimension and signed offset constraints can be edited by replacing their RHS.
An underconstrained system returns its minimum-norm representative for diagnostics,
but callers must reject it for geometry execution.  Rank/DOF refer to this affine
parameter system only, not to every geometric freedom of an arbitrary CAD sketch.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import Any

import numpy as np


class ConstraintSolveError(ValueError):
    """Malformed, unsupported or numerically unsafe solver input."""


_ARITY = {"dimension": 1, "equal": 2, "offset": 2, "symmetric": 3}
_MAX_PARAMETERS = 1024
_MAX_CONSTRAINTS = 4096
_ABS_TOL = 1.0e-9
_REL_TOL = 1.0e-12
_MAX_CONDITION = 1.0e8  # Conservative supported numerical boundary, not an accuracy certificate.


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ConstraintSolveError(f"{context} must be a finite real number")
    try:
        result = float(value)
    except (OverflowError, ValueError, TypeError) as exc:
        raise ConstraintSolveError(f"{context} must be a finite real number") from exc
    if not np.isfinite(result):
        raise ConstraintSolveError(f"{context} must be a finite real number")
    return result


def _indexed_records(value: Any, label: str, limit: int) -> dict[str, dict]:
    if not isinstance(value, list):
        raise ConstraintSolveError(f"{label} must be an array")
    if len(value) > limit:
        raise ConstraintSolveError(f"{label} exceeds solver limit {limit}")
    result = {}
    for record in value:
        if not isinstance(record, Mapping):
            raise ConstraintSolveError(f"Each {label} entry must be an object")
        identifier = record.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ConstraintSolveError(f"Each {label} entry needs a nonempty string id")
        if identifier in result:
            raise ConstraintSolveError(f"Duplicate {label} id: {identifier}")
        result[identifier] = record
    return result


def solve(ir: dict, edits: dict[str, float] | None = None) -> dict:
    """Solve dimension/equal/offset/symmetric equations without mutating ``ir``.

    ``edits`` is keyed by DIMENSION/OFFSET CONSTRAINT ID, not parameter ID. Contradictory
    equations return ``status='inconsistent'`` and their least-squares residuals;
    malformed or unsupported input raises :class:`ConstraintSolveError`.

    The rank and nullity are computed from actual equation coefficients using
    NumPy's SVD least-squares solver.  ``redundant_equations = equation_count-rank``
    describes row dependence, also when dependent rows contradict one another.
    ``inconsistent_constraints`` reports residual-bearing equations, not a
    guaranteed minimal conflict set.  No approval or execution decision is made
    here; the caller owns candidate validation and execution policy.
    """
    if not isinstance(ir, Mapping):
        raise ConstraintSolveError("IR must be an object")
    parameters = _indexed_records(ir.get("parameters"), "parameters", _MAX_PARAMETERS)
    constraints = _indexed_records(ir.get("constraints"), "constraints", _MAX_CONSTRAINTS)
    for identifier, parameter in parameters.items():
        _finite_number(parameter.get("value"), f"Parameter {identifier} value")

    if edits is None:
        edits = {}
    if not isinstance(edits, Mapping):
        raise ConstraintSolveError("edits must map dimension or offset constraint IDs to numbers")
    checked_edits = {}
    for identifier, value in edits.items():
        if not isinstance(identifier, str) or identifier not in constraints:
            raise ConstraintSolveError(f"Unknown driving constraint edit ID: {identifier!r}")
        if constraints[identifier].get("type") not in {"dimension", "offset"}:
            raise ConstraintSolveError(f"Only dimension or offset constraints can be edited: {identifier}")
        checked_edits[identifier] = _finite_number(value, f"Edit {identifier}")

    # Canonical row/column order makes repeated and reordered proposals reproducible.
    parameter_ids = sorted(parameters)
    constraint_ids = sorted(constraints)
    columns = {identifier: index for index, identifier in enumerate(parameter_ids)}
    n, m = len(parameter_ids), len(constraint_ids)
    coefficients = np.zeros((m, n), dtype=np.float64)
    rhs = np.zeros(m, dtype=np.float64)
    for row, identifier in enumerate(constraint_ids):
        constraint = constraints[identifier]
        kind = constraint.get("type")
        if not isinstance(kind, str) or kind not in _ARITY:
            raise ConstraintSolveError(f"Unsupported constraint type for {identifier}: {kind!r}")
        refs = constraint.get("refs")
        if not isinstance(refs, list) or len(refs) != _ARITY[kind]:
            raise ConstraintSolveError(f"Constraint {identifier} requires {_ARITY[kind]} refs")
        if any(not isinstance(ref, str) or ref not in columns for ref in refs):
            raise ConstraintSolveError(f"Constraint {identifier} has unknown parameter refs")
        weights = {
            "dimension": (1.0,),
            "equal": (1.0, -1.0),
            "offset": (1.0, -1.0),
            "symmetric": (1.0, 1.0, -2.0),
        }[kind]
        # Accumulate to handle repeated references mathematically (e.g. x=x).
        for ref, weight in zip(refs, weights):
            coefficients[row, columns[ref]] += weight
        if kind in {"dimension", "offset"}:
            original_value = _finite_number(constraint.get("value"), f"Constraint {identifier} value")
            rhs[row] = checked_edits.get(identifier, original_value)
        elif "value" in constraint:
            raise ConstraintSolveError(f"Constraint {identifier} of type {kind} must not have value")

    if m == 0 or n == 0:
        values = np.zeros(n, dtype=np.float64)
        rank = 0
        singular_values = np.empty(0, dtype=np.float64)
    else:
        try:
            # rcond=None uses eps*max(m,n) for numerical SVD rank determination.
            values, _, rank, singular_values = np.linalg.lstsq(coefficients, rhs, rcond=None)
        except np.linalg.LinAlgError as exc:
            raise ConstraintSolveError("Affine constraint SVD failed to converge") from exc
        if not np.all(np.isfinite(values)):
            raise ConstraintSolveError("Affine solution is not finite")

    try:
        with np.errstate(over="raise", invalid="raise"):
            residual = coefficients @ values - rhs
            scale = np.maximum(np.abs(rhs), np.abs(coefficients) @ np.abs(values))
            tolerances = _ABS_TOL + _REL_TOL * scale
    except FloatingPointError as exc:
        raise ConstraintSolveError("Constraint magnitudes exceed safe numerical range") from exc
    if not np.all(np.isfinite(residual)) or not np.all(np.isfinite(tolerances)):
        raise ConstraintSolveError("Constraint residual calculation is not finite")
    conflicting = [identifier for i, identifier in enumerate(constraint_ids) if abs(residual[i]) > tolerances[i]]
    rank = int(rank)
    dof = n - rank
    condition = (float(singular_values[0] / singular_values[-1])
                 if rank == n and n and len(singular_values) and singular_values[-1] > 0 else None)
    ill_conditioned = condition is not None and condition > _MAX_CONDITION
    status = ("inconsistent" if conflicting else "underconstrained" if dof
              else "ill_conditioned" if ill_conditioned else "fully_constrained")
    return {
        "values": {identifier: float(values[i]) for i, identifier in enumerate(parameter_ids)},
        "status": status,
        "degrees_of_freedom": dof,
        "rank": rank,
        "variable_count": n,
        "equation_count": m,
        "redundant_equations": m - rank,
        "max_residual": float(np.max(np.abs(residual))) if m else 0.0,
        "residuals": {identifier: float(residual[i]) for i, identifier in enumerate(constraint_ids)},
        "residual_tolerances": {identifier: float(tolerances[i]) for i, identifier in enumerate(constraint_ids)},
        "inconsistent_constraints": conflicting,
        "applied_edits": dict(sorted(checked_edits.items())),
        "solver": "numpy.linalg.lstsq",
        "solution_policy": "minimum_norm",
        "dof_scope": "affine_scalar_parameter_system",
        "nonlinear_sketch_dof_supported": False,
        "singular_values": [float(value) for value in singular_values],
        "condition_number": condition,
        "condition_limit": _MAX_CONDITION,
        "numerical_policy": "Reject full-rank ill-conditioned systems; small residual alone is not accuracy proof.",
    }

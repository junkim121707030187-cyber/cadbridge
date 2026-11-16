"""Local single-user selection policy; plan hashes are not authentication."""

from .model import BridgeError, plan_sha256


def require_selection(plan: dict, selected_sha: str | None) -> str:
    """Require explicit selection of this canonical plan version.

    This only prevents execution without a selection or with a stale selection.
    It does not establish an approval identity or multi-user authorization.
    """
    current_sha = plan_sha256(plan)
    if type(selected_sha) is not str or not selected_sha:
        raise BridgeError("selection_required", "explicit selection of a plan hash is required")
    if selected_sha != current_sha:
        raise BridgeError("stale_selection", "selected hash does not match the current plan version")
    return current_sha

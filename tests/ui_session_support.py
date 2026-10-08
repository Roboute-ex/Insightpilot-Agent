"""Read AppTest user/widget state across supported Streamlit versions."""
from __future__ import annotations


def session_snapshot(app):
    """Return a shallow filtered snapshot without changing the live session.

    Streamlit 1.65 exposes a dict-like tester wrapper with ``to_dict``;
    older AppTest versions expose SafeSessionState.filtered_state directly.
    Resolve the method on the type so a user-state key cannot mask the API.
    """
    state = app.session_state
    to_dict = getattr(type(state), "to_dict", None)
    if callable(to_dict):
        return to_dict(state)
    return state.filtered_state

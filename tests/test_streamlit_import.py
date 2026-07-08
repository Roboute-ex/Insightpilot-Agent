from __future__ import annotations


def test_streamlit_app_imports_without_starting_server() -> None:
    import app.ui_streamlit as ui

    assert hasattr(ui, "main")
    assert callable(ui.main)

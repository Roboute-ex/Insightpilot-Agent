from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_every_streamlit_json_call_is_explicitly_collapsed() -> None:
    paths = [*PROJECT_ROOT.joinpath("app").rglob("*.py"), *PROJECT_ROOT.joinpath("insightpilot", "ui").rglob("*.py")]
    calls = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "json":
                calls.append(node)
                expanded = next((item.value for item in node.keywords if item.arg == "expanded"), None)
                assert isinstance(expanded, ast.Constant) and expanded.value is False
    assert calls

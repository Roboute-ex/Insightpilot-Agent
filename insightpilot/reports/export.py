"""Report export helpers."""

from __future__ import annotations

from pathlib import Path


def write_text_report(path: str | Path, content: str) -> Path:
    """Write a markdown report and return the resolved path."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target

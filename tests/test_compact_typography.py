from __future__ import annotations

from insightpilot.ui.theme import COMPACT_THEME_CSS


def test_compact_card_typography_uses_required_sizes() -> None:
    assert "font-size: 12pt" in COMPACT_THEME_CSS
    assert "font-size: 10.5pt" in COMPACT_THEME_CSS
    assert ".ip-summary-card" in COMPACT_THEME_CSS

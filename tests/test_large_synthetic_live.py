from __future__ import annotations


def test_live_standard_scale(live_dataset) -> None:
    sessions = live_dataset.tables["live_sessions"]
    assert len(sessions) >= 50_000
    assert sessions["date"].nunique() >= 90


def test_live_buffering_pattern_is_detectable(live_dataset) -> None:
    sessions = live_dataset.tables["live_sessions"]
    target = sessions["date"].max()
    current = sessions[sessions["date"] >= target - __import__("pandas").Timedelta(days=2)]
    risky = current[(current["device"] == "Tablet") & (current["network_type"] == "Cellular")]["buffering_rate"].mean()
    control = current[(current["device"] != "Tablet") | (current["network_type"] != "Cellular")]["buffering_rate"].mean()
    assert risky > control

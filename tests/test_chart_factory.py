from __future__ import annotations

import pandas as pd

from insightpilot.visualization.factory import build_chart, build_charts
from insightpilot.visualization.specs import ChartSpec


def test_chart_factory_handles_empty_data() -> None:
    spec = ChartSpec("empty", "bar", "Empty", "table", x="x", y=["y"])
    assert build_chart(spec, {"table": pd.DataFrame()}) is None
    assert "warning" in spec.metadata


def test_time_series_chart_is_built() -> None:
    spec = ChartSpec("trend", "time_series", "Trend", "table", x="date", y=["metric"])
    frame = pd.DataFrame({"date": ["2026-01-02", "2026-01-01"], "metric": [2, 1]})
    charts = build_charts([spec], {"table": frame})
    assert len(charts) == 1
    assert pd.Timestamp(list(charts[0][1].data[0].x)[0]).day == 1

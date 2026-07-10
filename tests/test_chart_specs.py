from __future__ import annotations

import json

import numpy as np

from insightpilot.visualization.specs import ChartSpec


def test_chart_spec_is_json_serializable() -> None:
    spec = ChartSpec("trend", "time_series", "Trend", "trend_table", x="date", y=["metric"], metadata={"count": np.int64(3)})
    assert json.loads(json.dumps(spec.to_dict()))["metadata"]["count"] == 3

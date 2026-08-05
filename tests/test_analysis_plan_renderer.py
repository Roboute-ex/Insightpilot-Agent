from __future__ import annotations

from insightpilot.ui import renderers


class _FakeStreamlit:
    def __init__(self) -> None:
        self.subheaders: list[str] = []
        self.json_calls: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def container(self, **kwargs):
        return self

    def expander(self, *args, **kwargs):
        return self

    def subheader(self, value, **kwargs):
        self.subheaders.append(value)

    def metric(self, *args, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def dataframe(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def json(self, value, **kwargs):
        self.json_calls.append(kwargs)


def test_analysis_plan_renderer_hides_json_until_developer_mode(monkeypatch) -> None:
    plan = {"goal_mode": "metric_diagnosis", "intent": "metric_drop_diagnosis", "analysis_steps": ["检查数据"]}
    fake = _FakeStreamlit()
    monkeypatch.setattr(renderers, "st", fake)
    renderers.render_analysis_plan_summary(plan, "demo")
    assert fake.subheaders == ["分析方案摘要"]
    assert fake.json_calls == []
    renderers.render_analysis_plan_summary(plan, "professional")
    assert fake.json_calls == []
    renderers.render_analysis_plan_summary(plan, "developer")
    assert fake.json_calls == [{"expanded": False}]

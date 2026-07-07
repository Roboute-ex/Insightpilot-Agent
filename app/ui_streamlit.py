"""Streamlit UI for InsightPilot Agent."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data
from insightpilot.planning.goal_modes import GOAL_MODE_OPTIONS
from insightpilot.visualization.charts import build_ab_test_comparison_chart, build_contribution_bar_chart


GOAL_MODE_BY_DISPLAY_NAME = {mode.display_name: mode.value for mode in GOAL_MODE_OPTIONS}
GOAL_MODE_DISPLAY_NAMES = list(GOAL_MODE_BY_DISPLAY_NAME.keys())
WORKFLOW_BACKENDS = {"Rule-based": False, "Optional LangGraph": True}

SCENARIOS: dict[str, dict[str, Any]] = {
    "交易转化异常分析": {
        "question": "为什么昨天某城市订单量下降？",
        "tables": ["daily_metrics", "traffic_events", "orders", "users"],
    },
    "内容消费与实验分析": {
        "question": "新策略是否提升了内容完播率？",
        "tables": ["content_events", "content_items", "experiments", "users"],
    },
    "体验质量分析": {
        "question": "请定位直播体验异常的主要维度。",
        "tables": ["live_quality_logs", "live_sessions", "live_interactions"],
    },
}


@st.cache_data(show_spinner=False)
def _load_tables() -> dict[str, pd.DataFrame]:
    return generate_all_demo_data(seed=42)


def _render_artifacts(result: dict[str, Any]) -> None:
    artifacts = result.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return
    contributions = artifacts.get("contributions")
    if isinstance(contributions, dict):
        for dimension, rows in contributions.items():
            frame = pd.DataFrame(rows)
            if frame.empty:
                continue
            st.plotly_chart(
                build_contribution_bar_chart(frame, title=f"{dimension} contribution"),
                use_container_width=True,
            )
            st.dataframe(frame, use_container_width=True)
    ab_test = artifacts.get("ab_test") or artifacts.get("optional_ab_test")
    if isinstance(ab_test, dict):
        st.plotly_chart(build_ab_test_comparison_chart(ab_test), use_container_width=True)


def _safe_json(data: Any) -> Any:
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def main() -> None:
    st.set_page_config(page_title="InsightPilot Agent", layout="wide")
    tables = _load_tables()

    st.title("InsightPilot Agent")
    scenario_name = st.sidebar.selectbox("Demo 场景", list(SCENARIOS.keys()))
    scenario = SCENARIOS[scenario_name]
    selected_goal_mode_display = st.sidebar.selectbox(
        "Analysis Goal Mode",
        GOAL_MODE_DISPLAY_NAMES,
        index=0,
    )
    selected_goal_mode = GOAL_MODE_BY_DISPLAY_NAME[selected_goal_mode_display]
    selected_backend_display = st.sidebar.selectbox("Workflow Backend", list(WORKFLOW_BACKENDS.keys()), index=0)
    use_langgraph = WORKFLOW_BACKENDS[selected_backend_display]

    st.sidebar.markdown("### synthetic data")
    selected_table = st.sidebar.selectbox("预览表", scenario["tables"])
    st.dataframe(tables[selected_table].head(20), use_container_width=True)

    if "question" not in st.session_state:
        st.session_state.question = scenario["question"]
    if st.button("使用示例问题"):
        st.session_state.question = scenario["question"]

    question = st.text_input("问题", value=st.session_state.question, key="question")
    if st.button("运行分析", type="primary"):
        result = run_agent_analysis(
            question,
            tables,
            goal_mode=selected_goal_mode,
            use_langgraph=use_langgraph,
        )
        trace = result.get("trace", {})
        reviewer = result.get("reviewer", {})

        st.subheader("Workflow Backend")
        st.write(result.get("workflow_backend", "rule_based"))
        st.subheader("Route Taken")
        st.write(" -> ".join(result.get("route_taken", [])))

        col_status, col_score, col_trace = st.columns(3)
        col_status.metric("Reviewer Status", reviewer.get("status", "UNKNOWN"))
        col_score.metric("Reviewer Score", reviewer.get("score", "N/A"))
        col_trace.metric("Trace ID", trace.get("trace_id", "N/A"))

        plan_tab, metrics_tab, findings_tab, reviewer_tab, trace_tab, report_tab = st.tabs(
            ["Analysis Plan", "Metrics", "Findings", "Reviewer Result", "Trace JSON", "Markdown Report"]
        )
        with plan_tab:
            st.metric("Analysis Goal Mode", f"{result['goal_mode_display_name']} ({result['goal_mode']})")
            st.write(f"Goal Mode Source: {result['goal_mode_source']}")
            st.json(_safe_json(result["plan"]))
        with metrics_tab:
            st.dataframe(pd.DataFrame(result["metrics"]), use_container_width=True)
            _render_artifacts(result)
        with findings_tab:
            for finding in result["findings"]:
                st.write(f"- {finding}")
            with st.expander("Caveats"):
                for caveat in result.get("caveats", []):
                    st.write(f"- {caveat}")
        with reviewer_tab:
            st.json(_safe_json(result["reviewer"]))
            with st.expander("Reviewer Checks"):
                st.json(_safe_json(reviewer.get("checks", {})))
        with trace_tab:
            st.json(_safe_json(result["trace"]))
        with report_tab:
            st.markdown(result["report_markdown"])


if __name__ == "__main__":
    main()

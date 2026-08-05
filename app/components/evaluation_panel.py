"""On-demand local evaluation dashboard."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from insightpilot.evaluation import run_core_evaluation, run_determinism_evaluation, run_safety_evaluation
from insightpilot.ui.i18n import t


def render_evaluation_panel() -> None:
    st.subheader(t("section.evaluation"), anchor=False)
    if st.button("运行本地评估套件", icon=":material/fact_check:"):
        with st.spinner("正在运行本地 core、safety 与 determinism 评估……"):
            st.session_state["evaluation_results"] = {
                "core": run_core_evaluation().to_dict(),
                "safety": run_safety_evaluation().to_dict(),
                "determinism": run_determinism_evaluation().to_dict(),
            }
    results = st.session_state.get("evaluation_results")
    if not isinstance(results, dict):
        st.caption("评估仅使用本地模拟数据，不访问在线服务。")
        return
    rows = [
        {
            "评估套件": name,
            "总体得分": value.get("overall_score"),
            "通过案例": value.get("passed_cases"),
            "警告案例": value.get("warning_cases"),
            "失败案例": value.get("failed_cases"),
            "最慢案例": value.get("slowest_case"),
        }
        for name, value in results.items()
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True)

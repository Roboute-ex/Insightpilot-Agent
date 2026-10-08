"""Native table selection drafts a validated child request; no click-to-query."""
from __future__ import annotations
import pandas as pd
import streamlit as st
from insightpilot.analysis.drilldown import city_candidates, build_drilldown_config, validate_selection


def render_drilldown_panel(result, snapshot, analysis_session):
    if snapshot is None:
        return
    node = next((n for n in analysis_session.history.nodes if n.run_id == str(result.get("run_manifest", {}).get("run_id"))), None)
    if node is None or not analysis_session.history.result_available(node, analysis_session.current):
        return
    candidates = city_candidates(result, node, snapshot)
    if not candidates:
        return
    st.subheader("按城市继续探索", anchor=False)
    st.caption("在表格左侧选择一个真实城市，仅生成筛选草稿。此处采用原生表格选择；描述性下钻不证明显著性或因果关系。")
    frame = pd.DataFrame([{"城市":c["label"],"指标":c["payload"]["metric_id"],"当前值":c["current_value"],"变化贡献":c["contribution_value"]} for c in candidates])
    event = st.dataframe(frame, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key="drilldown_select_"+node.run_id+"_"+str(snapshot.revision))
    rows = event.selection.rows
    selection = candidates[rows[0]]["payload"] if len(rows) == 1 and isinstance(rows[0], int) and 0 <= rows[0] < len(candidates) else None
    if selection:
        try:
            selection = validate_selection(selection, result, node, snapshot)
            st.session_state["workbench_drilldown_draft"] = selection
            st.info("筛选草稿：city = " + str(selection["value"]) + "；尚未执行。将按原指标口径生成所选城市的描述性汇总。")
        except ValueError as exc:
            st.warning(str(exc))
            selection = None
    else:
        st.session_state.pop("workbench_drilldown_draft", None)
    if st.button("基于选中分组继续分析", disabled=selection is None, key="workbench_drilldown_submit"):
        from app.components.exploration_panel import stage_exploration
        try:
            config = build_drilldown_config(selection, result, node, snapshot)
            stage_exploration(snapshot, config, parent_run_id=node.run_id)
        except ValueError as exc:
            st.warning(str(exc))
    for error in st.session_state.get("exploration_errors", []):
        st.warning(str(error))

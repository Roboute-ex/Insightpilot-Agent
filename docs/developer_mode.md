# 开发者模式

## 用途

开发者模式用于审计稳定内部结构，不作为默认分析结果页面。

## 可查看内容

- AnalysisPlan JSON
- WorkflowState JSON
- AnalysisTrace JSON
- QueryPlan 与 JoinPlan JSON
- RunManifest 与 ChartSpec JSON
- Lineage、Contract 和 Telemetry JSON
- SQL 只读模板与脱敏参数类型
- catalog fingerprint 与 dataset fingerprint

## 折叠规则

所有 JSON 位于“开发者技术详情”折叠区域，并调用 `st.json(data, expanded=False)`。

## 安全边界

参数仅显示类型摘要，不显示凭据。Manifest 不包含完整数据表、上传路径或明文数据库连接密码。

## 兼容性

开发者模式展示源对象，不翻译 JSON key，也不改变 WorkflowState、Trace 或 QueryPlan schema。

## 验证

`tests/test_developer_details.py` 检查所有 `st.json` 默认折叠，`tests/test_streamlit_developer_mode.py` 检查模式切换与 session state。

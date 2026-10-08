# 架构与执行边界

## 数据与规划

文件/数据库/模拟数据产生 TableRegistry；质量和 ColumnMapping 先验证真实 schema。规则 Planner 或显式 Playbook 构建 AnalysisPlan。
语义路径使用 Catalog、RelationshipGraph、JoinPlanner、MetricCompiler 与受限 QueryPlan。预览不执行查询。

## 执行与结果

规则工作流与可选 LangGraph 复用节点。DuckDB 用于注册内存表受控SQL，Pandas/SciPy用于统计。AnalysisResultPackage保存实际结果表并派生摘要、证据与建议。
Reviewer检查方法、样本、证据与限制，Manifest绑定执行快照；UI和六类导出读取同一次结果。

## 治理与复现

Data Contracts验证质量；Lineage记录处理关系；LocalTracer记录内存spans。默认无在线模型、遥测或训练。
层级入口为 insightpilot.cli 和 app/ui_streamlit.py。examples/run_demo.py为兼容包装。
详细模块修复、实际能力和限制见验收报告。

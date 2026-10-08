# InsightPilot Agent 维护说明

当前项目版本为 0.1.0。它是公开源码的历史能力恢复整合版本，来源见 docs/migration_notes.md。

- 详细实施进度与验收项见 docs/implementation_plan.md；能力矩阵见 docs/acceptance_report.md。
- 所有演示、测试使用确定性模拟数据，默认中文、规则工作流、无在线模型、无 API key。
- 不提交上传数据、数据库、运行报告、凭据或虚拟环境。只读数据接入和脱敏不可退化。
- 修改分析、数据、工作流、导出或界面后运行相关测试，并在交付前运行完整 pytest 和 core/safety/determinism。
- 字段映射优先、计划预览不执行、结果有证据、实验统计单位明确、PDF 优先。
- 保留许可证与来源；本轮禁止 git add/commit/tag/push、变更旧历史或配置新推送目标。
- 源码快照采用白名单且含未提交文件；恢复步骤见 docs/backup_and_restore.md。
- UTF-8 多行文本，单个结尾换行。维护安全边界见 docs/data_ingestion.md、docs/semantic_layer.md。
- 引导式分析复用 planning.prepare_analysis_request/analysis_advisor；预检不得扫描数据或执行SQL。新首页为单一工作台，模式枚举仅作兼容；参数表单提交后重检冻结请求。测试及实际边界见 docs/guided_analysis_acceptance.md。

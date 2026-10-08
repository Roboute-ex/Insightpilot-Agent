# 迁移与来源

## 固定恢复来源

公开仓库：https://github.com/Roboute-ex/Insightpilot-Agent.git
main 提交：`2532e4665eda9fe16dee98994691a3e6ddbec0e8`，与 v0.6 标签一致；222 个受跟踪文件。只读 HTTPS clone，原始 origin 仅用作来源，未推送。

外层 source-original/ 保留源码和 .git；recovery-notes/source_inventory.json 记录分支、v0.1–v0.6 标签、文件清单与哈希。原 ZIP 和 Git bundle 存在 recovery-backups/。工作副本从固定提交 archive 提取，无 .git 或旧 origin。

## 新旧版本关系

新 **0.1.0** 是历史 v0.1–v0.6 能力的恢复整合版本，不是旧 v0.1 标签源码，也不是缩减功能的 MVP。
原始基线和恢复快照保持原始版本，不修改提交历史、远程或标签。旧 releases 文档仅为历史材料；历史成绩不作为本次成绩。

## 恢复、修复与重建

保留原 ingestion、metrics、planning、agents、analysis、playbooks、semantic、contracts、lineage、observability、evaluation、UI、可视化和已有五类导出的实际实现。
全部可见 Git 历史未找到 reports/pdf.py、data/scenarios/ 和 data/example_questions.py；按规格补建并连接原入口。
原始 .gitignore 中裸 data/、reports/ 可能误忽略源码，新工作项目改为根目录锚定规则。
新增稳定包内 CLI，旧 examples/run_demo.py 包装同一实现；新增打包、环境检查、快照与恢复验证工具。
安全、统计、结果、界面等具体修复见 engine_audit.md、data_recovery.md、ui_export_verification.md 和 acceptance_report.md。

## 原始基线实际验证

使用本次环境、禁止写缓存运行导入/pytest收集/Demo，退出码分别1/4/1，均报缺少 insightpilot.reports.pdf。原始输出存于外层 recovery-notes/baseline_validation.json。
这表明原始上传源码不能直接运行；没有将 README 宣称或历史测试数当作本次恢复成绩。

## 兼容与权利说明

项目版本0.1.0；Manifest协议与CLI JSON schema版本独立维护，稳定英文键继续兼容。数据目录和页面职责保持原结构。
未发现许可证文件，保留公开来源与原作者标识 Roboute-ex，不另选许可证。
本轮不创建仓库、不 git add/commit/tag/push、不配置推送目标，不提交报告、数据、数据库或凭据。

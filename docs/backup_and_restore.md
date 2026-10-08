# 源码备份与恢复

## 基线与整合快照

外层 source-original/ 不可修改，保留原始 .git。原始固定提交 ZIP、Git bundle 与整合源码快照位于 recovery-backups/。
整合快照使用 scripts/export_source_snapshot.py 白名单收集未提交源码，包含合法隐藏配置、语义YAML、测试和文档。不会复制旧Git、环境、缓存、报告、上传数据或凭据，也不覆盖同名包。

## 创建快照

```powershell
& ./.venv/Scripts/python.exe scripts/export_source_snapshot.py --output-dir ../recovery-backups
```

ZIP外部 .sha256 校验整包；内部 SHA256SUMS.json 校验文件数量、大小及每个文件。请同时保留ZIP与校验信息，不要只依赖远程仓库。

## 独立恢复

解压到不存在的新目录，核对清单，进入 insightpilot-agent/，用可用Python创建新的 .venv，再执行 pip install -e ".[app,test]"。不要设置旧PYTHONPATH。
可用 scripts/verify_project.py 执行三场景、三套评估和六类导出。scripts/check_distribution.py单独构建无源码引用的wheel环境。
本次独立恢复结果见 acceptance_report.md 和外层 recovery-notes/clean_restore_validation.json。

## 离线依赖边界

源码包不包含Python解释器或平台依赖；首次安装需要网络，或另外准备相同Python版本/平台的wheelhouse。
如已保存本次依赖wheelhouse，可用 --no-index --find-links <wheelhouse> 安装。不同Python/平台需重新准备对应依赖，不能把Windows wheel用于Linux。
安装完成后默认分析、测试与报告生成不需要网络、旧账号、API key或旧项目环境。

## 本次已验恢复包

insightpilot-agent-0.1.0-source-20260907T081238059190Z.zip（268文件）已在 source-restore-validation-final 新venv离线恢复，281项测试及三套评估/三场景六导出通过。SHA256：`56c69668a57eb7a7f865450eed7d3db2e9f1448f0d3d6c171dc0a4eb99d57b8e`。

快照内文档记录打包时待验证状态；外层recovery-notes/clean_restore_validation.json和备份旁的verification资料记录随后真实通过结果。工作副本随后只补写验收文档；执行源码保持与快照一致。恢复代码时使用原始已验ZIP及SHA256，不改写ZIP来追加运行结果。


## 2026-09-23 增量轮次

前文备份与测试数量保留为对应历史记录，本轮不可直接沿用。本轮修改前源码快照291文件、最终wheel138项package data/源码模块验证；准确SHA256、独立环境命令和任务评估记录见`reports/upstream/wheel-acceptance-utf8.json`。最终含README与增量验收文档的白名单源码快照、独立恢复pytest/四评估/三个Demo六导出记录统一写入`reports/upstream/source-restore-result.json`；该机器证据不打入源码ZIP。

包装工具支持精确`--wheel`和多个`--wheelhouse`；不会按同版本文件名字母序误验旧包。恢复校验ZIP外部SHA与内部每文件SHA，拒绝未列成员/重复成员/路径逃逸/链接/128MiB展开超限；拒绝覆盖已有目标。隔离命令显式`-X utf8`，避免Windows `-I`忽略环境编码导致中文捕获乱码。软件版本仍0.1.0，不自动发布。

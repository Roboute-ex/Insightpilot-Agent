# InsightPilot Agent 0.1.0 实施与验收计划

本次使用固定 main 源码恢复，保留原实现，仅修复/补齐缺失。完整规范为外层 REBUILD_SPEC.md.md。

|阶段|验收要求|实际进度|剩余|
|---|---|---|---|
|1 恢复与审计|固定提交、原始ZIP/bundle、隔离副本|完成；222文件，main=2532e4665eda9fe16dee98994691a3e6ddbec0e8|无；baseline导入/收集/Demo真实失败1/4/1均缺PDF|
|2 数据与指标|规模、信号、39问题、映射接入|缺失3场景及问题已补，标准/large实测、对账、xls/xlsm/编码通过；补50,400开播与54,000观看会话|新快照独立281项全量通过|
|3 统计与实际结果|实验、基准、结果证据、Reviewer|已恢复并修复；新统计/安全反例通过，真实LangGraph治理状态已修，三场景业务/data_quality逐表一致|最终可选环境复验已通过|
|4 剧本与语义|10剧本、Join安全、审批|10剧本真实COMPLETED/PASS；安全评估曾抓出表函数访问后已修；补跨组累计partition、结构化排序和受限跨事实独立聚合，完整metrics/filters/null日期CLI链路已实测|新快照内三套全部通过|
|5 中文UI与导出|3模式、实际明细、图表、6导出、PDF|AppTest实点交互与浏览器预览/执行/三模式通过，PDF31页最终视觉检查通过；补导出tab持久化及内置中文枚举|最终PDF/浏览器下载已通过|
|6 评估与复现|Manifest、血缘、spans、CLI|首次3套评估、3场景6导出、语义预览退出0；增加独立expected与反例|最终新环境全部通过|
|7 打包与备份|wheel/sdist、快照新venv、文档|wheel/sdist构建；独立离线wheel环境导入/package-data通过，依赖wheelhouse已保存，快照安全9项通过|最终快照离线新venv完整运行通过|

## 本次真实中间检查

- 原始基线：import=1、pytest收集=4、Demo=1，错误为缺失 reports.pdf，详见外层baseline_validation.json。
- 缺失模块补入过程的初次全量：196 passed / 4 failed，退出1，随后按实际契约与误报逐项修复，未删除失败测试。
- CLI/接入/包数据/快照17项通过；源码过滤/格式9项通过。
- 最终核心49项定向回归通过；真实LangGraph3场景和零查询预览通过，跨事实完整多指标CLI退出0。
- 标准场景与六导出、3套初始评估及预览全部退出0；这些中间成绩不替代最终验收。
- 真实LangGraph首轮发现data_quality行数不同，需补共享状态；独立wheel首轮相对路径错误已修，新目录重试成功，原失败日志保留。

## 交付边界

所有操作仅在授权工作区；无git add/commit/tag/push，无旧历史修改或新推送目标，无上传数据。远程CI未运行。
最终数字、证据位置与限制统一见 acceptance_report.md，日志在外层recovery-notes与根reports/verification。

## 最终独立验收已完成

源码快照268文件在新venv独立离线恢复：281 passed in 136.24s，0失败/错误/跳过。core 5、safety 4、determinism 2个案例全部通过；三场景CLI、六格式导出、语义预览及pip check全部退出0。另一个新venv中的最终wheel导入和CLI六导出通过；真实LangGraph与冻结后浏览器PDF下载通过。完整实际退出码见外层recovery-notes/clean_restore_validation.json。

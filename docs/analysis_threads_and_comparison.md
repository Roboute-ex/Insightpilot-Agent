# 分支历史、可比性与选定运行导出

版本0.1.0；本轮日期2026-09-23。入口为 `insightpilot/analysis/threads.py`、`app/session_data.py`、`app/components/history_panel.py`，复用RunManifest和现有后台任务管理器。

## 运行与存储

RunNode是冻结对象，配置、上下文与有限聚合摘要以严格JSON字符串冻结。每次显式提交绑定会话、数据revision、request/node_id及分析配置；完成后只引用真实run_id。相同成功配置命中原结果，不新建虚假运行。新分支只预填表单，必须点击“开始分析”才执行。旧任务节点不匹配时不能覆盖新选择。

默认仍只保留一份完整结果，最多10条历史元数据。历史512KiB从原256MiB结果预算中扣除，不另加内存预算；配置不能包含DataFrame。摘要最多128个聚合值，不复制原始表。原数据1GiB/1份、导出64MiB/6项、30分钟会话TTL、全局2个后台任务/每会话1个限制保持。元数据淘汰或完整结果释放会明确提示重新执行，不能从小摘要伪造完整结果或报告。更换数据或释放会话使旧引用失效。

## 用户操作与对比

“基于本次结果继续分析”“修改维度重新分析”“修改对比基准”“恢复此运行配置”只恢复配置；“返回上一步”和历史选择不执行分析。高级分支和对比使用显式开关，关闭时不构建对比DataFrame。

compare_runs先检查执行状态、必需口径、版本/单位/分子分母/去重/独立单位、数据身份revision/schema、过滤/维度、日期/时区/时间粒度、方法及分组方向。无法确认单位不能因两边相同而当作已确认。同定义不同窗口为context_differs，只作描述性比较；语义或维度不同为not_comparable。少量聚合按指标与维度键对齐，重复键拒绝，缺失组保留未定义；基数为0时相对变化未定义。比例绝对变化乘100显示百分点。运行差异不提供新的显著性或因果判断。

完整结果按原缓存策略淘汰。因此可以比较保留下来的有限摘要，但不能任意切换历史大表；释放的旧运行须恢复配置后显式重跑，此时产生新的run_id。这个边界是内存预算约束，不声称提供无限历史数据库。

## 导出与脱敏文件

六类报告绑定选定且仍可用的运行及原配置；未提交的新问题/参数不进入报告。纯展示标题改变且计算指纹一致时，仅浅拷贝口径显示信息，更新展示指纹以使报告缓存失效，数值表共享、原历史不修改。单PDF不调用其他导出器，ZIP只在显式请求时复用同run缓存。

历史JSON需点击生成，复用原导出缓存；不包含DataFrame、原始值或结果引用授权。问题、筛选值、连接信息、路径等以requires_input替换。导入只核验schema/版本/大小/有限标量/状态/计数/引用关系，不自动恢复数据或执行授权。512KiB文件上限及当前历史元数据预算同时检查；上传后清除大字节引用，只保存验证提示。重复键、非法非有限值、深层嵌套、循环/前向引用均拒绝；不执行pickle/Python或读取文件指定路径。模板保存属于P1，本轮未实现。

## 已运行验证

`tests/test_upstream_threads.py`覆盖冻结、预算、跨会话、旧任务、淘汰、键对齐、百分点、缺失组与文件边界。独立反例在`tests/test_upstream_threads_adversarial.py`。`tests/test_upstream_ui.py`实际点击多收入/多转化率澄清、城市/渠道分支、返回、窗口对比、历史运行PDF/Excel/ZIP，并断言未请求不导出、切换不分析。真实浏览器与AppTest分开记录，最终结果见upstream_improvement_acceptance.md。

复测：`.\.venv\Scripts\python.exe -m pytest tests/test_upstream_threads.py tests/test_upstream_threads_adversarial.py tests/test_upstream_ui.py tests/test_performance_ui.py tests/test_performance_background_ui.py -q`。

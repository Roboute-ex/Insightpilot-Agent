# 全部分析方法与因果入口验收

日期：2026-09-29。版本保持 0.1.0。工作目录：`D:\InsightPilot Agent\insightpilot-agent`。

## 结论与实际原因

轻量因果探索没有被删除。本轮读取源码并实际运行确认：`insightpilot/playbooks/builtins.py:120` 保留 `causal_exploration` 定义；`insightpilot/playbooks/executor.py:501` 的 `_execute_causal_exploration` 调用 `insightpilot/analysis/causal_light.py:46` 的 `estimate_adjusted_effect`。计算实现和执行器与本轮修改前快照逐字节一致，没有恢复或新加算法。

原 `app/components/semantic_panel.py:24` 的 `playbook_options()` 已列出完整 Registry；Advisor 的 `candidates` 只保留最多三个推荐，但 `other_methods` 补全了其余方法，原目录也会拼接二者。因此，没有证据表明原界面把推荐列表当作全部目录、删除方法注册或遗漏执行路由。

实际问题是入口层级：原首页看不到完整目录，必须先展开“调整方法与参数”，再展开“查看全部方法及要求”。目录项只有名称/状态/原因，没有直接配置按钮。补丁前实际 AppTest 结构保存在 `reports/method-discovery/before-ui.json`。当前交易数据确实缺少处理字段，这是执行被阻断的独立原因，不应导致方法从目录消失。

交互验证另发现并修复：首次从目录配置时，字段编辑器默认切到第一张 users 表、结果变为 profile_id；现在复用当前预检口径映射，交易场景保持 daily_metrics/orders。用户明确清空结果字段时，旧 Advisor 会重新补成 orders，Planner 也会丢失未确认建议中的清空约束；现在显式空值必须阻断，未确认的正向建议仍不冒充用户确认。

## 十个实际剧本及界面入口

下表每个配置按钮都经 AppTest 实际点击。注册表仍有十个剧本，新增目录直接遍历 Registry，即使推荐对象不完整也不会漏项。三个多表方法：语义查询、漏斗、队列走既有 `_execute_multi_table_playbook` 分派，其余七个走 `EXECUTORS`；不能仅数后者而误报方法缺失。

|中文名称|稳定 ID|首页入口|既有计算函数|
|---|---|---|---|
|轻量因果探索|`causal_exploration`|查看全部分析方法 → 配置：轻量因果探索|`_execute_causal_exploration`|
|队列留存分析|`cohort_retention`|查看全部分析方法 → 配置：队列留存分析|`_execute_cohort_retention`|
|数据概览与质量检查|`data_profile`|查看全部分析方法 → 配置：数据概览与质量检查|`_execute_data_profile`|
|维度贡献分析|`dimension_contribution`|查看全部分析方法 → 配置：维度贡献分析|`_execute_dimension_contribution`|
|实验组对照组比较|`experiment_comparison`|查看全部分析方法 → 配置：实验组对照组比较|`_execute_experiment_comparison`|
|漏斗转化分析|`funnel_analysis`|查看全部分析方法 → 配置：漏斗转化分析|`_execute_funnel_analysis`|
|指标趋势分析|`metric_trend`|查看全部分析方法 → 配置：指标趋势分析|`_execute_metric_trend`|
|周期对比分析|`period_comparison`|查看全部分析方法 → 配置：周期对比分析|`_execute_period_comparison`|
|周期分析摘要|`periodic_summary`|查看全部分析方法 → 配置：周期分析摘要|`_execute_periodic_summary`|
|语义指标查询|`semantic_metric_query`|查看全部分析方法 → 配置：语义指标查询|`_execute_semantic_metric_query`|

自动推荐和“保留现有自动工作流”继续保留在高级方法选择器中，未把它们算成十个注册剧本之一。方法目录对每项显示用途、基本要求、缺失条件和配置按钮；状态区分可用、待补充、与当前问题不匹配、当前数据不支持。不可用的方法仍然可查看与配置，但不能执行。多表漏斗、留存和语义分析仍要求各自的数据表、字段、模型及安全/审批条件，不保证任意交易表都适用。

## 准确操作路径

首页“查看全部分析方法” → “配置：轻量因果探索” → 自动展开“调整方法与参数”及“配置分析范围与字段映射”。根据研究目的明确选择“分析目标：轻量因果探索”，核对真实处理字段、结果字段和协变量，点击“确认当前字段映射”；在方法参数选择处理/对照真实取值与控制变量，点击“应用参数并更新建议”。预检通过后再点击“开始分析”。

结果通过“结论”查看实际估计与样本量，“明细”选择 `adjusted_effect_summary`，“报告”按需生成 PDF 等六种格式。配置按钮只更新手动选择并打开已有设置，不替用户更改问题、分析目标或执行；来源记为 `user_selected`。问题编辑和面板收起不会覆盖该选择。

## 有效与无效输入实测

- 标准交易数据、订单下降问题：目录仍显示因果探索；缺少真实处理字段，已有 orders 结果字段不会被误报缺失。treatment/control 仅作为组值不能使配置就绪。分析按钮禁用，SQL、统计、分析执行器、后台任务、导出均为0，无新增成功历史。显式清空结果字段后另报缺结果字段。
- 独立小表：24行，control/treatment各12行，协变量 x=0..11；结果 `10+x+组效应+交替±0.25`，处理组效应为2。两组拥有相同 x 和残差，独立手算原始差及回归调整估计均为2。真实上传 CSV 后经界面配置运行，实际结果均为2、有效样本24；明细与页面摘要、PDF、Excel一致。
- 核心另用 `y=10+3*x+2*t` 的24行独立表核对，组均值29.5/31.5，调整估计2.000000000000001。单组、结果全空、缺结果字段各自准确阻断。未给映射的合法内置因果配置仍可运行。
- 现有因果方法的摘要以前仅为“执行完成，状态PASS”；现在从实际结果表读取差异、调整估计和样本量。去掉成功映射后仍残留的“只能提供数据概览”提示，并如实说明当前剧本不执行倾向评分加权。没有协变量时不伪造调整值。
- 字段齐全和运行完成不等于因果关系成立。结果继续说明随机化、无未观测混杂、重叠性和时序前提未验证，估计沿用结果变量原量纲。

## 调用、资源与验证成绩

新界面12项测试全部通过；相关既有UI回归63项通过。目录完整性、四种状态、十个配置按钮、手动选择、原订单自动推荐、有/无效因果输入、PDF真实结果均有覆盖。AppTest 使用既有展开器事件适配器；有效小表只替换加载入口，所有配置和运行操作经过控件，不注入建议或结果。

完整 pytest：**632 passed，1 skipped，0 failed**，179.639秒。跳过的是 `test_real_langgraph_propagates_worker_context_and_cancellation`，原因是本机未安装可选 `langgraph.graph`；未声称此真实运行路径已验证。其余相关回退、安全、取消与隔离测试通过。四套评估：core **5/5**，safety **4/4**，determinism **2/2**，task **51/51**。依赖检查、语义校验、三个主Demo及各自六格式导出、plan-only均退出0。

最终输出在 `reports/method-discovery/verification-final/20260929T103255574700Z/`。首轮全量为626通过、1失败、1跳过，失败正是显式清空结果字段未阻断；该记录保留在 verification/，修复后完整重跑，不删除或跳过失败用例。

|交互范围|加载|完整指纹|分析|因果统计|SQL|后台任务|导出|
|---|---:|---:|---:|---:|---:|---:|---:|
|交易数据准备后，展开/关闭目录、逐项进入配置|增量0|增量0|0|0|0|0|0|
|交易无效因果请求及清空结果字段|增量0|增量0|0|0|0|0|0|
|24行有效因果表准备后，完整配置过程|增量0|增量0|0|0|0|0|0|
|明确开始因果分析|增量0|增量0|1|1|0|AppTest同步模式|0|
|明细/报告切页后只点击生成PDF|增量0|增量0|不增加|不增加|0|不增加|1|

交易准备阶段本身实际加载1次、完整指纹6次；小表加载1次、指纹1次，后续未增加。当前因果计算沿用 pandas/OLS，不执行分析 SQL，因此有效运行SQL为0是其既有实现方式。证据为 directory-apptest.json、invalid-causal-apptest.json、valid-causal-apptest.json。未进行新的大数据速度或RSS优越性宣称。

`insightpilot/performance.py`、`performance_tasks.py`、`app/background_tasks.py`、`app/session_data.py`、`app/components/export_panel.py` 与修改前快照逐字节一致，未提高缓存预算或并发。仍按会话隔离、按需生成、PDF优先六格式；没有新建全局数据缓存或临时磁盘数据缓存。测试生成的合成CSV与报告仅用于明确的本地验收，不是产品缓存。

## 真实浏览器与视觉检查

最终脚本 `scripts/check_method_discovery_browser.py` 使用隔离 Chrome、真实文件上传、原生控件点击，未注入 session_state 或分析结果。`reports/method-discovery/browser-07/checks.json` 中 **25项断言全部通过**、无 pageerror；健康接口另测 **200**。真实路径包括交易无效配置→接受推荐→订单运行，以及新会话上传因果小表→全部方法→配置→执行→明细选择→PDF/Excel/ZIP下载。

下载 Excel 的 naive_difference=2、adjusted_effect=2、样本量=24，协变量确实进入OLS；PDF含实际数值和因果限制，Excel/PDF属于同一run_id，ZIP内PDF与单独下载PDF字节相同。六个生成入口依次为PDF、Markdown、HTML、Excel、运行清单JSON、ZIP；未请求时不预生成。

截图另经实际视觉检查，首页入口相邻、因果条目完整、明细与摘要可读；记录为 browser-07 下截图、browser-07/visual-review.json 及 reports/method-discovery/root-visual-review.json。AppTest、浏览器点击、视觉检查、health分别记录，不相互替代。浏览器脚本早期同值选择等待、多选菜单操作及JSON按钮空格预期错误均保留原失败证据；修正的是测试操作/精确标签，没有为通过测试绕过产品预检。

## 备份、文件与边界

修改前使用已有快照工具保存包括未提交源码的331文件：`D:\InsightPilot Agent\recovery-backups\insightpilot-agent-0.1.0-source-20260929T101636745678Z.zip`，SHA256 `2f558af53a699e633e395d36d1621e5807b3da5127e8eefef95af531905f8ac1`。快照不含环境、用户数据、运行报告或凭据，未覆盖旧备份。

源码变更：guidance_panel.py（顶层完整目录和明确配置回调）；mapping_panel.py（初始化当前映射）；ui_streamlit.py（入口位置）；analysis_advisor.py / planner.py（清空结果字段不被补回、准确计划文字）；workflow.py / package_builder.py（成功因果实际摘要）。新增两份测试及一份浏览器验收脚本；更新README、analysis_guidance.md、ui_simplification.md和本文。完整清单见 change-inventory.json。

`source-original` 的222个源码文件哈希、HEAD、main及六个旧标签均与既有读取记录一致，工作区仍无旧Git关联。算法、执行器、版本文件未改，保持0.1.0；没有执行 git add/commit/tag/push，未新增模型、依赖或平台。其余九个方法已逐项验证入口和配置可达，本轮真实浏览器完整运行重点为因果与订单诊断，不将“入口可达”冒充九种方法在任意数据上都能执行。

## 本机复测

以下命令在项目根目录执行；首个终端保留服务运行，测试结束用Ctrl+C停止。浏览器检查的输出目录必须使用尚不存在的新目录，避免覆盖证据。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8='1'
& ./.venv/Scripts/python.exe -m pytest tests/test_method_discovery_ui.py tests/test_causal_result_presentation.py -q
& ./.venv/Scripts/python.exe scripts/verify_project.py --output-dir reports/method-discovery/verification-final
& ./.venv/Scripts/python.exe -m streamlit run app/ui_streamlit.py --server.address 127.0.0.1 --server.port 8509 --server.headless true --browser.gatherUsageStats false
```

另一个终端（本次实际通过使用 browser-07；复测时换新目录名）：

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
& ./.venv/Scripts/python.exe scripts/check_method_discovery_browser.py --url http://127.0.0.1:8509 --output reports/method-discovery/browser-07
```

浏览器验收另需现有本机Playwright与Chrome；产品运行无需浏览器自动化依赖。此次未安装完整平台或下载模型。

非阻断日志：服务器首次初始化映射时仍有字段默认值与SessionState同时赋值的Streamlit提示；浏览器关闭会产生连接重置日志。最终页面无异常，实际配置、计算和下载均通过。本轮未将这些日志解释为分析失败。

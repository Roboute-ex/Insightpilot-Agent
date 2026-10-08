# 独立任务评估与质量展示

实施及本轮核查日期：2026-09-23。软件版本保持 0.1.0。

## 范围与入口

在原 `EvaluationCase`、`EvaluationHarness`、core/safety/determinism 三套评估基础上增加 `insightpilot/evaluation/task_suite.py`，没有新增独立评估平台。`--suite task` 运行新任务集；`--suite all` 运行原三套和 task。评估只使用源码中的固定小表、内存数据库、显式映射与本地报告生成器；不访问在线模型，不使用用户输入文件。

每项任务包含问题、fixture 标识、预期状态与数值、必需证据、禁止行为和逐项 checks。任一契约检查不满足则该任务 FAIL，异常和原因保留在结果中；不靠其余通过项的平均分掩盖关键失败。总体得分仅是这些确定性检查的通过情况，不是统计结论正确的概率。原有评分接口保持兼容。

正常数值、正确要求澄清、正确拒绝和正确释放引用都可能构成任务通过；不能以强行返回数字为目标。运行结果记录 `task_families`，可查看每族通过/警告/失败数和逐项原因。

## 独立预期与任务族

手算依据固定于 case 元数据和 fixture 源码，不调用被测聚合、规划、比较、实验函数生成 expected：

- 16 行日期×城市小表：当前期订单 8+12=20、金额 80+120=200；基准期订单 10+20=30、金额 100+200=300；访问转化率为 20/(20+100)=1/6。
- 去重示例 user_id 为 `[1,1,2,2,3]`：5 行，3 人。只有已明确按该键去重的指标才对重复同一实体保持不变。
- 两行点击为 1、80，曝光为 10、100：总体比率 81/110；逐行比率均值 0.45 不作为总体比率。零分母返回未定义。
- 连续实验 8 条事件归为 4 位用户，用户均值为 `[2,4]` 与 `[4,6]`：均值差 2，每组 2 个独立用户，SE 为 sqrt(2)、Welch 自由度 2；双侧 p 值独立闭式为 1-1/sqrt(2)，区间用独立 SciPy 分布分位数与手算标准误组成。
- 二元实验为 `[0,0,0,1]` 与 `[0,1,1,1]`：25% 对 75%，绝对差 50 个百分点，SE=sqrt(3/32)。p 值和区间分别以独立标准正态函数及相同手算 SE 复核。
- 同金额定义比较 200 与 300，绝对差 100 元、相对差 0.5；维度、单位或计算定义不一致时不得直接相减。两次运行差异不产生新的显著性或因果结论。

数值检查通常采用绝对/相对容差 `1e-10`；计数、状态、引用与执行次数采用精确比较。报表读回使用数字/标识与内容检查，PDF 布局另作视觉验收。

| 任务族 | 本轮用例 | 本轮结果 |
| --- | --- | --- |
| 订单口径与净/毛收入 | `revenue_gross_200`<br>`revenue_ambiguous`<br>`revenue_net_unsupported` | 3/3 通过 |
| 转化率澄清 | `conversion_ambiguous`<br>`conversion_selected_weighted` | 2/2 通过 |
| 去重人数与行数 | `users_distinct_three`<br>`users_rows_are_not_uv`<br>`metamorphic_safe_column_alias` | 3/3 通过 |
| 加权比率与均值比率 | `weighted_ratio_not_mean`<br>`weighted_zero_denominator`<br>`metamorphic_shuffle_and_declared_dedup` | 3/3 通过 |
| 维度分支与窗口对比 | `branch_dimension_diff`<br>`branch_window_descriptive` | 2/2 通过 |
| 不可比单位/口径 | `comparison_unit_rejected`<br>`comparison_definition_rejected` | 2/2 通过 |
| 连接放大与跨事实边界 | `fanout_no_silent_sum`<br>`cross_fact_time_unsupported` | 2/2 通过 |
| 安全作用域与危险分支 | `sql_safe_cte_chinese_bound`<br>`sql_union_forbidden_zero_execution` | 2/2 通过 |
| 实验单位/方向/区间 | `experiment_user_welch`<br>`experiment_direction_and_overlap`<br>`experiment_binary_percentage_points` | 3/3 通过 |
| 缓存失效与历史不可变 | `cache_filter_revision_invalidates`<br>`history_config_immutable`<br>`metamorphic_display_no_recompute` | 3/3 通过 |
| 释放与分支归属 | `released_result_restore_config_only`<br>`stale_task_node_rejected` | 2/2 通过 |
| 六类导出绑定 | `exports_six_bound_to_run`<br>`exports_pdf_only_and_wrong_run` | 2/2 通过 |

变形检查包括行序打乱、明确去重下重复实体、安全映射字段别名，以及显示标题/颜色变化。缓存用例调用真实 `analysis_cache_key` 和 `AnalysisSession`：过滤、数据 revision 和语义指纹变化必须改变键；纯展示变化保持键与计算次数。评估中的历史节点存真实执行结果的小摘要，再检查配置不可变、结果释放和旧 node 拒绝。完整浏览器分页、异步竞态与会话资源测试仍由相应 UI/性能套件负责，不能把这里的小表用例替代这些验收。

## 五维质量展示

`insightpilot.analysis.quality.derive_quality_status(result)` 返回五个稳定英文键，每个含 `status`、中文 `label` 与 `reason`；`quality_rows(result)` 提供中文行。`app.components.reviewer_panel.render_quality_dimensions(result, view_mode)` 沿用现有 12pt/10.5pt 摘要卡，三个模式均明确评分边界。该适配只读取已经计算的结果、契约和有限质量摘要，不重新读取输入、画像、指纹或统计计算。

| 维度 | 判定依据 | 不作出的推断 |
| --- | --- | --- |
| execution_status | COMPLETED 且无已记录 errors；预览、缺输入、待审批等单独说明 | 完成流程不等于答案正确 |
| definition_status | 已确认/内置已验证且具备指标、版本、单位、表达式及聚合方式 | draft 或导入声明不会变成全局授权；确认不等于因果正确 |
| data_quality_status | 已执行 contract 和 data_quality 摘要，FAIL/WARN 优先；无记录为未验证 | 通过已执行检查不代表所有质量问题已排除 |
| inference_status | 有实验结果或因果探索时保留尚未验证；描述性路径不作推断认证 | p 值、CI、Reviewer 100 均不验证随机化、独立性、无混杂 |
| evidence_status | 已有证据 ID 唯一、结果表引用和建议引用相互对应 | 引用完整不等于内容已经独立复算 |

明确提示为：“流程检查评分不代表统计结论百分之百正确；未验证的前提不会因评分较高而变为已验证。”没有新增统计诊断库或虚构已验证的前提。

## 六类导出与运行绑定

PDF、Markdown、离线 HTML、Excel 增加指标口径与出处，Manifest 保留对应原运行定义；ZIP 使用同一组输出字节。没有新增自动预生成路径，单 PDF 仍不调用 HTML/Excel。默认 Excel 新增中文“指标口径”“质量维度”“评分说明”页。原有公式注入防护、HTML 转义、分页与大小预算保持。

Manifest schema 从 1.0 增量为 1.1，软件版本仍为 0.1.0。新增带兼容默认值的 `metric_definitions`、`semantic_fingerprint`、`presentation_fingerprint`、`planning_status`、`clarification`。旧 1.0 缺这些字段可以读入，未知字段和无效类型仍拒绝。导入配置不构成执行授权。

PDF/HTML/Excel 显式传入 Manifest 时，检查 result、结果包与 Manifest 的 run_id，并比较已声明语义指纹和实际计算定义。仅复制旧指纹却改变表达式/单位也会拒绝。展示标题变化可以使用同 run_id、同计算定义的新展示元数据，且不修改缓存原对象或历史节点。Markdown 读取传入结果自身的 Manifest；这些出口不读取当前 Streamlit 编辑控件。

口径卡最多展示 32 项，完整定义保存在 Manifest；卡片保留真实指标 ID 与表达式，不把 `sum(revenue)` 改成翻译后的伪表达式。现有 PDF/Excel/CSV 结果表行数及页宽限制不变。

为正式 `--suite task` 和安装后 wheel 提供真实 PDF 文本读回，本次仅新增纯 Python pypdf；`pyproject.toml` 声明 `pypdf>=6.19,<7`，`requirements.txt` 和 `requirements-lock.txt` 均固定实际验证的 `pypdf==6.19.0`。2026-09-23 从[官方 PyPI JSON](https://pypi.org/pypi/pypdf/6.19.0/json)核实该版本为 BSD-3-Clause、Python>=3.9、非撤回 wheel，发布文件时间为 2026-09-16；安装使用官方 PyPI、`--only-binary=:all: --no-deps`，没有升级其它包。PDF 生成继续使用既有 ReportLab，pypdf 只用于评估读回。

## 本轮实际运行

从项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m insightpilot.evaluation.cli --suite task --output-format json
.\.venv\Scripts\python.exe -X utf8 -m insightpilot.evaluation.cli --suite all --output-format json
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_experiment_result_outputs.py tests/test_text_file_formatting.py tests/test_upstream_task_evaluation.py tests/test_report.py tests/test_report_chinese_sections.py tests/test_report_has_actual_results.py tests/test_run_manifest.py tests/test_performance_exports.py -q
```

上述 CLI 入口已实际运行（all 包含 task），退出码 0；core 5、safety 4、determinism 2、task 29 项均通过。最后一次组合 pytest 为 37 passed、0 skipped，JUnit 时间 7.087 秒，退出码 0；其中本次新增 11 项质量/任务/导出回归。证据位于 `reports/upstream/evaluation-all.json` 与 `reports/upstream/task-report-pytest-final.xml`。这是本轮实测，不沿用历史测试数量；全量 pytest、打包及独立恢复另见总体验收。

首轮 27 个任务为 25 通过、2 失败，原记录 `reports/upstream/task-first.json` 保留。实际发现澄清选指标给未声明 metric 参数的 period_comparison 塞入了该参数，导致 FAILED，已修复规划器而未删除用例；PDF 读回缺依赖按上文补齐。随后新增二元百分点和字段别名用例至 29 个。Excel 口径表检查一度错误地在单元格内容中查找工作表名，已改为实际读取该工作表并核对指标/单位/版本，再读取运行清单核对 run_id；保留当时失败 JUnit，不改手算数值预期。

整合全量首跑另暴露 3 项兼容失败，原日志保留在 `reports/upstream/final-pytest.log`。口径卡需要保留真实指标 ID，因此旧中文统计断言改为检查实际实验统计段落，原统计内容检查全部保留；PDF 表格辅助函数恢复原调用签名，以预构造文本单元格保留表达式，并继续执行 500 字符单元格上限；`requirements.txt` 改为单版本精确依赖，保持原逐行格式质量检查。上述边界均包含在最终 37 项定向复测中。

独立审阅还要求加强实际计算定义比较、真实展示缓存键、Excel run_id，以及“未认定净收入”的检查；对应失败边界已经纳入新增测试。评估结果不会因为总分达到 1.0 就说明所有业务场景或统计前提都已验证。

## PDF 与六格式读回

本轮视觉验收的小表运行编号 `708d0a1f-7199-4a5f-a638-0649fa398b10`；PDF 4 页、12158 字节，SHA256 `7cf7e4186451a294e5e906f088f776f83062f1403ed02e77b58299d7c784e6c6`。金额当前 200、基准 300，定义为 revenue、元、sum(revenue)。

六类导出实物及哈希位于 `reports/upstream/exports/`，逐项读回记录为 `verification.json`。ZIP 内 PDF、Markdown、HTML、Excel、Manifest 与单独文件逐字节一致；Excel 运行清单编号匹配、公式单元格数为 0；PDF 每页存在页脚，文本可提取中文、原指标 ID、表达式与原 run_id。ZIP 仅含报告和有限结果 CSV，无输入 daily 表、数据库或凭据文件。

视觉验收使用 bundled Poppler 渲染全部 4 页，逐页联络图检查分页、表头、页脚、中文和遮挡，并单独放大第 1 页口径卡。最终图为 `definition_report-1.png` 至 `definition_report-4.png`、`definition_contact.jpg`、`definition_page1.jpg`。未发现重叠、裁切、缺字方框或页脚缺失；不声称每页都以原尺寸逐字审阅，也不把历史三场景 PDF 视觉验收重复算作本轮成绩。

视觉验收后恢复表格辅助函数旧签名，并增加长文本截断回归；短口径卡的内容和布局未改变，未把这次兼容修复记录为第二次视觉验收。

本机 Poppler 仍提示 Symbol/ArialUnicode display-font 及 STSong-Light 替代为 SimSun；上述最终图中中文正常。未嵌入或下载字体，其他阅读器的 CJK 支持未在本子任务验证。更广的三场景、真实浏览器、资源及独立恢复检查由总体验收记录。

本子任务未修改 source-original，未执行 Git 写入，临时报告和研究原文位于项目忽略目录或工作区隔离研究目录。

# 上游参考核查记录

读取日期：2026-09-23。对象为 InsightPilot Agent 0.1.0 本轮指标口径、澄清、分析分支、SQL AST 和任务质量的有限设计研究。

本次只读取官方仓库、官方文档和公开 API，未安装或运行五个平台、其安装脚本、hooks、skills、生成代码或测试。下载的源码仅作为文本检查，未复制到产品中。下列“测试”指检查其测试源码中的断言，不能视为本机运行通过，更不能视为本项目的统计验证或性能对比。候选设计仍须经本项目独立实现与回归验证。

研究原始材料位于工作项目之外的 `D:/InsightPilot Agent/upstream-research-20260923/`。其中 `source_reads.json` 逐文件记录固定提交 URL、读取日期、字节数和 SHA256；`read_sources/` 下以 `.txt` 保存 37 份源文件。`metadata.json`、`release_records.json`、`tree_paths.json` 及 SQLGlot 的发布/问题摘录记录接口返回事实。大型实现和测试文件只检查相关定义及用例，未宣称完整审计整个仓库。

## 1. 实际版本与读取范围

以下均为本次读取时观察到的记录，不把主分支等同发布版本，也不保证今后仍为最新。提交时间与发布条目时间均按 UTC 记录；2026-09-23 是本次读取日期。

| 项目 | 实际读取分支及固定提交 | 提交时间 | 观察到的发布记录 |
| --- | --- | --- | --- |
| WrenAI | `main` / [`4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85`](https://github.com/Canner/WrenAI/commit/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85) | 2026-09-23T03:04:35Z | [wren-v0.15.0](https://github.com/Canner/WrenAI/releases/tag/wren-v0.15.0)，2026-09-21T02:43:50Z |
| data-formulator | `main` / [`5477f0e236426dc8f74a498ec400414fba7fbc0f`](https://github.com/microsoft/data-formulator/commit/5477f0e236426dc8f74a498ec400414fba7fbc0f) | 2026-08-15T20:35:31Z | [0.8b1](https://github.com/microsoft/data-formulator/releases/tag/0.8b1)，2026-08-15T20:54:12Z |
| DB-GPT | `main` / [`ca9f014cb3ead157ca2ee6ce645658f5fb55138c`](https://github.com/eosphoros-ai/DB-GPT/commit/ca9f014cb3ead157ca2ee6ce645658f5fb55138c) | 2026-09-16T06:51:17Z | [v0.8.2](https://github.com/eosphoros-ai/DB-GPT/releases/tag/v0.8.2)，2026-08-26T11:10:31Z |
| metricflow | `main` / [`e2f17cbb6563f1ed90450639e51588057da0ba4e`](https://github.com/dbt-labs/metricflow/commit/e2f17cbb6563f1ed90450639e51588057da0ba4e) | 2026-09-10T20:32:09Z | [v0.213.0](https://github.com/dbt-labs/metricflow/releases/tag/v0.213.0)，2026-09-10T20:48:05Z |
| sqlglot | `main` / [`1d0e3f34864037c54cf6bdf45af594db62ad7319`](https://github.com/tobymao/sqlglot/commit/1d0e3f34864037c54cf6bdf45af594db62ad7319) | 2026-09-22T21:24:36Z | [标签 v30.19.0](https://github.com/tobymao/sqlglot/tree/v30.19.0)；[PyPI JSON](https://pypi.org/pypi/sqlglot/json) 版本 30.19.0，wheel 上传 2026-09-22T15:19:56.761939Z |

需要保留的差异和访问边界：

- WrenAI 发布正文的变更说明日期为 2026-09-16，发布条目的 `published_at` 是 2026-09-21；两者不是同一种时间。
- Data Formulator 的标签是 `0.8b1`，CHANGELOG 写 `0.8.0b1`，GitHub 发布 API 的 `prerelease` 字段为 `false`。保留三项事实，不将字段 `false` 推断为生产稳定性，也不直接照抄规格中的版本判断。
- DB-GPT 的 v0.8.2 已从官方发布记录核实；同时能读到 v0.8.1 的 2026-06-18 发布记录，不只依靠搜索索引。
- SQLGlot 的 GitHub releases 接口返回空列表，但 tags 与 PyPI 有发布记录，不能将空列表解释为停止维护。v30.19.0 标签指向 `02562228357e7d933ef66e27c56e257b88faad8f`，与本次读取主分支的提交不同。PyPI HTML 页读取失败，改用官方 JSON 接口成功核实版本、MIT 声明和未撤回的发布文件；未安装这些发布包。本轮不据此提出升级本地依赖。

可复查的官方接口：

- WrenAI：[主分支提交](https://api.github.com/repos/Canner/WrenAI/commits/main)、[发布记录](https://api.github.com/repos/Canner/WrenAI/releases)、[固定提交文件树](https://api.github.com/repos/Canner/WrenAI/git/trees/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85?recursive=1)。
- data-formulator：[主分支提交](https://api.github.com/repos/microsoft/data-formulator/commits/main)、[发布记录](https://api.github.com/repos/microsoft/data-formulator/releases)、[固定提交文件树](https://api.github.com/repos/microsoft/data-formulator/git/trees/5477f0e236426dc8f74a498ec400414fba7fbc0f?recursive=1)。
- DB-GPT：[主分支提交](https://api.github.com/repos/eosphoros-ai/DB-GPT/commits/main)、[发布记录](https://api.github.com/repos/eosphoros-ai/DB-GPT/releases)、[固定提交文件树](https://api.github.com/repos/eosphoros-ai/DB-GPT/git/trees/ca9f014cb3ead157ca2ee6ce645658f5fb55138c?recursive=1)。
- metricflow：[主分支提交](https://api.github.com/repos/dbt-labs/metricflow/commits/main)、[发布记录](https://api.github.com/repos/dbt-labs/metricflow/releases)、[固定提交文件树](https://api.github.com/repos/dbt-labs/metricflow/git/trees/e2f17cbb6563f1ed90450639e51588057da0ba4e?recursive=1)。
- sqlglot：[主分支提交](https://api.github.com/repos/tobymao/sqlglot/commits/main)、[发布记录](https://api.github.com/repos/tobymao/sqlglot/releases)、[固定提交文件树](https://api.github.com/repos/tobymao/sqlglot/git/trees/1d0e3f34864037c54cf6bdf45af594db62ad7319?recursive=1)。

SQLGlot 另读了[标签接口](https://api.github.com/repos/tobymao/sqlglot/tags)和[问题 8315 接口](https://api.github.com/repos/tobymao/sqlglot/issues/8315)。该问题在读取时为 `closed` / `completed`，关闭时间 2026-09-10T11:35:14Z；这里只用它说明跨方言 NULL 语义需要独立检查，不作为仍未修复漏洞的宣传，也未独立运行其修复用例。

## 2. 许可证范围与采用方式

本轮默认借鉴设计并独立实现；下列为所读路径的源仓库许可核查，不推断所有历史版本、依赖、商业模块或商标资产采用同一许可。没有复制或改写上述源文件进入产品，因此本阶段不新增虚构代码复用的 THIRD_PARTY_NOTICES 条目；将来若决定复用代码，仍须按准确版本和路径逐项保留声明。

| 项目 | 本次核查的适用路径 | 许可及依据 | 未覆盖边界 |
| --- | --- | --- | --- |
| WrenAI | `core/**`，包括所读 Python/Rust 模块及测试；根 README | Apache-2.0；[根许可证映射](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/LICENSE)与[模块许可证](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren-core-base/LICENSE) | 根映射将 `docs/**` 列为 CC BY 4.0；预留 AGPL 文本不表示本次所读 core 路径采用 AGPL。已发布包许可按其 manifest，商标不随代码许可授权。 |
| Data Formulator | 所读 `src/`、`tests/`、README/CHANGELOG | MIT；[LICENSE](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/LICENSE) | 未调查其他依赖和资产授权。 |
| DB-GPT | 所读 `packages/dbgpt-core/`、`packages/dbgpt-serve/` 与 README | MIT；[LICENSE](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/LICENSE) | 文件树中另有 skills 的独立 LICENSE，不在本次采用范围；未安装模型或技能。 |
| MetricFlow | 所读 `metricflow/`、`metricflow_semantics/` 及其测试、TENETS | Apache-2.0；[LICENSE](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/LICENSE) | 不概括历史许可证，不推断本次未读的 `dbt-metricflow/` 子包及其历史。 |
| SQLGlot | 所读 `sqlglot/`、`tests/test_parser.py`、`tests/test_optimizer.py` | MIT；[LICENSE](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/LICENSE) | `tests/fixtures/jsonpath/` 有独立 LICENSE，本次未取用其文件。 |

## 3. WrenAI：可审查模型与分阶段校验

实际检查 [core/wren-core-base/src/mdl/manifest.rs](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren-core-base/src/mdl/manifest.rs) 的主键、模型来源及内嵌测试：主键可为单列或多列，模型来源要求表引用与 SQL 引用二选一，空主键会被拒绝。这里只核实显式模型约束；指标的全部业务口径字段并未从一个宏生成文件中得到验证。

[core/wren/src/wren/engine.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/src/wren/engine.py) 将原始 SQL 策略检查、规划/转写后检查、执行区分开；[core/wren/src/wren/model/error.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/src/wren/model/error.py) 分别表达无效 SQL、无效模型、阻止函数/语句等代码及发生阶段。[core/wren/tests/unit/test_engine.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/tests/unit/test_engine.py) 可见 strict 模式拒绝未注册表、允许 MDL 表、拒绝指定危险函数和超时分类的断言；非 strict 模式允许未知表的断言也存在，不能把该宽松设置直接用于本项目授权范围。[core/wren/tests/unit/test_check_descriptions_guards.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/tests/unit/test_check_descriptions_guards.py) 检查非映射 properties 的输入错误。

采用建议：把已有语义模型的口径与来源变成可审查元数据；复用当前查询通道，在原查询及限流改写后坚持同一策略；中文错误由稳定代码和阶段生成。拒绝整套引擎、通用转写、商业权限系统及旧 GenBI UI 的移植。[当前 README](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/README.md) 区分当前主线、旧 GenBI 与商业功能；本次未验证其行列权限或生产部署。本地澄清规则和统计可信度须另做独立测试。

## 4. Data Formulator：有版本的操作与分支配置

[src/dataOperations/models.ts](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/dataOperations/models.ts) 定义有 schema 版本的操作、候选计划、选中计划、结果引用、失败信息和 superseded 状态，输入转换为独立视图对象。[tests/frontend/unit/dataOperations/models.test.ts](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/tests/frontend/unit/dataOperations/models.test.ts) 对原对象修改不影响视图、未知版本、无效 selectedPlanId、错误哈希以及部分失败信息有具体断言。借鉴点是不可变配置快照、显式父子/替代关系和计划选择校验；无需搬入其执行器或模型调用。

[src/views/DataThread.tsx](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/DataThread.tsx) 本次只检查父节点链、按 ID 定位分支、焦点切换及运行/澄清显示相关片段；[src/views/threadLayout.ts](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/threadLayout.ts) 仅作为布局实现背景。[CHANGELOG.md](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/CHANGELOG.md) 的线程与澄清功能声明可由这些路径部分支撑，但未证明跨分支数值可比、历史大结果预算、会话隔离或因果结论正确。[tests/backend/agents/test_provenance_models.py](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/tests/backend/agents/test_provenance_models.py) 包含来源模型往返与特定敏感字段样例断言，不足以得出全平台脱敏正确的结论。

采用建议：在现有会话中增加有限数量的配置节点与摘要，保留 parent_run_id 和数据 revision；浏览只恢复配置，显式提交才计算。可比性必须由本项目逐项核对指标、单位、窗口、过滤条件、维度和统计单位。拒绝将任意多轮自然语言理解、React 重写或模型推理作为本次分支闭环的前提。

## 5. DB-GPT：执行状态与评估结果分开

[packages/dbgpt-core/src/dbgpt/core/awel/task/base.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/awel/task/base.py) 的任务状态与 TaskOutput 分开，[packages/dbgpt-core/src/dbgpt/core/awel/task/task_impl.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/awel/task/task_impl.py) 本次检查空输出、普通输出及同步/异步转换接口；[packages/dbgpt-core/src/dbgpt/core/awel/tests/test_run_dag.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/awel/tests/test_run_dag.py) 的输入、map、reduce、join、branch 用例分别断言状态和预期输出。借鉴任务状态不应替代结果正确性，不引入第二套 DAG 或任务管理器。

[packages/dbgpt-core/src/dbgpt/core/interface/evaluation.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/interface/evaluation.py) 区分 metric_name、score、passing、feedback 等信息，并提供精确匹配和自定义函数评价；passing 的默认值不表示统计前提已成立。[packages/dbgpt-serve/src/dbgpt_serve/agent/evaluation/evaluation_metric.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-serve/src/dbgpt_serve/agent/evaluation/evaluation_metric.py) 的部分指标检查应用/意图命中，不能充当分析数值或统计置信度。

采用建议：在已有评估框架中分别记录执行、口径、质量、推断前提和证据；小表手算或独立参考实现给出 expected，正确澄清和正确拒绝同样可通过任务验证。拒绝 LLM judge、检索相关性分数、意图命中率与 p-value/置信区间相混；未部署或评估 DB-GPT 模型、RAG、数据库接入质量与平台性能。

## 6. MetricFlow：实体粒度与连接约束

[metricflow_semantics/model/semantics/semantic_model_join_evaluator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/metricflow_semantics/model/semantics/semantic_model_join_evaluator.py) 明确按实体类型判定连接，拒绝目标端 FOREIGN 等会扩大匹配的组合，并单独处理时间有效性约束；[tests_metricflow_semantics/model/semantics/test_semantic_model_join_evaluator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/tests_metricflow_semantics/model/semantics/test_semantic_model_join_evaluator.py) 可见 distinct/foreign/natural 目标及缺失实体的具体测试。[metricflow/validation/dataflow_join_validator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/metricflow/validation/dataflow_join_validator.py) 对聚合后唯一实体集合与普通实体集合区分处理，[tests_metricflow/validation/test_join_validator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/tests_metricflow/validation/test_join_validator.py) 检查对应连接约束。

[官方连接文档](https://docs.getdbt.com/docs/build/join-logic) 用实体定义连接路径并解释 fanout/chasm 限制；这是读取日的动态文档，不具有上表源码的固定版本保证。[TENETS.md](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/TENETS.md) 把正确性排在性能等目标之前。

采用建议：口径卡显式写统计单位、去重键、可加性与允许粒度；沿用现有关系验证，遇到一对多 fanout 或不受支持的跨事实关系明确拒绝，不能仅凭 SQL 能执行就认定定义正确。拒绝引入 dbt 项目、适配器与完整 MetricFlow 编译器，也不扩大本轮允许的跨事实时间关联范围。上游可支持的其他连接和所有历史版本许可均未核实。

## 7. SQLGlot：完整语句、作用域和方言边界

[sqlglot/__init__.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/sqlglot/__init__.py) 的 parse 返回语句列表；[tests/test_parser.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/tests/test_parser.py) 的 test_multi 包含多条 SELECT 与空语句位置，说明策略层必须检查完整返回列表。[sqlglot/optimizer/scope.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/sqlglot/optimizer/scope.py) 区分真实表、CTE/子查询作用域及别名；[tests/test_optimizer.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/tests/test_optimizer.py) 的 test_scope 涵盖嵌套 CTE、相关子查询、UNION 和 DML 内子查询，故能构建作用域不等于根语句只读。不能把只看第一个 SELECT 或全局表名集合当成作用域授权。

[README.md](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/README.md) 明确建议指定来源方言，并说明解析器可能接受数据库拒绝的语句；跨方言不支持项默认可能只告警后尽力转换。[sqlglot/errors.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/sqlglot/errors.py) 的 RAISE/IMMEDIATE 可提供显式错误，但这些选项不能替代权限、函数白名单、列范围和数据库自身只读限制。

采用建议：使用当前实际锁定并测试的 SQLGlot 版本作为语法与作用域工具；DuckDB/SQLite 各自指定 read dialect，单条受支持只读查询、完整分支授权、固定函数/节点允许列表、SQL 长度和 AST 节点预算由本项目策略完成。解析或限流重写失败时拒绝，缺依赖不能回退到弱正则继续执行。拒绝通用优化器自动改写所有业务查询或自动跨方言转换。本次读取主分支不代表本机已经测试此版本；NULL、除法与日期语义仍须按实际数据库分别验证。

## 8. 完整来源清单与未验证项

下表列出实际取得的全部固定提交文本。检查范围是上述相关定义与测试断言；README 和发布信息只用于能力边界、版本与入口定位。每个链接可直接复查相同版本，不依赖后续 main 内容。

| 项目 | 取得并检查的文件 |
| --- | --- |
| WrenAI | [LICENSE](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/LICENSE)<br>[README.md](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/README.md)<br>[core/wren-core-base/LICENSE](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren-core-base/LICENSE)<br>[core/wren-core-base/src/mdl/manifest.rs](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren-core-base/src/mdl/manifest.rs)<br>[core/wren/src/wren/model/error.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/src/wren/model/error.py)<br>[core/wren/src/wren/engine.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/src/wren/engine.py)<br>[core/wren/tests/unit/test_engine.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/tests/unit/test_engine.py)<br>[core/wren/tests/unit/test_check_descriptions_guards.py](https://github.com/Canner/WrenAI/blob/4d55c52a223c641dacb2fbd3c6a6cfcdb37d9a85/core/wren/tests/unit/test_check_descriptions_guards.py) |
| data-formulator | [LICENSE](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/LICENSE)<br>[README.md](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/README.md)<br>[CHANGELOG.md](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/CHANGELOG.md)<br>[src/dataOperations/models.ts](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/dataOperations/models.ts)<br>[src/views/threadLayout.ts](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/threadLayout.ts)<br>[src/views/DataThread.tsx](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/src/views/DataThread.tsx)<br>[tests/frontend/unit/dataOperations/models.test.ts](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/tests/frontend/unit/dataOperations/models.test.ts)<br>[tests/backend/agents/test_provenance_models.py](https://github.com/microsoft/data-formulator/blob/5477f0e236426dc8f74a498ec400414fba7fbc0f/tests/backend/agents/test_provenance_models.py) |
| DB-GPT | [LICENSE](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/LICENSE)<br>[README.md](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/README.md)<br>[packages/dbgpt-core/src/dbgpt/core/awel/task/base.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/awel/task/base.py)<br>[packages/dbgpt-core/src/dbgpt/core/awel/task/task_impl.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/awel/task/task_impl.py)<br>[packages/dbgpt-core/src/dbgpt/core/interface/evaluation.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/interface/evaluation.py)<br>[packages/dbgpt-core/src/dbgpt/core/awel/tests/test_run_dag.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-core/src/dbgpt/core/awel/tests/test_run_dag.py)<br>[packages/dbgpt-serve/src/dbgpt_serve/agent/evaluation/evaluation_metric.py](https://github.com/eosphoros-ai/DB-GPT/blob/ca9f014cb3ead157ca2ee6ce645658f5fb55138c/packages/dbgpt-serve/src/dbgpt_serve/agent/evaluation/evaluation_metric.py) |
| metricflow | [LICENSE](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/LICENSE)<br>[README.md](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/README.md)<br>[TENETS.md](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/TENETS.md)<br>[metricflow_semantics/model/semantics/semantic_model_join_evaluator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/metricflow_semantics/model/semantics/semantic_model_join_evaluator.py)<br>[tests_metricflow_semantics/model/semantics/test_semantic_model_join_evaluator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/tests_metricflow_semantics/model/semantics/test_semantic_model_join_evaluator.py)<br>[metricflow/validation/dataflow_join_validator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/metricflow/validation/dataflow_join_validator.py)<br>[tests_metricflow/validation/test_join_validator.py](https://github.com/dbt-labs/metricflow/blob/e2f17cbb6563f1ed90450639e51588057da0ba4e/tests_metricflow/validation/test_join_validator.py) |
| sqlglot | [LICENSE](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/LICENSE)<br>[README.md](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/README.md)<br>[sqlglot/__init__.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/sqlglot/__init__.py)<br>[sqlglot/optimizer/scope.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/sqlglot/optimizer/scope.py)<br>[sqlglot/errors.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/sqlglot/errors.py)<br>[tests/test_optimizer.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/tests/test_optimizer.py)<br>[tests/test_parser.py](https://github.com/tobymao/sqlglot/blob/1d0e3f34864037c54cf6bdf45af594db62ad7319/tests/test_parser.py) |

尚未验证：五个平台的安装可用性、运行时正确性、横向性能、在线模型表现、生产安全性、全部依赖许可和所有历史版本。未研究本轮五个项目之外的维护状态，因此不复述 Vanna/PandasAI 的维护结论。公开源文件取得成功不代表任何产品功能已完成；本地实现、测试、性能及导出验收由本轮对应报告单独记录。

本阶段只增加本文；原始恢复基线未改动，未执行 Git 写入，未上传项目数据、连接信息或源码快照。外部文本留在隔离研究目录，不进入产品包或源码快照。

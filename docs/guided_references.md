# 引导式分析的有限参考记录

读取日期：2026-09-29。以下均为第一方资料，只借鉴交互契约与职责划分；本轮本地代码独立实现，没有安装、启动或复制这些平台，没有执行其安装脚本或技能。

|资料与实际 URL|读取身份和范围|具体借鉴与本地边界|
|---|---|---|
|[Data Formulator README](https://github.com/microsoft/data-formulator)、[CHANGELOG](https://github.com/microsoft/data-formulator/blob/main/CHANGELOG.md)|GitHub commits API 实取 main `5477f0e236426dc8f74a498ec400414fba7fbc0f`，提交日期2026-08-15。读到统一 Data Thread 的问题、澄清、结果与分支说明；日志标注 `0.8.0b1`。|把加载数据、提问、查看结果及继续探索放在统一工作台。本地沿用既有历史和受控结果引用，没有引入其代理或数据连接平台。|
|[WrenAI README](https://github.com/Canner/WrenAI)、[Architecture](https://docs.getwren.ai/oss/reference/architecture)、[What is context](https://docs.getwren.ai/oss/concepts/what_is_context)|GitHub commits API 实取 main `7b74af177ea9a0ad387175dd7849ea7ad30c73da`，提交日期2026-09-29；公开文档未暴露对应提交。|业务口径、字段实际值和批准关系共同决定可回答性；规划、校验、执行分离，错误提供修复路径。本地复用 Planner/requirements，不引入其 Rust 引擎、向量记忆、模型或跨方言转换。|
|[Cortex Analyst REST API](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api)|滚动文档，无可核对提交或固定版本。读取非流式响应和歧义建议示例。|歧义问题应提供下一步建议，不能同时声称已生成可执行答案。文档说明 suggestions 与 SQL 互斥，并推荐迁移 Cortex Agents。本地仅参考契约，不调用任一云 API。|
|[Streamlit selectbox](https://docs.streamlit.io/develop/api-reference/widgets/st.selectbox)|在线文档显示1.64.0；本机实际安装1.63.0，已通过 inspect.signature 核对所用参数。|默认 index=0 会选首项；自动模式必须用明确稳定 ID。index=None 可空选，format_func 只改显示，disabled 作用于整个控件，并无逐项禁用参数。|
|[Streamlit forms](https://docs.streamlit.io/develop/concepts/architecture/forms)|滚动官方文档；本机1.63.0。|表单未提交时值不发送后端；问题放表单外，在 Enter/失焦触发轻量建议。表单提交再使用本次值预检，不能假称读取了未提交参数。|
|[Streamlit Session State](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)|滚动官方文档；本机1.63.0。|回调先于脚本重跑；控件创建后禁止直接改其状态。示例应用在回调中原子更新，稳定 ID 与来源状态分开保存。|
|[Streamlit fragment](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)|在线API文档1.64.0；本机1.63.0签名已核对。|局部交互可只重跑 fragment；仍需自行约束副作用。本地保留既有任务轮询和会话隔离，不新增统计轮询或并行 fragment。|

## 许可证与未核实事项

- Data Formulator 实读[固定提交 LICENSE](https://raw.githubusercontent.com/microsoft/data-formulator/5477f0e236426dc8f74a498ec400414fba7fbc0f/LICENSE)，为 MIT，版权归 Microsoft Corporation。本轮未复制其代码或文档段落。
- WrenAI 实读 [main LICENSE](https://raw.githubusercontent.com/Canner/WrenAI/main/LICENSE)：`core/`、`sdk/`、`skills/`、`examples/` 及根文件对应 Apache-2.0，`docs/` 对应 CC-BY-4.0；存在预备 AGPL 文本但当前清单未指定 AGPL 模块。README 的简写不能代替路径许可证。固定提交 LICENSE 经浏览工具读取失败，因此这里只声明读到的 main 许可证，不声称固定提交逐字一致。
- Snowflake 与 Streamlit 站点文档没有在所读页面给出代码复用许可；本轮只用链接和独立概述，不复制示例或平台实现。其文档版本与本机行为以实际本地测试区分。
- GitHub commits API 最初经浏览工具返回 Internal Error，随后通过 HTTPS API 成功取得上述 SHA；没有关闭证书校验或使用账户凭据。
- Data Formulator 的 CHANGELOG 链接指向 [0.8.0b1 tag](https://github.com/microsoft/data-formulator/releases/tag/0.8.0b1)，访问返回404。只能确认日志声明，不能确认对应发布包或标签内容。
- 本轮未在本机运行外部平台，也未核验其推荐准确率、性能或安全结论。没有把宣传描述当成本地能力证据。

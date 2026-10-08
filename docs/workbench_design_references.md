# 工作台界面参考资料与本地取舍

读取日期：2026-09-29（Asia/Shanghai）。本次只读规格列出的公开第一方页面与图片，没有登录、安装平台、运行外部脚本或采用外部代码。项目版本保持 0.1.0。

## 来源事实、借鉴与边界

|资料与实际 URL|实际读取版本、事实和可见界面|本地借鉴思想|本地取舍与未验证内容|
|---|---|---|---|
|[Metabase query builder](https://www.metabase.com/docs/latest/questions/query-builder/editor)、[官方 notebook 示例图](https://www.metabase.com/docs/latest/questions/images/notebook-editor.png)|文本与真实 Chrome 页面均读取成功，页面版本显示 v0.63。图中可见 Data/Orders、Filter、Summarize/Count/Created At: Month 以及 Visualize 动作；这是文档静态示例，未操作实际部署。|让选表、筛选、指标与分组范围可见，明确提交后生成结果。|继续使用本地已认证查询、映射和显式执行，不引入自由表达式、任意 SQL 或连接管理平台。图片只存研究证据，不进入应用。|
|[Metabase drill-through](https://www.metabase.com/docs/latest/questions/visualizations/drill-through)|实际读取官方文档文本；文档说明图表不同位置提供不同探索动作，原始 SQL 问题的动作存在限制。未逐一操作所有图型。|选择结果分组后建立有来源的新分析，而不是无痕覆盖父结果。|本地必须有真实键、run_id 和数据修订校验，选择仅生成草稿，明确提交才计算；不宣称所有鼠标事件或原始记录下钻都可用。|
|[Superset 6.1.0 Explore](https://superset.apache.org/user-docs/6.1.0/using-superset/exploring-data/)|文本、页面及透视示例均读取，页面明确显示 Version 6.1.0。实际看到左侧文档导航、图型选择目录、分类/搜索、Pivot Table 示例说明；正文说明数据参数与 Customize 展示设置。|把字段配置、图表与结果表放在同一探索流程；方法与图型可显式查找，展示设置和计算范围分开。|只支持本轮有限单表分布、分组与二维透视；不引入 SQL Lab、任意变换、拖拽看板平台。未安装 6.1.0，也未认证上游透视统计实现。|
|[Superset 原 chart creation 链接](https://superset.apache.org/docs/creating-charts-dashboards/exploring-data/)|本次请求被重定向到 `https://superset.apache.org/docs/using-superset/creating-your-first-dashboard/`，文本工具返回0行；不把此链接当作已读取的 Next 内容。|无新增实现依据。|未验证重定向页的界面、版本或实现，以明确6.1.0文档为本次来源。|
|[Lightdash metrics catalog](https://www.lightdash.com/metrics-catalog)、[interactive dashboards](https://www.lightdash.com/interactive-dashboards)|两页官方文本已读；目录页真实浏览器截图可见指标名称、定义/描述、类别标签与 Explore 提示。页面未给固定发行版本，是产品展示页；互动页文本描述分组、筛选和继续探索。|可搜索目录展示定义，选择、图表和口径引用同一语义对象；已有结果提供后续探索动作。|这些页面不证明所有功能在任意开源部署可用。未核验商业/开源版本差异，未进入在线Demo、未采用AI或计划推送功能。|
|[JASP methods](https://jasp-stats.org/features/)、[homepage](https://jasp-stats.org/)、[how-to](https://jasp-stats.org/how-to-use-jasp/)|三个第一方页面文本已读，Features真实截图可见 Modules 与 Frequentist/Bayesian 列，以及描述统计、T-tests、ANOVA等方法行。how-to页脚标示 JASPVersion 0.19.3；不能据此推断全站所有模块都属于同一版本。|按分析目的组织方法，把用途、前提和输出说明放在配置附近。|本地仍保留十个既有剧本，不引入上游全部模型或自动实时重算。没有启动JASP，未核验其各方法算法或原生应用界面交互。|

表中“本地借鉴”是本轮独立设计选择，不是声称上游具备相同的 Agent 工作流、预检、审批或分支协议。未复制Logo、字体、截图、界面源码；没有复用第三方代码，因而没有新增第三方代码许可证声明。研究记录不作法律合规保证。

## 实现接口核查

官方网页会更新，因此以下文本版本和本机版本分开记录；产品调用以本机安装API及回归为准。

|接口资料|读取到的官方版本/事实|本机实际检查与实施约束|
|---|---|---|
|[Streamlit Plotly selection](https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart)|页面显示1.64.0，说明 `on_select` 与 points/box/lasso 选择。|本机1.63.0签名实际含 `on_select`、`selection_mode`、`key`；仅采用真实支持的选择契约，服务端检查事件，不能信任行号或任意客户端值。|
|[Streamlit tabs](https://docs.streamlit.io/develop/api-reference/layout/st.tabs)|默认会计算全部标签内容；显式 `on_change` 与 `.open` 支持条件构建。|本机1.63.0签名实际含 `on_change`、`key`、`default`。页面路由/子页使用条件分支；只写 `st.tabs` 不能声称按需执行。|
|[Streamlit forms](https://docs.streamlit.io/develop/concepts/architecture/forms)、[session state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)|官方表单与状态文档已读。表单值按提交发送；控件创建后的非法赋值有约束。|问题、草稿、冻结请求分开；参数必须提交后重检，callback读取当前状态，不捕获旧值，不以SessionState赋值伪造用户点击。|
|[pandas pivot_table](https://pandas.pydata.org/docs/reference/api/pandas.pivot_table.html)|页标题3.0.6，说明聚合、`margins`、缺失组、`observed`；文档标示3.0起 observed 默认变化。|本机3.0.5，实际签名 `aggfunc='mean'`、`margins=False`、`dropna=True`、`observed=True`。这些默认值不是本地业务口径；显式处理mean、比率、跨格去重与未观测组合，不靠显示格相加生成合计。|
|[SciPy pearsonr](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html)、[spearmanr](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html)|官方页面标题1.18.0；两种系数及输入/前提边界文本已读。|本机1.18.1；这里只用于有限P1边界核查，不证明本轮新建相关性方法。P0未完成不能开放假入口，已有能力优先复用。|

本机实际签名记录在 `reports/workbench/research/access.json`，包含 `plotly_chart`、`tabs`、`form`、`dataframe`、`expander` 与 `pandas.pivot_table`。本轮没有升级这些依赖。

## 可见界面证据与失败记录

使用已安装的 Chrome 153.0.8010.53、隔离浏览器上下文、1440×900、默认100%缩放访问公开页面。没有使用用户浏览器档案。CUA入口曾遇到本机Windows登录错误1385，实际资料截图采用现有本地Playwright/Chrome方式完成，没有把失败当成网页不可访问。

以下截图均已实际打开检查，保存在 `reports/workbench/research/`，只作本地研究证据，不打包到产品：

- `metabase-editor.png`：文档标题、v0.63标记和查询步骤示例。
- `metabase-notebook.png`：官方2058×1146示例图在浏览器内完整可见，数据/过滤/汇总/提交层次清楚。
- `superset-explore-page.png`：6.1.0版本标记与探索文档页面。
- `superset-pivot-example.png`：文档中的创建图表目录与Pivot Table示例；这是静态截图，不冒充已运行Superset。
- `lightdash-catalog.png`：产品目录展示，实际可见指标行、说明和类别。
- `jasp-methods.png`：方法模块列表及 Frequentist/Bayesian 两列。

首次Superset截图尝试得到HTTP200，但精确标题定位因标题结尾零宽字符超时，记录在 `access.json`；第二次读取真实heading后完成截图，记录 `superset-retry.json`。没有删除这条失败证据。Lightdash互动页、JASP首页/how-to与Metabase下钻页本次仅确认文字，不声称额外截图或完整交互已验证。

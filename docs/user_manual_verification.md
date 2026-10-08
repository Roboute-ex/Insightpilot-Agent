# 中文使用手册核对记录

核对日期：2026-09-30；产品版本：0.1.0。本轮仅制作文档。详细规格实际在父目录 `D:/InsightPilot Agent/USER_MANUAL_SPEC.md`，已完整读取；项目根没有另一个同名文件。

## 事实来源及优先级

以当前源码控件、注册方法和输入校验为第一依据，以用户刚完成的 `reports/workbench/browser-final-all-20260930-114015987` 为最新运行事实。该目录 `checks.json` 的 scenario=all，174个已列检查全部true，page_errors为空，无error键。进程退出码0由用户明确提供，本地没有独立退出码文件；本轮没有重跑all，也没有将这些成绩算成本轮新测试。旧browser-08中途失败状态已被这次完整串联补齐，不能当作当前未完成。

辅助读取：AGENTS、README、requirements-lock、版本声明、workbench_redesign_acceptance、workbench_performance、data_exploration、analysis_guidance及method_discovery文档。旧文档的数值例子只在与最新fixture/源码一致时使用。尤其核心测试整体distinct=2与本手册四行数据distinct=3不同，手册使用后者。

## 章节事实核对

|手册章节|直接依据|本轮核对范围与边界|
|---|---|---|
|第一次交易分析|app/ui_streamlit.py、guidance_panel、result_panel、export_panel；最新all首页/订单/导出截图|准确中文控件、standard场景、数据参考日、推荐不执行、生成与下载两步；没有在用户会话重新操作|
|启动、打开、停止|README、USER_MANUAL_SPEC既有启动命令、Streamlit当前配置|记录既有命令与安全停止说明；本轮未启动、停止或重启8511|
|四导航|workbench_shell、method_gallery及最新01/02截图|四入口、十方法目录/筛选/清除；预览不改分析表|
|自有数据|data_source_panel、mapping_panel、ingestion/file_loader、db_loader|编码/sheet/字段映射与来源变化；后缀存在不等于本轮实际验证所有Excel格式|
|十方法|playbooks/registry、builtins、models、validation、executor、planning/analysis_advisor/planner|交叉核对最低输入和可提交状态；不能只用Registry布尔标记推断漏斗/留存输入|
|趋势/周期/贡献/下钻|playbooks/executor、analysis/drilldown、drilldown_panel|默认窗口、份额与变化贡献；父目标日城市子范围、选择只形成草稿|
|实验|analysis/experiments、data/scenarios/content、semantic_panel|独立user_id、mean/Welch、0/1 proportion、方向、p-value和差值区间；不证明随机化|
|因果|analysis/causal_light、executor、mapping/semantic_panel、最新24行fixture及报告|只写实际原始差/OLS，covariate真实列、n24、限制；明确参数控制变量不能仅靠映射协变量|
|探索与透视|exploration_panel、analysis/exploration、data_exploration及最新4行fixture|有限筛选、sum/mean/ratio/distinct、总计、Others/未观测、50×30展示与100000聚合输出边界|
|历史比较|history_panel、analysis/threads、performance|10条小历史/一份完整结果、恢复/比较的身份要求、JSON不恢复数据或授权|
|六类导出|export_panel、reports/pdf/html/excel/bundle/manifest|顺序、按钮、行数上限、run绑定、ZIP依赖与下载位置|
|故障/性能|background_tasks、performance_tasks、performance、SQL安全/审批校验|协作取消和内存状态边界；不提供关闭校验、杀全部Python等操作|
|CLI与术语|insightpilot/cli.py、实际--help/--list-playbooks|仅两条查询命令本轮实际执行；分析示例参数按当前定义/已有证据核对，不声称本轮运行|

详细源码事实与参数审计保留在 `reports/user-manual/facts-audit.md`，不塞入日常手册正文。

## 教学数据与截图

两份CSV原样复制自最新all目录，来源脚本为check_workbench_browser.py，全部合成。字节SHA与来源一致；字段名没有改写。离线使用独立NumPy最小二乘和基础分组运算复核，不调用应用分析器生成expected：

- 因果24行，control/treatment各12，字段date/group/outcome/covariate。组均值15.5/17.5，原始差2，含截距、处理指示和covariate的OLS处理系数2，有效n24。
- 透视4行，amount合计120、均值30，甲/乙均值20/40；分子总量10、分母总量92，比率10/92；乙组0/0为缺失。整体entity_id去重3，甲乙各2，不能相加或套用其它fixture的2。
- 最新七个run的六格式文件已离线检查存在，ZIP内PDF与单独PDF字节一致。没有生成新的应用报告。

9张图片全部先用view_image实际查看，再原样复制到docs/assets/user_manual。来源、SHA、用途、尺寸、已看范围与PDF显示区域见 `reports/user-manual/assets-verification.json`。原图未改字、数值或控件，PDF仅通过绘图裁切窗口展示主区域，HTML内嵌完整图。完整映射表单不在已存截图中；手册采用源码核对的文字步骤，不声称图片包含全部字段。

## 本轮低成本检查

已实际执行CLI --help与--list-playbooks，均exit0，后者10项。命令带-B防止写产品pyc，输出保存在 `reports/user-manual/20260930-125203/cli-help.txt` 与 `cli-playbooks.txt`。没有执行分析Demo、全量pytest、性能基准、浏览器all或完整源码恢复。

构建使用独立docs/tools脚本、已安装ReportLab/Pillow/pypdf、系统Microsoft YaHei字体。PDF嵌入必要字体子集，不复制或下载字体文件。HTML与PDF从同一份user_manual.md生成；速查PDF从quick_reference.md生成，正文事实与手册同版本。

### 最终格式与链接结果

阅读版目录为 `reports/user-manual/20260930-125203/`，三份规定文件均已生成。手册30页，其中9页为A4横向截图页，其余A4纵向；速查卡2页A4纵向。正文保持10.5pt，速查卡通过段落留白和表格间距整理为两页，没有压小正文字号。中文字体子集实际嵌入；提取文字可搜索、无替换字符。主手册42个书签、36个内部链接目标均可解析；速查卡6个书签。目录页码与实际章节位置一致。

两份PDF全部32页都已实际渲染并目视检查：主手册1–30页、速查卡1–2页。使用已安装的pypdfium2按1.6倍渲染；先逐页检查，修正两处图注和两张表的列宽后再次渲染。交付渲染与已看版本只有主手册6、15、20、22页不同，这四页已重新目视；其余28页PNG的SHA完全相同。没有用文字提取代替视觉检查。完整渲染在 `rendered-delivery/`；没有发现中文缺字、正文截断、表格覆盖或代码越界。跨页表头正常。横向截图单独成页，因此部分邻接正文页留白较大，这是可读性取舍。

HTML使用独立、隔离、离线Chrome 153.0.8010.53仅打开本地手册，13项检查全部true：中文文本可搜索、13个目录入口、实际目录点击、9张内嵌图加载、全部内部目标存在、两份内嵌CSV下载且字节一致、无外部请求、无页面错误；1440/1024/760宽度均无整页水平溢出。1440和760截图已目视。未点击通往8511的应用链接。HTML不依赖外部CDN、脚本、字体或账号。

Markdown目录锚点、图片和文件链接全部有效；README追加的7条静态链接全部指向现有文件。README原有字节保持不变。8个PowerShell代码块经本机Parser只做语法解析，错误0；这不等于重新执行启动、分析或计划命令。当前分析命令的参数来源仍为CLI帮助和源码，不将静态解析写成实际分析通过。

最终内容主源SHA256：

- user_manual.md：`e2de0a94e6c98ec7fbc6743bc8ce664ebb6987e57c01b4dbbf786f77bff31f7e`
- quick_reference.md：`376effc8e4fd1ecd9702b1456d789702345ab4336d22a7ad9843f6cc6efca7f8`

HTML与手册PDF由上述同一主源构建；速查PDF由上述速查源构建。构建记录中顶层outline列表长度不是递归书签总数，真实递归计数见 `pdf-structure-validation.json`。

### 已实际执行的低成本命令

在项目根目录执行过以下文档命令。`--replace-generated`仅用于本轮新目录中的排版迭代，不应拿它覆盖以前交付或用户正在阅读的文件。日后再生成请先使用新的时间戳目录。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8 = '1'
& .\.venv\Scripts\python.exe -B -m insightpilot.cli --help
& .\.venv\Scripts\python.exe -B -m insightpilot.cli --list-playbooks
& .\.venv\Scripts\python.exe -B docs/tools/build_user_manual.py `
  --output-dir reports/user-manual/20260930-125203 --replace-generated
& .\.venv\Scripts\python.exe -B docs/tools/check_user_manual_html.py `
  --html reports/user-manual/20260930-125203/InsightPilot_Agent_使用手册_0.1.0.html `
  --output-dir reports/user-manual/20260930-125203/html-check-delivery
```

PDF渲染使用Codex现有依赖Python `C:/Users/zhangyutao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`中的pypdfium2，不为项目安装依赖。普通沙箱命令最初受Windows1385限制，后续限于文档和只读检查的命令由自动审批执行；没有修改系统权限或安全配置。

### 核对产物索引

- [独立数据与原图核对](../reports/user-manual/assets-verification.json)
- [源码和控件事实审计](../reports/user-manual/facts-audit.md)
- [构建与链接记录](../reports/user-manual/20260930-125203/build-validation.json)
- [HTML离线检查](../reports/user-manual/20260930-125203/html-check-delivery/html-validation.json)
- [PDF结构与字体](../reports/user-manual/20260930-125203/pdf-structure-validation.json)
- [最终渲染比对](../reports/user-manual/20260930-125203/pdf-rendering-delivery.json)
- [最终视觉复核](../reports/user-manual/20260930-125203/pdf-final-review.md)
- [产品前后哈希核验](../reports/user-manual/20260930-125203/product-integrity.json)
- [命令语法检查](../reports/user-manual/20260930-125203/powershell-syntax.json)

## 已知边界与未验证内容

- 当前数据库摄入执行仅已存在SQLite文件；DuckDB是本地分析引擎。没有依据SQLAlchemy存在宣传任意数据库支持。本轮未连接数据库。
- 上传入口接受.csv/.xlsx/.xlsm/.xls，当前依赖有对应引擎；本轮仅核对源码与已有记录，没有用新Excel文件实测各后缀。
- 周期对比的Top N控件存在，但当前执行没有用其截断分组；手册不承诺该控件限制结果数量。本轮不修改此行为。
- 语义参数存在静态可见的界面限制：“语义指标集合”被声明为dimensions类型，控件会给维度候选；“结果排序”“维度筛选”的复杂结构走普通文本控件，未见相应结构化解析。手册只介绍已核对的单指标/基本配置，将复杂项留空，并提供按当前CLI参数整理的预览命令。上述问题来自源码检查，本轮未在运行界面复现，也不声称相关控件已验证可用；不顺手修产品。
- 不把普通多文件上传写成自动安全关联，受控多表仍受现有模型、Join、SQL与审批约束。
- 真实LangGraph缺依赖路径没有在本轮执行；不新增或宣传通用相关性、预测、倾向评分、自由公式、完整MCP功能。
- 当前8511及用户浏览器没有被访问、刷新、修改参数、清缓存或释放数据。本轮仅可选读取端口监听身份，不向应用发请求。文档HTML检查使用独立离线Chrome本地文件，和用户应用会话无关。

## 安全与变更范围

本轮开工对app/、insightpilot/、tests/、requirements*、pyproject.toml和.streamlit内273个产品/测试/配置文件建立SHA256基线，记录 `reports/user-manual/20260930-125203/product-before.json`；交付前再次比对：前后均273个文件，改变、增加、缺失均为0。排除运行时pyc，检查真实源码/配置内容。README只追加7条静态文档链接，原正文前缀逐字节一致。

8511起止只读监听记录均为127.0.0.1:8511、PID38968；没有发起health或分析请求，没有操作用户浏览器。这只能佐证服务身份保持，不能替代用户会话内部状态测试；本轮没有对该状态做任何写操作。

不修改source-original、不执行git add/commit/tag/push、不安装/升级依赖，不下载模型/浏览器/字体。所有新增文件限于手册文档、合成教学CSV、已核对截图、独立文档脚本及新时间戳阅读/验收产物。

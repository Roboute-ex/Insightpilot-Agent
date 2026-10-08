# 当前0.1.0工作台演示路径（2026-09-29）

1. 内置交易模拟数据、standard。在分析工作台输入“昨日订单量为什么下降？”，查看自动推荐、真实数据范围与配置后点击开始分析。结论优先展示实际摘要、KPI、关键图、表和质量五维。
2. 点击查看全部分析方法。默认十个方法可见；因果方法即使缺处理字段也显示缺口。配置方法不会执行或修改问题目标。合法24行因果小表经真实字段/方向配置后仍产生原始差2、调整估计2、n24；无协变量时不伪造调整。
3. 进入数据探索，字段概览不重新统计。选择分组或交叉表、一个明确指标和sum/mean/去重或分子分母比率，确认范围后点击生成探索结果。图型切换只改变已有聚合的展示，参数编辑仍是草稿。
4. 订单结果的城市表选择一行，查看筛选草稿，再点击基于选中分组继续分析。它创建所选城市目标日的描述性汇总子分支，不覆盖父配置，也不宣称因果或显著性。
5. 历史比较中查看父子节点；超过现有单个大结果缓存后，旧节点提示需要重新执行。报告页依次按需生成PDF、Markdown、HTML、Excel、manifest、ZIP，均绑定选定成功run_id。

完整本轮真实测试与边界见[工作台验收](workbench_redesign_acceptance.md)。以下保留既有主Demo操作参考，其历史截图或成绩不是本轮成绩。

# 中文模拟数据演示脚本

本演示只使用本地确定性模拟数据，不上传业务数据。命令从项目根目录执行。

## 1. 交易诊断与贡献

启动UI，简洁模式选择交易 standard、seed42，点击“预览分析方案”，确认只出现计划；再点击“开始分析”。
检查实际摘要、指标当前/基准/变化、维度正负贡献、Others、证据与建议。不同维度贡献不可相加。

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario transaction --scale standard --goal-mode metric_diagnosis --export-dir ./reports/demo_transaction
```

## 2. 结果明细与实验

打开结果明细确认指标/异常/贡献/证据等实际表。切换专业模式后，保留最近结果并提示数据切换的过期状态。
选择内容场景的实验问题，执行后核对两组独立样本、均值、差、p-value和绝对差置信区间。实际数值由本次运行产生，不设置目标p-value。

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario content --scale standard --goal-mode experiment_analysis --export-format pdf,markdown,html,excel,manifest,bundle --export-dir ./reports/demo_content
```

## 3. PDF优先导出

报告导出页第一项为PDF；检查中文标题、正文、跨页表头和页码。再比较Excel实验sheet和CLI数值。ZIP不包含输入原表。

## 4. 自定义CSV映射

用 examples/generate_demo_files.py 在未使用过的 local_data/ 子目录生成 small 模拟文件，或手工创建少量 日期/销售额/城市 行。
上传其中CSV，映射日期/指标/维度，执行增长趋势。换成无效字段时检查明确警告，不伪装完整结果。

```powershell
& ./.venv/Scripts/python.exe examples/generate_demo_files.py --scenario transaction --scale small --output-dir ./local_data/demo_files
```

## 5. 多表方案预览

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario multi_table_commerce --metrics total_revenue,order_count --dimensions customer_city --plan-only --output-format json --export-dir ./reports/demo_plan
```

检查表关系、粒度、风险、受控SQL摘要，确认没有分析查询或伪结果。请求变化需重新生成计划；不允许审批绕过不安全扇出。

## 6. 直播与开发者模式

运行直播质量问题，查看设备+网络组合、卡顿和观看时长。开发者模式才展开脱敏JSON/SQL/spans。
完成后Ctrl+C停止Streamlit；报告和生成模拟文件均在忽略目录，不提交。

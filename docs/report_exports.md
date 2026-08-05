# 中文报告导出

v0.6 提供六类导出，顺序固定为 PDF、Markdown、离线 HTML、Excel、Manifest JSON 和 ZIP Bundle。Streamlit 默认在内存中生成；CLI 仅在明确请求时写入导出目录。

## PDF

PDF 使用 A4、ReportLab Platypus 和 `STSong-Light` CID 字体，不提交字体文件。报告包含执行摘要、指标对比、异常、漏斗、维度贡献、证据、建议、Reviewer、风险、数据质量、分析方案和运行清单，并带页码与项目版本。

## Markdown 与 HTML

Markdown 和离线 HTML 都包含实际分析结果，而不只显示 AnalysisPlan。HTML 不依赖在线 CDN，用户文本经过 escape，结果表最多预览前 100 行。

## Excel

Excel 使用 `BytesIO`、`pandas.ExcelWriter` 和 openpyxl。中文工作表包括执行摘要、指标对比、异常检测、漏斗拆解、维度贡献、证据链、建议清单、质量检查和运行清单，同时保留 v0.5 英文兼容别名。

工作表名称会清洗并限制长度。单张结果表最多导出 100000 行，不默认加入原始上传表。

## Manifest JSON

Manifest JSON 保存复现配置和输入指纹，不保存完整 DataFrame、上传文件绝对路径或数据库凭据。导入时进行 manifest 主版本兼容检查。

## ZIP Bundle

ZIP 包含 `report.pdf`、`report.md`、`report.html`、`report.xlsx`、`manifest.json`、`results/*.csv` 和 `README.txt`。文件全部在内存中组装。

CSV 只来自分析结果表，限制表数量和行数；不加入原始上传文件或数据库源表。

## 安全边界

导出失败不影响主分析结果。文件名使用安全 ASCII 名称。完整数据库连接信息、密码、token 和 secret 不得进入报告、manifest、CSV 或 ZIP。

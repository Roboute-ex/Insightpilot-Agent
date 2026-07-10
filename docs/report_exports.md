# Report Exports

v0.5 提供 Markdown、Interactive HTML、Excel、Manifest JSON 和 ZIP Bundle。Streamlit 默认在内存中生成；CLI 仅在明确请求时写入导出目录。

## Markdown

Markdown 报告包含 Analysis Playbook、Visual Diagnostics、Run Manifest 和 Available Exports，同时保留 goal mode、route、reviewer、mapping 与 caveats。

## Interactive HTML

HTML 是单文件离线报告。Plotly 运行时代码内嵌，不依赖在线 CDN。用户文本经过 HTML escape，结果表最多预览前 100 行。

## Excel

Excel 使用 `BytesIO`、`pandas.ExcelWriter` 和 openpyxl。工作表包括 Summary、Findings、Reviewer、Mapping、Manifest，以及每张分析结果表。

工作表名称会清洗并限制长度。单张结果表最多导出 100000 行，不默认加入原始上传表。

## Manifest JSON

Manifest JSON 保存复现配置和输入指纹，不保存完整 DataFrame、上传文件绝对路径或数据库凭据。导入时进行 manifest 主版本兼容检查。

## ZIP Bundle

ZIP 包含 `report.md`、`report.html`、`report.xlsx`、`manifest.json`、`results/*.csv` 和 `README.txt`。文件全部在内存中组装。

CSV 只来自分析结果表，限制表数量和行数；不加入原始上传文件或数据库源表。

## 安全边界

导出失败不影响主分析结果。文件名使用安全 ASCII 名称。database URL、密码、token 和 secret 不得进入报告、manifest、CSV 或 ZIP。

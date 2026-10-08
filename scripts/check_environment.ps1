$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProjectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
Write-Host "项目：$ProjectRoot"
if (-not (Test-Path -LiteralPath $ProjectPython)) { throw '项目 .venv 不存在，请先使用已验证的解释器创建。' }
& $ProjectPython -c "import sys,importlib.metadata as m; import insightpilot; from insightpilot.reports.pdf import generate_pdf_report; from insightpilot.data.scenarios import generate_scenario; print(sys.executable); print(sys.version); print('InsightPilot',insightpilot.__version__); print({p:m.version(p) for p in ['pandas','numpy','duckdb','scipy','statsmodels','streamlit','reportlab','sqlglot','xlrd']})"
if ($LASTEXITCODE -ne 0) { throw "环境检查失败，退出码：$LASTEXITCODE" }
& $ProjectPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "依赖检查失败，退出码：$LASTEXITCODE" }

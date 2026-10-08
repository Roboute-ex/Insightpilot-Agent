param([int]$Port = 8501)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProjectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $ProjectPython)) { throw '项目 .venv 不存在，请按 README 创建环境并安装依赖。' }
$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listener) { throw "端口 $Port 已被占用，请尝试 -Port $($Port + 1)。不会停止其他进程。" }
Write-Host "服务运行于 http://127.0.0.1:$Port ，请手动打开。终端需保持运行，Ctrl+C 停止。"
& $ProjectPython -m streamlit run (Join-Path $ProjectRoot 'app\ui_streamlit.py') --server.address 127.0.0.1 --server.port $Port --server.headless true --browser.gatherUsageStats false
if ($LASTEXITCODE -ne 0) { throw "Streamlit 退出码：$LASTEXITCODE" }

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python environment is missing. Run npm run setup first."
}
$port = if ($env:PORT) { $env:PORT } else { "4173" }
& $venvPython -m uvicorn backend.app:app --host 127.0.0.1 --port $port
if ($LASTEXITCODE -ne 0) {
    throw "Coastal Sentinel API stopped unexpectedly."
}

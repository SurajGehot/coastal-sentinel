$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python environment is missing. Run npm run setup first."
}
& $venvPython -m backend.download_data
if ($LASTEXITCODE -ne 0) {
    throw "NOAA dataset download failed."
}

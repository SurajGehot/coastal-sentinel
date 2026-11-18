$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python environment is missing. Run npm run setup first."
}
& $venvPython -m unittest discover -s tests_python -v
if ($LASTEXITCODE -ne 0) {
    throw "Python tests failed."
}

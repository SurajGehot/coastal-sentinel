$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) {
        throw "Python 3.13 is required. Install Python and rerun npm run setup."
    }
    & py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the virtual environment."
    }
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Could not prepare pip in the virtual environment."
}
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Could not install Python dependencies."
}
& $venvPython -m backend.download_data
if ($LASTEXITCODE -ne 0) {
    throw "NOAA dataset download failed; training was not started."
}
& $venvPython -m backend.train
if ($LASTEXITCODE -ne 0) {
    throw "Training failed; the website model was not updated."
}

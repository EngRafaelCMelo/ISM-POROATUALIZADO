$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    $BuildPython = ".venv\Scripts\python.exe"
} else {
    $BuildPython = (Get-Command python -ErrorAction Stop).Source
}

& $BuildPython -m pip install -r requirements-dev.txt
& $BuildPython -m PyInstaller --noconfirm PermeabilimetroSupervisorio.spec

$BuildVersion = & $BuildPython -c "from core.version import APP_VERSION; print(APP_VERSION.replace('.', '_'))"
Write-Host "Executavel criado em dist\PermeabilimetroSupervisorio_v$BuildVersion\PermeabilimetroSupervisorio_v$BuildVersion.exe"

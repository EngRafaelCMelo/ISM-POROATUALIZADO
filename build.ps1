$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    $BuildPython = ".venv\Scripts\python.exe"
} else {
    $BuildPython = (Get-Command python -ErrorAction Stop).Source
}

& $BuildPython -m pip install -r requirements.txt
& $BuildPython -m PyInstaller --noconfirm PorosimetroSupervisorio.spec

Write-Host "Executavel criado em dist\PorosimetroSupervisorio_v1_5_0\PorosimetroSupervisorio_v1_5_0.exe"

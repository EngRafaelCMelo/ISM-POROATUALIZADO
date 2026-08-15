$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    throw "Crie o ambiente virtual primeiro: python -m venv .venv"
}

& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".venv\Scripts\pyinstaller.exe" --noconfirm PorosimetroSupervisorio.spec

Write-Host "Executavel criado em dist\PorosimetroSupervisorio_v2_0_0\PorosimetroSupervisorio_v2_0_0.exe"

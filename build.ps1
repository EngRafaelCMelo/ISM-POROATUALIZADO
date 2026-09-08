$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    $BuildPython = ".venv\Scripts\python.exe"
} else {
    $BuildPython = (Get-Command python -ErrorAction Stop).Source
}

& $BuildPython -m pip install -r requirements.txt
& $BuildPython -m PyInstaller --noconfirm PermeabilimetroSupervisorio.spec

Write-Host "Executavel criado em dist\PermeabilimetroSupervisorio_v2_1_0\PermeabilimetroSupervisorio_v2_1_0.exe"

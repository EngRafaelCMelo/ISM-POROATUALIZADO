$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    $BuildPython = ".venv\Scripts\python.exe"
} else {
    $BuildPython = (Get-Command python -ErrorAction Stop).Source
}

function Invoke-CheckedPython {
    & $BuildPython @args
    if ($LASTEXITCODE -ne 0) { throw "Falha em python $($args -join ' ')" }
}

Invoke-CheckedPython -m pip install -r requirements-dev.txt
Invoke-CheckedPython -m compileall -q app.py communication config core database services ui tests
Invoke-CheckedPython -m ruff check .
Invoke-CheckedPython -m ruff format --check .
Invoke-CheckedPython -m pytest -q -W error::FutureWarning
Invoke-CheckedPython -m platformio run -d firmware
Invoke-CheckedPython -m PyInstaller --clean --noconfirm PermeabilimetroSupervisorio.spec

$BuildVersion = & $BuildPython -c "from core.version import APP_VERSION; print(APP_VERSION.replace('.', '_'))"
$PackageName = "PermeabilimetroSupervisorio_v$BuildVersion"
$Executable = Join-Path $PSScriptRoot "dist\$PackageName\$PackageName.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "Executável ausente: $Executable" }
$SmokeDirectory = Join-Path $env:TEMP "ism-smoke-$BuildVersion-$(Get-Date -Format yyyyMMddHHmmssfff)"
New-Item -ItemType Directory -Force -Path $SmokeDirectory | Out-Null
$Smoke = Start-Process -FilePath $Executable -ArgumentList @('--report-smoke', $SmokeDirectory) -PassThru -Wait -WindowStyle Hidden
if ($Smoke.ExitCode -ne 0) { throw "Smoke test falhou: $($Smoke.ExitCode)" }
$SmokeFit = Start-Process -FilePath $Executable -ArgumentList @('--report-smoke-klinkenberg', $SmokeDirectory) -PassThru -Wait -WindowStyle Hidden
if ($SmokeFit.ExitCode -ne 0) { throw "Smoke Klinkenberg falhou: $($SmokeFit.ExitCode)" }
$Report = Get-ChildItem -LiteralPath $SmokeDirectory -Filter '*.pdf' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Report) { throw 'PDF demonstrativo ausente.' }
$SmokeReports = @(Get-ChildItem -LiteralPath $SmokeDirectory -Filter '*.pdf')
if ($SmokeReports.Count -lt 2) { throw 'Os dois relatórios de smoke test estão ausentes.' }
foreach ($SmokeReport in $SmokeReports) {
    Invoke-CheckedPython -c "from pypdf import PdfReader; import sys; r=PdfReader(sys.argv[1]); t=' '.join(p.extract_text() or '' for p in r.pages); assert len(r.pages)>=4; assert len(r.pages[0].images)>=1; assert 'RELATÓRIO FINAL DE ENSAIO' in t; assert 'Resumo da aquisição' in t; assert 'NL/min' in t; assert 'Tempo ativo de aquisição' in t; assert not any(x in t for x in ('NaN','None','flow_l_min'))" $SmokeReport.FullName
}
Invoke-CheckedPython -c "from pypdf import PdfReader; import sys; t=' '.join(p.extract_text() or '' for p in PdfReader(sys.argv[1]).pages); assert 'Pontos utilizados' in t; assert 'Coeficiente R²' in t" (Join-Path $SmokeDirectory 'ENS-PACOTE-KLINKENBERG_relatorio_final.pdf')
$Archive = Join-Path $PSScriptRoot "dist\$PackageName.zip"
Compress-Archive -LiteralPath (Join-Path $PSScriptRoot "dist\$PackageName") -DestinationPath $Archive -Force
$Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
"$Hash  $PackageName.zip" | Set-Content -LiteralPath "$Archive.sha256" -Encoding ascii
Write-Host "Executável: $Executable"
Write-Host "PDF demonstrativo: $($Report.FullName)"
Write-Host "Pacote SHA-256: $Archive.sha256"

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & (Join-Path $PSScriptRoot 'check.ps1')
    $appVersion = & .venv/Scripts/python.exe -c "from codex_insights import __version__; print(__version__)"
    if ($LASTEXITCODE) { throw 'Could not read the app version' }
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm packaging/windows.spec
    if ($LASTEXITCODE) { throw 'Windows build failed' }
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm packaging/bridge.spec
    if ($LASTEXITCODE) { throw 'Bridge build failed' }
    Copy-Item -LiteralPath dist/CodexInsightsBridge.exe -Destination dist/CodexSessionInsights
    & .venv/Scripts/python.exe scripts/smoke_bridge.py dist/CodexSessionInsights/CodexInsightsBridge.exe
    if ($LASTEXITCODE) { throw 'Packaged bridge smoke test failed' }
    & .venv/Scripts/python.exe scripts/smoke_exporter.py dist/CodexSessionInsights/CodexSessionInsights.exe
    if ($LASTEXITCODE) { throw 'Packaged v5 exporter/importer smoke test failed' }
    Copy-Item -LiteralPath packaging/Start.cmd, 'packaging/Startup diagnostics.cmd' -Destination dist/CodexSessionInsights
    New-Item -ItemType Directory -Force release | Out-Null
    $archivePath = "release/CodexSessionInsights-$appVersion-windows-x64.zip"
    Compress-Archive -Path dist/CodexSessionInsights -DestinationPath $archivePath -Force
    Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$archivePath.sha256" -Value "$hash  $(Split-Path -Leaf $archivePath)" -Encoding ascii
} finally { Pop-Location }

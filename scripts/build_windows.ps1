$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm packaging/windows.spec
    if ($LASTEXITCODE) { throw 'Windows build failed' }
    New-Item -ItemType Directory -Force release | Out-Null
    Compress-Archive -Path dist/CodexSessionInsights -DestinationPath release/CodexSessionInsights-0.1.0-windows-x64.zip -Force
    Get-FileHash release/CodexSessionInsights-0.1.0-windows-x64.zip -Algorithm SHA256
} finally { Pop-Location }

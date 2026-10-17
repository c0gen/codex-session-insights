param([string]$App, [switch]$LiveAllowance, [switch]$WidgetOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$checkRoot = Join-Path $projectRoot ('.local-data\desktop-check-' + [guid]::NewGuid().ToString('N'))
$oldDesktopSmoke = $env:CODEX_INSIGHTS_DESKTOP_SMOKE_RESULT
$oldBasicSmoke = $env:CODEX_INSIGHTS_SMOKE_RESULT
$oldWidgetOnly = $env:CODEX_INSIGHTS_WIDGET_SMOKE_ONLY
Push-Location $projectRoot
try {
    $program = if ($App) { (Resolve-Path -LiteralPath $App).Path } else { Join-Path $projectRoot '.venv\Scripts\python.exe' }
    $prefix = if ($App) { @() } else { @('-m', 'codex_insights') }
    function Invoke-DesktopCheck([string[]]$CheckArguments) {
        $quoted = ($prefix + $CheckArguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
        $process = Start-Process -FilePath $program -ArgumentList $quoted -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit(90000)) {
            Stop-Process -Id $process.Id
            throw "Native check timed out. Logs: $checkRoot"
        }
        if ($process.ExitCode -ne 0) { throw "Native check exited with $($process.ExitCode). Logs: $checkRoot" }
    }
    Remove-Item Env:CODEX_INSIGHTS_DESKTOP_SMOKE_RESULT, Env:CODEX_INSIGHTS_SMOKE_RESULT -ErrorAction SilentlyContinue
    if ($WidgetOnly) { $env:CODEX_INSIGHTS_WIDGET_SMOKE_ONLY = '1' } else { Remove-Item Env:CODEX_INSIGHTS_WIDGET_SMOKE_ONLY -ErrorAction SilentlyContinue }
    Invoke-DesktopCheck @('--data-dir', (Join-Path $checkRoot 'diagnostics'), '--diagnose')
    if (Test-Path -LiteralPath (Join-Path $checkRoot 'diagnostics\insights.sqlite3')) { throw 'Diagnostics unexpectedly created an index' }

    $basicResult = Join-Path $checkRoot 'basic.json'
    Invoke-DesktopCheck @('--data-dir', (Join-Path $checkRoot 'basic'), '--demo', 'gui', '--smoke-result', $basicResult)
    if (-not (Get-Content -Raw -LiteralPath $basicResult | ConvertFrom-Json).ok) { throw "Basic native smoke failed: $basicResult" }

    $env:CODEX_INSIGHTS_DESKTOP_SMOKE_RESULT = Join-Path $checkRoot 'desktop.json'
    Invoke-DesktopCheck @('--data-dir', (Join-Path $checkRoot 'desktop'), '--demo', 'gui')
    $result = Get-Content -Raw -LiteralPath $env:CODEX_INSIGHTS_DESKTOP_SMOKE_RESULT | ConvertFrom-Json
    if (-not $result.ok) { throw "Desktop smoke failed: $($result.error). See $checkRoot" }
    if (-not $WidgetOnly) {
        $persistentImage = Join-Path $checkRoot 'summary-after-exit.png'
        $escapedImagePath = $persistentImage.Replace("'", "''")
        $clipboardCheck = "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; `$image = [System.Windows.Forms.Clipboard]::GetImage(); if (`$null -eq `$image -or `$image.Width -ne 1200 -or `$image.Height -ne 720) { throw 'Summary clipboard did not survive app exit' }; try { `$image.Save('$escapedImagePath', [System.Drawing.Imaging.ImageFormat]::Png) } finally { `$image.Dispose() }"
        & powershell.exe -NoProfile -STA -Command $clipboardCheck
        if ($LASTEXITCODE) { throw 'Persistent image clipboard check failed' }
        if (-not (Test-Path -LiteralPath $persistentImage)) { throw 'Persistent summary image was not saved' }
    }
    $result | ConvertTo-Json -Depth 4
    if ($LiveAllowance) {
        $allowanceResult = Join-Path $checkRoot 'allowance.json'
        Invoke-DesktopCheck @('--allowance-smoke-result', $allowanceResult)
        $allowance = Get-Content -Raw -LiteralPath $allowanceResult | ConvertFrom-Json
        if (-not $allowance.ok) { throw "Live allowance smoke failed: $($allowance.error)" }
        $allowance | ConvertTo-Json -Depth 6
    }
    Write-Output "Native executable exited cleanly. Results: $checkRoot"
} finally {
    $env:CODEX_INSIGHTS_DESKTOP_SMOKE_RESULT = $oldDesktopSmoke
    $env:CODEX_INSIGHTS_SMOKE_RESULT = $oldBasicSmoke
    $env:CODEX_INSIGHTS_WIDGET_SMOKE_ONLY = $oldWidgetOnly
    Pop-Location
}

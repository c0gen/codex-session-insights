$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $testDirectory = Join-Path $projectRoot ('.local-data\pytest-' + [guid]::NewGuid().ToString('N'))
    & .venv/Scripts/python.exe -m pytest -q --basetemp=$testDirectory
    if ($LASTEXITCODE) { throw 'Python checks failed' }
    foreach ($check in @('qa_filter_state_unit', 'qa_token_activity_data', 'qa_metric_interface_data', 'qa_account_identity', 'qa_dashboard_data', 'qa_widget_data', 'qa_export_feedback')) {
        & node "scripts/$check.mjs"
        if ($LASTEXITCODE) { throw "Dashboard data check failed: $check" }
    }
    Push-Location frontend
    try {
        & npm run build
        if ($LASTEXITCODE) { throw 'Frontend checks or build failed' }
    } finally { Pop-Location }
} finally { Pop-Location }

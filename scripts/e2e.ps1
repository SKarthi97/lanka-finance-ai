<#
.SYNOPSIS
  Runs the browser tests against a SEPARATE copy of the app (own project name, database volume and
  port), so your real data is never touched. The copy is removed afterwards.

.DESCRIPTION
  One-time setup (needs the internet once):
    cd frontend; npm install; npx playwright install chromium
  Then, from the project folder:
    .\scripts\e2e.ps1
  Add -Keep to leave the test copy running afterwards (it is stopped and its data deleted otherwise).
#>
param([switch]$Keep)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# These scripts run in your PowerShell session: put back whatever they change, so a later
# `docker compose up -d` in the same window still uses your own .env settings.
$touched = "POSTGRES_PASSWORD", "FRONTEND_PORT", "LLM_CLASSIFY_ENABLED", "COOKIE_SECURE", "E2E_BASE_URL"
$savedEnv = @{}
foreach ($n in $touched) { $savedEnv[$n] = [Environment]::GetEnvironmentVariable($n, "Process") }
function Restore-Env { foreach ($n in $touched) { [Environment]::SetEnvironmentVariable($n, $savedEnv[$n], "Process") } }

$env:POSTGRES_PASSWORD = "e2e-only-password"
$env:FRONTEND_PORT = "3100"
$env:LLM_CLASSIFY_ENABLED = "false"
$env:COOKIE_SECURE = "false"
$project = "lanka-e2e"

try {
    docker compose -p $project up -d --build postgres backend worker frontend
    if ($LASTEXITCODE -ne 0) { throw "could not start the test copy" }

    # wait until the front page answers
    $up = $false
    for ($i = 0; $i -lt 60 -and -not $up; $i++) {
        try { $null = Invoke-WebRequest -Uri "http://127.0.0.1:3100/" -UseBasicParsing -TimeoutSec 3; $up = $true }
        catch { Start-Sleep -Seconds 3 }
    }
    if (-not $up) { throw "the test copy did not come up on port 3100" }

    Push-Location frontend
    $env:E2E_BASE_URL = "http://127.0.0.1:3100"
    npx playwright test
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Write-Host "Browser tests failed. Open frontend\playwright-report\index.html for traces and screenshots." -ForegroundColor Red }
    exit $code
}
finally {
    if (-not $Keep) {
        docker compose -p $project down -v | Out-Null
    }
    Restore-Env
}

<#
.SYNOPSIS
  Proves a backup can really bring the app back, WITHOUT touching your live data.

.DESCRIPTION
  Starts a separate copy of the app (own project name, own database volume, port 3200), restores the
  newest backup (or the one you name) into it, lets the app apply its migrations, checks that the
  backend answers and that the restored counts match the dump, then removes the copy. Your running
  app and its database are not touched. Run it now and then; a backup nobody has restored is only a hope.

.PARAMETER File
  The dump to try. Default: the newest file in backups\.

.PARAMETER Keep
  Leave the test copy running afterwards (open http://127.0.0.1:3200 to look at it). Remove it later with:
    docker compose -p lanka-drill down -v

.EXAMPLE
  .\scripts\restore-drill.ps1
#>
param(
  [string]$File,
  [switch]$Keep
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Assert-Ok([string]$what) {
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." }
}

if (-not $File) {
  $latest = Get-ChildItem -Path (Join-Path $root "backups") -Filter "lanka-*.dump*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $latest) { throw "No backup found in backups\. Run .\scripts\backup.ps1 first." }
  $File = $latest.FullName
}
if (-not (Test-Path $File)) { throw "File not found: $File" }
$File = (Resolve-Path $File).Path

# An encrypted backup (.dump.enc) is opened into a temporary file that is removed afterwards.
$plainTemp = $null
if ($File -like "*.enc") {
  . (Join-Path $PSScriptRoot "crypto.ps1")
  $secret = Read-LfPassphrase -File (Get-LfPassphraseFile)
  $plainTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("lanka-drill-" + [guid]::NewGuid().ToString("N") + ".dump")
  Write-Host "Decrypting ..."
  Unprotect-LfFile -Path $File -Out $plainTemp -Passphrase $secret
}
$source = if ($plainTemp) { $plainTemp } else { $File }
Write-Host "Trying the backup: $File"

$project = "lanka-drill"
$env:POSTGRES_PASSWORD = "drill-only-password"
$env:FRONTEND_PORT = "3200"
$env:LLM_CLASSIFY_ENABLED = "false"
$inside = "/tmp/drill.dump"
$ok = $false

try {
  docker compose -p $project up -d postgres
  Assert-Ok "Starting the drill database"

  # wait for the database to accept connections
  $ready = $false
  for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
    docker compose -p $project exec -T postgres pg_isready -U lanka -d lanka | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true } else { Start-Sleep -Seconds 2 }
  }
  if (-not $ready) { throw "The drill database did not become ready." }

  docker compose -p $project cp $source "postgres:$inside"
  Assert-Ok "Copying the dump in"
  docker compose -p $project exec -T postgres pg_restore --list $inside | Out-Null
  Assert-Ok "Reading the dump"

  docker compose -p $project exec -T postgres psql -U lanka -d lanka -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" | Out-Null
  Assert-Ok "Emptying the drill database"
  docker compose -p $project exec -T postgres pg_restore -U lanka -d lanka --no-owner $inside
  if ($LASTEXITCODE -ne 0) { Write-Warning "pg_restore reported warnings (exit code $LASTEXITCODE); checking the result below." }

  $sql = "select (select count(*) from documents) || ' documents, ' || (select count(*) from transactions) || ' transactions, ' || (select count(*) from categories) || ' categories'"
  $before = docker compose -p $project exec -T postgres psql -U lanka -d lanka -t -A -c $sql
  Assert-Ok "Counting the restored rows"
  Write-Host "In the restored database: $before"

  Write-Host "Starting the app on the restored data (it applies any newer migrations) ..."
  docker compose -p $project up -d --build backend
  Assert-Ok "Starting the backend"

  $healthy = $false
  for ($i = 0; $i -lt 60 -and -not $healthy; $i++) {
    $state = docker compose -p $project ps backend --format "{{.Health}}"
    if ($state -match "healthy") { $healthy = $true } else { Start-Sleep -Seconds 3 }
  }
  if (-not $healthy) { throw "The backend did not become healthy on the restored data. Check: docker compose -p $project logs backend" }

  $after = docker compose -p $project exec -T postgres psql -U lanka -d lanka -t -A -c $sql
  Write-Host "After the app started:        $after"
  if ($before -ne $after) { throw "The counts changed when the app started: that is not expected." }

  docker compose -p $project up -d worker frontend | Out-Null
  $ok = $true
  Write-Host ""
  Write-Host "DRILL PASSED: this backup restores, the app starts on it and the data is intact." -ForegroundColor Green
}
finally {
  docker compose -p $project exec -T postgres rm -f $inside 2>$null | Out-Null
  if ($plainTemp) { Remove-Item $plainTemp -Force -ErrorAction SilentlyContinue }
  if ($Keep -and $ok) {
    Write-Host "The test copy is running on http://127.0.0.1:3200 . Remove it later with: docker compose -p $project down -v"
  }
  else {
    docker compose -p $project down -v | Out-Null
  }
}
if (-not $ok) { exit 1 }

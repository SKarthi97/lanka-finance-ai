<#
.SYNOPSIS
  Restore the Lanka Finance AI database from a backup made by backup.ps1.

.DESCRIPTION
  REPLACES the current database with the contents of the dump. Before doing that it makes a
  safety backup of the current state (unless -SkipSafetyBackup), stops the app while it
  works, and starts it again afterwards. The app applies any newer database migrations when
  it starts, so a dump from an older version is fine.

  Retained statement PDFs are not part of the restore; see docs/06-backup-and-restore.md.

.PARAMETER File
  The dump to restore, for example backups\lanka-20261104-120000.dump.

.PARAMETER Force
  Do not ask for the RESTORE confirmation.

.PARAMETER SkipSafetyBackup
  Do not back up the current database first (use only when it is empty or broken).

.EXAMPLE
  .\scripts\restore.ps1 -File backups\lanka-20261104-120000.dump
#>
param(
  [Parameter(Mandatory = $true)][string]$File,
  [switch]$Force,
  [switch]$SkipSafetyBackup
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Assert-Ok([string]$what) {
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." }
}

if (-not (Test-Path $File)) { throw "File not found: $File" }
$File = (Resolve-Path $File).Path

if (-not $Force) {
  Write-Host "This REPLACES the current database with:"
  Write-Host "  $File"
  $answer = Read-Host "Type RESTORE to continue"
  if ($answer -ne "RESTORE") { Write-Host "Cancelled. Nothing was changed."; exit 1 }
}

if (-not $SkipSafetyBackup) {
  Write-Host "Making a safety backup of the current database first ..."
  & (Join-Path $PSScriptRoot "backup.ps1") -Keep 1000
}

$inside = "/tmp/restore.dump"
Write-Host "Stopping the app ..."
docker compose stop frontend worker backend
Assert-Ok "Stopping the app"

try {
  docker compose cp $File "postgres:$inside"
  Assert-Ok "Copying the dump into the container"

  docker compose exec -T postgres pg_restore --list $inside | Out-Null
  Assert-Ok "Reading the dump"

  Write-Host "Replacing the database ..."
  docker compose exec -T postgres psql -U lanka -d lanka -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  Assert-Ok "Emptying the database"

  docker compose exec -T postgres pg_restore -U lanka -d lanka --no-owner $inside
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "pg_restore reported warnings (exit code $LASTEXITCODE); checking the result below."
  }
}
finally {
  docker compose exec -T postgres rm -f $inside | Out-Null
}

Write-Host "Starting the app (it applies any newer migrations) ..."
docker compose up -d
Assert-Ok "Starting the app"

$counts = docker compose exec -T postgres psql -U lanka -d lanka -t -A -c "select (select count(*) from documents) || ' documents, ' || (select count(*) from transactions) || ' transactions'"
Assert-Ok "Counting the restored rows (the restore did not produce the expected tables)"
Write-Host "Restored: $counts"
Write-Host "Sign in again if the page still shows the old session."

<#
.SYNOPSIS
  Upgrade the app to the code in this folder, safely: back up first, rebuild, check it came up and the
  database is migrated, and say how to go back if it did not.

.DESCRIPTION
  1. Notes what is running now (the git commit and the database version) in backups\last-upgrade.txt.
  2. Makes a verified backup (backup.ps1 -Verify; add -Encrypt to encrypt it).
  3. Rebuilds and restarts the app (docker compose up -d --build). The backend applies database
     migrations itself when it starts.
  4. Waits for every service to be healthy and checks the database is at the newest version.
  5. If LAN access was on, turns it back on (a plain restart would switch it off).

  If something is wrong it stops and prints the exact steps to go back. Your data is not deleted at any
  point; the backup from step 2 is what you restore if a migration went wrong.

  To pick up new code first:  git pull   (then run this).

.PARAMETER Encrypt
  Encrypt the backup (see backup.ps1).

.PARAMETER SkipBackup
  Skip step 2. Only for an empty or throw-away install.

.PARAMETER Project
  Use another compose project name (for trying this on a copy). Normally leave it out.

.EXAMPLE
  .\scripts\upgrade.ps1 -Encrypt
#>
param(
  [switch]$Encrypt,
  [switch]$SkipBackup,
  [string]$Project
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$p = if ($Project) { @("-p", $Project) } else { @() }

function Invoke-Quiet([scriptblock]$command) {
  # docker prints progress on stderr, which Windows PowerShell treats as an error
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { & $command } finally { $ErrorActionPreference = $old }
}

function Get-Revision([string]$text) {
  if ($text -match "([0-9a-f]{4}_[a-z0-9_]+|[0-9]{4}[a-z0-9_]*)") { return $Matches[1] }
  return ($text | Out-String).Trim()
}

# --- 1. what is running now -------------------------------------------------------------------------
$commit = (git rev-parse --short HEAD) 2>$null
$dirty = [bool](git status --porcelain 2>$null)
$before = Invoke-Quiet { docker compose @p exec -T backend alembic current 2>$null | Select-Object -Last 1 }
$lanWasOn = [bool](Invoke-Quiet { docker ps --filter "label=com.docker.compose.service=lan-proxy" --filter "status=running" -q 2>$null })
New-Item -ItemType Directory -Force "backups" | Out-Null
$note = "backups\last-upgrade.txt"
@("When:      $(Get-Date -Format s)", "Code:      $commit$(if ($dirty) { ' (with uncommitted changes)' })", "Database:  $before") | Set-Content $note
Write-Host "Running now: code $commit, database $before"

# --- 2. backup --------------------------------------------------------------------------------------
if (-not $SkipBackup) {
  Write-Host "Making a verified backup first ..."
  $args2 = @("-Verify"); if ($Encrypt) { $args2 += "-Encrypt" }
  & (Join-Path $PSScriptRoot "backup.ps1") @args2
  $newest = Get-ChildItem "backups" -Filter "lanka-*.dump*" | Sort-Object Name -Descending | Select-Object -First 1
  Add-Content $note "Backup:    $($newest.FullName)"
  Write-Host "Backup: $($newest.Name)"
}
else { Write-Warning "Skipping the backup." }

# --- 3. rebuild and restart -------------------------------------------------------------------------
Write-Host "Rebuilding and restarting (this takes a few minutes) ..."
Invoke-Quiet { docker compose @p up -d --build }
if ($LASTEXITCODE -ne 0) { throw "docker compose up failed. Nothing was deleted; see the steps below." }

# --- 4. wait for health, check migrations -----------------------------------------------------------
$deadline = (Get-Date).AddMinutes(4)
$healthy = $false
while ((Get-Date) -lt $deadline -and -not $healthy) {
  $states = Invoke-Quiet { docker compose @p ps --format "{{.Service}}={{.Status}}" 2>$null }
  $bad = $states | Where-Object { $_ -notmatch "healthy|Exited .*0\)" -and $_ -notmatch "^ollama-pull" -and $_ -match "(starting|unhealthy|Restarting)" }
  if (-not $bad -and ($states | Where-Object { $_ -match "^backend=.*healthy" })) { $healthy = $true } else { Start-Sleep -Seconds 4 }
}
$current = Invoke-Quiet { docker compose @p exec -T backend alembic current 2>$null | Select-Object -Last 1 }
$head = Invoke-Quiet { docker compose @p exec -T backend alembic heads 2>$null | Select-Object -Last 1 }
$migrated = $current -and $head -and ((Get-Revision $current) -eq (Get-Revision $head))

if ($healthy -and $migrated) {
  Write-Host ""
  Write-Host "UPGRADE DONE: every service is healthy and the database is at the newest version ($(Get-Revision $head))." -ForegroundColor Green
  if ($lanWasOn) { Write-Host "Turning LAN access back on ..."; & (Join-Path $PSScriptRoot "lan.ps1") }
  Add-Content $note "Result:    ok"
  exit 0
}

Add-Content $note "Result:    FAILED (healthy=$healthy, migrated=$migrated)"
Write-Host ""
Write-Host "THE UPGRADE DID NOT COMPLETE (healthy: $healthy, database at newest version: $migrated)." -ForegroundColor Red
Write-Host "Look first:      docker compose logs --tail 80 backend"
Write-Host "To go back:"
Write-Host "  1. git checkout $commit            (the code that was running; 'git checkout -' returns here)"
Write-Host "  2. docker compose up -d --build"
Write-Host "  3. If the database was changed and the old code will not start on it, restore the backup:"
Write-Host "       .\scripts\restore.ps1 -File <the backup named in backups\last-upgrade.txt>"
Write-Host "The notes are in $note."
exit 1

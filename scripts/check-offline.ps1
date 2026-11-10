<#
.SYNOPSIS
  Proves the offline override works: with it, the backend has no route to the internet.

.DESCRIPTION
  Starts a SEPARATE copy of the stack (project lanka-offline, its own database volume), once with the
  normal compose file and once with docker-compose.offline.yml added, and from inside the backend
  container tries to open a connection to an outside address (by number, and by name). The normal copy
  is the control: if it cannot reach out either (you are offline), the check says so instead of
  claiming success. It also confirms the backend can still reach its own database. The copy is
  removed afterwards; your running app and data are not touched.

    .\scripts\check-offline.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:POSTGRES_PASSWORD = "offline-check-only"
$env:FRONTEND_PORT = "3300"
$env:LLM_CLASSIFY_ENABLED = "false"
$project = "lanka-offline"

# What the backend container runs: prints one word per probe.
$probe = @'
import socket
def tcp(host, port):
    try:
        socket.create_connection((host, port), timeout=5).close()
        return "reachable"
    except OSError:
        return "blocked"
def dns(name):
    try:
        socket.getaddrinfo(name, 443)
        return "reachable"
    except OSError:
        return "blocked"
print("outside_by_number", tcp("1.1.1.1", 443))
print("outside_by_name", dns("example.com"))
print("own_database", tcp("postgres", 5432))
'@

# Passed as base64 so no quote characters have to survive the trip to the container.
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($probe))
$command = "import base64;exec(base64.b64decode('$encoded'))"

function Get-Probe([string[]]$files) {
  $args = @("compose", "-p", $project) + $files
  docker @args up -d --build postgres backend | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "could not start the check copy" }
  $result = @{}
  for ($i = 0; $i -lt 20 -and $result.Count -eq 0; $i++) {
    $text = docker @args exec -T backend python -c $command
    if ($LASTEXITCODE -eq 0) {
      foreach ($line in $text) { $k, $v = $line -split " ", 2; $result[$k] = $v }
    } else { Start-Sleep -Seconds 3 }
  }
  docker @args down -v | Out-Null
  return $result
}

try {
  Write-Host "Control: the normal stack ..."
  $control = Get-Probe @("-f", "docker-compose.yml")
  Write-Host "  outside by number: $($control['outside_by_number']), by name: $($control['outside_by_name']), database: $($control['own_database'])"

  Write-Host "With docker-compose.offline.yml ..."
  $offline = Get-Probe @("-f", "docker-compose.yml", "-f", "docker-compose.offline.yml")
  Write-Host "  outside by number: $($offline['outside_by_number']), by name: $($offline['outside_by_name']), database: $($offline['own_database'])"

  $ok = $true
  if ($offline["outside_by_number"] -ne "blocked" -or $offline["outside_by_name"] -ne "blocked") {
    Write-Host "FAIL: the offline override still lets the backend reach the internet." -ForegroundColor Red; $ok = $false
  }
  if ($offline["own_database"] -ne "reachable") {
    Write-Host "FAIL: with the override the backend cannot reach its own database." -ForegroundColor Red; $ok = $false
  }
  if ($control["outside_by_number"] -ne "reachable") {
    Write-Host "NOTE: the normal stack could not reach the internet either (are you offline?), so this run proves nothing about the override." -ForegroundColor Yellow
    $ok = $false
  }
  if ($ok) { Write-Host "OFFLINE CHECK PASSED: the normal stack can reach out, the offline one cannot, and its database still works." -ForegroundColor Green }
  else { exit 1 }
}
finally {
  $ErrorActionPreference = "Continue"
  docker compose -p $project down -v *> $null
}

<#
.SYNOPSIS
  Use the app from another device on your home network, over HTTPS.

.DESCRIPTION
  Starts the stack with docker-compose.lan.yml: a small Caddy proxy listens on port 8443, signs its own
  certificate for this computer's address, and passes requests to the app. The session cookie becomes
  HTTPS-only. Nothing is sent to the internet.

  First time:
    .\scripts\lan.ps1 -OpenFirewall          (run PowerShell as administrator for the firewall rule)
  It prints the address to open on the other device and saves lan\lanka-local-ca.crt. Install that
  certificate on each device ONCE (docs/windows-setup.md), or the browser shows a warning.

  Later starts: .\scripts\lan.ps1   |   Turn it off: .\scripts\lan.ps1 -Down

.PARAMETER HostName
  This computer's address on your network. Default: found automatically. Give it a fixed address in your
  router (a DHCP reservation), or the certificate stops matching when the address changes.

.PARAMETER Name
  A second name for the certificate. Default: <computer name>.local

.PARAMETER Port
  Default 8443.

.PARAMETER OpenFirewall
  Adds a Windows Firewall rule that allows the port from your local network only, on Private networks
  only. Needs an administrator PowerShell.

.PARAMETER Gpu
  Also applies docker-compose.gpu.yml (NVIDIA GPU for ollama, and for the backend's Hardware panel).

.PARAMETER Down
  Stops the proxy (the app itself keeps running on this computer) and removes the firewall rule if present.
#>
param(
  [string]$HostName,
  [string]$Name,
  [int]$Port = 8443,
  [switch]$OpenFirewall,
  [switch]$Gpu,
  [switch]$Down
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$ruleName = "Lanka Finance AI (LAN HTTPS)"
$files = @("-f", "docker-compose.yml", "-f", "docker-compose.lan.yml")
if ($Gpu) { $files += @("-f", "docker-compose.gpu.yml") }

if ($Down) {
  $env:LAN_HOST = "x"; $env:LAN_NAME = "y"
  docker compose @files stop lan-proxy
  docker compose @files rm -f lan-proxy
  docker compose up -d backend          # cookie back to its normal setting
  Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
  Write-Host "LAN access is off. The app still runs on this computer."
  exit 0
}

if (-not $HostName) {
  $cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | Select-Object -First 1
  if (-not $cfg) { throw "Could not find this computer's network address. Pass it with -HostName 192.168.x.y" }
  $HostName = $cfg.IPv4Address.IPAddress
}
if (-not $Name) { $Name = ($env:COMPUTERNAME.ToLower() + ".local") }
if ($Name -eq $HostName) { throw "-Name must differ from -HostName." }

$env:LAN_HOST = $HostName
$env:LAN_NAME = $Name
$env:LAN_PORT = "$Port"

Write-Host "Starting the LAN proxy for $HostName and $Name on port $Port ..."
docker compose @files up -d
if ($LASTEXITCODE -ne 0) { throw "Could not start the stack." }
docker compose @files restart lan-proxy | Out-Null   # picks up a changed lan\Caddyfile

# wait for the proxy to make its certificate authority
$crt = Join-Path $root "lan\lanka-local-ca.crt"
$got = $false
$ErrorActionPreference = "Continue"   # docker prints progress on stderr, which Windows PowerShell treats as an error
for ($i = 0; $i -lt 30 -and -not $got; $i++) {
  Start-Sleep -Seconds 2
  docker compose @files cp "lan-proxy:/data/caddy/pki/authorities/local/root.crt" $crt *> $null
  $got = ($LASTEXITCODE -eq 0) -and (Test-Path $crt)
}
$ErrorActionPreference = "Stop"
if (-not $got) { throw "The proxy did not create its certificate. Check: docker compose $($files -join ' ') logs lan-proxy" }

if ($OpenFirewall) {
  $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $admin) {
    Write-Warning "Not an administrator: the firewall rule was not added. Run PowerShell as administrator, or run:"
    Write-Host "  New-NetFirewallRule -DisplayName `"$ruleName`" -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -RemoteAddress LocalSubnet -Action Allow"
  }
  else {
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -RemoteAddress LocalSubnet -Action Allow | Out-Null
    Write-Host "Firewall: port $Port is open to your local network on Private networks only."
  }
}

$category = "" + (Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne "Disconnected" } | Select-Object -First 1).NetworkCategory
$blocked = $false
try {
  $blocked = [bool](Get-NetFirewallRule -Direction Inbound -Enabled True -Action Block -ErrorAction Stop |
      Where-Object { $_.DisplayName -match "docker" -and ("" + $_.Profile) -match "Public|Any|All" })
} catch { }
if ($category -and $category -ne "Private") {
  Write-Warning "This network is marked '$category'. Windows blocks incoming connections on it, so other devices will TIME OUT."
  if ($blocked) { Write-Warning "Docker Desktop also has a firewall rule blocking incoming connections on Public networks." }
  Write-Host "  Fix (needs an administrator): mark the network Private, then allow the port:" -ForegroundColor Yellow
  Write-Host "    Set-NetConnectionProfile -InterfaceAlias Wi-Fi -NetworkCategory Private"
  Write-Host "    New-NetFirewallRule -DisplayName `"$ruleName`" -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -RemoteAddress LocalSubnet -Action Allow"
}

Write-Host ""
Write-Host "On the other device (same Wi-Fi / network), open:" -ForegroundColor Green
Write-Host "  https://${HostName}:$Port"
Write-Host "  https://${Name}:$Port   (if the name resolves on that device)"
Write-Host ""
Write-Host "Install this certificate on the device once, so the browser trusts it:"
Write-Host "  $crt"
Write-Host "Steps per device are in docs/windows-setup.md. Turn LAN access off with: .\scripts\lan.ps1 -Down"

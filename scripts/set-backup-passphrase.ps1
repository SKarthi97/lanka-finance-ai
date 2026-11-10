<#
.SYNOPSIS
  Save the backup passphrase for scheduled, encrypted backups (backup.ps1 -Encrypt).

.DESCRIPTION
  Asks for a passphrase twice and stores it protected by Windows for your user account on this computer
  (DPAPI) in %LOCALAPPDATA%\LankaFinanceAI\backup.key. A scheduled task running as you can then encrypt
  without asking. The file is useless on another computer or for another user.

  WRITE THE PASSPHRASE DOWN SOMEWHERE SAFE (a password manager). If this computer is lost, the stored copy
  goes with it, and without the passphrase an encrypted backup cannot be opened by anyone.
#>
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "crypto.ps1")

$file = Get-LfPassphraseFile
New-Item -ItemType Directory -Force (Split-Path $file) | Out-Null
$secret = Read-LfPassphrase -Confirm
$secret | ConvertFrom-SecureString | Set-Content -Path $file -Encoding ASCII
Write-Host "Saved (protected for this Windows user): $file"
Write-Host "Keep the passphrase itself somewhere safe: it cannot be recovered from this file on another computer."

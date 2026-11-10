<#
.SYNOPSIS
  Back up the Lanka Finance AI database (and optionally the retained statement PDFs).

.DESCRIPTION
  Writes backups\lanka-<date>-<time>.dump (a PostgreSQL custom-format dump) next to the
  project. The dump holds every transaction, category, rule and the account fingerprint key,
  so it is as confidential as the database itself: keep the folder on an encrypted drive and
  never commit it (backups\ is in .gitignore).

  Nothing is sent anywhere. Everything runs on this computer through Docker.

.PARAMETER Folder
  Where backups are written. Default: backups (inside the project).

.PARAMETER Keep
  How many of the newest backups to keep. Older lanka-*.dump files (and their documents-*
  folders) are removed. Default: 14.

.PARAMETER IncludeDocuments
  Also copy the statement PDFs kept for review (the "documents" volume) into
  documents-<date>-<time>\ beside the dump. Reconciled statements are normally deleted after
  extraction, so this is usually small or empty.

.PARAMETER Encrypt
  Encrypt the dump with a passphrase (AES-256, see crypto.ps1) and keep only the .dump.enc file. The
  passphrase is asked for, or read from the file made by set-backup-passphrase.ps1 (for scheduled runs).
  There is no recovery: keep the passphrase somewhere safe. restore.ps1 and restore-drill.ps1 accept the
  .enc file and ask for the passphrase.

.PARAMETER PassphraseFile
  Where the saved passphrase is. Default: %LOCALAPPDATA%\LankaFinanceAI\backup.key

.PARAMETER Verify
  After the dump, restore it into a throwaway database (lanka_verify), print how many
  documents and transactions it holds, and drop it again. The live database is not touched.

.EXAMPLE
  .\scripts\backup.ps1 -Verify
#>
param(
  [string]$Folder = "backups",
  [int]$Keep = 14,
  [switch]$IncludeDocuments,
  [switch]$Verify,
  [switch]$Encrypt,
  [string]$PassphraseFile
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Assert-Ok([string]$what) {
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." }
}

New-Item -ItemType Directory -Force $Folder | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $Folder "lanka-$stamp.dump"
$inside = "/tmp/lanka-$stamp.dump"

Write-Host "Dumping the database ..."
docker compose exec -T postgres pg_dump -U lanka -d lanka --format=custom --no-owner -f $inside
Assert-Ok "pg_dump"

try {
  # Make sure the dump can be read back before trusting it.
  docker compose exec -T postgres pg_restore --list $inside | Out-Null
  Assert-Ok "Reading the dump"

  docker compose cp "postgres:$inside" $target
  Assert-Ok "Copying the dump out of the container"

  if ((Get-Item $target).Length -lt 1024) { throw "The dump is suspiciously small; not trusting it." }

  if ($Verify) {
    Write-Host "Checking the dump by restoring it into a throwaway database ..."
    docker compose exec -T postgres dropdb -U lanka --if-exists lanka_verify
    Assert-Ok "Dropping an old lanka_verify"
    docker compose exec -T postgres createdb -U lanka lanka_verify
    Assert-Ok "Creating lanka_verify"
    try {
      docker compose exec -T postgres pg_restore -U lanka -d lanka_verify --no-owner $inside
      if ($LASTEXITCODE -ne 0) {
        Write-Warning "pg_restore reported warnings (exit code $LASTEXITCODE); judging by the row counts below."
      }
      $counts = docker compose exec -T postgres psql -U lanka -d lanka_verify -t -A -c "select (select count(*) from documents) || ' documents, ' || (select count(*) from transactions) || ' transactions'"
      Assert-Ok "Counting the restored rows"
      Write-Host "Restore check passed: $counts"
    }
    finally {
      docker compose exec -T postgres dropdb -U lanka --if-exists lanka_verify | Out-Null
    }
  }
}
finally {
  docker compose exec -T postgres rm -f $inside | Out-Null
}

if ($Encrypt) {
  . (Join-Path $PSScriptRoot "crypto.ps1")
  if (-not $PassphraseFile) { $PassphraseFile = Get-LfPassphraseFile }
  $secret = Read-LfPassphrase -File $PassphraseFile -Confirm
  $encrypted = "$target.enc"
  Write-Host "Encrypting the backup ..."
  Protect-LfFile -Path $target -Out $encrypted -Passphrase $secret
  # Prove the encrypted copy opens with this passphrase and matches, before the plain one is removed.
  $check = Join-Path ([System.IO.Path]::GetTempPath()) ("lanka-check-" + [guid]::NewGuid().ToString("N"))
  try {
    Unprotect-LfFile -Path $encrypted -Out $check -Passphrase $secret
    if ((Get-FileHash $check).Hash -ne (Get-FileHash $target).Hash) { throw "The encrypted copy does not match the dump." }
  }
  finally { Remove-Item $check -Force -ErrorAction SilentlyContinue }
  Remove-Item $target -Force
  $target = $encrypted
}

if ($IncludeDocuments) {
  $docs = Join-Path $Folder "documents-$stamp"
  Write-Host "Copying retained statement PDFs ..."
  docker compose cp "backend:/data/documents" $docs
  Assert-Ok "Copying the documents folder"
}

# Keep only the newest $Keep backups.
$old = Get-ChildItem $Folder -Filter "lanka-*.dump*" | Sort-Object Name -Descending | Select-Object -Skip $Keep
foreach ($file in $old) {
  $suffix = ($file.Name -replace '^lanka-', '') -replace '\.dump(\.enc)?$', ''
  Remove-Item $file.FullName -Force
  $leftover = Join-Path $Folder "documents-$suffix"
  if (Test-Path $leftover) { Remove-Item $leftover -Recurse -Force }
}

$size = [math]::Round((Get-Item $target).Length / 1KB)
Write-Host "Backup written: $target ($size KB)"
if ($Encrypt) { Write-Host "The backup is encrypted. Keep the passphrase safe: without it the file cannot be opened." }
else { Write-Host "Keep this folder on an encrypted drive (or use -Encrypt). It is never committed to git." }

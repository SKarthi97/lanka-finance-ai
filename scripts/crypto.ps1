<#
  Passphrase encryption for backup files (dot-source this file: . .\scripts\crypto.ps1).

  Format of a .enc file:  "LFAI1" | salt (16) | IV (16) | AES-256-CBC ciphertext | HMAC-SHA256 (32)
  The key and the MAC key both come from the passphrase with PBKDF2-SHA256 (200,000 rounds). The MAC
  covers everything before it, and is checked BEFORE anything is decrypted, so a wrong passphrase or a
  damaged file is reported plainly and never produces garbage. Uses only what ships with Windows.
  There is no recovery: lose the passphrase and the backup cannot be opened.
#>

$script:LfMagic = [System.Text.Encoding]::ASCII.GetBytes("LFAI1")
$script:LfRounds = 200000

function ConvertTo-LfPlain([System.Security.SecureString]$Secure) {
  $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Get-LfKeys([System.Security.SecureString]$Passphrase, [byte[]]$Salt) {
  $plain = ConvertTo-LfPlain $Passphrase
  $kdf = New-Object System.Security.Cryptography.Rfc2898DeriveBytes($plain, $Salt, $script:LfRounds, [System.Security.Cryptography.HashAlgorithmName]::SHA256)
  try {
    $bytes = $kdf.GetBytes(64)
    return @{ Aes = $bytes[0..31]; Mac = $bytes[32..63] }
  }
  finally { $kdf.Dispose() }
}

function Protect-LfFile {
  param([string]$Path, [string]$Out, [System.Security.SecureString]$Passphrase)
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  $salt = New-Object byte[] 16; $rng.GetBytes($salt)
  $iv = New-Object byte[] 16; $rng.GetBytes($iv)
  $keys = Get-LfKeys $Passphrase $salt

  $aes = [System.Security.Cryptography.Aes]::Create()
  $aes.Mode = "CBC"; $aes.Padding = "PKCS7"; $aes.Key = [byte[]]$keys.Aes; $aes.IV = $iv
  $mac = New-Object System.Security.Cryptography.HMACSHA256(,[byte[]]$keys.Mac)

  $in = [System.IO.File]::OpenRead($Path)
  $outStream = [System.IO.File]::Create($Out)
  try {
    $header = $script:LfMagic + $salt + $iv
    $outStream.Write($header, 0, $header.Length)
    $crypto = New-Object System.Security.Cryptography.CryptoStream($outStream, $aes.CreateEncryptor(), "Write")
    $in.CopyTo($crypto)
    $crypto.FlushFinalBlock()
    # MAC over what was written so far (header + ciphertext), read back in chunks
    $outStream.Flush()
    $outStream.Position = 0
    $buffer = New-Object byte[] 1048576
    while (($n = $outStream.Read($buffer, 0, $buffer.Length)) -gt 0) { [void]$mac.TransformBlock($buffer, 0, $n, $null, 0) }
    [void]$mac.TransformFinalBlock($buffer, 0, 0)
    $outStream.Position = $outStream.Length
    $outStream.Write($mac.Hash, 0, $mac.Hash.Length)
  }
  finally { $in.Dispose(); $outStream.Dispose(); $aes.Dispose(); $mac.Dispose(); $rng.Dispose() }
}

function Unprotect-LfFile {
  param([string]$Path, [string]$Out, [System.Security.SecureString]$Passphrase)
  $file = [System.IO.File]::OpenRead($Path)
  try {
    $headerLength = $script:LfMagic.Length + 32
    if ($file.Length -lt ($headerLength + 16 + 32)) { throw "This does not look like an encrypted backup (too small)." }
    $header = New-Object byte[] $headerLength
    [void]$file.Read($header, 0, $headerLength)
    for ($i = 0; $i -lt $script:LfMagic.Length; $i++) {
      if ($header[$i] -ne $script:LfMagic[$i]) { throw "This is not an encrypted Lanka backup (wrong file type)." }
    }
    $salt = $header[5..20]; $iv = $header[21..36]
    $keys = Get-LfKeys $Passphrase ([byte[]]$salt)

    # Check the MAC first: everything before the last 32 bytes.
    $mac = New-Object System.Security.Cryptography.HMACSHA256(,[byte[]]$keys.Mac)
    $file.Position = 0
    $remaining = $file.Length - 32
    $buffer = New-Object byte[] 1048576
    while ($remaining -gt 0) {
      $n = $file.Read($buffer, 0, [int][math]::Min($buffer.Length, $remaining))
      if ($n -le 0) { break }
      [void]$mac.TransformBlock($buffer, 0, $n, $null, 0)
      $remaining -= $n
    }
    [void]$mac.TransformFinalBlock($buffer, 0, 0)
    $stored = New-Object byte[] 32
    [void]$file.Read($stored, 0, 32)
    $diff = 0
    for ($i = 0; $i -lt 32; $i++) { $diff = $diff -bor ($stored[$i] -bxor $mac.Hash[$i]) }
    if ($diff -ne 0) { throw "Wrong passphrase, or the backup file is damaged. Nothing was decrypted." }

    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = "CBC"; $aes.Padding = "PKCS7"; $aes.Key = [byte[]]$keys.Aes; $aes.IV = [byte[]]$iv
    $outStream = [System.IO.File]::Create($Out)
    try {
      $file.Position = $headerLength
      $limited = New-Object LfLimitedStream($file, ($file.Length - 32 - $headerLength))
      $crypto = New-Object System.Security.Cryptography.CryptoStream($limited, $aes.CreateDecryptor(), "Read")
      $crypto.CopyTo($outStream)
    }
    finally { $outStream.Dispose(); $aes.Dispose(); $mac.Dispose() }
  }
  finally { $file.Dispose() }
}

# A read-only window onto the first N bytes of a stream (the ciphertext, without the MAC at the end).
if (-not ("LfLimitedStream" -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.IO;
public class LfLimitedStream : Stream {
  private readonly Stream inner; private long left;
  public LfLimitedStream(Stream inner, long length) { this.inner = inner; this.left = length; }
  public override int Read(byte[] buffer, int offset, int count) {
    if (left <= 0) return 0;
    int n = inner.Read(buffer, offset, (int)Math.Min(count, left));
    left -= n; return n;
  }
  public override bool CanRead { get { return true; } }
  public override bool CanSeek { get { return false; } }
  public override bool CanWrite { get { return false; } }
  public override long Length { get { throw new NotSupportedException(); } }
  public override long Position { get { throw new NotSupportedException(); } set { throw new NotSupportedException(); } }
  public override void Flush() { }
  public override long Seek(long o, SeekOrigin s) { throw new NotSupportedException(); }
  public override void SetLength(long v) { throw new NotSupportedException(); }
  public override void Write(byte[] b, int o, int c) { throw new NotSupportedException(); }
}
"@
}

# The default place for a passphrase kept for scheduled backups: protected by Windows for THIS user
# on THIS computer (DPAPI). Another user or another computer cannot read it.
function Get-LfPassphraseFile { return (Join-Path $env:LOCALAPPDATA "LankaFinanceAI\backup.key") }

function Read-LfPassphrase {
  param([string]$File, [switch]$Confirm)
  if ($File -and (Test-Path $File)) {
    return ((Get-Content $File -Raw).Trim() | ConvertTo-SecureString)
  }
  $first = Read-Host "Backup passphrase" -AsSecureString
  if ($Confirm) {
    $second = Read-Host "Type it again" -AsSecureString
    if ((ConvertTo-LfPlain $first) -ne (ConvertTo-LfPlain $second)) { throw "The two passphrases differ." }
  }
  if ((ConvertTo-LfPlain $first).Length -lt 8) { throw "Use at least 8 characters." }
  return $first
}

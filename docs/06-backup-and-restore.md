# Backup, restore and protecting the data

Status: implemented (scripts in `scripts/`). Everything runs on this computer through Docker;
nothing is sent anywhere.

## What is at risk

All your data lives in one Docker volume (`pgdata`). If it is lost (a Docker reset, a disk
problem, a mistaken `docker compose down -v`), every statement has to be uploaded again and every
category correction is gone. A backup is a single file you can keep elsewhere.

A backup holds **every transaction, category, rule and the account fingerprint key**, so it is as
confidential as the database. `backups/` and `*.dump` are in `.gitignore`; keep the folder on an
encrypted drive (see "Encryption" below).

## Back up

From the project folder, in PowerShell:

```
.\scripts\backup.ps1 -Verify
```

- Writes `backups\lanka-<date>-<time>.dump` (PostgreSQL custom format).
- Checks the dump can be read back before trusting it.
- `-Verify` also restores it into a throwaway database (`lanka_verify`), prints
  `N documents, M transactions`, and drops it again. The live database is not touched. Run it
  with `-Verify` at least the first time, and now and then afterwards.
- Keeps the newest 14 backups (`-Keep 30` to change) and removes older ones.
- `-IncludeDocuments` also copies the statement PDFs kept for review (statements still needing
  review keep their file; reconciled ones are deleted after extraction, so this is usually small).
- `-Folder D:\Safe\lanka` writes somewhere else (an external or encrypted drive).

### Backing up automatically (Windows Task Scheduler)

Docker Desktop must be running at that time. A daily run at 21:00:

```
schtasks /Create /SC DAILY /ST 21:00 /TN "Lanka Finance backup" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\lanka-finance-ai\scripts\backup.ps1"
```

A safer version that checks every backup can be read back and keeps the newest 14 (the default):

```
schtasks /Create /SC DAILY /ST 21:00 /TN "Lanka Finance backup" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\lanka-finance-ai\scripts\backup.ps1 -Verify" /F
```

If the computer is often off at 21:00, open the task in Task Scheduler, go to Settings, and tick "Run task
as soon as possible after a scheduled start is missed".

Once a month, prove the newest backup restores (the drill uses its own copy and removes it):

```
schtasks /Create /SC MONTHLY /D 1 /ST 21:30 /TN "Lanka Finance restore drill" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File D:\lanka-finance-ai\scripts\restore-drill.ps1" /F
```

Check them with `schtasks /Query /TN "Lanka Finance backup" /V /FO LIST`, run one now with
`schtasks /Run /TN "Lanka Finance backup"`, and remove them with
`schtasks /Delete /TN "Lanka Finance backup" /F` and `schtasks /Delete /TN "Lanka Finance restore drill" /F`.

## Prove it works: the restore drill

```
.\scripts\restore-drill.ps1
```

Starts a separate copy of the app (project `lanka-drill`, its own database volume, port 3200),
restores the newest backup into it, lets the app apply its migrations, checks the backend becomes
healthy and that the counts did not change, and then removes the copy. Your running app and its
database are not touched. `-File` picks a specific dump, `-Keep` leaves the copy running so you can
look at it (remove it with `docker compose -p lanka-drill down -v`). Run it after your first backup
and now and then afterwards; `backup.ps1 -Verify` only checks that the dump reads back.

## Restore

```
.\scripts\restore.ps1 -File backups\lanka-20261104-120000.dump
```

- Asks you to type `RESTORE`: it **replaces** the current database.
- Makes a safety backup of the current state first (`-SkipSafetyBackup` if it is empty or
  broken), stops the app, empties the database, restores the dump, and starts the app again.
- The app applies any newer database migrations when it starts, so a dump from an older version
  of the app is fine.
- It prints the restored counts. Sign in again if the page still shows an old session.

Retained statement PDFs are not restored by the script. If you saved them with
`-IncludeDocuments`, copy them back after the restore:

```
docker compose cp "backups\documents-<date>-<time>\." backend:/data/documents/
```

(This step has not been tried on the real install; the database restore does not depend on it.)

### Restoring on a new computer

1. Install Docker Desktop, clone the project, and create `.env` as before (same
   `POSTGRES_PASSWORD` is not required; the dump carries the data, not the database password).
2. `docker compose up -d --build`, wait until the backend is healthy.
3. Run `restore.ps1` with the dump file.

If `ACCOUNT_FINGERPRINT_KEY` was set in `.env`, set the same value on the new computer. When it
is not set, the key is stored inside the database and comes back with the dump.

## Encryption at rest

The database is not encrypted by the application. The data sits in Docker Desktop's disk image
and in your `backups` folder, so protect the drive instead:

- Turn on **BitLocker** for the drive that holds Docker Desktop's data (normally `C:`) and for any
  drive you write backups to. Check with `manage-bde -status` in an administrator PowerShell.
- Keep the recovery key somewhere other than this computer.
- A backup copied to a USB stick or cloud folder leaves that protection. Put it on a BitLocker
  drive, or encrypt the file first (for example 7-Zip with a password and AES-256).

Database-level encryption would add complexity (key handling, performance) without protecting
more than BitLocker does for a single-user, single-machine install, so it is not planned.

## Categories survive re-extraction

Re-running extraction on a statement (the Re-run button, or an adapter fix) replaces its rows.
Categories you set by hand are kept: each is matched to the new row with the same date, debit,
credit, balance and description, and restored before the rules run. Rows you never touched are
categorised again by the rules and the model. The account is deliberately not part of the match,
so a row still matches if the new run finds an account number the first run missed.

## Duplicates when the account number is not found

Rows are matched across statements by a hash of account, date, amounts, balance and description.
When no account number was found, the hash has no account in it, so rows are now only compared
**within the same bank**: two banks' statements are never merged on date, amount and text alone,
while a re-downloaded copy of the same bank's statement still is. The Statements tab and tracker
show "account not detected" for such statements; if the number is on the PDF but not found, send
a masked `verify_pdf --shape` output and the adapter can be taught the layout.

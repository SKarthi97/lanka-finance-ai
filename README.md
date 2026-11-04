# Lanka Finance AI

A privacy-first, offline bank-statement analyzer for one user. Upload a statement PDF, check
that it reconciles, then explore, categorise and chart your money. Nothing leaves your machine:
the optional AI is a local model (Ollama) and the app never calls an external service.

Status: Bank of Ceylon (BOC), Hatton National Bank (HNB), Commercial Bank and Sampath Bank
statements work end to end (all but BOC are checked against one or two layouts so far). Other banks, backups, reports and the chat assistant are
planned (see `docs/00-architecture.md`, section 12).

## What it does

- Upload text-based PDF statements (password-protected ones too). The same file twice is
  refused; overlapping statements are de-duplicated transaction by transaction.
- Extract every row, then validate it with exact arithmetic (row balances, opening + credits -
  debits = closing, dates, gaps). A statement that does not reconcile is held for review.
- Dashboard: balances, month and year income/expense, trends, comparison, largest expenses,
  spending by category, and a tracker showing which months have a statement.
- Categorise with built-in rules, your own rules and rules learned from your corrections; an
  optional local model handles the rest and only suggests, with a clear confidence tier.
- Transactions explorer with filters, sorting, CSV export, bulk category change and a detail
  panel.

## Run it (Windows 11 + Docker Desktop)

1. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD` (never commit `.env`).
2. Start everything: `docker compose up -d --build`
3. Download the local model once: `docker compose --profile setup run --rm ollama-pull`
4. Open http://127.0.0.1:3000 and create your account on first visit (the page only binds to
   your own machine by default).

Set `OLLAMA_MODEL` in `.env` to change the model. See `docs/04-categorization.md` for which
model and thresholds to use. After changing code, rebuild with
`docker compose up -d --build backend worker frontend`.

## Tests

```
cd backend
venv/Scripts/python.exe -m pytest        # backend, uses SQLite and synthetic PDFs only
cd ../frontend
node_modules/.bin/tsc --noEmit           # type check
```

## Privacy rules for development

Real statements live only in `sample_pdfs/` or `tests/fixtures/private/` (gitignored, never
shared with any assistant). Tests use synthetic fixtures. Full account numbers are never stored
or logged (last 4 digits plus a keyed fingerprint only). Logs and error records contain ids,
codes and counts, never descriptions or amounts.

## Documentation

| File | Contents |
|---|---|
| `docs/00-architecture.md` | Design, security model and the implementation status of each part |
| `docs/01-gap-analysis.md` | Review of the original prototype and what has since been resolved |
| `docs/02-upload-and-queue.md` | Upload checks, error codes, retention, the job queue |
| `docs/03-extraction.md` | BOC extraction, validation, duplicates, dashboard, tracker, API |
| `docs/04-categorization.md` | Rules, learning, the local AI, tiers, model evaluation |
| `docs/05-user-interface.md` | Pages, account settings, dialogs, remembered choices, accessibility |
| `docs/06-backup-and-restore.md` | Backup and restore scripts, scheduling, encryption, what survives re-extraction |
| `docs/windows-setup.md` | Windows, WSL2 and Docker setup |
| `docs/licenses.md` | Third-party and model licences |

# Transaction Extraction (Phase 2: BOC)

Status: implemented for Bank of Ceylon. Follows `00-architecture.md` sections 5, 7, 8.

## Privacy rule for development

Real statements (`sample_pdfs/`, `tests/fixtures/private/`) are never shared with the AI
assistant used to build this project, and are never committed. Parsers are developed
against **synthetic** fixtures (`backend/tests/synthetic.py`). Real files are checked
locally with `app.tools.verify_pdf`, whose output is redacted (see below).

## Pipeline

```
upload -> inspect_document (page kinds) -> extract_transactions:
  page text (PyMuPDF) -> select adapter (bank chosen by user, else best identify score)
  -> adapter.parse -> validate -> persist (account, transactions, document summary)
  -> reconciled | needs_review ; parse failures -> failed (no retries)
  -> reconciled: stored PDF deleted (unless RETAIN_DOCUMENTS=true)
```

Statuses: `queued -> processing -> inspected -> processing -> reconciled | needs_review |
failed`, and `needs_review -> accepted` by user decision. Only `reconciled` and `accepted`
statements count in `/api/dashboard`. Statements needing review are excluded until resolved
or accepted (architecture section 8.6).

## Adapters

`app/adapters/`: `base.py` (types, `BankAdapter` protocol), `registry.py`, `boc.py`.
Adapters are pure functions of page text. Adding a bank means writing one adapter and
registering it; nothing else changes. The BOC adapter is a port of the prototype parser
(`src/parsers/boc_parser.py`) with exact `Decimal` arithmetic, per-row page numbers,
repeated column headers and page footers ignored, and issue codes instead of free text.

Debit vs credit is decided from the running-balance movement, then validated.

## Validation (deterministic, `services/validation.py`)

| Check | Rule |
|---|---|
| `row_amounts` | exactly one of debit / credit is non-zero |
| `row_balance` | previous balance - debit + credit = row balance |
| `date_in_period` | between period start - 1 day and statement date + 1 day |
| `statement_reconciliation` | opening + credits - debits = closing |
| `rows_parsed` | the parser skipped no row |
| cross-statement | opening = previous closing; no period overlap or gap (same account; reported, never blocking) |

Confidence is computed from these checks (share of clean rows, capped at 0.5 when the
statement does not reconcile), never self-reported by a model.

## Account numbers

The full account number is **never stored or logged**. Only the last 4 digits and an
HMAC-SHA256 fingerprint are kept (`accounts` table), so the same account is recognised
across statements. The HMAC key is `ACCOUNT_FINGERPRINT_KEY`, or a random key generated
once in the `settings` table. This deviates from the architecture doc's encrypted full
number on purpose; masked display and cross-statement matching need nothing more.

The BOC account-number finder is best effort (a label such as "A/C No" in the header area
above the first transaction). Whether it matches the real layout is confirmed with the
verify tool (`account number found: yes/no`).

## Verify a real statement locally (redacted)

```
docker compose run --rm -v "D:\lanka-finance-ai\sample_pdfs:/samples:ro" worker \
    python -m app.tools.verify_pdf /samples/Statement.pdf
```
It prompts for the PDF password if needed (hidden, not stored). Output contains counts,
pass/fail and issue codes only. Add `--shape` for the page layout with every digit masked
to `9` and every letter to `A`/`a` (structural words such as PARTICULARS are kept). Review
the output before sharing it.

## Dashboard and tracker

- **Current balance:** per bank/account, the closing balance of its latest reconciled or
  accepted statement, with the statement date ("as of"); the total is their sum. It is the
  balance at the last statement, not a live balance.
- **Income / expense:** credits / debits of reconciled or accepted statements whose
  transaction date falls in the chosen month and year (default: the browser's current
  month, so the server's timezone never decides). Until categories exist (Phase 4) these
  include transfers and loan payments. Statements needing review are excluded.
- **Tracker:** one row per bank/account, one column per month. A statement belongs to the
  month its period **ends** in (31 Oct - 30 Nov is the November statement). A tick means
  reconciled or accepted, `!` needs review, a dot means no statement. A month cell links
  to the statement.
- Statements without a detectable account number are grouped per bank, so two real
  accounts at one bank would share a row until the account number is found.

## Data model additions (migration 0004)

`accounts`; `documents` gains period, balances, adapter, confidence and a `validation`
JSON (codes, pages and row numbers only); `transactions` holds `NUMERIC(18,2)` money,
`source_page`, `validation_status` and a `row_hash` (the architecture's dedupe key, used for
overlap detection in Phase 5).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/documents/{id}` | status, period, balances, adapter, confidence, checks and issues |
| `GET /api/transactions` | each row carries `bank_code`, `bank_name`, `account_last4`; filters: `document_id`, `bank_code`, `year`, `month`, `flagged`, `validation_status`, `q`; `limit` (max 500) / `offset` |
| `GET /api/banks` | supported banks (for filters) |
| `GET /api/dashboard?year=&month=` | current balances, income/expense for the month and the year, `needs_review` count |
| `GET /api/tracker?year=` | bank/account x month grid of uploaded statements |
| `POST /api/documents/{id}/accept` | accept a `needs_review` statement |
| `GET /api/documents/{id}/pages/{n}/image` | page PNG of the original; 404 `file_not_retained` once deleted |

## Differences from the architecture doc

- Source-page viewer uses server-rendered PNGs (PyMuPDF) instead of pdf.js: no extra
  frontend dependency, same privacy. It needs the original, so it is available for
  `needs_review`/`failed` documents or when `RETAIN_DOCUMENTS=true`.
- Adapter interface is `identify` + `parse` for now; the richer interface (column
  detection, per-row normalise) returns when a layout needs coordinates (HNB).
- Debit/credit uses balance movement, not column x-positions (text-only extraction).
- No OCR, so scanned PDFs fail with `no_text_layer`.

## Known limits

- Real BOC layout details not covered by the prototype's sample (multi-page, account
  number position) are unverified until checked with the verify tool.
- Transactions are not categorised yet (Phase 4) and duplicate transactions across
  overlapping statements are not removed yet (Phase 5).

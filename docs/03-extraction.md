# Transaction Extraction (Phase 2: BOC, HNB, Commercial, Sampath)

Status: implemented for Bank of Ceylon, Hatton National Bank (HNB), Commercial Bank and
Sampath Bank. Follows
`00-architecture.md` sections 5, 7, 8.

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

Dates carry no year (`DD/MM`), so statements spanning many years are resolved **from the
end**: the last row is in the statement-date year, and going backwards the year drops by
one whenever the date jumps forward in the calendar (a December row before a January
row). This assumes rows are chronological; reconciliation still checks the balances.

A row reads: date, description (possibly wrapped), then amounts. Description text is taken
only from **before the first amount**. Text after the amounts is page furniture that landed
in the same block (page footer, the next page's account/branch header, "END OF STATEMENT"
notes) and is discarded, with no list of phrases to maintain. If a row has text only after
its amounts, that text is used as a fallback.

BOC prints zero as `.00` (no leading digit), so `.00` is a valid amount; a nil opening
balance (an account's first statement) is read as `0.00`.

Multi-page statements: only the **first** `BALANCE B/F` is the opening balance and the
**last** `BALANCE C/F` is the closing balance. A `B/F` on a later page is a page
carry-forward; it must equal the previous row's balance (`carry_forward_mismatch`
otherwise, which blocks reconciliation because a row may be missing). Lines that repeat
page 1's header (names, addresses, titles) on later pages are dropped so they cannot
leak into the previous row's description, and a row whose amounts fall on the next page
stays one row.

### HNB (`adapters/hnb.py`)

Written from the layout of one real single-page savings statement, seen only as a masked
shape; the tests use synthetic statements. What the text layer holds:

- One table row per line: `dd.mm.yy`, an optional reference (letters + digits, dropped from
  the description), the particulars, **one amount**, the balance. Two-digit years, so no year
  inference is needed.
- Opening balance: the first `B/F` row (`01.10.26 B/F <balance>`); its date is the period
  start. A later page's `B/F` must equal the previous balance (`carry_forward_mismatch`),
  and `C/F` rows are skipped.
- Closing balance and statement date: the line `dd-mm-yyyy <balance>` ("BALANCE AS AT DATE").
  Without it the statement fails with `statement_date_not_found`.
- Totals line `<debits> <credits>` (amounts only, no item counts) is read as declared totals
  and compared like BOC's, informational only.
- A line without a date after a row, on the same page, is a wrapped description. Header text
  at the top of a later page and the footer ("HNB is a member of ...") are never attached.
- The column headings and the TOTAL / BALANCE AS AT DATE labels are images, so the bank is
  recognised from the footer wording and the row structure. Debit vs credit comes from the
  balance movement, as for BOC.
- Account number: a standalone 9 to 16 digit number in the header above the first row
  (best effort; the "ACCOUNT NO" label is an image). Stored only as last 4 + fingerprint.

### Commercial Bank (`adapters/commercial.py`)

Written from the masked layout of one real single-page statement (interest and tax rows
only); the tests use synthetic statements. What the text layer holds, one value per line:

- Header: statement date (`dd/mm/yy`), the currency (`LKR`), the account number, name and
  address, `PAGE n OF m`. A date directly followed by the currency is a page header, never a row.
- A row is `dd/mm/yy`, the particulars, **one amount**, then the balance with a `CR` suffix
  (`DR` is read as negative). Debit vs credit comes from the balance movement, as for BOC.
- `OPENING BALANCE` and `CLOSING BALANCE` are rows of their own: the opening row's date is the
  period start, the closing row sets the closing balance. A missing one is reported
  (`opening_balance_unidentified`, `closing_balance_unidentified`).
- `TOTAL DEPOSITS - n ITEMS` / `TOTAL WITHDRAWALS - n ITEMS` followed by an amount are read as
  declared totals (informational). On the sample, the printed item counts did not match the
  interest rows, which is another reason they never affect `reconciled`.
- The logo, title, column headings and footer are images, so the bank is recognised from the
  structure (CR balances, opening/closing rows, the totals lines) and from the words
  "COMMERCIAL BANK" if the text layer holds them.
- Not yet seen on real data: ordinary debits and credits, multi-page statements, `DR` balances
  and carry-forward rows (skipped by name, unconfirmed).

**Quarterly layout (adapter version 2).** A second Commercial layout (a "Statement of
Account" with branch, posting and effective dates, text column headings) is read by the same
adapter:

- Dates are `31 Jul 2026`; the posting and effective dates come out as one line or two, and
  the posting date is used. Balances are bare figures (no `CR`), taken as positive; the last
  figure on a row is the balance, the other the amount.
- The opening figure is printed **before** its `BALANCE AS OF dd/mm/yy` label; that date is
  the period start. The statement date comes from `STATEMENT DATE dd/mm/yy`.
- `CLOSING BALANCE AS OF dd/mm/yy` is followed by three figures (payments total, receipts
  total, closing balance), then `TOTAL DEPOSITS n ITEMS` / `TOTAL WITHDRAWALS n ITEMS`
  (counts only). The two totals are taken in column order; if the verify output shows a
  swapped total mismatch, that order is wrong. The year-to-date interest and tax notes after
  the totals are never read as rows.
- "Commercial Bank **Of Ceylon** PLC" contains "Bank Of Ceylon", so BOC returns 0 for any
  statement naming Commercial Bank.

### Sampath Bank (`adapters/sampath.py`)

Written from the masked layout of one real single-page statement; the tests use synthetic
statements. One table row per line (the logo, title and column headings are images):

- Header: `<account number> LKR PAGE_NO: n` and `FOR THE PERIOD : dd-mm-yyyy to dd-mm-yyyy
  DATE: dd-mm-yyyy`. The statement date is the **end of the period**; the printed DATE is the
  day it was produced and is ignored. Without a period the statement fails with
  `statement_date_not_found`.
- A transaction row is `ddMonyy`, a branch code (dropped from the description), the
  particulars, **one amount** and the balance with a `Cr`/`Dr` suffix (`Dr` is negative).
  Debit vs credit comes from the balance movement, as for BOC.
- Opening and closing rows have a 4-digit year: `22DEC2025 <balance>` (no label; a zero
  balance has no suffix) and `31Dec2025 C/F <balance>`. A later `B/F` must equal the previous
  balance (`carry_forward_mismatch`).
- `TOTAL : <debits> <credits>` is read as declared totals (no item counts), informational.
  The two figures are taken in column order; the verify output shows whether they match.
- Lines without a date are ignored (particulars are cut to the column width, not wrapped).
- The bank name is an image, so the bank is recognised from the period line, `PAGE_NO:` and the
  row shapes (and from the word "Sampath" if it is in the text layer).
- Not yet seen on real data: multi-page statements, `B/F` rows, `Dr` balances, wrapped text.

Unverified until checked on real statements: multi-page layout (repeated headers, carry
forward rows), wrapped descriptions, current and other account types, the account number
position. Run the verify tool (below) and share only its redacted output.

## Validation (deterministic, `services/validation.py`)

| Check | Rule |
|---|---|
| `row_amounts` | exactly one of debit / credit is non-zero |
| `row_balance` | previous balance - debit + credit = row balance |
| `date_in_period` | between period start - 1 day and statement date + 1 day |
| `statement_reconciliation` | opening + credits - debits = closing |
| `rows_parsed` | the parser skipped no row |
| `date_sequence` | consecutive rows are at most 300 days apart; a larger jump means a mis-ordered row shifted the inferred year, so the statement goes to review |
| cross-statement | opening = previous closing; no period overlap or gap (same account; reported, never blocking) |

Confidence is computed from these checks (share of clean rows, capped at 0.5 when the
statement does not reconcile), never self-reported by a model.

### Statement totals (informational)

The statement prints "TOTAL DEPOSITS n item(s) amount" and "TOTAL WITHDRAWALS ...". They are
compared with the extracted credit and debit rows and shown on the statement page and in
`validation.declared`. They never affect `reconciled`: what the item counts cover has not
been confirmed against real statements yet. Once it has, this can become a blocking check.

To find out what they cover, `validation.declared_window` tries every "last N rows" window
against the declared counts and totals and reports `all` rows, `last_rows` (with N and the
starting page: the totals describe a recent period only) or `unknown` (no window matches).
The statement page shows it in words and `verify_pdf` prints it as counts only
(`statement totals cover: ...`). Run the tool on a real statement to learn the answer.

## Duplicate transactions (overlapping statements)

A long statement plus a monthly one (or a re-downloaded copy with different bytes) contain
the same transactions; the file hash cannot see that. `services/dedupe.py` compares rows by
`row_hash` (account, date, debit, credit, **running balance**, normalised description). The
running balance makes false matches practically impossible, and identical rows inside one
statement are never treated as duplicates of each other.

One copy stays the original; the others get `is_duplicate` and `duplicate_of_id`. Which copy
is the original: a statement that counts (reconciled or accepted) beats one needing review;
among equals, the earlier upload. Flags are recomputed after extraction, after accepting, after
deleting a statement, and once at worker startup (backfill, idempotent). Duplicates stay visible
(explorer "Show duplicates", grey rows on the statement page) but are excluded from the
dashboard totals, balances' income/expense and year lists. The match depends on identical
descriptions, so re-run extraction after a parser change that alters descriptions.

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
pass/fail and issue codes only. It also reports, as counts and yes/no only (never a date, year or amount): how many years the
rows span and rows per year, the largest gap between consecutive rows in days, and how the
statement's own totals compare with what was extracted.
Add `--blocks` for the masked lines around BALANCE B/F and C/F.
Add `--shape` for the page layout with every digit masked
to `9` and every letter to `A`/`a` (structural words such as PARTICULARS are kept). Review
the output before sharing it.

## Dashboard and tracker

- **Current balance:** per bank/account, the closing balance of its latest reconciled or
  accepted statement, with the statement date ("as of"); the total is their sum. It is the
  balance at the last statement, not a live balance.
- **Trend (`GET /api/dashboard/trend?year=&month=&months=12&bank_code=`):** income, expense
  (transfers excluded) and the month-end total balance for each of the last N months. The
  balance is, per account, the running balance of its last transaction up to the month's end,
  summed; it is empty after the latest data rather than drawn flat. The dashboard shows it as
  two charts; clicking a month selects it.
- **Comparison and attention:** the month cards say how income and expense moved against the
  previous month and the share of income saved. "Needs your attention" lists unreconciled
  statements, uncategorised transactions (and unsure AI suggestions), a stale latest statement
  (over 45 days) and months missing between statements in the tracker.
- **Drill-down:** category names open Transactions with the category, period and bank already
  filtered. The dashboard can be limited to one bank, and "Hide amounts" masks every figure
  for screen sharing (remembered in the browser only).
- **Largest expenses:** the top five debits of the month, transfers excluded.
- **Income / expense:** credits / debits of reconciled or accepted statements whose
  transaction date falls in the chosen month and year (default: the browser's current
  month, so the server's timezone never decides). Transfers between your own accounts are
  left out (see `04-categorization.md`); uncategorised rows count by direction. Statements
  needing review and duplicate rows are excluded.
- **Tracker (Statements tab of the dashboard, following the bank chip):** one row per
  bank/account, one column per month. The attention panel counts missing months and balance
  breaks (next section) and links to it. A statement counts for the
  month its period **ends** in and for every month **wholly inside** its period. So a
  31 Oct - 30 Nov statement is the November statement only (a missing October stays
  visible), while a multi-year statement fills every month it spans. The month containing
  the period's opening date is not ticked unless fully covered. A tick means reconciled or
  accepted, `!` needs review, a dot means no statement. A month cell links to the statement.
- **Year selectors** (dashboard, tracker, transactions filter) list every year that has
  transactions, not just statement end years, so old years of a long statement can be chosen.
- Statements without a detectable account number are grouped per bank, so two real
  accounts at one bank would share a row until the account number is found. The UI says
  "account not detected" on those rows instead of hiding the fact.
- Income and expense leave out transfers between your own accounts; see `04-categorization.md`.

## Checks across statements and banks

These work on statements that are already extracted, so they apply to every bank the same way.
All of them are exact arithmetic on stored values.

- **Missing months** (`services/coverage.py`): per bank account, a month between the first and
  last statement that no statement covers is shown as `✗` on the tracker and counted in the
  dashboard's attention panel (all years, not only the one selected). Months before the first
  or after the last statement are not "missing". Statements still needing review count here
  because they are on the tracker.
- **Balance breaks**: when one statement ends where the next begins (up to a day apart), the
  first one's closing balance must equal the second one's opening balance. When it does not,
  transactions are missing between them or a statement was read wrongly. Only reconciled or
  accepted statements take part, and only when the account number is known (several accounts
  can hide under "account not detected"). The tracker lists each break with both balances and
  links to both statements.
- **Own-account transfers** (`services/transfers.py`, `routers/transfers.py`, the Transfers
  tab on the Categories page): a debit and a credit of **exactly the same amount** in
  **different accounts**, within **3 days**, matched one-to-one (closest dates first). A pair
  is flagged "ambiguous" when another row could equally be the other half. Rows you set a
  non-transfer category on yourself are never offered, and a pair where both halves are
  already transfers is skipped. Nothing changes until you confirm. Confirming files both rows
  under the Transfers category as a manual choice (so it survives re-extraction, see
  `06-backup-and-restore.md`) and learns no rule, because a description alone does not make
  something a transfer. "Not a transfer" is remembered in `transfer_rejections` (migration
  0011) by row hash, so it also survives re-extraction. The dashboard links to the tab while
  suggestions are waiting.
- **Per-bank split:** with "All banks" selected, the month and year income/expense cards show
  a table per bank (same rules as the cards: transfers and repeated rows left out). It adds
  up to the cards; it is hidden when one bank is selected.
- **Account history:** each account card shows up to 12 month-end balances (the running
  balance of its last transaction in each month, carried through months without
  transactions), a small line of them and the change in the latest month. Balances shown are
  still the closing balance of the latest statement.

## Data model additions (migration 0004)

`accounts`; `documents` gains period, balances, adapter, confidence and a `validation`
JSON (codes, pages and row numbers only); `transactions` holds `NUMERIC(18,2)` money,
`source_page`, `validation_status` and a `row_hash` (the architecture's dedupe key, used for
overlap detection; duplicate flags arrived in migration 0005, categories in 0006 and AI hint
categories in 0007).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/documents/{id}` | status, period, balances, adapter, confidence, checks and issues |
| `GET /api/transactions` | each row carries `bank_code`, `bank_name`, `account_last4`; filters: `document_id`, `bank_code`, `year`, `month`, `flagged`, `validation_status`, `q`, `category_id`, `uncategorised`, duplicates; `sort` / `order`; `limit` (max 500) / `offset` |
| `GET /api/transactions/export.csv` | the same filters as a CSV file |
| `GET /api/banks` | supported banks (for filters) |
| `GET /api/dashboard?year=&month=&bank_code=` | current balances (with month-end `history` and `change`), income/expense for the month and the year (with `*_by_bank` when no bank is selected), spending by category, `coverage` (missing months, balance breaks), `transfer_suggestions`, `needs_review` count |
| `GET /api/dashboard/trend?year=&month=&months=&bank_code=` | monthly income, expense and balance series |
| `DELETE /api/documents/{id}` | delete a statement and its rows |
| `GET /api/documents` | list statements with status |
| `GET /api/tracker?year=` | bank/account x month grid of uploaded statements, plus `gap_months`, `gap_total` and `breaks` per row |
| `GET /api/savings/interest?year=&bank_code=` | interest credited per month and the annual rate it works out to (`07-budgets-recurring-reports.md`) |
| `GET /api/reports/ird?year=` (and `/ird.csv`) | income by head and tax withheld for a year of assessment starting 1 April |
| `GET /api/transfers/suggestions` | possible transfers between your own accounts |
| `POST /api/transfers/confirm`, `/reject` | `{out_id, in_id}`: file both halves as Transfers, or remember it is not a transfer |
| `POST /api/documents/{id}/accept` | accept a `needs_review` statement |
| `POST /api/documents/{id}/reprocess` | run extraction again on the stored original (needs the file; replaces the old rows) |
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
- Re-running extraction (`reprocess`) replaces the rows, including categories you set by
  hand on that statement. Preserving manual categories across re-extraction is not done yet.
- Rows with no account number are matched per bank, so duplicate detection across such
  statements is weaker.
- BOC, HNB, Commercial and Sampath are supported; other banks come one at a time with real samples.

Categorisation and duplicate removal are implemented: see `04-categorization.md` and the
"Duplicate transactions" section above.

## Layouts no adapter knows, and statements that are not PDFs

**Fallback reader** (`adapters/generic.py`). When no bank adapter recognises a PDF, the worker tries a
best-effort reader instead of failing at once. It looks for lines of the form `DATE DESCRIPTION AMOUNT
[AMOUNT] BALANCE` (the date must carry a year; day first). Every row must move the balance by exactly its
amount, and the statement is `reconciled` only if the statement's own "closing balance" line agrees. With no
such line, or if any row does not follow, it goes to review. It reads only text PDFs (no OCR) and
only the one-row-per-line shape; anything else still fails with `unsupported_layout`.

**CSV import and typed rows** (`services/importer.py`, `routers/imports.py`; Upload page, "No PDF..."
panel). `POST /api/imports/csv` (file, optional `bank_code`, `account_number`, `opening_balance`) and
`POST /api/imports/manual` (JSON rows). A CSV needs a header row with a date, a description and either
Debit and Credit or one signed Amount column; a Balance column is optional (then an opening balance is
needed). Dates are read day first. The rows become a document with adapter `import` and are checked like
any statement; the same rows imported twice are refused (409). Errors are short codes with a row number,
never row text.

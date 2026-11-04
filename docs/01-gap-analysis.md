# Gap Analysis: Current Application vs. Requirements

Status: historical. Written against the Streamlit + SQLite + Ollama prototype in `src/`, before
the FastAPI / Next.js / Postgres rebuild. Section 8 maps its gaps to the rebuilt application.
Sections 1 to 7 are kept as written.

## 1. Documentation vs. implementation

`docs/00-architecture.md` describes a Next.js / FastAPI / Postgres / worker design.
The code in `src/` is a single-process Streamlit app with SQLite. The two must be
reconciled: either mark `src/` as a prototype and keep the architecture as the target,
or update the architecture to match what exists.

| Topic | Architecture doc | Current code |
|---|---|---|
| Frontend / API | Next.js + FastAPI | Streamlit only |
| Database | Postgres (+ queue), `user_id` on tables | SQLite, no `user_id` |
| Default LLM | `qwen3:4b` | `qwen2.5:1.5b` (`OLLAMA_MODEL`) |
| Assistant | LLM picks predefined analytics function; code computes numbers | LLM answers free-form from a text summary |
| Banks | Commercial, Sampath, HNB, BOC | BOC only |
| OCR | Tesseract | None (warning only) |
| Transfer matching | Cross-account, +/-3 days | None |
| Packaging | Docker named volumes, internal network | Only Ollama is in Docker |

## 2. Correctness and data integrity

| # | Gap | Impact | Suggested fix |
|---|---|---|---|
| 2.1 | No database-level duplicate protection (only `session_state`) | Re-uploads or overlapping statements double-count | Unique key or stored file hash |
| 2.2 | Transactions saved before reconciliation is shown | Mismatching statements already stored | Save after validation or user confirmation |
| 2.3 | `review_required` rows have no review screen | Flagged rows are never resolved | Review queue UI |
| 2.4 | No transactional import | Partial imports on failure | Single DB transaction per statement |
| 2.5 | Debit/credit inferred from balance movement only | Wrong side when balance unchanged or rows mis-grouped | Use column positions as a second signal |
| 2.6 | Year inferred from statement date | Wrong dates across year boundaries | Validate against opening/closing dates |
| 2.7 | Money stored as `REAL`, summed as floats | Rounding drift | Integer cents or `NUMERIC` |
| 2.8 | Page-break, repeated header/footer and multi-account edge cases unhandled | Dropped or merged rows | Fixtures from real statements |

## 3. Missing features

- Additional banks and bank auto-detection (parser registry).
- OCR for scanned PDFs.
- Account entity (account number, per-account views).
- Dashboard filters (date range, category, account).
- Transaction search, edit and delete; delete an imported statement.
- Bulk categorization and "create rule from correction".
- Budgets, recurring-payment detection, anomaly detection, forecasts.
- Backup, restore and full-data export.
- Assistant: chat history, streaming output, analytics-function calling, model-assisted
  categorization.

## 4. Engineering gaps

- One parser test with a single transaction; no tests for `parse_money`,
  categorization, database, reconciliation or UI.
- No schema versioning (ad hoc `ALTER TABLE` checks).
- `recategorize_saved_transactions` runs on every Streamlit rerun and queries the
  rules table once per transaction.
- Relative `DATABASE_PATH`; app only runs correctly from `src/`.
- No logging; blanket `except Exception` in the upload flow.
- Ollama calls: no model-not-found message, retry or configurable timeout.
- No `pyproject.toml`, linting, formatting, type checking or CI.
- No Dockerfile for the app itself.
- Tests exist in two places (`src/tests/` and `tests/`).

## 5. Security and privacy

- Plaintext SQLite database; no encryption.
- No authentication on the Streamlit port.
- PDF password remains in a Streamlit widget and session state (the architecture
  requires in-memory only, never stored).
- Raw extracted PDF text is displayed; assistant prompts include transaction
  descriptions that may contain personal identifiers.
- Real sample statements live in `sample_pdfs/`; confirm they are ignored and were never
  committed.

## 6. Documentation gaps

- `README.md` is two lines: no setup, run or architecture pointer.
- No usage guide for the Docker/Ollama setup (`docker compose up -d ollama`,
  `docker compose up ollama-pull`).
- About page is stale: lists categorization as "planned" and omits the AI Assistant.
- No data-flow, schema or parser-format documentation.
- `docs/windows-setup.md` and `docs/licenses.md` are not linked from the README.

## 7. Suggested priority

1. Duplicate protection and validate-before-save.
2. Money as integer cents; schema version table.
3. Tests using real sample statements (kept private) and parser edge cases.
4. Review queue for `review_required` rows.
5. Account concept, filters, then a second bank parser.
6. Model-assisted categorization and analytics-function calling for the assistant.
7. Reconcile `00-architecture.md` with the implementation.

## 8. Status in the rebuilt application

| Gap | Status |
|---|---|
| 1 Architecture vs code | Resolved: the architecture is implemented; `00-architecture.md` section 12 lists the differences |
| 2.1 Duplicate protection | Resolved: sha256 per user plus transaction-level `row_hash` across overlapping statements |
| 2.2, 2.4 Validate before save, transactional import | Resolved: one transaction per statement; unreconciled statements are held for review |
| 2.3 Review screen | Resolved: statement review/accept, category Review queue |
| 2.5 Debit/credit from balance only | Open (balance movement, then validated) |
| 2.6 Year inference | Resolved for BOC: resolved from the end, `date_sequence` check |
| 2.7 Money as floats | Resolved: `NUMERIC(18,2)` and `Decimal` |
| 2.8 Page breaks, repeated headers | Resolved for BOC; unverified for other banks |
| 3 Additional banks | HNB, Commercial and Sampath added (each from one real layout) |
| 3 OCR | Open |
| 3 Account entity, filters, search, delete statement, bulk categorise, rule from correction | Resolved |
| 3 Transfer matching (cross-account, 3 days) | Resolved: suggested, confirmed by you |
| 3 Budgets, recurring, anomalies, forecasts, assistant | Open |
| 3 Backup | Resolved: see `06-backup-and-restore.md` |
| 4 Tests, schema versioning, logging, Dockerfile | Resolved (pytest suite, Alembic, logging, Dockerfiles); CI and lockfiles open |
| 5 Authentication, plaintext database, PDF password handling | Resolved: auth, password never stored. Database encryption at rest is not done |
| 5 Descriptions sent to the model | Mitigated: only description stems go to the local model, never amounts or account numbers |
| 6 README, docs | Resolved: README and `docs/0*.md` |

### Current backlog

- Offline compose override and healthchecks for every service.
- (Done, see `06-backup-and-restore.md`: backups and restore, manual categories kept on
  re-extract, duplicate matching within one bank when no account number is found.)
- (Done, see `03-extraction.md` "Checks across statements and banks": own-account transfer
  matching, missing-month and balance-break checks, per-bank split, account history.)
- Confirm the HNB adapter on real multi-page statements; then Commercial, Sampath, a generic
  adapter and OCR.
- CI and dependency lockfiles.
- Review SQL parameter handling for anything built from user text.
- Forward the remaining `LLM_*` settings through `docker-compose.yml` if they need tuning.

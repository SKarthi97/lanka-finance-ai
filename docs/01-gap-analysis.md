# Gap Analysis: Current Application vs. Requirements

Status: DRAFT. Based on a read of every file in `src/` (Streamlit + SQLite + Ollama
prototype). The app and tests were not executed for this review.

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

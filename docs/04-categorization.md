# Categorisation (Phase 4)

Status: implemented. Follows `00-architecture.md` sections 4 and 6.

## What it does

Every transaction can have a category. Categories have a **kind**: `income`, `expense` or
`transfer`. Transfers (money moving between your own accounts) are left out of income and
expense totals; everything else counts. A transaction with no category is counted by direction
(a credit is income, a debit is expense), so the totals keep their meaning while categorising
is unfinished.

## Order of authority (strongest first)

| Source | Set by | Overwritten by |
|---|---|---|
| `manual` | you, on one transaction | nothing |
| `user_rule` | your rules, and rules learned from your corrections | a higher-priority rule |
| `rule` | built-in rules for common bank wording | your rules |
| `llm` | the local model, when confident | any rule |
| (none) | nothing matched | |

Rules match the normalised description (upper case, single spaces). Among matching rules the
higher priority wins, then the longer pattern, so "INTEREST WITHHELD" (tax) beats
"INTEREST PAY" (income). Pattern types: `contains` (anywhere) and `word` (whole word only, so
`CEB` does not match "FACEBOOK"). Priorities: built-in 10 to 30, rules you write 40, learned
corrections 50.

## Learning from corrections

Change a category in the Transactions page. If other transactions look the same you are asked
whether to use it for them and for future statements. The "stem" of a description is its first
four words without digits ("LOAN RECO 12345678" becomes "LOAN RECO"), so one correction covers
every month. This creates a `correction` rule and applies it to every transaction that is not
set by hand (replacing built-in results and AI suggestions). Each correction is logged in
`classification_feedback`.

## Review queue

Categories page, Review tab: uncategorised transactions grouped by stem, biggest first. Choose
a category once per group; it applies to the whole group and is remembered. Duplicates (the same
transaction in two overlapping statements) are not listed.

## The local AI fallback

For transactions the rules leave, the worker asks the local model (Ollama, default
`qwen2.5:1.5b`) in a separate `classify_llm` job after extraction. Safeguards:

- **Only description text is sent**, as stems, to the Ollama container on the internal network.
  No amounts, balances, dates, account numbers or filenames. A test asserts this.
- The reply is **schema-constrained JSON** and re-validated. A category id the model invents is
  ignored; an out-of-range index is ignored; an unusable reply leaves the rows untouched so a
  later pass retries them.
- Descriptions are treated as **data**. The prompt says so, and since the output can only be a
  category id from the list, text hidden in a description has nothing to act on.
- Only suggestions at or above `LLM_CONFIDENCE_THRESHOLD` (default 0.8) are applied, marked
  `AI` in the explorer. The rest are marked `llm_unsure` and stay in the review queue. The
  button "Ask the local AI to suggest" gives them another chance.
- Every call is recorded in `model_runs` (model, digest, prompt **hash**, duration, whether the
  JSON was valid). The text is never stored.
- A failed AI pass (Ollama down, model missing) **never changes a statement's status**; the job
  just fails and can be asked again. Turn it off with `LLM_CLASSIFY_ENABLED=false`.

A 1.5B model on CPU makes mistakes. That is why only confident answers apply, why they are
labelled, and why any rule or your own choice overrides them.

## Built-in rules

`services/categorizer.py` (`CATEGORIES`, `RULES`). They hold generic wording only (ATM, SLIPS
IN, LOAN RECO, INTEREST, SERVICE CHARGE, CEFT, ...) and nothing personal. They are created per
user the first time they are needed; adding entries and raising `SYSTEM_VERSION` adds them for
existing users on the next run without touching your own rules. You can turn a built-in rule
off but not delete it.

## API

| Endpoint | Purpose |
|---|---|
| `GET/POST /api/categories`, `DELETE /api/categories/{id}` | list, add, delete (custom and unused only) |
| `GET/POST /api/rules`, `PATCH/DELETE /api/rules/{id}` | list, add, turn on/off, delete (not built-in) |
| `PUT /api/transactions/{id}/category` | set a category; `create_rule` also learns it |
| `GET /api/categorization/review` | the review queue |
| `POST /api/categorization/apply` | one category for a whole description group |
| `POST /api/categorization/reclassify` | re-run the rules on rows not set by hand |
| `POST /api/categorization/ai`, `GET /api/categorization/status` | ask the AI pass, see its state |
| `GET /api/transactions?category_id=&uncategorised=` | filters |
| `GET /api/dashboard` | income/expense without transfers, transfers shown separately, spending by category |

## Limits

- No sub-categories or merchants yet (the schema allows `parent_id`; merchants come later).
- Rules match descriptions only. They cannot use amounts or direction.
- A transaction in an overlapping statement shares its original's category.
- Category names are unique per user; renaming is not available yet (add a new one and move
  transactions).

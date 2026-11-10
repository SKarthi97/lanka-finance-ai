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

## AI suggestions tab

The Categories page lists what the model applied, grouped by description, with its confidence.
Accepting a group makes it your choice and saves a rule; you can pick a different category first,
or accept everything at once. Rejecting a group clears those transactions back to the Review
queue (the model may suggest them again the next time you ask).

## Review queue

Categories page, Review tab: uncategorised transactions grouped by stem, biggest first. Choose
a category once per group; it applies to the whole group and is remembered. Duplicates (the same
transaction in two overlapping statements) are not listed.

## The local AI fallback

For transactions the rules leave, the worker asks the local model (Ollama, default
`qwen2.5:1.5b`) in a separate `classify_llm` job after extraction. Safeguards:

- **Only description text is sent**, as stems, to the Ollama container on the internal network.
  No amounts, balances, dates, account numbers or filenames. A test asserts this.
- The reply is **schema-constrained JSON** and re-validated. The model answers with a category
  *name* from a closed list (small models mix up numeric ids); the name is mapped to an id here.
  A name the model invents is ignored; an out-of-range index is ignored; an unusable reply leaves the rows untouched so a
  later pass retries them.
- Descriptions are treated as **data**. The prompt says so, and since the output can only be a
  category id from the list, text hidden in a description has nothing to act on.
- **Three confidence tiers.** At or above `LLM_CONFIDENCE_THRESHOLD` (default 0.8) a suggestion
  is applied, marked `AI` in the explorer and listed in the AI suggestions tab (where
  "Accept confident" covers those at or above `LLM_CONFIDENT_THRESHOLD`, default 0.9). Between
  `LLM_HINT_THRESHOLD` (0.4) and the threshold it is only a **hunch**: not applied, but kept in
  `suggested_category_id` and shown beside the Review row as a one-click choice. Below that
  the row is simply `llm_unsure`. The button "Ask the local AI to suggest" gives them another go.
- **It learns from you.** Rules you made or learned from corrections are sent as examples
  (`stem => category`, up to `LLM_EXAMPLE_LIMIT`, the ones sharing words with the batch first).
  Still description text only.
- **Merchants are grouped before asking.** Stems drop trailing branch/reference words and
  near-identical spellings (typos) are judged once through the most common one.
- **Optional amount hints**, off by default (`LLM_AMOUNT_HINTS=true`): "money in/out" and a
  coarse size band (small, medium, large, very large) per stem, never an exact figure. Helps
  tell salary from a transfer; turn it on only if you accept that coarse signal reaching the
  local model.
- **Choosing a model.** `python -m app.tools.eval_categorizer qwen2.5:1.5b qwen2.5:3b` (run in
  the backend container) scores models on a synthetic labelled set: coverage, accuracy, accuracy
  when confident, and time. Changing the model is just `OLLAMA_MODEL`; see the thresholds above
  if a larger model is over-confident.
- Every call is recorded in `model_runs` (model, digest, prompt **hash**, duration, whether the
  JSON was valid). The text is never stored.
- A failed AI pass (Ollama down, model missing) **never changes a statement's status**; the job
  just fails and can be asked again. Turn it off with `LLM_CLASSIFY_ENABLED=false`.

A small model on CPU makes mistakes. That is why only confident answers apply, why they are
labelled, and why any rule or your own choice overrides them.

### Which model and thresholds

Measured with the evaluation script on its 41 synthetic descriptions (batch 5, CPU only):

| Model | Answered | Right | Right when confident | Time |
|---|---|---|---|---|
| `qwen2.5:1.5b` | 6/41 (the rest null) | 5 | 5/6 | 60 s |
| `qwen2.5:3b`, numeric ids in the prompt | 30/41 | 18 | 18/29 | 249 s |
| `qwen2.5:3b`, category names | 36/41 | 32 | 32/36 | 173 s |
| `qwen3:4b`, category names, `think: false` (recommended) | 41/41 | 37 | 37/41 | 247 s |
| `qwen3.5:4b`, category names, `think: false` | 41/41 | 38 | 38/41 | 368 s |

Findings: 1.5B is too small for about 20 categories; the closed list of names fixed most of the
3B model's mix-ups; the model reports 1.00 for almost everything, so **its confidence does not
separate right from wrong**. Its remaining errors are overlapping categories (groceries versus
food, fixed deposit versus deposits). Recommended `.env` until your own corrections have taught
it more:

```
OLLAMA_MODEL=qwen2.5:3b
LLM_TIMEOUT_S=300
LLM_CONFIDENCE_THRESHOLD=1.01   # nothing is auto-applied; every guess is an AI hunch in Review
```

**Reasoning models (Qwen3, Qwen3.5):** these "think" before answering, which on a CPU can
multiply the time for a task that is a lookup. The app therefore sends `think: false` by
default (`OLLAMA_THINK`, default `false`, in `app/config.py`, forwarded by compose to the backend
and worker). Set `OLLAMA_THINK=true` only to let every call reason; code that genuinely needs
reasoning can ask for it for one call (`think=True` in `services/ollama.generate` /
`llm_json.ask`). A model with no reasoning mode (such as `qwen2.5`) rejects the option; the
request is then repeated without it and that model is remembered, so no setting needs changing
when you switch models.

Compose forwards `OLLAMA_MODEL`, `LLM_CLASSIFY_ENABLED`, `LLM_TIMEOUT_S` (worker) and
`OLLAMA_TIMEOUT_S` (backend, used by the "ask the AI" button; default 60, too short for 3B),
and `LLM_CONFIDENCE_THRESHOLD` (worker). `LLM_HINT_THRESHOLD`, `LLM_EXAMPLE_LIMIT`,
`LLM_AMOUNT_HINTS` and `LLM_CONFIDENT_THRESHOLD` use their defaults unless added to the compose
`environment` lists. A larger model needs no code change: set `OLLAMA_MODEL`, raise the timeout,
and re-run the evaluation.

### Evaluating a model

```
docker compose exec backend python -m app.tools.eval_categorizer qwen2.5:3b --timeout 400 --batch 5 --verbose
```

Options: `--timeout S` (per call), `--batch N` (descriptions per call), `--verbose` (one line
per description: expected, model said, confidence). "no reply" means a timeout or unusable
answer; "null" means the model declined. The set (`app/tools/eval_set.json`) is synthetic, so
the output is safe to share. Install a model first with `docker compose exec ollama ollama pull
qwen2.5:3b` and rebuild the backend image after changing the script.

## Rules with conditions, renaming and sub-categories

A rule can also be limited to **money in** or **money out** and to an **amount range** (Rules tab:
"Money", "From amount", "Up to amount"). A row matches only when its words match and its direction
and amount fit. Among rules of the same strength the one with more conditions wins, so a rule for
"ACME" credits over 50,000 beats a plain "ACME" rule. The same words may have several rules with
different conditions (`classification_rules.conditions_key`, migration 0015).

Categories you made can be **renamed** and put **under a parent** ("Food and dining › Groceries")
from the Categories tab. The pickers show the full name. The Rules tab has **Re-run rules on my
transactions** (`POST /api/categorization/reclassify`) for after you add or switch on a rule;
choices you set by hand and AI suggestions are left alone.

## Built-in rules

`services/categorizer.py` (`CATEGORIES`, `RULES`). They hold generic wording only (ATM, SLIPS
IN, LOAN RECO, INTEREST, SERVICE CHARGE, CEFT, ...) and nothing personal. They are created per
user the first time they are needed; adding entries and raising `SYSTEM_VERSION` adds them for
existing users on the next run without touching your own rules. When the version changes the
rules are also re-run once on the rows you already have (manual choices and AI suggestions are
left alone), so a new rule is not just for future statements. You can turn a built-in rule off but
not delete it.

Income categories: Salary, Interest income, **Dividend**, Deposits, Other income. Tax rules cover
the ways banks word tax on interest: "INTEREST WITHHELD", "WHT", "AIT" (advance income tax, as a
whole word), "ADVANCE INCOME TAX", "TAX ON INTEREST", "INTEREST TAX", "WITHHOLDING TAX", plus
"STAMP DUTY". The version is 3 at the time of writing.

A correction rule is saved under the description's stem (words without digits), so it also matches
a description with a number between the words ("CRDLESDEP 0000769618638 AECT" matches the stem
"CRDLESDEP AECT").

## API

| Endpoint | Purpose |
|---|---|
| `GET/POST /api/categories`, `DELETE /api/categories/{id}` | list, add (optionally under a parent), delete (custom, unused, without sub-categories) |
| `PATCH /api/categories/{id}` | rename a category you made, or move it under a parent (`set_parent`, `parent_id`) or back to top level; built-in categories cannot be renamed or moved |
| `GET/POST /api/rules`, `PATCH/DELETE /api/rules/{id}` | list, add, turn on/off, delete (not built-in). A rule may carry `direction` (`in` or `out`) and `min_amount` / `max_amount` |
| `PUT /api/transactions/{id}/category` | set a category; `create_rule` also learns it; `preview: true` changes nothing and returns `similar_count` |
| `GET /api/categorization/review` | the review queue; each group may carry `hint_category_id`, `hint_category_name`, `hint_confidence` |
| `POST /api/categorization/apply` | one category for a whole description group |
| `POST /api/categorization/reclassify` | re-run the rules on rows not set by hand |
| `POST /api/categorization/ai`, `GET /api/categorization/status` | ask the AI pass, see its state |
| `GET /api/transactions?category_id=&uncategorised=&sort=&order=` | filters and ordering (`sort`: date, amount, description, bank, category) |
| `GET /api/transactions/export.csv` | the same filters as a CSV file (the whole result; cells that start with `=`, `+`, `-` or `@` are neutralised) |
| `POST /api/transactions/bulk-category` | one category for up to 500 selected transactions (set by you; no rule is learned) |
| `GET /api/categorization/suggestions` | what the AI applied, grouped by description and category, plus `confident_threshold` |
| `POST /api/categorization/suggestions/accept`, `/reject` | accept (makes it your choice and learns a rule) or reject (back to Review) one group |
| `GET /api/dashboard` | income/expense without transfers, transfers shown separately, spending by category |

## Data model

Migration 0006 adds `categories`, `classification_rules`, `classification_feedback` and the
`transactions` category columns (`category_id`, `classification_source`,
`classification_confidence`, `classification_explanation`). Migration 0007 adds
`transactions.suggested_category_id` (the AI hunch). Sources: `rule`, `user_rule`, `manual`,
`llm`, `llm_unsure`. Later migrations add `transfer_rejections` (0011), `budgets` and `saved_views`
(0012), `merchant_names` (0013) and `stem_embeddings` (0014).

## Limits

- Sub-categories are one level only (a child of a top-level category of the same kind) and are a naming aid: reports and budgets still count each category on its own, with no roll-up into the parent. Merchant names exist as a display layer (`08-ai-features.md`) but rules still match descriptions, not merchants.
- A rule needs words from the description; it can also be limited to credits or debits and to an amount range (migration 0015). It cannot match on the date or the account.
- A transaction in an overlapping statement shares its original's category.
- Category names are unique per user. You can rename the categories you made, not the built-in ones: interest, tax, salary and the IRD figures find them by name.

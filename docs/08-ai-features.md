# AI features: names, search, similarity hints, summaries, flag explanations

Rule for every feature here: **code computes, the local model only labels.** The model runs in
the Ollama container on the internal network; nothing goes to the internet. It never sees
amounts, balances, dates, account numbers or filenames. Each call is recorded in `model_runs`
as a hash of the prompt, never its text. A feature must work, more plainly, with the model off.

## Clean merchant names (4.1)

`POS PURCHASE KEELLS SUPER CITY 4471` becomes **Keells Super City** on the Transactions page, with
the original description kept underneath. The original is never changed.

- **Stored by stem, not by row** (`merchant_names`, migration 0013, `services/merchants.py`). The
  stem is the reusable part of a description (words without digits, at most four, the same stem
  the categoriser uses). One name therefore covers every row with that stem, survives a
  statement being extracted again, and applies to future statements.
- **Layer 1, code (always on):** `rule_clean` drops payment-method words at the front (POS, CARD,
  PURCHASE...) and fixes capitalisation. Nothing is empty or unreadable.
- **Layer 2, the model (background job `name_merchants`):** queued after each extraction, or with
  **Improve names** on the Transactions page. It is sent only stems, in batches of 15, with a
  reply schema `{results: [{index, name}]}`. Your own manual names are shown as style examples.
- **A name is accepted only if it is plausible** (`plausible`): at most 40 characters, no digits,
  no line breaks, and every word shares its first three letters with a word of the stem. So the
  model can shorten and tidy but cannot invent: "Hatton National Bank" for `HNB` is refused.
  A refused name falls back to layer 1.
- **You have the last word:** rename in the transaction's detail panel; it is stored as `manual`,
  applies to every row with that stem, and the model never overwrites it or is asked about it
  again. "Reset" removes it.

| Endpoint | Purpose |
|---|---|
| `GET /api/transactions` | each row has `merchant` and `merchant_source` (`manual`, `llm`, `rule`) |
| `PUT/DELETE /api/transactions/{id}/merchant` | set or reset the name for that description stem |
| `POST /api/merchants/name` | queue a naming pass |

## Search in plain words (4.2)

On the Transactions page, "Ask in plain words": *fuel over 5k last month*, *money received from
Sampath in March*, *between 1,000 and 2,500 in 2025*. The result is an ordinary set of filters
shown as chips with a summary sentence, so you see exactly what was understood and can change
it, save it as a view, or clear it. Nothing is run or changed by the question itself.

**Code reads** (`services/search.py`, no model): months and years ("march", "last month",
"december" said in November means last December, "2025"), amounts ("over 5k", "under rs. 500",
"between 1,000 and 2,500", "2 million"), direction ("spent", "paid" / "received", "income"; both
means no filter), a bank named in the text, and a category named in the text.

**The model labels only what is left**, and only when there are words left and no category was
named: it picks ONE category from the closed list of your own category names (or null) or names a
keyword. It sees the leftover words and your category names, nothing from your transactions. The
reply is re-checked: a category that is not in your list is ignored, and a keyword must be made
of words you typed. The output is a filter object with a fixed set of fields, never SQL, so a
hostile phrase has nothing to act on.

**Without the model** the code-read parts still work, and up to three leftover words become a
plain text search. The page says so ("The local AI is not available...").

New filters on `GET /api/transactions` (and the CSV export): `min_amount`, `max_amount` (a row's
amount is its debit or credit), `direction` (`in` / `out`). Saved views can hold them.

`POST /api/search/interpret` `{query}` returns `{filters, summary, used_ai, ai_error}`.

## Progress and AI activity

Local models are slow on a CPU, so waiting has to look like working:

- **`AiBusy`** (component) shows animated dots, a live timer, and a bar. When the server knows a
  usual duration the bar fills towards it (never past 95%) and turns amber with "taking longer
  than the usual..." if it overruns; otherwise it shimmers. Reduced-motion settings switch the
  animation off; the text says everything. It is used on Categories ("Ask the local AI"), on
  Transactions for **Improve names** (follows the background job every 3 s, then reloads the
  list and says how long it took), and for "Ask in plain words" (after 0.4 s, so quick answers do
  not flash).
- **Where the estimate comes from** (`services/ai_activity.py`): the average of the last 30 valid
  calls of that kind from `model_runs`, times the number of calls the job needs (descriptions
  waiting divided by the batch size, capped at what one job covers). With no history yet there is
  no estimate and no bar, only the timer. `GET /api/categorization/status` and
  `GET /api/merchants/status` return `progress` (`running`, `queued`, `elapsed_s`, `eta_s`,
  `waiting`, `avg_call_s`); the elapsed time comes from the job, so it is right after a reload.
- **Search timing:** `POST /api/search/interpret` also returns `took_ms` (whole question) and
  `model_ms` (waiting for the model, or null when code alone understood it). The page shows
  "the local AI took 4.2 s" or "read in 12 ms".
- **AI activity log** (System page, `GET /api/ai/activity`): per kind of call (categorising,
  merchant names, search) the number of calls, how many replies were usable, average, slowest and
  total time over 30 days, and the latest calls. It holds durations and outcomes only. **Prompts
  and replies are never stored**, and not even the prompt hash is sent to the browser. Its use:
  see what the chosen model really costs on this PC, and compare models after a switch.

## Similarity hints, "like ones you chose" (4.3)

Built, **off by default**, and meant to be measured on your own corrections before it is turned on.

**What it does.** Each description stem is turned into a vector by a small local embedding model
(Ollama `/api/embed`, default `nomic-embed-text`). For an uncategorised stem the app looks at its
5 nearest stems among those **you categorised yourself** (manual choices and rules you made or
learned from corrections; never built-in rules or earlier AI guesses). Neighbours at least 0.80
similar vote, weighted by similarity; a hint needs two or more of them and 80% of the vote on one
category. The hint goes to Review as "Like ones you chose: Fuel (72%)", with "Similar to 4
descriptions you categorised" as the reason. It is **never applied automatically**. Stems that get a
hint skip the slow chat model; the rest go on to it as before. The "confidence" is agreement
times average similarity: a ranking, not a probability.

**Why it is measured first.** Small English embedding models know few Sri Lankan merchant names,
so for brands the similarity may come only from shared generic words that rules already catch.
Whether it is worth having depends on your data, so:

```
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec backend python -m app.tools.eval_embeddings             # your corrections
docker compose exec backend python -m app.tools.eval_embeddings --synthetic # invented set, no data needed
```

The tool hides each of your labelled descriptions in turn and predicts it from the others, over a
grid of similarity and agreement settings. It prints **counts and percentages only** (never a
description, category name or amount), the "always the biggest category" baseline, and a verdict:
it recommends settings only if some row reaches 90% accuracy while covering at least 15% of your
labelled descriptions (`--min-accuracy`, `--min-coverage`). Then set, in `.env`:

```
EMBED_SUGGEST_ENABLED=true
EMBED_MIN_SIMILARITY=0.80   # from the tool's verdict
EMBED_MIN_AGREE=0.80
```

It also needs at least 20 descriptions you categorised yourself (`embed_min_labelled`); below that
it stays quiet. Vectors are cached per stem and model (`stem_embeddings`, migration 0014, about
3 KB each), so only new stems are embedded. A missing model or an unusable answer just skips the
tier. `GET /api/ai/similarity` reports the state (shown on the Categories page). numpy is the one
new dependency.

## The month in words (4.4)

On the Report page, "The month in words" is in two layers:

1. **Written by code, always shown:** income, spending and net with the real amounts; change on
   the previous month; share kept; the biggest three categories; the category that rose most;
   budgets over or close; overdue recurring payments; uncategorised count.
2. **A friendly paragraph from the local AI, on request** (**Add a friendly paragraph**). It is
   given the facts **without any amount**: percentages, counts and category names. What it writes
   is checked (`services/llm_guard.py`): every number in it must already be in those facts, it must
   not mention money (LKR, Rs, a currency sign), and it must not contain markup. A paragraph that
   breaks a rule is dropped and the page says so; the code-written bullets are unaffected.

`POST /api/summary` `{year, month, ai}` returns `{bullets, narrative, used_ai, ai_note, took_ms,
model_ms}`. It prints with the report.

## Explain a flagged transaction (4.5)

**Code decides what is unusual** (`services/flags.py`) and writes each reason as a fixed sentence,
shown under "Why this is flagged" in a transaction's detail panel:

| Reason | When |
|---|---|
| row_balance_mismatch, row_amounts_invalid, suspicious_date_gap, date_outside_period, ... | the statement check doubted this row |
| statement_not_reconciled | its statement is held for review |
| large_for_category | at least 3 times the usual (median) for its category **and** in your top 10% for it; needs 5 comparable payments |
| first_time_large | a payee seen once, among your largest payments; needs 30 payments |
| possible_double_charge | same description and amount within a day |
| negative_balance | the balance after the row is below zero |

History checks use reconciled or accepted statements only and leave out repeated rows.
**Explain in plain words** asks the local AI to rephrase the reasons for a non-expert and say what to
check. It is given the reasons, the money direction and the category name, and **nothing else: no
description (untrusted PDF text), no amount, no date, no account**. Its answer passes the same number
guard and is dropped if it adds a figure. With the AI off or failing, the code-written reasons remain.

`GET /api/transactions/{id}/flags`, `POST /api/transactions/{id}/explain` (409 when nothing is
flagged).

## Re-analysis for the current model: 4.6 and 4.7

**What changed since the first look.** The first assessment was made on `qwen2.5:3b` (32 of 41
right, 36 answered). The model now is `qwen3:4b` with thinking off: **37 of 41 right, 41 of 41
answered, 0 unusable replies in 9 calls**, about 27 s per call of five one-line descriptions on this
CPU. Closed-list labelling and JSON discipline are good. Anything that needs long input, long output
or open reasoning is still slow and weak, and its confidence number still means nothing.

### 4.6 Parsing unknown statement layouts with the model: viable, but not the way first imagined

Three designs, in the order I would try them:

| Design | Verdict with the current model |
|---|---|
| **C. A generic code adapter** (no model): a row is a line that starts with a date and ends with one or two money amounts, then the same balance reconciliation. | Try first. Free, instant, deterministic, private. The four supported banks share this shape, so it may already cover many others. |
| **B. The model proposes a "layout recipe" once per layout** from a **redacted** sample (digits masked, names removed): date format, which column is which, how debit and credit are marked, where the opening and closing lines are, and the lines that identify the bank. Code then parses every page like a normal adapter and reconciles; the recipe is saved and reused each month. | Worth building when a real unsupported statement exists. It is one short call with a closed schema (the kind this model does well), it sends no real amounts, and a wrong recipe is harmless: the statement fails to reconcile and waits for review, as today. |
| **A. The model reads every page and returns every row.** | Not as an everyday path. A page is about 40 rows of output, which on this CPU is likely minutes per page and tens of minutes per statement (an estimate from the 27 s per small call; I would measure one page before believing it). It also sends the whole statement (names, account numbers, amounts) to the model: still local, still not logged, but a break from "only stems are sent", so it needs your explicit yes. |

Why the safety net is unusually strong: every statement must reconcile (opening plus credits minus
debits equals closing, and every row's balance follows from the one before). A model that omits,
swaps or garbles a row almost always breaks that arithmetic. Add a verbatim check (each date, amount
and description fragment it returns must occur in the page text) and it can only copy, not invent.
What arithmetic does not check: a wrong but real date, or a description attached to the wrong row.

Scanned PDFs are a separate problem. `qwen3.5` models accept images, but a 4B vision model reading
dense numeric tables is likely to misread digits; reconciliation would catch that, at a cost in time
and review. Ordinary OCR (Tesseract) plus design C or B is the sounder route. Not tested.

**Recommendation:** keep 4.6 open and start only when you have a statement from a bank we do not
support: build C, measure how far it gets, then add B for what is left. Nothing to build without a
real layout to test against.

### 4.7 Free-form chat over the data: still no; a smaller thing instead

The better model does not change the problem. A chat that answers "how much did I spend on fuel in
March?" must get the number from code, so every answer is two model calls (choose a function, then
phrase the result), at 10 to 30 s each on this CPU. Follow-ups ("and in April?") need conversation
history, which is longer prompts, slower turns, more wrong guesses about what "and" refers to, and a
conversation log that the privacy rule says we do not keep. The worst failure of a finance chat, a
plausible wrong figure, is exactly the one that cannot be fully guarded.

What is worth having is most of the value at a fraction of the risk: **answer one standalone
question with a computed number** (new tracker item 4.8). It extends the search box: the same code
that reads dates, amounts, banks and categories also recognises "how much / how many / average /
biggest / compare", picks one of a few fixed functions (sum, count, average, largest, compare two
months, top categories), and shows the answer with its interpretation spelled out ("Total spent on
Fuel in March 2026, 12 transactions") and a link to the rows behind it. The model is barely needed:
keyword rules cover the function choice, and the model only labels what code cannot (as now). No
history, no free text from the model in the answer. I would build a 40-question synthetic test set
first, in the style of the categoriser evaluation.

**Recommendation:** leave 4.7 dropped; build 4.8 when you want it.

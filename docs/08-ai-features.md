# AI features: merchant names, plain-words search, and the embedding analysis

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

## 4.3 Category suggestions by similarity (embeddings): analysis, not built

**The idea.** Turn each description stem into a vector with a small embedding model. For an
uncategorised stem, find the nearest stems you have already categorised and suggest what most of
them have. Today a correction teaches only that exact stem (a `contains` rule); a similar-looking
merchant is still unknown to the rules.

**What exists now, so the gap is clear.** Built-in rules (generic words), your rules and
corrections (exact stems), `cluster_stems` (typo-level string similarity, 0.9), and the local
model with your confirmed rules as examples (picked by shared words). Measured on 41 synthetic
descriptions, `qwen2.5:3b` with category names answers 36 and gets 32 right, takes about 173 s,
and reports a confidence of about 1.00 for nearly everything, so its confidence does not separate
right from wrong.

**What embeddings would add**

| Gain | Why it is real |
|---|---|
| Speed: milliseconds per stem against minutes for the chat model | The whole uncategorised list could be suggested at once, instantly, as a first tier |
| A score that can be tested | Cosine similarity plus "how many of the k nearest agree" can be thresholded and measured on your own labels, unlike the chat model's constant 1.00 |
| Generalisation beyond exact words | "PHARMACY" next to "PHARMA", "PETROL" next to "FUEL", a typo or a different branch word |
| Better examples for the chat model | The few examples in its prompt could be the nearest confirmed ones instead of word-overlap matches |

**Honest limits**

1. **Sri Lankan merchants are mostly unknown to small English embedding models.** Keells,
   Cargills, Arpico, Dialog, SLT, CEB, LECO sit near random in the space; similarity then comes
   from shared generic words, which rules and substring matching already catch. The gain is
   largest for descriptions made of ordinary words and smallest for brand names, and brand names
   are most of what is left uncategorised.
2. **Bank strings are cryptic** (`IPG PAYMENT`, `CEFT`, `TRF`). Short, jargon-heavy stems embed
   poorly.
3. **Class imbalance:** most of your labels will be a few big categories (transfers, ATM, salary),
   so nearest neighbours lean toward them. It needs a vote with a minimum agreement and a
   similarity floor, not just "closest wins".
4. **Few labels at the start.** With only a handful of corrected stems there is little to be
   near. Usefulness grows with your own corrections.
5. **It must stay a suggestion.** Like the chat model's low-confidence tier, it goes to Review as
   a hint, never applied automatically.

**What it would cost**

- One more local model: `nomic-embed-text` (about 270 MB), `all-minilm` (about 45 MB, weaker), or
  `mxbai-embed-large` (about 670 MB). One extra `ollama pull` while online, offline afterwards.
  The Ollama container has a 5 GB limit; an embedding model fits beside the 3B chat model.
- Storage: a vector per **distinct stem** (not per transaction): 768 numbers, about 3 KB. Five
  thousand stems is about 15 MB. A table `stem_embeddings(stem, model, digest, vector)` is
  enough; **no pgvector and no change to the Postgres image**. Nearest-neighbour search over a few
  thousand vectors is instant with `numpy` (one new dependency).
- Re-embed when the model's digest changes. Embeddings of stems only, so the same privacy as the
  categoriser.
- Roughly: a service to embed and search, a job to keep embeddings current, a new "similar to
  what you chose" hint in Review, and an evaluation tool. About the size of the AI categoriser
  itself.

**Recommendation: measure first, then decide.** Build only the evaluation (no UI, no schema
beyond a temporary table): a tool in the style of `eval_categorizer` that embeds your categorised
stems and reports **leave-one-out accuracy** (hide one label, predict it from the rest) by
similarity threshold and vote size, printing only aggregates so the output is safe to share. Ship
the feature only if, on your own data, the confident subset is right about 90% of the time **and**
it categorises a meaningful share (say 15% or more) of what the rules leave open. If not, drop it
and put the effort into more rules from your corrections. Order of value if it passes: (1) a
suggestion tier in Review, (2) nearest examples in the chat model's prompt. Wait until you have
corrected a couple of hundred stems; before that there is nothing to be near.

# Budgets, recurring payments, saved views and the monthly report

Status: implemented. All of it is computed on this computer from the stored transactions;
the local model is not involved.

## Budgets (`services/budgets.py`, `routers/budgets.py`, page `/budgets`)

A budget is a monthly limit for one **expense** category (income and transfer categories are
refused). **Spent** for a month is the category's debits minus its credits (a refund reduces
it), never below zero, from reconciled or accepted statements, repeated rows left out.
State: `under` below 80% of the limit, `near` from 80% up to the limit, `over` above it.
Setting a budget again changes the existing one. The page shows a bar per budget for the
chosen month, with "left" or "over" in words as well as colour.

| Endpoint | Purpose |
|---|---|
| `GET /api/budgets?year=&month=` | limits with spent, remaining, percent, state, and totals |
| `PUT /api/budgets/{category_id}` | `{amount}` (above zero): create or change |
| `DELETE /api/budgets/{category_id}` | remove |

## Recurring payments (`services/recurring.py`, `routers/recurring.py`, page `/recurring`)

Rows are grouped by direction and the reusable part of the description (the same stem the
categoriser uses), transfers excluded. A group is recurring when:

- the median gap between dates is near a cadence: weekly 7 (needs 4 occurrences),
  fortnightly 14 (4), monthly 30 (3), quarterly 91 (3), yearly 365 (2), and at least 75% of
  gaps fit it; and
- at least 75% of the amounts are within 20% of the median amount.

Several rows on one day count as one event. Status is derived from the last date and the
cadence: `upcoming`, `due`, `overdue`, or `ended` (more than two intervals with nothing).
Monthly totals use the median amount scaled to 30 days and leave out `ended` ones.

Limits: a bill that swings by more than 20% (for example electricity) is not detected; two
merchants whose descriptions share their first words are grouped together, though the amount
check usually separates them; a yearly item needs two years of statements.

`GET /api/recurring` returns the list and the two monthly totals.

## Saved views (`routers/views.py`, component `SavedViews`)

On the Transactions page, **Save these filters** stores the current filters under a name
(`saved_views`, migration 0012); the "Saved views" menu applies one and "Delete view" removes
it. A view holds only these filters: search text, bank, category or uncategorised, year,
month, needs-review, duplicates. Any other key is rejected, so a view can never carry more
than filter values. Saving under an existing name replaces it (at most 50 views). Views are in
the database, so a backup (`06-backup-and-restore.md`) includes them.

## Monthly report (`routers/reports.py`, page `/reports`)

Pick a month (last month by default). The page shows income, expense and net, transfers not
counted, a per-bank table when there is more than one bank, spending by category, budgets
against actual, and the largest expenses. **Print / save as PDF** opens the browser's print
dialog with the menu and top bar hidden; choose "Save as PDF" as the printer (no PDF library
is used). **Download CSV** (`GET /api/reports/monthly.csv?year=&month=`) writes the same
sections; cells that start with `= + - @` are prefixed so a spreadsheet will not run them, and
the file starts with a byte-order mark so Excel reads it as UTF-8.

## Reports page: tabs

The page `/reports` (menu: Reports) has three tabs.

* **Monthly report**: the month summary above.
* **Growth (net savings)**: income minus expenses per month for a year, all banks or one, with
  the interest credited each month and the annual rate it works out to (`services/interest.py`,
  `GET /api/savings/interest`): interest / (sum of the end-of-day balances over the days it covers)
  x 365, the days running from the previous interest credit.
* **IRD (Sri Lanka)**: income by head for a year of assessment (1 April to 31 March, "2025/26"),
  `GET /api/reports/ird?year=2025` and `/api/reports/ird.csv`. Salary, interest, dividends and other
  income come from the categories; tax lines (category Tax) are split into tax on interest, on
  dividends, and other, by their wording (WHT, AIT, withheld, ...) and, when the wording says
  nothing, by sitting within three days of an interest or dividend credit on the same account.
  Uncategorised debits in that position are flagged as likely tax, not counted. It lists missing statement months per account, statements waiting for review and
  uncategorised credits, because each makes the figures incomplete. It sorts what the statements show;
  it does not compute tax (rates and reliefs change, and employer-deducted tax and interest credited
  after tax are not on a statement), and the page says so.

## Savings page (`/savings`, `services/savings.py`, `GET /api/savings/insights`)

Four things, all arithmetic on the statements (no model):

* **What each bank pays you**: the rate over the last 12 months per bank, worked out like the Growth
  tab (interest / balance-days x 365), with the interest, the average balance and the best bank.
* **A falling rate**: the rate on a bank's latest interest credit against the average of up to three
  before it; a fall of half a percentage point or more is shown here and in the bell
  (`services/notifications.py`, kind `rate`). It needs at least three credits to judge.
* **Money that may be idle**: an account with an average balance of 25,000 or more over the last
  90 days and no interest credit in the last 180, with what that balance would earn a year at your
  best rate. Accounts whose statements stopped more than 60 days before the latest data are skipped.
  A current account may pay no interest by design; this is a pointer, not advice.
* **Where the balance is heading**: the average monthly change of your total balance over up to six
  months, continued in a straight line for twelve months, with an optional goal ("you would reach it
  in about N months"). The goal is kept in the browser only. It is not a forecast.

## IRD: figures you enter

The IRD tab also has "Tax paid outside the bank": the employer's tax (APIT) and other tax paid, with
a note, kept per year of assessment (`GET/PUT /api/reports/ird/extras?year=`, stored in `settings`).
They are shown on the page and in the CSV, and are not mixed into the figures read from statements.

## Sub-categories roll up into their parent

A sub-category (one level, see `04-categorization.md`) now counts toward its parent:

* a **budget** on a parent counts what its sub-categories spent (a budget on the sub-category counts only
  its own);
* **Spending by category** on the dashboard and the Reports page shows one line per parent with the
  breakdown underneath (`frontend/lib/rollup.ts`, sums in whole cents); the API still returns each category
  separately with `parent_id` and `parent_name`;
* filtering Transactions by a parent category also shows its sub-categories' rows.

## IRD pack for an accountant

`GET /api/reports/ird.pdf?year=` (`services/ird_pack.py`, button "PDF for your accountant"): a printable PDF
with the figures, what to check (statements in review, uncategorised credits, possible tax, missing months),
the month and bank tables and up to 300 of the transactions behind them. Built from the same report as the IRD
tab, with the same "not tax advice" note.

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

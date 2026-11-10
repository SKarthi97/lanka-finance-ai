# User Interface and Account

Status: implemented. Next.js 16 (App Router), React 19, Tailwind 3.4, TypeScript. The browser
talks only to the Next.js server, which proxies `/api` to the backend on the internal network.

## Pages

| Page | Purpose |
|---|---|
| Dashboard (`/`) | Balances, month and year figures, trends, spending by category, attention panel |
| Upload (`/upload`) | Upload a statement (with password if encrypted), status of each document |
| Transactions (`/transactions`) | Explorer with filters, sorting, paging, export, bulk edit and detail panel |
| Categories (`/categories`) | Review queue, AI suggestions, Transfers, categories, rules |
| Budgets (`/budgets`) | Monthly limits per expense category, with progress |
| Recurring (`/recurring`) | Payments and income that repeat on a schedule |
| Reports (`/reports`) | Tabs: Monthly report, Growth (net savings and interest), IRD (Sri Lanka) |
| Savings (`/savings`) | What each bank pays, falling rates, idle money, where the balance is heading |
| Statement (`/documents/{id}`) | One statement: status, checks, issues, rows, source pages |
| System (`/system`) | Local AI status, hardware, and a collapsible AI activity card |
| Settings (`/settings`) | Account, password, remembered choices, Local AI status |

The sidebar shows badges (statements needing review, uncategorised rows) and a status icon per
document. A "Skip to content" link is the first focusable element.

## First run and sign-in

The first visit to an empty install shows account creation (`POST /api/auth/setup`, only
possible while no user exists). After that, sign in with `POST /api/auth/login`. Sessions are
server-side, in an HttpOnly cookie; every change needs the CSRF token. Login is rate limited
(`LOGIN_MAX_ATTEMPTS` within `LOGIN_WINDOW_S`). The dashboard shows a short getting-started
guide until the first statement is uploaded.

### Changing the password

Settings, Account. `POST /api/auth/change-password` with the current and new password:

- Wrong current password: 403. New password too short (`MIN_PASSWORD_LENGTH`, default 12) or
  the same as the current one: 422.
- On success every **other** session is deleted (the one you are using stays), and the change
  is written to the audit log (no password material).

## Notification bell

The bell in the top bar (it replaced the gear; Settings stays in the sidebar) shows a count and a
list of what needs attention: an account whose latest statement ended more than 45 days ago,
months with no statement, statements that did not reconcile, balance breaks between statements,
possible transfers between your own accounts, and an interest rate that has fallen. The list is worked out from the data each time
(`GET /api/notifications`, `services/notifications.py`), so a notice disappears when its cause
is fixed and nothing needs marking as read. Text holds bank names, the last four digits and
dates only, never descriptions or amounts.

## Dashboard layout

Above the tabs: **bank chips** ("All banks" plus one per bank; shown when there is more than
one bank, remembered in the browser) and "Hide amounts" (masks every figure for screen
sharing). The chosen bank applies to every tab. Below them, five tabs (the last one is
remembered; arrow keys move between tabs):

| Tab | Contents |
|---|---|
| Overview | "Needs your attention", four summary cards for the latest month with data, the month-end balance chart for the chosen year |
| Accounts | One card per account: balance, month-end line (up to 12 months) and the change in the latest month, as-of date and age, "out of date" flag (over 45 days), share of the total, "Show only this bank" and a link to its transactions |
| Cash flow | Year and month pickers, income/expense and balance charts (click a month to select it), month and year income/expense/net cards, each with a per-bank table when "All banks" is chosen |
| Spending | Year and month pickers, spending by category for the month (largest expenses beneath) and for the year |
| Statements | Statement problems (not reconciled, stale, missing months, balance breaks), the statement tracker, a link to Upload; the tab shows a badge with the number needing review |

Headings state the period explicitly (for example "March 2025" or "2025 totals") so a card can
never be mistaken for a different period. The statement tracker follows the bank chip (only that bank's accounts are listed); it is no longer on the Upload page.

Charts have hover tooltips (keyboard focusable), hidden data tables for screen readers, and
`aria-hidden` drawings.

## Upload

A drop zone (drag a PDF in, or choose a file; anything that is not a PDF is refused), bank
selection (automatic by default), a password field that appears only for protected PDFs, and the
list of statements with bank label, pages, size, upload date and status. Failed rows are tinted
red and rows needing review amber; a summary line counts statements in progress, needing review
and failed.

## Transactions

- Filters: bank, year, month, category, uncategorised, flagged, duplicates, free-text search,
  minimum and maximum amount, direction (in or out). **Ask in plain words** turns a sentence into
  these filters (`08-ai-features.md`); **Saved views** keep a set of filters (`07`).
- Sorting by date, amount, description, bank or category. Above the table a strip shows money in,
  money out and net for the whole filter (not only the page). The table scrolls in its own box
  with a sticky heading; when sorted by date, a header row marks each month.
- Reading aids: debits red with a minus and credits green with a plus, the category box tinted by
  its kind (income green, transfer blue, uncategorised amber), a left edge on credit and flagged
  rows, the bank as a coloured label, the merchant name as the bold first line with the original
  text under it (**Improve names** runs the AI naming pass).
- Columns drop on narrow screens; the row opens a **detail panel** (full description,
  statement, page, validation status, category source and confidence, AI hunch).
- Changing a category is **ask first**: the page calls
  `PUT /transactions/{id}/category` with `preview: true`, which changes nothing and returns how
  many similar rows exist. A dialog then asks whether to change only this row or all similar
  rows (and learn a rule). Closing the dialog any other way (outside click, Escape) cancels:
  `ConfirmDialog` resolves `true`, `false` or `null`, and `null` means dismissed.
- Bulk category change for up to 500 selected rows; CSV export of the current filter.

## Categories page

- Categories tab: add (optionally under a parent), rename and move categories you made. Rules tab: rules by words, direction and amount, and a button to re-run the rules.
- Transfers tab: possible transfers between your own accounts (same amount, different accounts,
  within 3 days). "Yes, my own accounts" files both halves as Transfers; "Not a transfer" is
  remembered. The dashboard links here (`?tab=transfers`). See `03-extraction.md`.
- Review tab: uncategorised groups, biggest first. An "AI hunch" button appears beside a group
  when the model had a low-confidence guess; one click applies it.
- AI suggestions tab: what the model applied, with **Accept confident** for those at or above
  the "confident" threshold. See `04-categorization.md`.

## Reports page

Three tabs, described in `07-budgets-recurring-reports.md`: **Monthly report** (with a month
stepper, print and CSV), **Growth (net savings)** (income minus expenses per month, with the
interest credited and its rate) and **IRD (Sri Lanka)** (income by head for 1 April to 31 March).
Print hides the menu, top bar and controls.

## Remembered choices

Stored in the browser only (`localStorage`, wrapped in try/catch so a blocked store just means
nothing is remembered): page size, sort, sort order, the dashboard bank and the dashboard tab. Settings has one
switch ("Remember my choices") which, when turned off, also clears the saved values. Nothing
here goes to the server.

## Styling

Shared helpers in `lib/format.ts`: `bankTint` (a fixed colour per bank code, used for bank labels
everywhere) and `kindChip` (the look of a category kind). Summary cards share a coloured top edge
(green good, red bad, accent neutral). Dark sidebar theme. Tailwind's slate scale is remapped in `tailwind.config.ts` for contrast
(`slate-400` and `slate-500` were lightened for readable secondary text). Loading, empty and
error states share `components/states.tsx`; dialogs share `components/ConfirmDialog.tsx`.

## Known limits

- English only; no i18n.
- The detail panel shows data already loaded; it does not open the source PDF page unless the
  original is still stored (see `RETAIN_DOCUMENTS` in `02-upload-and-queue.md`).

## Import without a PDF, ask for a number, history

* **Upload page, "No PDF, or a statement the app cannot read?"**: import a CSV or type rows by hand
  (see `03-extraction.md`).
* **Ask in plain words** (Transactions page) now also answers questions that ask for a number: "how much
  did I spend on fuel in March", "how many transactions over 10k last month", "average spent in 2025",
  "largest money in September". The answer box shows money out and money in separately unless the question
  names one, and says the filters it used.
* **Transaction side panel, History**: where the row was read from (statement or import), every category you
  changed, merchant names you set or cleared, and its category now with the reason.

## Getting started, shortcuts, small screens, accessibility

* **Getting started** (dashboard, once a first statement is in): a five-step checklist (statement in, every statement
  reconciled, transactions categorised, a budget set, a backup made). Each step ticks itself from the data; "Hide
  this" dismisses it for good (remembered in this browser), and it disappears when everything is done.
* **Keyboard on Transactions**: `/` search, `j` / `k` next / previous row, `x` select the row, `Enter` open its
  details, `Esc` clear, `?` show the list. They are off while typing in a box. Selected rows can be given a category
  together with the bar that appears above the table.
* **System page**: "Storage and backup" shows sizes and the last backup.
* **Small screens**: the browser tests open every page at phone (390 px) and tablet (820 px) widths and fail if
  any page scrolls sideways as a whole; screenshots go to `frontend/test-results/responsive/`. Wide tables scroll
  inside their own box.
* **Accessibility**: text colours are checked for contrast on every dark surface (muted text is at least 4.5:1,
  the orange accent carries dark text, never white); the focus ring is always visible; there is a skip-to-content
  link; budget bars are progress bars for screen readers; ESLint's accessibility rules (labels, roles, key handlers)
  run with the rest of the lint.

# User Interface and Account

Status: implemented. Next.js 16 (App Router), React 19, Tailwind 3.4, TypeScript. The browser
talks only to the Next.js server, which proxies `/api` to the backend on the internal network.

## Pages

| Page | Purpose |
|---|---|
| Dashboard (`/`) | Balances, month and year figures, trends, spending by category, attention panel |
| Upload (`/upload`) | Upload a statement (with password if encrypted), status of each document |
| Transactions (`/transactions`) | Explorer with filters, sorting, paging, export, bulk edit and detail panel |
| Categories (`/categories`) | Categories, rules, Review queue, AI suggestions |
| Statement (`/documents/{id}`) | One statement: status, checks, issues, rows, source pages |
| System (`/system`) | Local AI status and hardware |
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

## Transactions

- Filters: bank, year, month, category, uncategorised, flagged, duplicates, free-text search.
  Sorting by date, amount, description, bank or category.
- Columns drop on narrow screens; the row opens a **detail panel** (full description,
  statement, page, validation status, category source and confidence, AI hunch).
- Changing a category is **ask first**: the page calls
  `PUT /transactions/{id}/category` with `preview: true`, which changes nothing and returns how
  many similar rows exist. A dialog then asks whether to change only this row or all similar
  rows (and learn a rule). Closing the dialog any other way (outside click, Escape) cancels:
  `ConfirmDialog` resolves `true`, `false` or `null`, and `null` means dismissed.
- Bulk category change for up to 500 selected rows; CSV export of the current filter.

## Categories page

- Transfers tab: possible transfers between your own accounts (same amount, different accounts,
  within 3 days). "Yes, my own accounts" files both halves as Transfers; "Not a transfer" is
  remembered. The dashboard links here (`?tab=transfers`). See `03-extraction.md`.
- Review tab: uncategorised groups, biggest first. An "AI hunch" button appears beside a group
  when the model had a low-confidence guess; one click applies it.
- AI suggestions tab: what the model applied, with **Accept confident** for those at or above
  the "confident" threshold. See `04-categorization.md`.

## Remembered choices

Stored in the browser only (`localStorage`, wrapped in try/catch so a blocked store just means
nothing is remembered): page size, sort, sort order, the dashboard bank and the dashboard tab. Settings has one
switch ("Remember my choices") which, when turned off, also clears the saved values. Nothing
here goes to the server.

## Styling

Dark sidebar theme. Tailwind's slate scale is remapped in `tailwind.config.ts` for contrast
(`slate-400` and `slate-500` were lightened for readable secondary text). Loading, empty and
error states share `components/states.tsx`; dialogs share `components/ConfirmDialog.tsx`.

## Known limits

- English only; no i18n.
- The detail panel shows data already loaded; it does not open the source PDF page unless the
  original is still stored (see `RETAIN_DOCUMENTS` in `02-upload-and-queue.md`).

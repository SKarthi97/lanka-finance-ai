const money = new Intl.NumberFormat("en-LK", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

// Privacy toggle: hides every amount (for screen sharing). Remembered in this browser only.
let amountsHidden = false;

export function areAmountsHidden(): boolean {
  return amountsHidden;
}

export function loadAmountsHidden(): boolean {
  try {
    amountsHidden = window.localStorage.getItem("hideAmounts") === "1";
  } catch {
    amountsHidden = false;
  }
  return amountsHidden;
}

export function setAmountsHidden(hidden: boolean) {
  amountsHidden = hidden;
  try {
    window.localStorage.setItem("hideAmounts", hidden ? "1" : "0");
  } catch {
    /* private window: the toggle still works for this visit */
  }
}

/** Display only. Amounts arrive as exact decimal strings and are never summed here. */
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "–";
  if (amountsHidden) return "••••••";
  return money.format(Number(value));
}

/** Month-over-month change as text, e.g. "up 12% on Oct". Display only. */
export function compareText(current: string, previous: string, label: string): string | null {
  const now = Number(current);
  const before = Number(previous);
  if (!before || !now) return null; // an empty side makes a percentage meaningless
  const change = ((now - before) / Math.abs(before)) * 100;
  if (Math.abs(change) < 0.5) return `same as ${label}`;
  if (Math.abs(change) > 500) return `${change > 0 ? "far higher" : "far lower"} than ${label}`;
  return `${change > 0 ? "up" : "down"} ${Math.abs(change).toFixed(0)}% on ${label}`;
}

// --- statuses -----------------------------------------------------------------

export const STATUS_STYLE: Record<string, string> = {
  queued: "bg-slate-100 text-slate-700",
  processing: "bg-blue-100 text-blue-800",
  inspected: "bg-blue-100 text-blue-800",
  reconciled: "bg-green-100 text-green-800",
  accepted: "bg-green-100 text-green-800",
  needs_review: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800",
};

export const STATUS_LABEL: Record<string, string> = {
  queued: "queued",
  processing: "processing",
  inspected: "processing",
  reconciled: "reconciled",
  accepted: "accepted",
  needs_review: "needs review",
  failed: "failed",
};

/** Statuses that will still change by themselves, so the page keeps polling. */
export const ACTIVE_STATUSES = new Set(["queued", "processing", "inspected"]);

// --- validation / error codes -> plain language --------------------------------

export const ISSUE_LABEL: Record<string, string> = {
  statement_not_reconciled:
    "Opening balance plus credits minus debits does not equal the closing balance.",
  row_balance_mismatch: "A row's amount does not match the change in the running balance.",
  row_amounts_invalid: "A row has both, or neither of, a debit and a credit.",
  date_outside_period: "A row is dated outside the statement period.",
  suspicious_date_gap:
    "Two consecutive rows are almost a year apart, so a row may be out of order or mis-dated.",
  opening_balance_missing: "The opening balance (BALANCE B/F) was not found.",
  closing_balance_missing: "The closing balance (BALANCE C/F) was not found.",
  opening_balance_unidentified: "The opening balance line could not be read.",
  opening_balance_unavailable: "A row could not be checked because there is no opening balance.",
  unexpected_amount_columns: "A row did not have the expected amount columns and was skipped.",
  carry_forward_mismatch:
    "A page's carried-forward balance does not match the last row of the previous page (a row may be missing).",
  opening_balance_ambiguous:
    "The opening balance line had several amounts; the last (balance column) was used.",
  negative_amount: "A row had a negative amount and was skipped.",
  invalid_date: "A row had an invalid date and was skipped.",
  balance_mismatch: "A row's amount differs from the change in running balance.",
  no_balance_movement: "A row did not change the running balance.",
  opening_balance_gap: "The opening balance differs from the previous statement's closing balance.",
  period_overlap: "This statement overlaps the previous one for the same account.",
  period_gap: "There is a gap between this statement and the previous one.",
};

export const CHECK_LABEL: Record<string, string> = {
  row_amounts: "One of debit / credit per row",
  row_balance: "Running balance per row",
  date_in_period: "Dates inside the statement period",
  statement_reconciliation: "Opening + credits − debits = closing",
  date_sequence: "No near-year jump between consecutive dates",
  rows_parsed: "All rows could be read",
};

export const ERROR_LABEL: Record<string, string> = {
  unsupported_layout: "The layout was not recognised as a supported bank statement.",
  format_mismatch: "This PDF does not match the selected bank's statement format.",
  statement_date_not_found: "The statement date was not found.",
  statement_date_invalid: "The statement date could not be read.",
  no_text_layer: "The PDF has no selectable text (a scan). OCR is not available yet.",
  file_missing: "The stored file is missing.",
  file_encrypted: "The stored file is still encrypted.",
  document_missing: "The document record is missing.",
};

/** "PermanentJobError: unsupported_layout" -> a readable sentence. */
export function explainError(error: string | null | undefined): string | null {
  if (!error) return null;
  const code = error.includes(": ") ? error.split(": ").pop()! : error;
  return ERROR_LABEL[code] ?? `Processing failed (${code}).`;
}

export const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]; // fmt: skip

export const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
]; // fmt: skip

export const NO_ACCOUNT_HINT =
  "No account number was detected on these statements, so they are grouped by bank. " +
  "Two accounts at the same bank would share this row.";

export const KIND_LABEL: Record<string, string> = {
  income: "Income",
  expense: "Expense",
  transfer: "Transfer",
};

export const SOURCE_LABEL: Record<string, string> = {
  rule: "Built-in rule",
  user_rule: "Your rule",
  manual: "Set by you",
  llm: "AI suggestion",
};

export const ORIGIN_LABEL: Record<string, string> = {
  system: "Built in",
  user: "Yours",
  correction: "Learned",
};

export const WINDOW_LABEL = (
  window: { covers: string; rows: number | null; from_page: number | null },
  totalRows: number,
): string => {
  if (window.covers === "all") return `The statement's totals match all ${window.rows} rows.`;
  if (window.covers === "last_rows")
    return `The statement's totals match only the last ${window.rows} of ${totalRows} rows (from page ${window.from_page}), so they appear to cover a recent period, not the whole statement.`;
  return "The statement's totals do not match any combination of rows, so they may cover something else.";
};

/** Zero debit/credit cells render empty so the active column stands out. */
export function formatAmount(value: string): string {
  return Number(value) === 0 ? "" : formatMoney(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "–";
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** "45 s", "2 min 5 s", "1 h 3 min". */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 ? `${m} min ${s % 60} s` : `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/** "850 ms", "4.2 s", "2 min 5 s" for a duration in milliseconds. */
export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return formatDuration(ms / 1000);
}

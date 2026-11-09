export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public detail?: Record<string, unknown>,
  ) {
    super(message);
  }
}

// CSRF token for the current session; sent on every state-changing request.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

type Options = Omit<RequestInit, "body"> & { json?: unknown; form?: FormData };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { json, form, ...init } = options;
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);

  let body: string | FormData | undefined;
  if (form !== undefined) {
    // Let the browser set the multipart boundary; never set Content-Type here.
    body = form;
  } else if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  }
  if (method !== "GET" && method !== "HEAD" && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  const response = await fetch(`/api${path}`, {
    ...init,
    method,
    headers,
    body,
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    let message = response.statusText;
    let code: string | undefined;
    let extra: Record<string, unknown> | undefined;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail && typeof data.detail === "object") {
        // Structured errors: { code, message, ...extra }
        message = String(data.detail.message ?? message);
        code = data.detail.code;
        extra = data.detail;
      }
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, message, code, extra);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export type Me = { username: string; csrf_token: string };
export type AuthStatus = { setup_required: boolean; authenticated: boolean };

export type OllamaStatus = {
  reachable: boolean;
  model: string;
  model_present: boolean;
  digest: string | null;
  installed_models: string[];
  warmup_ok: boolean | null;
  warmup_ms: number | null;
  error: string | null;
};

export type HardwareReport = {
  cpu_threads: number | null;
  cpu_cores: number | null;
  ram_total_gb: number;
  ram_available_gb: number;
  disk_total_gb: number;
  disk_free_gb: number;
  gpu: { present: boolean; name: string | null };
  recommended_model_size: string;
};

export type DocumentItem = {
  id: number;
  original_filename: string;
  sha256: string;
  size_bytes: number;
  page_count: number | null;
  is_encrypted: boolean;
  status: string;
  error: string | null;
  bank_code: string | null;
  file_available: boolean;
  created_at: string;
};

export type Issue = { code: string; page: number | null; seq: number | null };

export type DeclaredComparison = {
  declared_count: number | null;
  found_count: number;
  count_match: boolean | null;
  declared_total: string | null;
  found_total: string;
  total_match: boolean | null;
};

export type DocumentDetail = DocumentItem & {
  pages: { page_no: number; kind: string; char_count: number }[];
  account_last4: string | null;
  period_start: string | null;
  period_end: string | null;
  opening_balance: string | null;
  closing_balance: string | null;
  adapter: string | null;
  adapter_version: string | null;
  extraction_confidence: number | null;
  validation: {
    reconciled: boolean;
    checks: Record<string, { passed: number; failed: number }>;
    issues: Issue[];
    declared?: Record<string, DeclaredComparison>;
    declared_window?: {
      covers: "all" | "last_rows" | "unknown";
      rows: number | null;
      from_page: number | null;
    } | null;
  } | null;
  transaction_count: number;
  duplicate_count: number;
};

// Money is sent as exact decimal strings; never do arithmetic on it in the browser.
export type TransactionItem = {
  id: number;
  document_id: number;
  seq: number;
  transaction_date: string;
  description: string;
  merchant: string;
  merchant_source: "manual" | "llm" | "rule";
  debit: string;
  credit: string;
  running_balance: string;
  source_page: number;
  validation_status: string;
  bank_code: string | null;
  bank_name: string | null;
  account_last4: string | null;
  is_duplicate: boolean;
  duplicate_of_id: number | null;
  category_id: number | null;
  category_name: string | null;
  category_kind: string | null;
  classification_source: string | null;
  classification_confidence: number | null;
  classification_explanation: string | null;
};

export type TransactionList = { total: number; money_in: string; money_out: string; items: TransactionItem[] };

export type Bank = { code: string; name: string };

export type Totals = {
  income: string;
  expense: string;
  net: string;
  transfers_in: string;
  transfers_out: string;
  transactions: number;
  uncategorised: number;
};

export type CategoryTotal = {
  category_id: number | null;
  name: string;
  kind: string | null;
  income: string;
  expense: string;
  transactions: number;
};

export type TopExpense = {
  id: number;
  transaction_date: string;
  description: string;
  amount: string;
  category_name: string | null;
  bank_code: string | null;
};

export type TrendMonth = {
  year: number;
  month: number;
  income: string;
  expense: string;
  net: string;
  balance: string | null;
};

export type Trend = { months: TrendMonth[] };

export type BankTotal = {
  bank_code: string | null;
  bank_name: string | null;
  income: string;
  expense: string;
  net: string;
  transactions: number;
};

export type AccountBalance = {
  bank_code: string | null;
  bank_name: string | null;
  account_last4: string | null;
  balance: string;
  as_of: string;
  history: { year: number; month: number; balance: string }[];
  change: string | null;
  change_year: number | null;
  change_month: number | null;
};

export type Dashboard = {
  balances: AccountBalance[];
  total_balance: string;
  as_of: string | null;
  month: Totals;
  previous_month: Totals;
  top_expenses: TopExpense[];
  uncategorised_total: number;
  ai_unsure: number;
  banks: Bank[];
  year: Totals;
  month_by_category: CategoryTotal[];
  year_by_category: CategoryTotal[];
  month_by_bank: BankTotal[];
  year_by_bank: BankTotal[];
  coverage: { gap_months: number; balance_breaks: number };
  transfer_suggestions: number;
  needs_review: number;
  has_data: boolean;
  years: number[];
};

export type Tracker = {
  year: number;
  years: number[];
  rows: {
    bank_code: string | null;
    bank_name: string | null;
    account_last4: string | null;
    cells: Record<string, { status: "ok" | "review"; document_id: number }>;
    gap_months: number[];
    gap_total: number;
    breaks: {
      from_document_id: number;
      to_document_id: number;
      on: string;
      expected: string;
      found: string;
    }[];
  }[];
};

export type TransferSide = {
  id: number;
  transaction_date: string;
  description: string;
  bank_code: string | null;
  account_last4: string | null;
};

export type TransferPair = {
  out: TransferSide;
  into: TransferSide;
  amount: string;
  days_apart: number;
  ambiguous: boolean;
};

export type TransferSuggestions = { total: number; window_days: number; items: TransferPair[] };

// --- categories ---------------------------------------------------------------------------

export type CategoryItem = {
  id: number;
  name: string;
  kind: "income" | "expense" | "transfer";
  is_system: boolean;
  transactions: number;
};

export type RuleItem = {
  id: number;
  pattern: string;
  pattern_type: "contains" | "word";
  category_id: number;
  category_name: string;
  origin: "system" | "user" | "correction";
  priority: number;
  enabled: boolean;
  hit_count: number;
};

export type ReviewQueue = {
  total: number;
  groups: {
    stem: string;
    count: number;
    example: string;
    hint_category_id: number | null; // a low-confidence AI guess, never applied on its own
    hint_category_name: string | null;
    hint_confidence: number | null;
    hint_reason: string | null; // e.g. "Similar to 3 descriptions you categorised"
  }[];
};

export type CorrectionResult = {
  transaction_id: number;
  category_id: number | null;
  category_name: string | null;
  stem: string;
  similar_count: number;
  rule_id: number | null;
  changed: number;
};

export type AiProgress = {
  running: boolean;
  queued: boolean;
  elapsed_s: number | null;
  eta_s: number | null;
  waiting: number;
  avg_call_s: number | null;
};

export type CategorizationStatus = {
  ai_enabled: boolean;
  ai_pending: boolean;
  uncategorised: number;
  progress: AiProgress;
};

export type NamingStatus = { ai_enabled: boolean; unnamed: number; progress: AiProgress };

export type AiActivity = {
  window_days: number;
  summary: { purpose: string; runs: number; ok_runs: number; avg_ms: number; max_ms: number; total_ms: number }[];
  recent: { at: string; purpose: string; model: string; duration_ms: number; ok: boolean }[];
};

export type SuggestionGroup = {
  stem: string;
  category_id: number;
  category_name: string;
  count: number;
  example: string;
  confidence: number;
};

export type Suggestions = { total: number; confident_threshold: number; groups: SuggestionGroup[] };

export type Notice = { key: string; kind: string; severity: "warn" | "info"; text: string; href: string };
export type Notifications = { count: number; items: Notice[] };

// --- budgets, recurring, saved views -------------------------------------------------------

export type BudgetLine = {
  category_id: number;
  category_name: string;
  limit: string;
  spent: string;
  remaining: string;
  percent: number;
  state: "under" | "near" | "over";
};

export type Budgets = {
  year: number;
  month: number;
  items: BudgetLine[];
  total_limit: string;
  total_spent: string;
  over: number;
};

export type RecurringItem = {
  stem: string;
  name: string;
  direction: "expense" | "income";
  cadence: string;
  count: number;
  typical_amount: string;
  last_date: string;
  next_expected: string;
  state: "upcoming" | "due" | "overdue" | "ended";
  category_name: string | null;
  monthly_equivalent: string;
};

export type RecurringList = { items: RecurringItem[]; monthly_expense: string; monthly_income: string };

export type ViewFilters = {
  q?: string | null;
  bank_code?: string | null;
  category_id?: number | null;
  uncategorised?: boolean;
  year?: number | null;
  month?: number | null;
  flagged?: boolean;
  duplicates?: "hide" | "show" | "only";
  min_amount?: string | null;
  max_amount?: string | null;
  direction?: "in" | "out" | null;
};

export type SearchReading = {
  filters: ViewFilters;
  summary: string[];
  used_ai: boolean;
  ai_error: string | null;
  took_ms: number;
  model_ms: number | null;
};

export type SavedViewItem = { id: number; name: string; filters: ViewFilters };

// --- summary, flags, similarity ----------------------------------------------------------------

export type MonthSummary = {
  label: string;
  bullets: string[];
  narrative: string | null;
  used_ai: boolean;
  ai_note: string | null;
  took_ms: number;
  model_ms: number | null;
};

export type TxFlag = { code: string; title: string };

export type FlagExplanation = {
  flags: TxFlag[];
  explanation: string | null;
  check: string | null;
  used_ai: boolean;
  ai_note: string | null;
  took_ms: number;
  model_ms: number | null;
};

export type Similarity = { enabled: boolean; model: string; labelled: number; needed: number; embedded: number };

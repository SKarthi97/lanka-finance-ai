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
  } | null;
  transaction_count: number;
};

// Money is sent as exact decimal strings; never do arithmetic on it in the browser.
export type TransactionItem = {
  id: number;
  document_id: number;
  seq: number;
  transaction_date: string;
  description: string;
  debit: string;
  credit: string;
  running_balance: string;
  source_page: number;
  validation_status: string;
  bank_code: string | null;
  bank_name: string | null;
  account_last4: string | null;
};

export type TransactionList = { total: number; items: TransactionItem[] };

export type Bank = { code: string; name: string };

export type Totals = { income: string; expense: string; net: string; transactions: number };

export type Dashboard = {
  balances: {
    bank_code: string | null;
    bank_name: string | null;
    account_last4: string | null;
    balance: string;
    as_of: string;
  }[];
  total_balance: string;
  as_of: string | null;
  month: Totals;
  year: Totals;
  needs_review: number;
  has_data: boolean;
};

export type Tracker = {
  year: number;
  years: number[];
  rows: {
    bank_code: string | null;
    bank_name: string | null;
    account_last4: string | null;
    cells: Record<string, { status: "ok" | "review"; document_id: number }>;
  }[];
};

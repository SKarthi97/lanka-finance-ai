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
  status: "queued" | "processing" | "inspected" | "failed" | string;
  error: string | null;
  bank_code: string | null;
  created_at: string;
};

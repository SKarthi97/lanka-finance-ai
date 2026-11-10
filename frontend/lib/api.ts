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

export * from "./types";

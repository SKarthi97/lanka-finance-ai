"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, AuthStatus, Me, setCsrfToken } from "@/lib/api";

const MIN_PASSWORD_LENGTH = 12;

export default function LoginPage() {
  const router = useRouter();
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<AuthStatus>("/auth/status")
      .then((status) => {
        if (status.authenticated) router.replace("/");
        else setSetupRequired(status.setup_required);
      })
      .catch(() => setError("Cannot reach the server. Is the backend running?"));
  }, [router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const me = await api<Me>(setupRequired ? "/auth/setup" : "/auth/login", {
        method: "POST",
        json: { username, password },
      });
      setCsrfToken(me.csrf_token);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-4">
      <h1 className="text-2xl font-semibold">Lanka Finance AI</h1>
      <p className="mt-1 text-sm text-slate-600">
        {setupRequired === null
          ? "Loading…"
          : setupRequired
            ? "First run: create your account."
            : "Sign in to continue."}
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <label className="block text-sm">
          Username
          <input
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            maxLength={64}
          />
        </label>

        <label className="block text-sm">
          Password
          <input
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={setupRequired ? "new-password" : "current-password"}
            required
            minLength={setupRequired ? MIN_PASSWORD_LENGTH : undefined}
          />
          {setupRequired && (
            <span className="mt-1 block text-xs text-slate-500">
              At least {MIN_PASSWORD_LENGTH} characters.
            </span>
          )}
        </label>

        {error && (
          <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || setupRequired === null}
          className="w-full rounded bg-slate-900 px-3 py-2 text-white disabled:opacity-50"
        >
          {setupRequired ? "Create account" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

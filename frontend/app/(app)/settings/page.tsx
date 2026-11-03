"use client";

import { useEffect, useState } from "react";
import { api, ApiError, Me, OllamaStatus } from "@/lib/api";

const input = "w-full rounded border border-slate-300 px-3 py-2 text-sm";

export default function SettingsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [ollama, setOllama] = useState<OllamaStatus | null>(null);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [rememberChoices, setRememberChoices] = useState(true);

  useEffect(() => {
    api<Me>("/auth/me").then(setMe).catch(() => undefined);
    api<OllamaStatus>("/system/ollama").then(setOllama).catch(() => undefined);
    try {
      setRememberChoices(window.localStorage.getItem("rememberChoices") !== "0");
    } catch {
      /* storage blocked */
    }
  }, []);

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    setMessage(null);
    if (next !== again) {
      setMessage({ ok: false, text: "The new passwords do not match." });
      return;
    }
    setBusy(true);
    try {
      await api("/auth/change-password", {
        method: "POST",
        json: { current_password: current, new_password: next },
      });
      setCurrent("");
      setNext("");
      setAgain("");
      setMessage({ ok: true, text: "Password changed. Other signed-in sessions were ended." });
    } catch (err) {
      setMessage({ ok: false, text: err instanceof ApiError ? err.message : "Could not change the password." });
    } finally {
      setBusy(false);
    }
  }

  function toggleRemember(value: boolean) {
    setRememberChoices(value);
    try {
      window.localStorage.setItem("rememberChoices", value ? "1" : "0");
      if (!value) {
        for (const key of ["txPageSize", "txSort", "txOrder", "dashBank"]) window.localStorage.removeItem(key);
      }
    } catch {
      /* storage blocked */
    }
  }

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      <div className="rounded border border-slate-200 bg-surface p-5">
        <h2 className="mb-1 font-medium">Account</h2>
        <p className="text-sm text-slate-600">Signed in as {me?.username ?? "…"}.</p>
      </div>

      <form onSubmit={changePassword} className="max-w-md space-y-3 rounded border border-slate-200 bg-surface p-5">
        <h2 className="font-medium">Change password</h2>
        <label className="block text-sm">
          Current password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={`${input} mt-1`}
          />
        </label>
        <label className="block text-sm">
          New password
          <input
            type="password"
            autoComplete="new-password"
            required
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className={`${input} mt-1`}
          />
        </label>
        <label className="block text-sm">
          Repeat the new password
          <input
            type="password"
            autoComplete="new-password"
            required
            value={again}
            onChange={(e) => setAgain(e.target.value)}
            className={`${input} mt-1`}
          />
        </label>
        {message && (
          <p
            role={message.ok ? "status" : "alert"}
            className={`rounded px-3 py-2 text-sm ${message.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700"}`}
          >
            {message.text}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !current || !next || !again}
          className="rounded bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
        >
          {busy ? "Saving…" : "Change password"}
        </button>
        <p className="text-xs text-slate-500">
          Changing the password signs out every other browser or device.
        </p>
      </form>

      <div className="max-w-md rounded border border-slate-200 bg-surface p-5">
        <h2 className="mb-2 font-medium">This browser</h2>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={rememberChoices}
            onChange={(e) => toggleRemember(e.target.checked)}
            className="mt-1"
          />
          <span>
            Remember my choices (rows per page, sort order, bank filter)
            <span className="block text-xs text-slate-500">
              Stored only in this browser. Turning it off clears what was saved.
            </span>
          </span>
        </label>
      </div>

      <div className="max-w-md rounded border border-slate-200 bg-surface p-5 text-sm">
        <h2 className="mb-2 font-medium">Local AI</h2>
        {ollama === null ? (
          <p className="text-slate-500">Status unavailable.</p>
        ) : (
          <p className="text-slate-600">
            {ollama.reachable && ollama.model_present
              ? `Ready: model ${ollama.model} runs on this computer. Only short description stems are ever sent to it.`
              : `Unavailable (${ollama.error ?? "model not installed"}). Rules keep working without it.`}
          </p>
        )}
        <p className="mt-2 text-xs text-slate-500">More detail is on the System page.</p>
      </div>
    </section>
  );
}

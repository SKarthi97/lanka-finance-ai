"use client";

import { FormEvent, useState } from "react";
import { AiBusy } from "@/components/AiBusy";
import { api, ApiError, SearchReading, ViewFilters } from "@/lib/api";
import { formatMs } from "@/lib/format";

/** Type a question in plain words; it becomes ordinary filters you can see, change and save. */
export function AskFilters({ onApply }: { onApply: (filters: ViewFilters) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState<SearchReading | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask(event: FormEvent) {
    event.preventDefault();
    const query = text.trim();
    if (!query) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<SearchReading>("/search/interpret", { method: "POST", json: { query } });
      setReading(result);
      if (result.summary.length > 0) onApply(result.filters);
    } catch (err) {
      setReading(null);
      setError(err instanceof ApiError ? err.message : "Could not read that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-1">
      <form onSubmit={ask} role="search" aria-label="Ask in plain words" className="flex flex-wrap items-center gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={200}
          placeholder="Ask in plain words: fuel over 5k last month, or money received from Sampath in March"
          aria-label="Ask in plain words"
          className="min-w-[16rem] flex-1 rounded border border-slate-300 bg-surface px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          className="rounded bg-accent px-3 py-2 text-sm text-accent-fg disabled:opacity-50"
        >
          {busy ? "Reading…" : "Apply"}
        </button>
      </form>

      {busy && <AiBusy compact showAfterMs={400} label="Reading your question with the local AI" />}

      {error && (
        <p role="alert" className="text-xs text-red-700">
          {error}
        </p>
      )}
      {reading && !busy && (
        <p role="status" className="text-xs text-slate-600">
          {reading.summary.length > 0 ? (
            <>
              Showing: <span className="font-medium">{reading.summary.join(" · ")}</span>
              {reading.used_ai && reading.model_ms !== null
                ? ` · the local AI took ${formatMs(reading.model_ms)}`
                : reading.used_ai
                  ? " · read with the local AI"
                  : ` · read in ${formatMs(reading.took_ms)}`}
              . Change any filter below.
            </>
          ) : (
            <>Nothing to filter on in that. Try a month, an amount, a bank or a category name.</>
          )}
          {reading.ai_error && <span className="ml-1 text-amber-700">{reading.ai_error}</span>}
        </p>
      )}
    </div>
  );
}

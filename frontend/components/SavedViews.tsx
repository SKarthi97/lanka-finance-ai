"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError, SavedViewItem, ViewFilters } from "@/lib/api";

const select = "rounded border border-slate-300 px-2 py-2 text-sm bg-surface";
const button = "rounded border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100 disabled:opacity-50";

/** Named sets of Transactions filters. A view holds filter values only, never rows. */
export function SavedViews({
  current,
  hasFilters,
  onApply,
}: {
  current: ViewFilters;
  hasFilters: boolean;
  onApply: (filters: ViewFilters) => void;
}) {
  const [views, setViews] = useState<SavedViewItem[]>([]);
  const [chosen, setChosen] = useState("");
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    api<SavedViewItem[]>("/views")
      .then(setViews)
      .catch(() => undefined);
  }, []);

  useEffect(load, [load]);

  function choose(id: string) {
    setChosen(id);
    setMessage(null);
    const view = views.find((v) => String(v.id) === id);
    if (view) onApply(view.filters);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const saved = await api<SavedViewItem>("/views", { method: "POST", json: { name: trimmed, filters: current } });
      setNaming(false);
      setName("");
      setMessage(`Saved “${saved.name}”.`);
      load();
      setChosen(String(saved.id));
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not save the view.");
    }
  }

  async function remove() {
    const view = views.find((v) => String(v.id) === chosen);
    if (!view) return;
    try {
      await api(`/views/${view.id}`, { method: "DELETE" });
      setChosen("");
      setMessage(`Deleted “${view.name}”.`);
      load();
    } catch {
      setMessage("Could not delete the view.");
    }
  }

  if (views.length === 0 && !hasFilters && !naming) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {views.length > 0 && (
        <select aria-label="Saved views" value={chosen} onChange={(e) => choose(e.target.value)} className={select}>
          <option value="">Saved views…</option>
          {views.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </select>
      )}
      {chosen && (
        <button type="button" onClick={remove} className={button}>
          Delete view
        </button>
      )}
      {naming ? (
        <form onSubmit={save} className="flex items-center gap-2">
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={64}
            placeholder="Name this view"
            aria-label="View name"
            className="w-48 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <button type="submit" disabled={!name.trim()} className="rounded bg-accent px-3 py-2 text-accent-fg disabled:opacity-50">
            Save
          </button>
          <button type="button" onClick={() => setNaming(false)} className={button}>
            Cancel
          </button>
        </form>
      ) : (
        <button type="button" onClick={() => setNaming(true)} disabled={!hasFilters} className={button}
          title={hasFilters ? "Keep the current filters under a name" : "Choose some filters first"}>
          Save these filters
        </button>
      )}
      {message && (
        <span role="status" className="text-xs text-slate-500">
          {message}
        </span>
      )}
    </div>
  );
}

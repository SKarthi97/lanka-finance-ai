"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { LoadError, RowsSkeleton } from "@/components/states";
import { api, ApiError, Budgets, CategoryItem } from "@/lib/api";
import { MONTHS_LONG, formatMoney, loadAmountsHidden } from "@/lib/format";

const select = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";
const input = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";
const primary = "rounded bg-accent px-3 py-1.5 text-sm text-accent-fg disabled:opacity-50";
const subtle = "rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100";

const BAR: Record<string, string> = { under: "bg-accent", near: "bg-amber-400", over: "bg-red-500" };
const WORD: Record<string, string> = { under: "On track", near: "Nearly used", over: "Over budget" };

export default function BudgetsPage() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [data, setData] = useState<Budgets | null>(null);
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [newCategory, setNewCategory] = useState("");
  const [newAmount, setNewAmount] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [editAmount, setEditAmount] = useState("");
  const [, setTick] = useState(0);

  useEffect(() => {
    loadAmountsHidden();
    setTick((n) => n + 1);
  }, []);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [b, c] = await Promise.all([
        api<Budgets>(`/budgets?year=${year}&month=${month}`),
        api<CategoryItem[]>("/categories"),
      ]);
      setData(b);
      setCategories(c);
    } catch {
      setError("Could not load budgets.");
    }
  }, [year, month]);

  useEffect(() => {
    load();
  }, [load]);

  async function save(categoryId: number, amount: string) {
    setMessage(null);
    try {
      await api(`/budgets/${categoryId}`, { method: "PUT", json: { amount } });
      setEditing(null);
      setNewCategory("");
      setNewAmount("");
      await load();
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof ApiError ? err.message : "Could not save the budget. Enter an amount above zero.",
      });
    }
  }

  async function remove(categoryId: number) {
    setMessage(null);
    try {
      await api(`/budgets/${categoryId}`, { method: "DELETE" });
      await load();
    } catch {
      setMessage({ kind: "error", text: "Could not remove the budget." });
    }
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (newCategory && newAmount) save(Number(newCategory), newAmount);
  }

  function step(by: number) {
    const moved = new Date(year, month - 1 + by, 1);
    setYear(moved.getFullYear());
    setMonth(moved.getMonth() + 1);
  }

  const budgeted = new Set((data?.items ?? []).map((b) => b.category_id));
  const available = categories.filter((c) => c.kind === "expense" && !budgeted.has(c.id));
  const years = Array.from(new Set([now.getFullYear() - 2, now.getFullYear() - 1, now.getFullYear(), year])).sort();

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Budgets</h1>
        <div className="flex items-center gap-2 text-sm">
          <div className="flex items-center overflow-hidden rounded border border-slate-300">
            <button type="button" onClick={() => step(-1)} aria-label="Previous month" className="px-2.5 py-1.5 hover:bg-slate-100">
              ‹
            </button>
            <span className="border-l border-slate-300 px-3 py-1.5 tabular-nums">
              {MONTHS_LONG[month - 1]} {year}
            </span>
            <button type="button" onClick={() => step(1)} aria-label="Next month" className="border-l border-slate-300 px-2.5 py-1.5 hover:bg-slate-100">
              ›
            </button>
          </div>
          <select aria-label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))} className={select}>
            {years.map((y) => (
              <option key={y}>{y}</option>
            ))}
          </select>
          <select aria-label="Month" value={month} onChange={(e) => setMonth(Number(e.target.value))} className={select}>
            {MONTHS_LONG.map((name, i) => (
              <option key={name} value={i + 1}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className="text-sm text-slate-600">
        A budget is a monthly limit for one expense category. What counts as spent is that category’s
        debits minus its credits (a refund reduces it) in the month, from reconciled or accepted
        statements. Transfers are never counted.
      </p>

      {message && (
        <p
          role={message.kind === "error" ? "alert" : "status"}
          className={`rounded px-3 py-2 text-sm ${message.kind === "error" ? "bg-red-50 text-red-700" : "bg-green-50 text-green-800"}`}
        >
          {message.text}
        </p>
      )}

      {error && <LoadError message={error} onRetry={load} />}
      {!error && !data && <RowsSkeleton />}

      {data && (
        <>
          {data.items.length > 0 && (
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 text-sm shadow-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  {MONTHS_LONG[month - 1]} {year}, all budgets
                </span>
                {data.over > 0 && (
                  <span className="rounded bg-red-50 px-2 py-0.5 text-xs text-red-700">
                    {data.over} categor{data.over === 1 ? "y" : "ies"} over
                  </span>
                )}
              </div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">
                {formatMoney(data.total_spent)}{" "}
                <span className="text-base font-normal text-slate-500">of {formatMoney(data.total_limit)} budgeted</span>
              </div>
              <div className="mt-2 h-2 rounded bg-slate-100" aria-hidden="true">
                <div
                  className={`h-2 rounded ${Number(data.total_spent) > Number(data.total_limit) ? "bg-red-500" : "bg-accent"}`}
                  style={{
                    width: `${Math.min(100, Number(data.total_limit) > 0 ? (Number(data.total_spent) / Number(data.total_limit)) * 100 : 0)}%`,
                  }}
                />
              </div>
            </div>
          )}

          {data.items.length === 0 ? (
            <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
              No budgets yet. Add one below, for example a monthly limit for Groceries.
            </p>
          ) : (
            <ul className="space-y-3">
              {data.items.map((b) => {
                const over = b.state === "over";
                return (
                  <li
                    key={b.category_id}
                    className={`rounded border border-l-2 border-slate-200 bg-surface p-4 ${
                      over ? "border-l-red-500" : b.state === "near" ? "border-l-amber-400" : "border-l-green-700"
                    }`}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-medium">{b.category_name}</span>
                      <span className={`text-sm tabular-nums ${over ? "text-red-700" : "text-slate-600"}`}>
                        {formatMoney(b.spent)} of {formatMoney(b.limit)} · {b.percent}%
                      </span>
                    </div>
                    <div
                      role="progressbar"
                      aria-label={`${b.category_name}: ${b.percent}% of the budget used`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.min(b.percent, 100)}
                      className="mt-2 h-2 rounded bg-slate-100"
                    >
                      <div className={`h-2 rounded ${BAR[b.state]}`} style={{ width: `${Math.min(b.percent, 100)}%` }} />
                    </div>
                    <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs">
                      <span className={over ? "text-red-700" : b.state === "near" ? "text-amber-700" : "text-slate-500"}>
                        {WORD[b.state]} ·{" "}
                        {over ? `${formatMoney(String(-Number(b.remaining)))} over` : `${formatMoney(b.remaining)} left`}
                      </span>
                      {editing === b.category_id ? (
                        <span className="flex items-center gap-2">
                          <input
                            aria-label={`New limit for ${b.category_name}`}
                            inputMode="decimal"
                            value={editAmount}
                            onChange={(e) => setEditAmount(e.target.value)}
                            className={`${input} w-28`}
                          />
                          <button className={primary} onClick={() => save(b.category_id, editAmount)}>
                            Save
                          </button>
                          <button className={subtle} onClick={() => setEditing(null)}>
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <span className="flex gap-3">
                          <button
                            className="text-accent underline"
                            onClick={() => {
                              setEditing(b.category_id);
                              setEditAmount(b.limit);
                            }}
                          >
                            Change limit
                          </button>
                          <button className="text-accent underline" onClick={() => remove(b.category_id)}>
                            Remove
                          </button>
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <form onSubmit={add} className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-surface p-4">
            <label className="text-sm">
              <span className="mb-1 block text-slate-600">Category</span>
              <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)} className={select} required>
                <option value="">Choose…</option>
                {available.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="mb-1 block text-slate-600">Monthly limit (LKR)</span>
              <input
                inputMode="decimal"
                value={newAmount}
                onChange={(e) => setNewAmount(e.target.value)}
                placeholder="25000"
                className={`${input} w-36`}
                required
              />
            </label>
            <button type="submit" className={primary} disabled={!newCategory || !newAmount}>
              Add budget
            </button>
          </form>
        </>
      )}
    </section>
  );
}

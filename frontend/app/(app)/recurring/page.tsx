"use client";

import { useEffect, useState } from "react";
import { LoadError, RowsSkeleton } from "@/components/states";
import { api, RecurringItem, RecurringList } from "@/lib/api";
import { formatDate, formatMoney, loadAmountsHidden } from "@/lib/format";

const STATE: Record<string, { label: string; cls: string }> = {
  overdue: { label: "Overdue", cls: "bg-red-100 text-red-800" },
  due: { label: "Due now", cls: "bg-amber-100 text-amber-800" },
  upcoming: { label: "Upcoming", cls: "bg-slate-100 text-slate-700" },
  ended: { label: "Seems to have stopped", cls: "bg-slate-100 text-slate-500" },
};

function Table({ title, items }: { title: string; items: RecurringItem[] }) {
  if (items.length === 0) return null;
  return (
    <section>
      <h2 className="mb-2 font-medium">{title}</h2>
      <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">What</th>
              <th className="px-3 py-2 font-medium">How often</th>
              <th className="px-3 py-2 text-right font-medium">Usual amount</th>
              <th className="px-3 py-2 font-medium">Last</th>
              <th className="px-3 py-2 font-medium">Next expected</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => {
              const state = STATE[r.state];
              return (
                <tr key={`${r.direction}-${r.stem}`} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-2">
                    <div className="break-words">{r.name}</div>
                    <div className="text-xs text-slate-500">
                      {r.category_name ?? <span className="text-amber-700">uncategorised</span>} · seen {r.count} times
                    </div>
                  </td>
                  <td className="px-3 py-2 capitalize">{r.cadence}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatMoney(r.typical_amount)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{formatDate(r.last_date)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.state === "ended" ? "–" : formatDate(r.next_expected)}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${state.cls}`}>{state.label}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function RecurringPage() {
  const [data, setData] = useState<RecurringList | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    loadAmountsHidden();
    setFailed(false);
    api<RecurringList>("/recurring")
      .then(setData)
      .catch(() => setFailed(true));
  }, [attempt]);

  return (
    <section className="space-y-5">
      <h1 className="text-xl font-semibold">Recurring payments</h1>
      <p className="text-sm text-slate-600">
        Found by looking for the same description repeating on a regular schedule (weekly to yearly)
        with similar amounts, in reconciled or accepted statements. Bills whose amount swings by more
        than 20% (such as electricity) are not detected, and transfers between your own accounts are
        ignored.
      </p>

      {failed && <LoadError message="Could not load recurring payments." onRetry={() => setAttempt((n) => n + 1)} />}
      {!failed && !data && <RowsSkeleton />}

      {data && data.items.length === 0 && (
        <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
          Nothing recurring found yet. It needs at least three monthly (or four weekly) repeats, so more
          statements help.
        </p>
      )}

      {data && data.items.length > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded border border-slate-200 bg-surface p-4">
              <div className="text-xs text-slate-500">Recurring payments, per month</div>
              <div className="mt-1 text-xl font-semibold tabular-nums text-red-700">{formatMoney(data.monthly_expense)}</div>
              <div className="mt-1 text-xs text-slate-500">Average, excluding ones that seem to have stopped</div>
            </div>
            <div className="rounded border border-slate-200 bg-surface p-4">
              <div className="text-xs text-slate-500">Recurring income, per month</div>
              <div className="mt-1 text-xl font-semibold tabular-nums text-green-700">{formatMoney(data.monthly_income)}</div>
              <div className="mt-1 text-xs text-slate-500">Average, excluding ones that seem to have stopped</div>
            </div>
          </div>
          <Table title="Payments" items={data.items.filter((r) => r.direction === "expense")} />
          <Table title="Income" items={data.items.filter((r) => r.direction === "income")} />
        </>
      )}
    </section>
  );
}

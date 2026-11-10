"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LoadError, RowsSkeleton } from "@/components/states";
import { api, SavingsInsights } from "@/lib/api";
import { MONTHS, bankTint, formatDate, formatMoney, loadAmountsHidden } from "@/lib/format";
import { loadPref, savePref } from "@/lib/prefs";

const plain = /^\d+(\.\d{1,2})?$/;

export default function SavingsPage() {
  const [data, setData] = useState<SavingsInsights | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [goal, setGoal] = useState("");
  const [, setTick] = useState(0);

  useEffect(() => {
    loadAmountsHidden();
    setTick((n) => n + 1);
    const saved = loadPref("savingsGoal");
    if (saved && plain.test(saved)) setGoal(saved);
  }, []);

  useEffect(() => {
    setFailed(false);
    const clean = goal.replace(/[,\s]/g, "");
    const query = plain.test(clean) && Number(clean) > 0 ? `?goal=${clean}` : "";
    api<SavingsInsights>(`/savings/insights${query}`)
      .then(setData)
      .catch(() => setFailed(true));
  }, [goal, attempt]);

  const plan = data?.projection ?? null;
  const top = Math.max(1, ...(plan?.points.map((p) => Number(p.balance)) ?? [1]), Number(plan?.current_balance ?? 0));

  return (
    <section className="space-y-5">
      <h1 className="text-xl font-semibold">Savings</h1>
      <p className="text-sm text-slate-600">
        What your banks pay you, where a rate is falling, money that may be sitting idle, and where your balance is
        heading. Everything is worked out from your statements; the rates are estimates (see the Growth tab on the
        Reports page for how).
      </p>

      {failed && <LoadError message="Could not load the savings figures." onRetry={() => setAttempt((n) => n + 1)} />}
      {!failed && !data && <RowsSkeleton rows={6} />}

      {data && data.as_of === null && (
        <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
          Nothing to show yet. Upload a statement first.
        </p>
      )}

      {data && data.as_of !== null && (
        <>
          <p className="text-xs text-slate-500">Up to {formatDate(data.as_of)}, the latest date in your statements.</p>

          {data.drops.length > 0 && (
            <section aria-label="Rates that fell" className="space-y-2">
              {data.drops.map((d) => (
                <p
                  key={d.bank_code ?? "none"}
                  className="rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900"
                >
                  <span className={`mr-2 rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(d.bank_code)}`}>{d.bank_code ?? "?"}</span>
                  {d.bank_name ?? "A bank"}: the rate on the latest interest credit ({formatDate(d.since)}) is about{" "}
                  <strong>{d.latest_rate}%</strong> a year, down from about {d.previous_rate}% on the ones before it.
                </p>
              ))}
            </section>
          )}

          <section>
            <h2 className="mb-1 font-medium">What each bank pays you</h2>
            {data.banks.length === 0 ? (
              <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
                No interest with enough statement history behind it to work out a rate. Interest credits need to be in the
                Interest income category, and a rate needs the days before each credit to be in your statements.
              </p>
            ) : (
              <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
                    <tr>
                      <th className="px-3 py-1.5 font-medium">Bank</th>
                      <th className="px-3 py-1.5 text-right font-medium">Rate (a year)</th>
                      <th className="px-3 py-1.5 text-right font-medium">Interest, last 12 months</th>
                      <th className="px-3 py-1.5 text-right font-medium">Average balance</th>
                      <th className="px-3 py-1.5 text-right font-medium">Accounts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.banks.map((b, i) => (
                      <tr key={b.bank_code ?? "none"} className="border-b border-slate-100 last:border-0">
                        <td className="px-3 py-1.5">
                          <span className={`mr-2 rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(b.bank_code)}`}>{b.bank_code ?? "?"}</span>
                          {b.bank_name ?? "Unknown bank"}
                          {i === 0 && data.banks.length > 1 && <span className="ml-2 rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-800">best</span>}
                        </td>
                        <td className="px-3 py-1.5 text-right font-medium tabular-nums">{b.annual_rate}%</td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-green-700">{formatMoney(b.interest)}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(b.average_balance)}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-slate-500">{b.accounts}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <h2 className="mb-1 font-medium">Money that may be sitting idle</h2>
            {data.idle.length === 0 ? (
              <p className="text-sm text-slate-500">
                Nothing found: every account with a sizeable balance was paid interest in the last 6 months, or its
                statements are out of date.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-surface text-sm">
                {data.idle.map((a, i) => (
                  <li key={i} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
                    <span>
                      <span className={`mr-2 rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(a.bank_code)}`}>{a.bank_code ?? "?"}</span>
                      {a.last4 ? `•••• ${a.last4}` : "account not detected"}: average {formatMoney(a.average_balance)} over the last 90
                      days, no interest in 6 months.
                    </span>
                    {a.could_earn_a_year && a.best_rate && (
                      <span className="text-xs text-slate-500">
                        at {a.best_rate}% (your best rate) that would be about{" "}
                        <span className="font-medium text-green-700">{formatMoney(a.could_earn_a_year)}</span> a year
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-1 text-xs text-slate-500">
              A current account may pay no interest by design. This only points at where money has stayed put; it is not a
              recommendation.
            </p>
          </section>

          <section>
            <h2 className="mb-1 font-medium">Where the balance is heading</h2>
            {!plan ? (
              <p className="text-sm text-slate-500">Not enough history yet: it needs at least two month-ends of statements.</p>
            ) : (
              <div className="space-y-3 rounded border border-slate-200 bg-surface p-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Balance now</div>
                    <div className="text-xl font-semibold tabular-nums">{formatMoney(plan.current_balance)}</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Recent change a month</div>
                    <div className={`text-xl font-semibold tabular-nums ${Number(plan.monthly_change) < 0 ? "text-red-700" : "text-green-700"}`}>
                      {Number(plan.monthly_change) > 0 ? "+ " : ""}
                      {formatMoney(plan.monthly_change)}
                    </div>
                    <div className="text-xs text-slate-500">average over the last {plan.months_used} month{plan.months_used === 1 ? "" : "s"}</div>
                  </div>
                  <label className="text-sm">
                    <span className="text-xs font-medium uppercase tracking-wide text-slate-500">A savings goal (LKR)</span>
                    <input
                      inputMode="decimal"
                      value={goal}
                      onChange={(e) => {
                        setGoal(e.target.value);
                        const c = e.target.value.replace(/[,\s]/g, "");
                        if (plain.test(c) || c === "") savePref("savingsGoal", c);
                      }}
                      placeholder="for example 1000000"
                      className="mt-1 block w-full rounded border border-slate-300 bg-surface px-2 py-1.5"
                    />
                  </label>
                </div>

                {plan.goal_reached && <p className="rounded bg-green-50 px-3 py-2 text-sm text-green-800">You are already past that goal.</p>}
                {!plan.goal_reached && plan.months_to_goal !== null && (
                  <p className="rounded bg-blue-50 px-3 py-2 text-sm text-blue-800">
                    At this pace you would reach the goal in about {plan.months_to_goal} month{plan.months_to_goal === 1 ? "" : "s"}.
                  </p>
                )}
                {!plan.goal_reached && plan.months_to_goal === null && plain.test(goal.replace(/[,\s]/g, "")) && (
                  <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    The balance is not growing at the moment, so this pace never reaches the goal.
                  </p>
                )}
                {goal.trim() !== "" && !plain.test(goal.replace(/[,\s]/g, "")) && (
                  <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    Enter the goal as a plain number, for example 1000000.
                  </p>
                )}

                <div role="img" aria-label="Projected month-end balance for the next 12 months" className="flex h-32 items-end gap-1">
                  {plan.points.map((p) => {
                    const d = new Date(`${p.day}T00:00:00`);
                    return (
                      <div key={p.day} className="flex h-full flex-1 flex-col items-center justify-end" title={`${MONTHS[d.getMonth()]} ${d.getFullYear()}: ${formatMoney(p.balance)}`}>
                        <div className="w-full rounded-t bg-accent/70" style={{ height: `${Math.max(2, (Math.max(0, Number(p.balance)) / top) * 100)}%` }} />
                        <span className="mt-1 text-[10px] text-slate-500">{MONTHS[d.getMonth()]}</span>
                      </div>
                    );
                  })}
                </div>
                <p className="text-xs text-slate-500">
                  A straight-line continuation of your recent monthly change (deposits, spending and interest together). It is
                  not a forecast: a change in pay, a large expense or a new rate will move it. Your goal is kept in this browser only.
                </p>
              </div>
            )}
          </section>

          <p className="text-xs text-slate-500">
            See the month-by-month interest and rate on the{" "}
            <Link href="/reports" className="underline">
              Reports
            </Link>{" "}
            page, Growth tab.
          </p>
        </>
      )}
    </section>
  );
}

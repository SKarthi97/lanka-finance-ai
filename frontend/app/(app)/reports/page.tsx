"use client";

import { useEffect, useState } from "react";
import { LoadError, RowsSkeleton } from "@/components/states";
import { api, Budgets, Dashboard } from "@/lib/api";
import { MONTHS_LONG, formatDate, formatMoney } from "@/lib/format";

const select = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";
const th = "px-3 py-1.5 font-medium";

export default function ReportsPage() {
  const now = new Date();
  // Default to last month: the one you are most likely to want a finished summary of.
  const last = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const [year, setYear] = useState(last.getFullYear());
  const [month, setMonth] = useState(last.getMonth() + 1);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [budgets, setBudgets] = useState<Budgets | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setFailed(false);
    setDash(null);
    Promise.all([
      api<Dashboard>(`/dashboard?year=${year}&month=${month}`),
      api<Budgets>(`/budgets?year=${year}&month=${month}`),
    ])
      .then(([d, b]) => {
        setDash(d);
        setBudgets(b);
      })
      .catch(() => setFailed(true));
  }, [year, month, attempt]);

  const years = Array.from(new Set([...(dash?.years ?? []), now.getFullYear(), year])).sort((a, b) => a - b);
  const title = `${MONTHS_LONG[month - 1]} ${year}`;
  const totals = dash?.month;
  const spending = (dash?.month_by_category ?? [])
    .filter((c) => c.kind !== "transfer" && Number(c.expense) > 0)
    .sort((a, b) => Number(b.expense) - Number(a.expense));
  const transfers = Number(totals?.transfers_in ?? 0) + Number(totals?.transfers_out ?? 0);

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <h1 className="text-xl font-semibold">Monthly report</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
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
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded bg-accent px-3 py-1.5 text-accent-fg"
            title="Opens the print dialog; choose “Save as PDF” as the printer"
          >
            Print / save as PDF
          </button>
          <a
            href={`/api/reports/monthly.csv?year=${year}&month=${month}`}
            download={`summary-${year}-${String(month).padStart(2, "0")}.csv`}
            className="rounded border border-slate-300 px-3 py-1.5 hover:bg-slate-100"
          >
            ⬇ Download CSV
          </a>
        </div>
      </div>

      {failed && <LoadError message="Could not load the report." onRetry={() => setAttempt((n) => n + 1)} />}
      {!failed && !dash && <RowsSkeleton rows={6} />}

      {dash && totals && (
        <article className="space-y-5" aria-label={`Report for ${title}`}>
          <header>
            <h2 className="text-lg font-semibold">Summary for {title}</h2>
            <p className="text-xs text-slate-500">
              Lanka Finance AI · all amounts in LKR · reconciled or accepted statements only · transfers
              between your own accounts and repeated rows are left out
            </p>
          </header>

          {totals.transactions === 0 ? (
            <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
              No transactions in {title}.
            </p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded border border-slate-200 bg-surface p-4">
                  <div className="text-xs text-slate-500">Income</div>
                  <div className="mt-1 text-xl font-semibold tabular-nums">{formatMoney(totals.income)}</div>
                </div>
                <div className="rounded border border-slate-200 bg-surface p-4">
                  <div className="text-xs text-slate-500">Expense</div>
                  <div className="mt-1 text-xl font-semibold tabular-nums">{formatMoney(totals.expense)}</div>
                </div>
                <div className="rounded border border-slate-200 bg-surface p-4">
                  <div className="text-xs text-slate-500">Net</div>
                  <div className="mt-1 text-xl font-semibold tabular-nums">{formatMoney(totals.net)}</div>
                  <div className="mt-1 text-xs text-slate-500">{totals.transactions} transactions</div>
                </div>
              </div>

              {transfers > 0 && (
                <p className="text-xs text-slate-500">
                  Not counted above: transfers between your own accounts, {formatMoney(totals.transfers_in)} in and{" "}
                  {formatMoney(totals.transfers_out)} out.
                </p>
              )}
              {totals.uncategorised > 0 && (
                <p className="text-xs text-amber-700">
                  {totals.uncategorised} transaction{totals.uncategorised === 1 ? " is" : "s are"} uncategorised and
                  counted by direction.
                </p>
              )}

              {dash.month_by_bank.length > 1 && (
                <section>
                  <h3 className="mb-1 font-medium">By bank</h3>
                  <table className="w-full rounded border border-slate-200 bg-surface text-sm">
                    <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
                      <tr>
                        <th className={th}>Bank</th>
                        <th className={`${th} text-right`}>Income</th>
                        <th className={`${th} text-right`}>Expense</th>
                        <th className={`${th} text-right`}>Net</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dash.month_by_bank.map((b) => (
                        <tr key={b.bank_code ?? "none"} className="border-b border-slate-100 last:border-0">
                          <td className="px-3 py-1.5">{b.bank_name ?? "Unknown bank"}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(b.income)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(b.expense)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(b.net)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}

              {spending.length > 0 && (
                <section>
                  <h3 className="mb-1 font-medium">Spending by category</h3>
                  <table className="w-full rounded border border-slate-200 bg-surface text-sm">
                    <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
                      <tr>
                        <th className={th}>Category</th>
                        <th className={`${th} text-right`}>Spent</th>
                        <th className={`${th} text-right`}>Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(() => {
                        const total = spending.reduce((n, c) => n + Number(c.expense), 0); // display only
                        return spending.map((c) => (
                          <tr key={c.category_id ?? "none"} className="border-b border-slate-100 last:border-0">
                            <td className="px-3 py-1.5">{c.name}</td>
                            <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(c.expense)}</td>
                            <td className="px-3 py-1.5 text-right tabular-nums">
                              {total > 0 ? Math.round((Number(c.expense) / total) * 100) : 0}%
                            </td>
                          </tr>
                        ));
                      })()}
                    </tbody>
                  </table>
                </section>
              )}

              {budgets && budgets.items.length > 0 && (
                <section>
                  <h3 className="mb-1 font-medium">Budgets</h3>
                  <table className="w-full rounded border border-slate-200 bg-surface text-sm">
                    <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
                      <tr>
                        <th className={th}>Category</th>
                        <th className={`${th} text-right`}>Limit</th>
                        <th className={`${th} text-right`}>Spent</th>
                        <th className={`${th} text-right`}>Left</th>
                        <th className={th}>Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {budgets.items.map((b) => (
                        <tr key={b.category_id} className="border-b border-slate-100 last:border-0">
                          <td className="px-3 py-1.5">{b.category_name}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(b.limit)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(b.spent)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{formatMoney(b.remaining)}</td>
                          <td className="px-3 py-1.5">
                            {b.state === "over" ? "Over" : b.state === "near" ? "Nearly used" : "On track"} ({b.percent}%)
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              )}

              {dash.top_expenses.length > 0 && (
                <section>
                  <h3 className="mb-1 font-medium">Largest expenses</h3>
                  <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-surface text-sm">
                    {dash.top_expenses.map((t) => (
                      <li key={t.id} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
                        <span className="min-w-0 break-words">
                          <span className="text-xs text-slate-500">{formatDate(t.transaction_date)}</span> {t.description}
                          <span className="text-xs text-slate-500"> · {t.category_name ?? "uncategorised"}</span>
                        </span>
                        <span className="shrink-0 tabular-nums">{formatMoney(t.amount)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </article>
      )}
    </section>
  );
}

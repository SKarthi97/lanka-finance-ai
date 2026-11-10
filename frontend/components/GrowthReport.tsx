"use client";

import { useEffect, useState } from "react";
import { LoadError, RowsSkeleton } from "@/components/states";
import { api, Bank, InterestReport, Trend, TrendMonth } from "@/lib/api";
import { MONTHS_LONG, formatMoney } from "@/lib/format";

const select = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";

// Money arrives as exact decimal strings. Adding is done in whole cents so the totals are exact.
const cents = (value: string) => Math.round(Number(value) * 100);
const money = (c: number) => formatMoney((c / 100).toFixed(2));

/** Net savings: income minus expenses, month by month, for all banks or one. Transfers between your
 * own accounts are not income or expense, so they never count. */
export function GrowthReport({
  initialYear,
  onOpenMonth,
}: {
  initialYear: number;
  onOpenMonth: (year: number, month: number) => void;
}) {
  const now = new Date();
  const [year, setYear] = useState(initialYear);
  const [bank, setBank] = useState("");
  const [banks, setBanks] = useState<Bank[]>([]);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [interest, setInterest] = useState<InterestReport | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    api<Bank[]>("/banks")
      .then(setBanks)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setFailed(false);
    setTrend(null);
    const params = new URLSearchParams({ year: String(year), month: "12", months: "12" });
    if (bank) params.set("bank_code", bank);
    api<Trend>(`/dashboard/trend?${params}`)
      .then(setTrend)
      .catch(() => setFailed(true));
    // The interest rate is an extra: if it cannot be worked out, the savings figures still show.
    const rateParams = new URLSearchParams({ year: String(year) });
    if (bank) rateParams.set("bank_code", bank);
    api<InterestReport>(`/savings/interest?${rateParams}`)
      .then(setInterest)
      .catch(() => setInterest(null));
  }, [year, bank, attempt]);

  const years = Array.from({ length: 6 }, (_, i) => now.getFullYear() - i);

  // Months after today have nothing yet; they stay out of the averages.
  const past = (m: TrendMonth) => m.year < now.getFullYear() || (m.year === now.getFullYear() && m.month <= now.getMonth() + 1);
  const active = (trend?.months ?? []).filter((m) => past(m) && (cents(m.income) !== 0 || cents(m.expense) !== 0));

  const income = active.reduce((n, m) => n + cents(m.income), 0);
  const expense = active.reduce((n, m) => n + cents(m.expense), 0);
  const net = income - expense;
  const rate = income > 0 ? Math.round((net / income) * 100) : null;
  const average = active.length > 0 ? Math.round(net / active.length) : 0;
  const best = active.reduce<TrendMonth | null>((a, m) => (a === null || cents(m.net) > cents(a.net) ? m : a), null);
  const worst = active.reduce<TrendMonth | null>((a, m) => (a === null || cents(m.net) < cents(a.net) ? m : a), null);
  const biggest = Math.max(1, ...active.map((m) => Math.abs(cents(m.net))));

  const rows = (trend?.months ?? []).reduce<{ m: TrendMonth; has: boolean; cumulative: number }[]>((acc, m) => {
    const has = past(m) && (cents(m.income) !== 0 || cents(m.expense) !== 0);
    const before = acc.length ? acc[acc.length - 1].cumulative : 0;
    acc.push({ m, has, cumulative: has ? before + cents(m.net) : before });
    return acc;
  }, []);

  const rateOf = (month: number) => interest?.months.find((r) => r.month === month);
  const interestTotal = (interest?.months ?? []).reduce((n, r) => n + cents(r.interest), 0);

  const tone = (c: number) => (c < 0 ? "text-red-700" : c > 0 ? "text-green-700" : "");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <div className="flex items-center overflow-hidden rounded border border-slate-300 text-sm">
          <button type="button" onClick={() => setYear(year - 1)} aria-label="Previous year" className="px-2.5 py-1.5 hover:bg-slate-100">
            ‹
          </button>
          <span className="border-x border-slate-300 px-3 py-1.5 tabular-nums">{year}</span>
          <button
            type="button"
            onClick={() => setYear(year + 1)}
            disabled={year >= now.getFullYear()}
            aria-label="Next year"
            className="px-2.5 py-1.5 hover:bg-slate-100 disabled:opacity-40"
          >
            ›
          </button>
        </div>
        <select aria-label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))} className={select}>
          {years.map((y) => (
            <option key={y}>{y}</option>
          ))}
        </select>
        <select aria-label="Bank" value={bank} onChange={(e) => setBank(e.target.value)} className={select}>
          <option value="">All banks</option>
          {banks.map((b) => (
            <option key={b.code} value={b.code}>
              {b.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
        >
          Print / save as PDF
        </button>
      </div>

      <header>
        <h2 className="text-lg font-semibold">
          Net savings in {year}
          {bank ? `, ${banks.find((b) => b.code === bank)?.name ?? bank}` : ", all banks"}
        </h2>
        <p className="text-xs text-slate-500">
          Net savings = income − expenses. Transfers between your own accounts and repeated rows are left out, and
          only reconciled or accepted statements count. It is not the same as the change in your balance: money you
          move out to somewhere not in the app, or a statement you have not uploaded, changes the balance but not this.
        </p>
      </header>

      <p className="text-xs text-slate-500">
        Interest rate: the interest credited in a month, divided by the money you kept in the account on each day it
        covers, as a rate for a year. A bank usually credits interest for the days since its last credit, so the rate
        in a row belongs to the days <em>before</em> that credit (often the previous month). It is worked out from your
        statements, so it is an estimate and can differ a little from the bank&apos;s own rate. A dash means no interest
        was credited that month; &ldquo;needs an earlier statement&rdquo; means interest was credited but the statements
        do not show enough of the days before it. A * means part of the figure rests on an assumption (hover for which).
      </p>
      {interest && interest.unrecognised > 0 && (
        <p role="status" className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-400">
          {interest.unrecognised} credit{interest.unrecognised === 1 ? "" : "s"} in {year} mention interest but{" "}
          {interest.unrecognised === 1 ? "is" : "are"} not in the Interest income category, so{" "}
          {interest.unrecognised === 1 ? "it is" : "they are"} left out of these figures.{" "}
          <a href={`/transactions?q=interest&year=${year}`} className="underline">
            Show them
          </a>
        </p>
      )}

      {failed && <LoadError message="Could not load the growth figures." onRetry={() => setAttempt((n) => n + 1)} />}
      {!failed && !trend && <RowsSkeleton rows={6} />}

      {trend && active.length === 0 && (
        <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
          No transactions in {year}
          {bank ? " for this bank" : ""}.
        </p>
      )}

      {trend && active.length > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className={`rounded border border-t-2 border-slate-200 bg-surface p-4 shadow-sm ${net < 0 ? "border-t-red-700" : "border-t-green-700"}`}>
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Net savings</div>
              <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone(net)}`}>{money(net)}</div>
              <div className="mt-1 text-xs text-slate-500">
                {money(income)} in − {money(expense)} out
              </div>
            </div>
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Savings rate</div>
              <div className={`mt-1 text-2xl font-semibold tabular-nums ${rate !== null ? tone(rate) : ""}`}>
                {rate !== null ? `${rate}%` : "–"}
              </div>
              <div className="mt-1 text-xs text-slate-500">{rate !== null ? "of income kept" : "no income in this period"}</div>
            </div>
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Average per month</div>
              <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone(average)}`}>{money(average)}</div>
              <div className="mt-1 text-xs text-slate-500">over {active.length} month{active.length === 1 ? "" : "s"} with data</div>
            </div>
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Best and worst month</div>
              <div className="mt-1 text-sm">
                {best && (
                  <div>
                    <span className="text-green-700">▲ {MONTHS_LONG[best.month - 1]}</span>{" "}
                    <span className="tabular-nums">{formatMoney(best.net)}</span>
                  </div>
                )}
                {worst && worst !== best && (
                  <div>
                    <span className="text-red-700">▼ {MONTHS_LONG[worst.month - 1]}</span>{" "}
                    <span className="tabular-nums">{formatMoney(worst.net)}</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 text-left text-xs text-slate-600">
                <tr>
                  <th className="px-3 py-2 font-medium">Month</th>
                  <th className="px-3 py-2 text-right font-medium">Income</th>
                  <th className="px-3 py-2 text-right font-medium">Expenses</th>
                  <th className="px-3 py-2 text-right font-medium">Net savings</th>
                  <th className="hidden px-3 py-2 font-medium md:table-cell">
                    <span className="sr-only">Bar</span>
                  </th>
                  <th className="px-3 py-2 text-right font-medium">Kept</th>
                  <th className="px-3 py-2 text-right font-medium">Interest</th>
                  <th className="px-3 py-2 text-right font-medium" title="Estimated from the days your money was kept">
                    Interest rate
                  </th>
                  <th className="px-3 py-2 text-right font-medium">Total so far</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ m, has, cumulative }) => {
                  const value = cents(m.net);
                  const share = (Math.abs(value) / biggest) * 100;
                  return (
                    <tr key={`${m.year}-${m.month}`} className={`border-b border-slate-100 last:border-0 hover:bg-slate-50 ${has ? "" : "text-slate-400"}`}>
                      <td className="px-3 py-1.5">
                        <button
                          type="button"
                          onClick={() => onOpenMonth(m.year, m.month)}
                          title="Open this month's report"
                          className="hover:underline"
                        >
                          {MONTHS_LONG[m.month - 1]}
                        </button>
                      </td>
                      {has ? (
                        <>
                          <td className="px-3 py-1.5 text-right tabular-nums text-green-700">{formatMoney(m.income)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-red-700">{formatMoney(m.expense)}</td>
                          <td className={`px-3 py-1.5 text-right font-medium tabular-nums ${tone(value)}`}>{formatMoney(m.net)}</td>
                          <td className="hidden w-40 px-3 py-1.5 md:table-cell" aria-hidden="true">
                            <div className="flex h-2 items-center">
                              <div className="flex h-2 w-1/2 justify-end">
                                {value < 0 && <div className="h-2 rounded-l bg-red-500" style={{ width: `${share}%` }} />}
                              </div>
                              <div className="h-4 w-px bg-slate-300" />
                              <div className="h-2 w-1/2">
                                {value > 0 && <div className="h-2 rounded-r bg-green-700" style={{ width: `${share}%` }} />}
                              </div>
                            </div>
                          </td>
                          <td className="px-3 py-1.5 text-right tabular-nums text-slate-500">
                            {cents(m.income) > 0 ? `${Math.round((value / cents(m.income)) * 100)}%` : "–"}
                          </td>
                          {(() => {
                            const r = rateOf(m.month);
                            return r ? (
                              <>
                                <td className="px-3 py-1.5 text-right tabular-nums text-green-700">{formatMoney(r.interest)}</td>
                                {r.annual_rate !== null && r.average_balance !== null ? (
                                  <td
                                    className="px-3 py-1.5 text-right tabular-nums"
                                    title={`Average balance ${formatMoney(r.average_balance)} over ${r.days} days${
                                      r.assumed ? `. The statements start too late to be sure, so this assumes the interest pays for ${r.assumed}.` : ""
                                    }${r.unrated > 0 ? ` ${r.unrated} more credit(s) this month had too little data and are not in the rate.` : ""}`}
                                  >
                                    <span className="font-medium text-slate-900">{r.annual_rate}%</span>
                                    <span className="text-xs text-slate-500"> a year{r.assumed || r.unrated > 0 ? " *" : ""}</span>
                                    <div className="text-xs text-slate-500">{r.monthly_rate}% a month</div>
                                  </td>
                                ) : (
                                  <td
                                    className="px-3 py-1.5 text-right text-xs text-slate-500"
                                    title="The statements do not go back far enough before this credit to know how much money was kept each day. Upload the earlier statement to get the rate."
                                  >
                                    needs an earlier statement
                                  </td>
                                )}
                              </>
                            ) : (
                              <>
                                <td className="px-3 py-1.5 text-right text-slate-400">–</td>
                                <td className="px-3 py-1.5 text-right text-slate-400">–</td>
                              </>
                            );
                          })()}
                          <td className={`px-3 py-1.5 text-right tabular-nums ${tone(cumulative)}`}>{money(cumulative)}</td>
                        </>
                      ) : (
                        <td colSpan={8} className="px-3 py-1.5 text-xs">
                          {m.year === now.getFullYear() && m.month > now.getMonth() + 1 ? "not yet" : "no transactions"}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="border-t border-slate-200 font-medium">
                <tr>
                  <td className="px-3 py-2">{year}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-green-700">{money(income)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-red-700">{money(expense)}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${tone(net)}`}>{money(net)}</td>
                  <td className="hidden md:table-cell" />
                  <td className="px-3 py-2 text-right tabular-nums text-slate-500">{rate !== null ? `${rate}%` : "–"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-green-700">{interestTotal > 0 ? money(interestTotal) : "–"}</td>
                  <td />
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

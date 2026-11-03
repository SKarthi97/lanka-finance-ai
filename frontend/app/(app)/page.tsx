"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CardSkeleton, LoadError, RowsSkeleton } from "@/components/states";
import { BalanceChart, IncomeExpenseChart } from "@/components/TrendCharts";
import { api, CategoryTotal, Dashboard, Tracker, Totals, Trend } from "@/lib/api";
import {
  MONTHS,
  MONTHS_LONG,
  NO_ACCOUNT_HINT,
  compareText,
  formatDate,
  formatMoney,
  loadAmountsHidden,
  setAmountsHidden,
} from "@/lib/format";

const select = "rounded border border-slate-300 bg-surface px-2 py-1 text-sm";

function Card({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "good" | "bad";
  hint?: string;
}) {
  const color = tone === "good" ? "text-green-700" : tone === "bad" ? "text-red-700" : "";
  return (
    <div className="rounded border border-slate-200 bg-surface p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

function CategoryBars({ items, filter }: { items: CategoryTotal[]; filter: string }) {
  // Spending by category, transfers excluded. The biggest few, then the rest.
  const spending = items
    .filter((c) => c.kind !== "transfer" && Number(c.expense) > 0)
    .sort((a, b) => Number(b.expense) - Number(a.expense));
  if (spending.length === 0) return null;

  const total = spending.reduce((sum, c) => sum + Number(c.expense), 0); // display only
  const top = spending.slice(0, 8);
  const rest = spending.slice(8);
  const rows = rest.length
    ? [...top, { ...rest[0], category_id: -1, name: `${rest.length} more`, expense: String(rest.reduce((n, c) => n + Number(c.expense), 0)) }]
    : top;

  return (
    <ul className="space-y-1.5 rounded border border-slate-200 bg-surface p-4 text-sm">
      {rows.map((c) => {
        const share = total > 0 ? (Number(c.expense) / total) * 100 : 0;
        const uncategorised = c.category_id === null;
        return (
          <li key={c.category_id ?? "none"}>
            <div className="flex justify-between gap-3">
              <span className={uncategorised ? "text-amber-700" : ""}>
                {c.category_id === -1 ? (
                  c.name
                ) : (
                  <Link
                    href={`/transactions?${uncategorised ? "uncategorised=true" : `category_id=${c.category_id}`}${filter}`}
                    className="underline decoration-slate-300 hover:decoration-slate-600"
                    title="Show these transactions"
                  >
                    {c.name}
                  </Link>
                )}
              </span>
              <span className="tabular-nums text-slate-600">
                {formatMoney(c.expense)} · {share.toFixed(0)}%
              </span>
            </div>
            <div className="mt-0.5 h-1.5 rounded bg-slate-100" aria-hidden="true">
              <div
                className={`h-1.5 rounded ${uncategorised ? "bg-amber-400" : "bg-accent"}`}
                style={{ width: `${Math.max(share, 1)}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** "35%" when you saved something; null otherwise. A percentage only means something between
 * 0 and 100, so overspending or no income is described in words by savingNote instead. */
function savingRate(totals: Totals): string | null {
  const income = Number(totals.income);
  const net = Number(totals.net);
  return totals.transactions > 0 && income > 0 && net >= 0 ? `${Math.round((net / income) * 100)}%` : null;
}

function savingNote(totals: Totals): string | null {
  if (totals.transactions === 0) return null;
  if (Number(totals.income) === 0) return "no income";
  if (Number(totals.net) < 0) return "spent more than earned";
  return `saved ${savingRate(totals)} of income`;
}

function PeriodCards({
  title,
  totals,
  byCategory,
  previous,
  previousLabel,
  filter,
  action,
}: {
  title: string;
  totals: Totals | undefined;
  byCategory: CategoryTotal[] | undefined;
  previous?: Totals;
  previousLabel?: string;
  filter: string; // query string for the transactions drill-down, e.g. "&year=2026&month=10"
  action?: React.ReactNode; // shown at the right of the heading (the month picker)
}) {
  const net = Number(totals?.net ?? 0);
  // Only compare with the previous month when both months have transactions: "down 100%" against
  // an empty month says nothing.
  const comparable = !!totals && !!previous && totals.transactions > 0 && previous.transactions > 0;
  const vs = (field: "income" | "expense") =>
    comparable && previousLabel ? compareText(totals![field], previous![field], previousLabel) : null;
  const saving = totals ? savingNote(totals) : null;
  const transfers = Number(totals?.transfers_in ?? 0) + Number(totals?.transfers_out ?? 0);
  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="font-medium">{title}</h2>
        {action}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Card label="Income" value={formatMoney(totals?.income)} tone="good" hint={vs("income") ?? undefined} />
        <Card label="Expense" value={formatMoney(totals?.expense)} tone="bad" hint={vs("expense") ?? undefined} />
        <Card
          label="Net"
          value={formatMoney(totals?.net)}
          tone={net < 0 ? "bad" : net > 0 ? "good" : undefined}
          hint={
            totals
              ? `${totals.transactions} transactions${saving ? ` · ${saving}` : ""}`
              : undefined
          }
        />
      </div>

      {totals && transfers > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          Not counted above: transfers between your own accounts, {formatMoney(totals.transfers_in)} in
          and {formatMoney(totals.transfers_out)} out.
        </p>
      )}
      {totals && totals.uncategorised > 0 && (
        <p className="mt-1 text-xs text-amber-700">
          {totals.uncategorised} transaction{totals.uncategorised === 1 ? "" : "s"} still uncategorised;
          they are counted by direction (credits as income, debits as expense).{" "}
          <Link href="/categories" className="underline">
            Review
          </Link>
        </p>
      )}

      <div className="mt-3">
        <h3 className="mb-1 text-sm text-slate-600">Spending by category</h3>
        {byCategory && <CategoryBars items={byCategory} filter={filter} />}
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [bank, setBank] = useState("");
  const [hidden, setHidden] = useState(false);

  const [dash, setDash] = useState<Dashboard | null>(null);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [dashFailed, setDashFailed] = useState(false);
  const [trendFailed, setTrendFailed] = useState(false);
  const [reload, setReload] = useState(0); // bump to retry the dashboard requests
  const [tracker, setTracker] = useState<Tracker | null>(null);

  useEffect(() => {
    setHidden(loadAmountsHidden());
  }, []);

  const bankParam = bank ? `&bank_code=${encodeURIComponent(bank)}` : "";

  useEffect(() => {
    setDashFailed(false);
    api<Dashboard>(`/dashboard?year=${year}&month=${month}${bankParam}`)
      .then(setDash)
      .catch(() => {
        setDash(null);
        setDashFailed(true);
      });
  }, [year, month, bankParam, reload]);

  // The summary cards always describe the latest month you have data for, whichever period is
  // picked below, so the top of the page does not change while you browse.
  const latestPeriod = dash?.as_of ? dash.as_of.split("-").map(Number).slice(0, 2) : null;
  const latestKey = latestPeriod ? `${latestPeriod[0]}-${latestPeriod[1]}` : null;
  const [kpi, setKpi] = useState<Dashboard | null>(null);
  useEffect(() => {
    if (!latestPeriod || !dash) return;
    if (latestPeriod[0] === year && latestPeriod[1] === month) {
      setKpi(dash);
      return;
    }
    api<Dashboard>(`/dashboard?year=${latestPeriod[0]}&month=${latestPeriod[1]}${bankParam}`)
      .then(setKpi)
      .catch(() => setKpi(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestKey, year, month, bankParam, dash]);

  // The charts show January to December of the chosen year.
  useEffect(() => {
    setTrendFailed(false);
    api<Trend>(`/dashboard/trend?year=${year}&month=12&months=12${bankParam}`)
      .then(setTrend)
      .catch(() => {
        setTrend(null);
        setTrendFailed(true);
      });
  }, [year, bankParam, reload]);

  useEffect(() => {
    api<Tracker>(`/tracker?year=${year}`)
      .then(setTracker)
      .catch(() => setTracker(null));
  }, [year]);

  const isNow = year === now.getFullYear() && month === now.getMonth() + 1;
  const monthTitle = isNow ? "This month" : `${MONTHS_LONG[month - 1]} ${year}`;
  const yearTitle = year === now.getFullYear() ? "This year" : String(year);

  const prevIndex = year * 12 + (month - 1) - 1;
  const previousLabel = MONTHS[prevIndex % 12];

  const emptyPeriod = dash?.has_data && dash.month.transactions === 0 && dash.year.transactions === 0;

  function toggleHidden() {
    setAmountsHidden(!hidden);
    setHidden(!hidden);
  }

  function jumpToLatest() {
    if (!dash?.as_of) return;
    const [y, m] = dash.as_of.split("-").map(Number);
    setYear(y);
    setMonth(m);
  }

  // Every year that has transactions (not just statement end years), plus the current
  // year and whatever is selected, so the list never loses the active choice.
  const years = Array.from(
    new Set([...(dash?.years ?? []), ...(tracker?.years ?? []), now.getFullYear(), year]),
  ).sort((a, b) => a - b);

  // --- things that need you ---------------------------------------------------------------
  const staleDays = dash?.as_of
    ? Math.floor((now.getTime() - new Date(`${dash.as_of}T00:00:00`).getTime()) / 86_400_000)
    : null;
  const stale = staleDays !== null && staleDays > 45;

  // Months without a statement between a row's first and last statement (this tracker year).
  let missingMonths = 0;
  for (const row of tracker?.rows ?? []) {
    const have = Object.keys(row.cells).map(Number);
    if (have.length === 0) continue;
    const lo = Math.min(...have);
    const hi = Math.max(...have);
    for (let m = lo; m <= hi; m++) if (!row.cells[String(m)]) missingMonths++;
  }

  const attention: { key: string; text: React.ReactNode }[] = [];
  if (dash && dash.needs_review > 0)
    attention.push({
      key: "review",
      text: (
        <>
          {dash.needs_review} statement{dash.needs_review === 1 ? "" : "s"} did not reconcile and{" "}
          {dash.needs_review === 1 ? "is" : "are"} excluded from every figure.{" "}
          <Link href="/upload" className="underline">
            Review
          </Link>
        </>
      ),
    });
  if (dash && dash.uncategorised_total > 0)
    attention.push({
      key: "uncat",
      text: (
        <>
          {dash.uncategorised_total} transaction{dash.uncategorised_total === 1 ? "" : "s"} uncategorised
          {dash.ai_unsure > 0 ? `, ${dash.ai_unsure} with an unsure AI suggestion` : ""}.{" "}
          <Link href="/categories" className="underline">
            Categorise
          </Link>
        </>
      ),
    });
  if (stale)
    attention.push({
      key: "stale",
      text: (
        <>
          Your latest statement ends {formatDate(dash?.as_of)}, {staleDays} days ago. Balances may be
          out of date.{" "}
          <Link href="/upload" className="underline">
            Upload a newer statement
          </Link>
        </>
      ),
    });
  if (missingMonths > 0)
    attention.push({
      key: "gaps",
      text: (
        <>
          {missingMonths} month{missingMonths === 1 ? "" : "s"} without a statement in {tracker?.year},
          between statements you have.{" "}
          <Link href="/upload#tracker" className="underline">
            See the tracker
          </Link>
        </>
      ),
    });

  const monthFilter = `${bankParam}&year=${year}&month=${month}`;
  const kpiMonthLabel = latestPeriod ? `${MONTHS_LONG[latestPeriod[1] - 1]} ${latestPeriod[0]}` : null;
  const kpiYearLabel = latestPeriod ? String(latestPeriod[0]) : null;
  const yearFilter = `${bankParam}&year=${year}`;

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {(dash?.banks.length ?? 0) > 1 && (
            <select aria-label="Bank" value={bank} onChange={(e) => setBank(e.target.value)} className={select}>
              <option value="">All banks</option>
              {dash?.banks.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={toggleHidden}
            aria-pressed={hidden}
            className={select}
            title="Hide every amount, for screen sharing"
          >
            {hidden ? "Show amounts" : "Hide amounts"}
          </button>
        </div>
      </div>

      {attention.length > 0 && (
        <section aria-labelledby="attention-heading">
          <h2 id="attention-heading" className="sr-only">
            Needs your attention
          </h2>
          <ul role="status" className="space-y-2">
            {attention.map((a) => (
              <li
                key={a.key}
                className="flex items-start gap-2 rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900"
              >
                <span aria-hidden="true">⚠</span>
                <span>{a.text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!dash ? (
        dashFailed ? (
          <LoadError
            message="Could not load the dashboard."
            onRetry={() => setReload((n) => n + 1)}
          />
        ) : (
          <div className="space-y-6">
            <div className="grid gap-3 md:grid-cols-[1fr_2fr]">
              <CardSkeleton />
              <CardSkeleton />
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              <RowsSkeleton rows={6} />
              <RowsSkeleton rows={6} />
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <CardSkeleton />
              <CardSkeleton />
              <CardSkeleton />
            </div>
          </div>
        )
      ) : !dash.has_data ? (
        <p className="text-sm text-slate-600">
          No reconciled statements yet.{" "}
          <Link href="/upload" className="underline">
            Upload one
          </Link>{" "}
          to see your balance and spending.
        </p>
      ) : (
        <>
          {/* Current finance */}
          <section>
            <h2 className="mb-2 font-medium">Current balance</h2>
            <div className="mb-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Card
                label="Total across accounts (LKR)"
                value={formatMoney(dash?.total_balance)}
                hint={
                  dash?.as_of
                    ? `As of ${formatDate(dash.as_of)}${staleDays !== null ? ` (${staleDays} days ago)` : ""}`
                    : undefined
                }
              />
              <Card
                label={kpiMonthLabel ? `${kpiMonthLabel} net` : "Latest month net"}
                value={kpi ? formatMoney(kpi.month.net) : "–"}
                tone={kpi ? (Number(kpi.month.net) < 0 ? "bad" : Number(kpi.month.net) > 0 ? "good" : undefined) : undefined}
                hint={kpi ? savingNote(kpi.month) ?? `${kpi.month.transactions} transactions` : undefined}
              />
              <Card
                label={kpiYearLabel ? `${kpiYearLabel} to date, net` : "Year to date, net"}
                value={kpi ? formatMoney(kpi.year.net) : "–"}
                tone={kpi ? (Number(kpi.year.net) < 0 ? "bad" : Number(kpi.year.net) > 0 ? "good" : undefined) : undefined}
                hint={kpi ? `${formatMoney(kpi.year.income)} in · ${formatMoney(kpi.year.expense)} out` : undefined}
              />
              <Card
                label={kpiYearLabel ? `Saved in ${kpiYearLabel}` : "Saved this year"}
                value={kpi ? savingRate(kpi.year) ?? "–" : "–"}
                hint={kpi ? (savingRate(kpi.year) ? "of income" : savingNote(kpi.year) ?? undefined) : undefined}
              />
            </div>
            <div>
              <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-200 text-slate-600">
                    <tr>
                      <th className="px-3 py-2 font-medium">Bank</th>
                      <th className="px-3 py-2 text-right font-medium">Balance (LKR)</th>
                      <th className="px-3 py-2 font-medium">As of</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(dash?.balances ?? []).map((b, index) => (
                      <tr key={index} className="border-b border-slate-100 last:border-0">
                        <td className="px-3 py-2">
                          <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium uppercase">
                            {b.bank_code ?? "?"}
                          </span>
                          {b.account_last4 ? (
                            <span className="ml-2 text-xs text-slate-500">•••• {b.account_last4}</span>
                          ) : (
                            <span className="ml-2 text-xs text-slate-400" title={NO_ACCOUNT_HINT}>
                              account not detected
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatMoney(b.balance)}</td>
                        <td className="px-3 py-2">{formatDate(b.as_of)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          {emptyPeriod && (
            <p className="rounded bg-slate-100 px-4 py-3 text-sm text-slate-700">
              No transactions in {MONTHS_LONG[month - 1]} {year}. Your latest statement ends{" "}
              {formatDate(dash?.as_of)}.{" "}
              <button onClick={jumpToLatest} className="underline">
                Show that period
              </button>
            </p>
          )}

          <section>
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="font-medium">Income, expense and balance by month</h2>
              <select
                aria-label="Year"
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                className={select}
              >
                {years.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
            {trend ? (
              <div className="grid gap-3 lg:grid-cols-2">
                <div className="rounded border border-slate-200 bg-surface p-4">
                  <h3 className="mb-1 text-sm text-slate-600">Income and expense</h3>
                  <IncomeExpenseChart
                    months={trend.months}
                    bank={bank}
                    selected={{ year, month }}
                    onPick={(y, m) => {
                      setYear(y);
                      setMonth(m);
                    }}
                  />
                </div>
                <div className="rounded border border-slate-200 bg-surface p-4">
                  <h3 className="mb-1 text-sm text-slate-600">Balance</h3>
                  <BalanceChart months={trend.months} />
                </div>
              </div>
            ) : trendFailed ? (
              <LoadError message="Could not load the charts." onRetry={() => setReload((n) => n + 1)} />
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                <RowsSkeleton rows={6} />
                <RowsSkeleton rows={6} />
              </div>
            )}
          </section>

          <PeriodCards
            title={monthTitle}
            action={
              <select
                aria-label="Month"
                value={month}
                onChange={(e) => setMonth(Number(e.target.value))}
                className={select}
              >
                {MONTHS_LONG.map((name, index) => (
                  <option key={name} value={index + 1}>
                    {name} {year}
                  </option>
                ))}
              </select>
            }
            totals={dash?.month}
            byCategory={dash?.month_by_category}
            previous={dash?.previous_month}
            previousLabel={previousLabel}
            filter={monthFilter}
          />

          {dash && dash.top_expenses.length > 0 && (
            <section>
              <h3 className="mb-1 text-sm text-slate-600">
                Largest expenses, {MONTHS_LONG[month - 1]} {year}
              </h3>
              <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-surface text-sm">
                {dash.top_expenses.map((t) => (
                  <li key={t.id} className="flex items-baseline justify-between gap-3 px-3 py-2">
                    <span className="min-w-0">
                      <span className="text-xs text-slate-500">{formatDate(t.transaction_date)}</span>{" "}
                      <span className="break-words">{t.description}</span>{" "}
                      <span className="text-xs text-slate-500">
                        {t.category_name ?? <span className="text-amber-700">uncategorised</span>}
                      </span>
                    </span>
                    <span className="shrink-0 tabular-nums">{formatMoney(t.amount)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <PeriodCards
            title={yearTitle}
            totals={dash?.year}
            byCategory={dash?.year_by_category}
            filter={yearFilter}
          />
          <p className="text-xs text-slate-500">
            Income and expense come from reconciled or accepted statements, without transfers between
            your own accounts. A transaction that appears in two overlapping statements counts once.
          </p>
        </>
      )}
    </section>
  );
}

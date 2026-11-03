"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, CategoryTotal, Dashboard, Tracker, Totals } from "@/lib/api";
import { MONTHS, MONTHS_LONG, NO_ACCOUNT_HINT, formatDate, formatMoney } from "@/lib/format";

const select = "rounded border border-slate-300 bg-white px-2 py-1 text-sm";

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
    <div className="rounded border border-slate-200 bg-white p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

function CategoryBars({ items }: { items: CategoryTotal[] }) {
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
    <ul className="space-y-1.5 rounded border border-slate-200 bg-white p-4 text-sm">
      {rows.map((c) => {
        const share = total > 0 ? (Number(c.expense) / total) * 100 : 0;
        const uncategorised = c.category_id === null;
        return (
          <li key={c.category_id ?? "none"}>
            <div className="flex justify-between gap-3">
              <span className={uncategorised ? "text-amber-700" : ""}>
                {uncategorised ? (
                  <Link href="/categories" className="underline">
                    {c.name}
                  </Link>
                ) : (
                  c.name
                )}
              </span>
              <span className="tabular-nums text-slate-600">
                {formatMoney(c.expense)} · {share.toFixed(0)}%
              </span>
            </div>
            <div className="mt-0.5 h-1.5 rounded bg-slate-100" aria-hidden="true">
              <div
                className={`h-1.5 rounded ${uncategorised ? "bg-amber-400" : "bg-slate-700"}`}
                style={{ width: `${Math.max(share, 1)}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function PeriodCards({
  title,
  totals,
  byCategory,
}: {
  title: string;
  totals: Totals | undefined;
  byCategory: CategoryTotal[] | undefined;
}) {
  const net = Number(totals?.net ?? 0);
  const transfers = Number(totals?.transfers_in ?? 0) + Number(totals?.transfers_out ?? 0);
  return (
    <section>
      <h2 className="mb-2 font-medium">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        <Card label="Income" value={formatMoney(totals?.income)} tone="good" />
        <Card label="Expense" value={formatMoney(totals?.expense)} tone="bad" />
        <Card
          label="Net"
          value={formatMoney(totals?.net)}
          tone={net < 0 ? "bad" : net > 0 ? "good" : undefined}
          hint={totals ? `${totals.transactions} transactions` : undefined}
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
        {byCategory && <CategoryBars items={byCategory} />}
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [trackerYear, setTrackerYear] = useState(now.getFullYear());

  const [dash, setDash] = useState<Dashboard | null>(null);
  const [tracker, setTracker] = useState<Tracker | null>(null);

  useEffect(() => {
    api<Dashboard>(`/dashboard?year=${year}&month=${month}`)
      .then(setDash)
      .catch(() => setDash(null));
  }, [year, month]);

  useEffect(() => {
    api<Tracker>(`/tracker?year=${trackerYear}`)
      .then(setTracker)
      .catch(() => setTracker(null));
  }, [trackerYear]);

  const isNow = year === now.getFullYear() && month === now.getMonth() + 1;
  const monthTitle = isNow ? "This month" : `${MONTHS_LONG[month - 1]} ${year}`;
  const yearTitle = year === now.getFullYear() ? "This year" : String(year);

  const emptyPeriod = dash?.has_data && dash.month.transactions === 0 && dash.year.transactions === 0;

  function jumpToLatest() {
    if (!dash?.as_of) return;
    const [y, m] = dash.as_of.split("-").map(Number);
    setYear(y);
    setMonth(m);
    setTrackerYear(y);
  }

  // Every year that has transactions (not just statement end years), plus the current
  // year and whatever is selected, so the list never loses the active choice.
  const years = Array.from(
    new Set([...(dash?.years ?? []), ...(tracker?.years ?? []), now.getFullYear(), year]),
  ).sort((a, b) => a - b);

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">Period</span>
          <select aria-label="Month" value={month} onChange={(e) => setMonth(Number(e.target.value))} className={select}>
            {MONTHS_LONG.map((name, index) => (
              <option key={name} value={index + 1}>
                {name}
              </option>
            ))}
          </select>
          <select aria-label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))} className={select}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
      </div>

      {dash && dash.needs_review > 0 && (
        <div role="status" className="rounded bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {dash.needs_review} statement{dash.needs_review === 1 ? "" : "s"} did not reconcile and{" "}
          {dash.needs_review === 1 ? "is" : "are"} excluded from every figure below.{" "}
          <Link href="/upload" className="underline">
            Review
          </Link>
        </div>
      )}

      {dash && !dash.has_data ? (
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
            <div className="grid gap-3 md:grid-cols-[1fr_2fr]">
              <Card
                label="Total across accounts (LKR)"
                value={formatMoney(dash?.total_balance)}
                hint={dash?.as_of ? `As of the latest statement, ${formatDate(dash.as_of)}` : undefined}
              />
              <div className="overflow-x-auto rounded border border-slate-200 bg-white">
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

          <PeriodCards title={monthTitle} totals={dash?.month} byCategory={dash?.month_by_category} />
          <PeriodCards title={yearTitle} totals={dash?.year} byCategory={dash?.year_by_category} />
          <p className="text-xs text-slate-500">
            Income and expense come from reconciled or accepted statements, without transfers between
            your own accounts. A transaction that appears in two overlapping statements counts once.
          </p>
        </>
      )}

      {/* Statement tracker */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-medium">Statement tracker</h2>
          <select
            aria-label="Tracker year"
            value={trackerYear}
            onChange={(e) => setTrackerYear(Number(e.target.value))}
            className={select}
          >
            {(tracker?.years ?? [trackerYear]).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {!tracker || tracker.rows.length === 0 ? (
          <p className="text-sm text-slate-500">
            Nothing to track yet. Each uploaded statement ticks its month here.
          </p>
        ) : (
          <div className="overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-center text-sm">
              <thead className="border-b border-slate-200 text-slate-600">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Bank</th>
                  {MONTHS.map((name) => (
                    <th key={name} className="px-2 py-2 font-medium">
                      {name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tracker.rows.map((row, index) => (
                  <tr key={index} className="border-b border-slate-100 last:border-0">
                    <td className="whitespace-nowrap px-3 py-2 text-left">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium uppercase">
                        {row.bank_code ?? "?"}
                      </span>
                      {row.account_last4 ? (
                        <span className="ml-2 text-xs text-slate-500">•••• {row.account_last4}</span>
                      ) : (
                        <span className="ml-2 text-xs text-slate-400" title={NO_ACCOUNT_HINT}>
                          account not detected
                        </span>
                      )}
                    </td>
                    {MONTHS.map((name, i) => {
                      const cell = row.cells[String(i + 1)];
                      const future =
                        tracker.year > now.getFullYear() ||
                        (tracker.year === now.getFullYear() && i > now.getMonth());
                      return (
                        <td key={name} className="px-2 py-2">
                          {cell ? (
                            <Link
                              href={`/documents/${cell.document_id}`}
                              title={cell.status === "ok" ? `${name}: statement reconciled` : `${name}: needs review`}
                              aria-label={`${name} ${tracker.year}: ${cell.status === "ok" ? "statement uploaded" : "needs review"}`}
                              className={
                                cell.status === "ok"
                                  ? "font-semibold text-green-700"
                                  : "font-semibold text-amber-600"
                              }
                            >
                              {cell.status === "ok" ? "✓" : "!"}
                            </Link>
                          ) : (
                            <span
                              className={future ? "text-slate-200" : "text-slate-300"}
                              title={future ? "Not due yet" : `${name}: no statement`}
                            >
                              ·
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-slate-500">
          ✓ statement uploaded and reconciled · ! needs review · · no statement. A statement
          counts for the month its period ends in and for every month wholly inside its period,
          so a long statement fills each month it spans.
        </p>
      </section>
    </section>
  );
}

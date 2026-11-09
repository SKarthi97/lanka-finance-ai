"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CardSkeleton, LoadError, RowsSkeleton } from "@/components/states";
import { Sparkline } from "@/components/Sparkline";
import { StatementTracker } from "@/components/StatementTracker";
import { BalanceChart, IncomeExpenseChart } from "@/components/TrendCharts";
import { loadPref, savePref } from "@/lib/prefs";
import { api, BankTotal, CategoryTotal, Dashboard, Tracker, Totals, Trend } from "@/lib/api";
import {
  MONTHS,
  MONTHS_LONG,
  NO_ACCOUNT_HINT,
  bankTint,
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
  // A coloured top edge says good, bad or neutral before the number is read.
  const edge = tone === "good" ? "border-t-green-700" : tone === "bad" ? "border-t-red-700" : "border-t-accent";
  return (
    <div className={`rounded border border-t-2 border-slate-200 bg-surface p-4 shadow-sm ${edge}`}>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
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
  byBank,
  level = 2,
  show = "both",
  children,
}: {
  show?: "totals" | "categories" | "both"; // which parts of the block to draw
  level?: 2 | 3; // heading level: 3 when this block sits inside another section
  children?: React.ReactNode; // extra content shown after the category bars
  byBank?: BankTotal[]; // income and expense per bank; drawn only when there is more than one
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
  const Heading = level === 3 ? "h3" : "h2";
  const Sub = level === 3 ? "h4" : "h3";
  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-3">
        <Heading className={level === 3 ? "text-sm font-medium text-slate-700" : "font-medium"}>{title}</Heading>
        {action}
      </div>
      {show !== "categories" && (
      <>
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

      {byBank && byBank.length > 1 && (
        <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-surface">
          <table className="w-full text-sm">
            <caption className="sr-only">Income and expense by bank</caption>
            <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
              <tr>
                <th className="px-3 py-1.5 font-medium">Bank</th>
                <th className="px-3 py-1.5 text-right font-medium">Income</th>
                <th className="px-3 py-1.5 text-right font-medium">Expense</th>
                <th className="px-3 py-1.5 text-right font-medium">Net</th>
              </tr>
            </thead>
            <tbody>
              {byBank.map((b) => (
                <tr key={b.bank_code ?? "none"} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-1.5">
                    <span className={`mr-2 rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(b.bank_code)}`}>
                      {b.bank_code ?? "?"}
                    </span>
                    {b.bank_name ?? "Unknown bank"}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-green-700">{formatMoney(b.income)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-red-700">{formatMoney(b.expense)}</td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${Number(b.net) < 0 ? "text-red-700" : ""}`}>
                    {formatMoney(b.net)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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

      </>
      )}

      {show !== "totals" && (
        <div className={show === "categories" ? "" : "mt-3"}>
          <Sub className="mb-1 text-sm text-slate-600">Spending by category</Sub>
          {byCategory && <CategoryBars items={byCategory} filter={filter} />}
        </div>
      )}
      {children}
    </section>
  );
}

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "accounts", label: "Accounts" },
  { id: "cashflow", label: "Cash flow" },
  { id: "spending", label: "Spending" },
  { id: "statements", label: "Statements" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function DashboardPage() {
  const now = new Date();
  const [tab, setTab] = useState<TabId>("overview");
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
    const savedBank = loadPref("dashBank");
    if (savedBank) setBank(savedBank);
    const savedTab = loadPref("dashTab");
    if (TABS.some((t) => t.id === savedTab)) setTab(savedTab as TabId);
  }, []);

  function chooseTab(next: TabId) {
    setTab(next);
    savePref("dashTab", next);
  }

  function chooseBank(code: string) {
    setBank(code);
    savePref("dashBank", code);
  }

  // A remembered bank filter that no longer exists would leave the dashboard empty with no
  // control to undo it, so drop it.
  useEffect(() => {
    if (bank && dash && !dash.banks.some((b) => b.code === bank)) setBank("");
  }, [bank, dash]);

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
  // Always name the period: "This month" is ambiguous once the pickers change it.
  const monthTitle = `${MONTHS_LONG[month - 1]} ${year}${isNow ? " (this month)" : ""}`;
  const yearTitle = `${year} totals${year === now.getFullYear() ? " (this year)" : ""}`;

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

  // Months without a statement between an account's first and last statement (every year), and
  // places where one statement's closing balance is not the next one's opening.
  const missingMonths = dash?.coverage.gap_months ?? 0;
  const balanceBreaks = dash?.coverage.balance_breaks ?? 0;

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
          {missingMonths} month{missingMonths === 1 ? "" : "s"} without a statement, between statements
          you have.{" "}
          <button onClick={() => chooseTab("statements")} className="underline">
            See the tracker
          </button>
        </>
      ),
    });
  if (balanceBreaks > 0)
    attention.push({
      key: "breaks",
      text: (
        <>
          {balanceBreaks} place{balanceBreaks === 1 ? "" : "s"} where a statement does not start from the
          previous one’s closing balance, so some transactions may be missing.{" "}
          <button onClick={() => chooseTab("statements")} className="underline">
            See where
          </button>
        </>
      ),
    });
  if (dash && dash.transfer_suggestions > 0)
    attention.push({
      key: "transfers",
      text: (
        <>
          {dash.transfer_suggestions} possible transfer{dash.transfer_suggestions === 1 ? "" : "s"} between
          your own accounts, counted as income and expense until you confirm.{" "}
          <Link href="/categories?tab=transfers" className="underline">
            Review
          </Link>
        </>
      ),
    });

  const monthFilter = `${bankParam}&year=${year}&month=${month}`;
  const kpiMonthLabel = latestPeriod ? `${MONTHS_LONG[latestPeriod[1] - 1]} ${latestPeriod[0]}` : null;
  const kpiYearLabel = latestPeriod ? String(latestPeriod[0]) : null;
  const yearFilter = `${bankParam}&year=${year}`;

  const totalBalance = Number(dash?.total_balance ?? 0); // display only
  const accountDays = (asOf: string | null | undefined) =>
    asOf ? Math.floor((now.getTime() - new Date(`${asOf}T00:00:00`).getTime()) / 86_400_000) : null;

  function onTabKeys(event: React.KeyboardEvent, index: number) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = TABS[(index + step + TABS.length) % TABS.length].id;
    chooseTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  }

  const attentionList = (items: { key: string; text: React.ReactNode }[]) =>
    items.length > 0 && (
      <section aria-labelledby="attention-heading">
        <h2 id="attention-heading" className="sr-only">
          Needs your attention
        </h2>
        <ul role="status" className="space-y-2">
          {items.map((a) => (
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
    );

  const periodBar = (showMonth: boolean) => (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-slate-600">Period</span>
      <select aria-label="Year" value={year} onChange={(e) => setYear(Number(e.target.value))} className={select}>
        {years.map((y) => (
          <option key={y} value={y}>
            {y}
          </option>
        ))}
      </select>
      {showMonth && (
        <select aria-label="Month" value={month} onChange={(e) => setMonth(Number(e.target.value))} className={select}>
          {MONTHS_LONG.map((name, index) => (
            <option key={name} value={index + 1}>
              {name}
            </option>
          ))}
        </select>
      )}
    </div>
  );

  const emptyNotice = emptyPeriod && (
    <p className="rounded bg-slate-100 px-4 py-3 text-sm text-slate-700">
      No transactions in {MONTHS_LONG[month - 1]} {year}. Your latest statement ends {formatDate(dash?.as_of)}.{" "}
      <button onClick={jumpToLatest} className="underline">
        Show that period
      </button>
    </p>
  );

  const bankChip = (active: boolean) =>
    `rounded-full border px-3 py-1 text-sm ${
      active ? "border-accent bg-accent text-accent-fg" : "border-slate-300 bg-surface hover:bg-slate-100"
    }`;

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <div className="flex flex-wrap items-center justify-between gap-3">
        {(dash?.banks.length ?? 0) > 1 ? (
          <div role="group" aria-label="Show figures for" className="flex flex-wrap items-center gap-1.5">
            <button type="button" aria-pressed={bank === ""} onClick={() => chooseBank("")} className={bankChip(bank === "")}>
              All banks
            </button>
            {dash?.banks.map((b) => (
              <button
                key={b.code}
                type="button"
                aria-pressed={bank === b.code}
                onClick={() => chooseBank(b.code)}
                className={bankChip(bank === b.code)}
              >
                {b.name}
              </button>
            ))}
          </div>
        ) : (
          <span />
        )}
        <button
          onClick={toggleHidden}
          aria-pressed={hidden}
          className={`${select} text-sm`}
          title="Hide every amount, for screen sharing"
        >
          {hidden ? "Show amounts" : "Hide amounts"}
        </button>
      </div>

      {!dash ? (
        dashFailed ? (
          <LoadError message="Could not load the dashboard." onRetry={() => setReload((n) => n + 1)} />
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
          </div>
        )
      ) : !dash.has_data ? (
        <section className="max-w-2xl rounded border border-slate-200 bg-surface p-5">
          <h2 className="mb-1 font-medium">Welcome — let’s get your first statement in</h2>
          <p className="mb-4 text-sm text-slate-600">Nothing to show yet. Everything stays on this computer.</p>
          <ol className="space-y-3 text-sm">
            {[
              {
                title: "Upload a bank statement PDF",
                text: "Drag a statement onto the Upload page. It is read and checked against its balances.",
                href: "/upload",
                action: "Go to Upload",
              },
              {
                title: "Review anything that did not reconcile",
                text:
                  dash.needs_review > 0
                    ? `${dash.needs_review} statement${dash.needs_review === 1 ? "" : "s"} waiting for your review.`
                    : "Statements whose balances do not add up wait for your check before they count.",
                href: "/upload",
                action: "Open statements",
              },
              {
                title: "Sort transactions into categories",
                text: "Rules and the local AI suggest categories; you confirm or correct them.",
                href: "/categories",
                action: "Open Categories",
              },
            ].map((step, index) => (
              <li key={step.title} className="flex gap-3">
                <span
                  aria-hidden="true"
                  className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-fg"
                >
                  {index + 1}
                </span>
                <div>
                  <p className="font-medium">{step.title}</p>
                  <p className="text-slate-600">{step.text}</p>
                  <Link href={step.href} className="text-accent underline">
                    {step.action}
                  </Link>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : (
        <>
          <div role="tablist" aria-label="Dashboard sections" className="flex flex-wrap gap-1 border-b border-slate-200">
            {TABS.map((t, index) => {
              const active = tab === t.id;
              const badge = t.id === "statements" ? dash.needs_review : 0;
              return (
                <button
                  key={t.id}
                  id={`tab-${t.id}`}
                  role="tab"
                  type="button"
                  aria-selected={active}
                  aria-controls={`panel-${t.id}`}
                  tabIndex={active ? 0 : -1}
                  onClick={() => chooseTab(t.id)}
                  onKeyDown={(e) => onTabKeys(e, index)}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                    active
                      ? "border-accent font-medium"
                      : "border-transparent text-slate-600 hover:border-slate-300"
                  }`}
                >
                  {t.label}
                  {badge > 0 && (
                    <span
                      className="ml-1.5 rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-black"
                      title={`${badge} statement${badge === 1 ? "" : "s"} need review`}
                    >
                      {badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="space-y-6 pt-2">
            {tab === "overview" && (
              <>
                {attentionList(attention)}
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Card
                    label="Total across accounts (LKR)"
                    value={formatMoney(dash.total_balance)}
                    hint={
                      dash.as_of
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

                <section>
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <h2 className="font-medium">Balance at the end of each month, {year}</h2>
                    <button onClick={() => chooseTab("cashflow")} className="text-sm text-accent underline">
                      Cash flow details
                    </button>
                  </div>
                  <div className="rounded border border-slate-200 bg-surface p-4">
                    {trend ? (
                      <BalanceChart months={trend.months} />
                    ) : trendFailed ? (
                      <LoadError message="Could not load the chart." onRetry={() => setReload((n) => n + 1)} />
                    ) : (
                      <RowsSkeleton rows={5} />
                    )}
                  </div>
                </section>

                <p className="text-sm text-slate-600">
                  {(dash.balances ?? []).length} account{(dash.balances ?? []).length === 1 ? "" : "s"}.{" "}
                  <button onClick={() => chooseTab("accounts")} className="text-accent underline">
                    See each account
                  </button>
                </p>
              </>
            )}

            {tab === "accounts" && (
              <section>
                <h2 className="mb-2 font-medium">Accounts</h2>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {(dash.balances ?? []).map((b, index) => {
                    const days = accountDays(b.as_of);
                    const old = days !== null && days > 45;
                    const share = totalBalance > 0 && Number(b.balance) > 0 ? (Number(b.balance) / totalBalance) * 100 : 0;
                    return (
                      <article
                        key={index}
                        className={`rounded border border-l-2 border-slate-200 bg-surface p-4 shadow-sm ${
                          old ? "border-l-amber-400" : "border-l-green-700"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <span className={`rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(b.bank_code)}`}>
                              {b.bank_code ?? "?"}
                            </span>
                            {b.account_last4 ? (
                              <span className="ml-2 text-xs text-slate-500">•••• {b.account_last4}</span>
                            ) : (
                              <span className="ml-2 text-xs text-slate-400" title={NO_ACCOUNT_HINT}>
                                account not detected
                              </span>
                            )}
                          </div>
                          {old && (
                            <span
                              className="rounded bg-amber-100 px-1.5 text-xs text-amber-800"
                              title="The latest statement for this account is more than 45 days old"
                            >
                              out of date
                            </span>
                          )}
                        </div>
                        <div className="mt-2 flex items-end justify-between gap-2">
                          <div className="text-xl font-semibold tabular-nums">{formatMoney(b.balance)}</div>
                          <Sparkline
                            values={b.history.map((p) => Number(p.balance))}
                            label={`Month-end balance, last ${b.history.length} months`}
                          />
                        </div>
                        <div className="text-xs text-slate-500">
                          As of {formatDate(b.as_of)}
                          {days !== null ? ` (${days} days ago)` : ""}
                        </div>
                        {b.change !== null && b.change_month !== null && (
                          <div
                            className={`mt-1 text-xs tabular-nums ${Number(b.change) < 0 ? "text-red-700" : Number(b.change) > 0 ? "text-green-700" : "text-slate-500"}`}
                          >
                            {Number(b.change) > 0 ? "▲" : Number(b.change) < 0 ? "▼" : "•"} {formatMoney(b.change)} in{" "}
                            {MONTHS_LONG[b.change_month - 1]}
                          </div>
                        )}
                        <div className="mt-2 h-1.5 rounded bg-slate-100" aria-hidden="true">
                          <div className="h-1.5 rounded bg-accent" style={{ width: `${Math.max(share, share > 0 ? 1 : 0)}%` }} />
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{share.toFixed(0)}% of the total</div>
                        <div className="mt-3 flex gap-3 text-sm">
                          {b.bank_code && (
                            <>
                              <button onClick={() => chooseBank(b.bank_code as string)} className="text-accent underline">
                                Show only this bank
                              </button>
                              <Link href={`/transactions?bank_code=${encodeURIComponent(b.bank_code)}`} className="text-accent underline">
                                Transactions
                              </Link>
                            </>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
                <p className="mt-3 text-xs text-slate-500">
                  Each balance is the closing balance of that account’s latest reconciled or accepted statement,
                  not a live balance.
                </p>
              </section>
            )}

            {tab === "cashflow" && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="font-medium">Year {year}: income, expense and balance</h2>
                    <p className="text-xs text-slate-500">Click a month in the chart to see it below.</p>
                  </div>
                  {periodBar(true)}
                </div>
                {emptyNotice}
                {trend ? (
                  <div className="grid gap-3 lg:grid-cols-2">
                    <div className="rounded border border-slate-200 bg-surface p-4">
                      <h3 className="mb-1 text-sm text-slate-600">Income and expense by month</h3>
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
                      <h3 className="mb-1 text-sm text-slate-600">Balance at the end of each month</h3>
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
                <PeriodCards
                  show="totals"
                  title={monthTitle}
                  totals={dash.month}
                  byCategory={dash.month_by_category}
                  byBank={dash.month_by_bank}
                  previous={dash.previous_month}
                  previousLabel={previousLabel}
                  filter={monthFilter}
                />
                <PeriodCards
                  show="totals"
                  level={3}
                  title={yearTitle}
                  totals={dash.year}
                  byCategory={dash.year_by_category}
                  byBank={dash.year_by_bank}
                  filter={yearFilter}
                />
                <p className="text-xs text-slate-500">
                  Income and expense come from reconciled or accepted statements, without transfers between your own
                  accounts. A transaction that appears in two overlapping statements counts once.
                </p>
              </>
            )}

            {tab === "spending" && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 className="font-medium">Spending</h2>
                  {periodBar(true)}
                </div>
                {emptyNotice}
                <PeriodCards
                  show="categories"
                  level={3}
                  title={monthTitle}
                  totals={dash.month}
                  byCategory={dash.month_by_category}
                  filter={monthFilter}
                >
                  {dash.top_expenses.length > 0 && (
                    <div className="mt-4">
                      <h4 className="mb-1 text-sm text-slate-600">Largest expenses</h4>
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
                    </div>
                  )}
                </PeriodCards>
                <PeriodCards
                  show="categories"
                  level={3}
                  title={yearTitle}
                  totals={dash.year}
                  byCategory={dash.year_by_category}
                  filter={yearFilter}
                />
              </>
            )}

            {tab === "statements" && (
              <>
                {attentionList(attention.filter((a) => ["review", "stale", "gaps", "breaks"].includes(a.key)))}
                <StatementTracker bank={bank} />
                <p className="text-sm">
                  <Link href="/upload" className="text-accent underline">
                    Upload a statement
                  </Link>
                </p>
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}

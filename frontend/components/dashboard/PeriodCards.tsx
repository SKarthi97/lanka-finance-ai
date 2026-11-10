"use client";

import Link from "next/link";
import { BankTotal, CategoryTotal, Totals } from "@/lib/api";
import { rollUp } from "@/lib/rollup";
import { bankTint, compareText, formatMoney } from "@/lib/format";

export function Card({
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

export function CategoryBars({ items, filter }: { items: CategoryTotal[]; filter: string }) {
  // Spending by category, transfers excluded. The biggest few, then the rest.
  const spending = rollUp(items)
    .filter((c) => c.kind !== "transfer" && Number(c.expense) > 0)
    .sort((a, b) => Number(b.expense) - Number(a.expense));
  if (spending.length === 0) return null;

  const total = spending.reduce((sum, c) => sum + Number(c.expense), 0); // display only
  const top = spending.slice(0, 8);
  const rest = spending.slice(8);
  const rows = rest.length
    ? [...top, { ...rest[0], children: [], category_id: -1, name: `${rest.length} more`, expense: String(rest.reduce((n, c) => n + Number(c.expense), 0)) }]
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
            {"children" in c && (c as { children: CategoryTotal[] }).children.length > 0 && (
              <div className="text-xs text-slate-500">
                {(c as { children: CategoryTotal[] }).children
                  .filter((k) => Number(k.expense) > 0)
                  .map((k) => `${k.name} ${formatMoney(k.expense)}`)
                  .join(" · ")}
              </div>
            )}
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
export function savingRate(totals: Totals): string | null {
  const income = Number(totals.income);
  const net = Number(totals.net);
  return totals.transactions > 0 && income > 0 && net >= 0 ? `${Math.round((net / income) * 100)}%` : null;
}

export function savingNote(totals: Totals): string | null {
  if (totals.transactions === 0) return null;
  if (Number(totals.income) === 0) return "no income";
  if (Number(totals.net) < 0) return "spent more than earned";
  return `saved ${savingRate(totals)} of income`;
}

export function PeriodCards({
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

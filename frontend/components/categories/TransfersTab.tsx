"use client";

import { RowsSkeleton } from "@/components/states";
import { TransferSuggestions, api } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import { primary, subtle, Run } from "@/components/categories/shared";

export function TransfersTab({ data, run }: { data: TransferSuggestions | null; run: Run }) {
  if (!data) return <RowsSkeleton />;

  const who = (side: { bank_code: string | null; account_last4: string | null }) =>
    `${(side.bank_code ?? "?").toUpperCase()}${side.account_last4 ? ` •••• ${side.account_last4}` : ""}`;

  function decide(kind: "confirm" | "reject", out: number, into: number) {
    return run(async () => {
      const result = await api<{ category_name: string } | void>(`/transfers/${kind}`, {
        method: "POST",
        json: { out_id: out, in_id: into },
      });
      return kind === "confirm" && result
        ? `Filed both as ${result.category_name}. They no longer count as income or expense.`
        : "Marked as not a transfer. It will not be suggested again.";
    });
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        Each pair below is a debit in one account and a credit of exactly the same amount in another,
        within {data.window_days} days. If it is you moving your own money, confirm it: both sides are
        filed as Transfers and leave income and expense. Nothing changes until you confirm.
      </p>
      {data.total === 0 ? (
        <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
          No possible transfers found. They appear when two of your accounts have statements covering the
          same days.
        </p>
      ) : (
        <ul className="space-y-3">
          {data.items.map((pair) => (
            <li key={`${pair.out.id}-${pair.into.id}`} className="rounded border border-slate-200 bg-surface p-3 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-base font-semibold tabular-nums">{formatMoney(pair.amount)}</span>
                <span className="text-xs text-slate-500">
                  {pair.days_apart === 0 ? "same day" : `${pair.days_apart} day${pair.days_apart === 1 ? "" : "s"} apart`}
                </span>
              </div>
              <dl className="mt-2 grid gap-1 sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-slate-500">Left</dt>
                  <dd>
                    {who(pair.out)} · {formatDate(pair.out.transaction_date)}
                    <div className="break-words text-slate-600">{pair.out.description}</div>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Arrived</dt>
                  <dd>
                    {who(pair.into)} · {formatDate(pair.into.transaction_date)}
                    <div className="break-words text-slate-600">{pair.into.description}</div>
                  </dd>
                </div>
              </dl>
              {pair.ambiguous && (
                <p className="mt-2 text-xs text-amber-700">
                  Another row of the same amount could also be the other half. Check the dates before
                  confirming.
                </p>
              )}
              <div className="mt-3 flex gap-2">
                <button type="button" className={primary} onClick={() => decide("confirm", pair.out.id, pair.into.id)}>
                  Yes, my own accounts
                </button>
                <button type="button" className={subtle} onClick={() => decide("reject", pair.out.id, pair.into.id)}>
                  Not a transfer
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

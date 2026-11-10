"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LoadError, RowsSkeleton } from "@/components/states";
import { api, IrdReport as Ird } from "@/lib/api";
import { MONTHS, bankTint, formatDate, formatMoney } from "@/lib/format";

const select = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";
const th = "px-3 py-1.5 font-medium";
const LINE_TITLE: Record<string, string> = {
  employment: "Salary and wage credits",
  interest: "Interest credits",
  dividends: "Dividend credits",
  tax: "Tax lines (withheld on interest and dividends, and other)",
};

// A year of assessment is named by the calendar year it starts in: 2025 is 2025/26, April to March.
function currentYear(): number {
  const now = new Date();
  return now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
}
const label = (y: number) => `${y}/${String(y + 1).slice(-2)}`;

export function IrdReport() {
  const [year, setYear] = useState(currentYear());
  const [data, setData] = useState<Ird | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setFailed(false);
    setData(null);
    api<Ird>(`/reports/ird?year=${year}`)
      .then(setData)
      .catch(() => setFailed(true));
  }, [year, attempt]);

  const years = Array.from({ length: 7 }, (_, i) => currentYear() - i);
  const head = (key: string) => data?.heads.find((h) => h.key === key);
  const money = (v: string | undefined) => (v === undefined ? "–" : formatMoney(v));
  const missing = (data?.coverage ?? []).filter((c) => c.missing.length > 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 print:hidden">
        <div className="flex items-center overflow-hidden rounded border border-slate-300 text-sm">
          <button type="button" onClick={() => setYear(year - 1)} aria-label="Earlier year" className="px-2.5 py-1.5 hover:bg-slate-100">
            ‹
          </button>
          <span className="border-x border-slate-300 px-3 py-1.5 tabular-nums">{label(year)}</span>
          <button
            type="button"
            onClick={() => setYear(year + 1)}
            disabled={year >= currentYear()}
            aria-label="Later year"
            className="px-2.5 py-1.5 hover:bg-slate-100 disabled:opacity-40"
          >
            ›
          </button>
        </div>
        <select aria-label="Year of assessment" value={year} onChange={(e) => setYear(Number(e.target.value))} className={select}>
          {years.map((y) => (
            <option key={y} value={y}>
              {label(y)}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => window.print()} className="rounded bg-accent px-3 py-1.5 text-sm text-accent-fg">
          Print / save as PDF
        </button>
        <a
          href={`/api/reports/ird.csv?year=${year}`}
          download={`ird-${year}-${String(year + 1).slice(-2)}.csv`}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
        >
          ⬇ Download CSV
        </a>
      </div>

      <header>
        <h2 className="text-lg font-semibold">Year of assessment {label(year)}</h2>
        <p className="text-xs text-slate-500">
          {data ? `${formatDate(data.period_start)} to ${formatDate(data.period_end)}` : "1 April to 31 March"} · all amounts
          in LKR · from reconciled or accepted statements, transfers between your own accounts and repeated rows left out
        </p>
      </header>

      <p role="note" className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-400">
        These are figures read from your bank statements, sorted by the kind of income. They are not a tax calculation or
        tax advice. Tax an employer deducts (APIT), interest a bank credits already after tax, and anything paid
        outside these accounts are not on a statement. Check the employer&apos;s and bank&apos;s certificates and the current
        IRD rules, reliefs and rates, or ask a tax adviser, before filing.
      </p>

      {failed && <LoadError message="Could not load the IRD figures." onRetry={() => setAttempt((n) => n + 1)} />}
      {!failed && !data && <RowsSkeleton rows={6} />}

      {data && (
        <>
          {(missing.length > 0 ||
            data.review_documents > 0 ||
            data.uncategorised_count > 0 ||
            data.possible_tax_count > 0 ||
            data.coverage.length === 0) && (
            <section aria-label="Things that make these figures incomplete" className="space-y-2">
              {data.coverage.length === 0 && (
                <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-600">
                  No statement in the app covers {label(year)}.
                </p>
              )}
              {missing.map((c, i) => (
                <p key={i} className="rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <span className={`mr-2 rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(c.bank_code)}`}>{c.bank_code ?? "?"}</span>
                  {c.account_last4 ? `•••• ${c.account_last4} ` : ""}has no statement for{" "}
                  {c.missing.map((m) => `${MONTHS[m.month - 1]} ${m.year}`).join(", ")}. Income in those months is not included.{" "}
                  <Link href="/upload" className="underline">
                    Upload
                  </Link>
                </p>
              ))}
              {data.review_documents > 0 && (
                <p className="rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  {data.review_documents} statement{data.review_documents === 1 ? "" : "s"} in this year still need{data.review_documents === 1 ? "s" : ""} review and are not in these figures.
                </p>
              )}
              {data.possible_tax_count > 0 && (
                <p className="rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  {data.possible_tax_count} debit{data.possible_tax_count === 1 ? "" : "s"} totalling {formatMoney(data.possible_tax)} sit
                  right next to an interest or dividend credit but {data.possible_tax_count === 1 ? "is" : "are"} not categorised. They look
                  like tax withheld; set their category to Tax and they will be counted.{" "}
                  <Link href="/categories" className="underline">
                    Review
                  </Link>
                </p>
              )}
              {data.uncategorised_count > 0 && (
                <p className="rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  {data.uncategorised_count} credit{data.uncategorised_count === 1 ? "" : "s"} totalling {formatMoney(data.uncategorised_credits)}{" "}
                  {data.uncategorised_count === 1 ? "is" : "are"} not categorised, so {data.uncategorised_count === 1 ? "it is" : "they are"} not counted as income.{" "}
                  <Link href="/categories" className="underline">
                    Review
                  </Link>
                </p>
              )}
            </section>
          )}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Employment income</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">{money(head("employment")?.amount)}</div>
              <div className="mt-1 text-xs text-slate-500">{head("employment")?.count ?? 0} salary and wage credits</div>
            </div>
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Interest credited</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">{money(head("interest")?.amount)}</div>
              <div className="mt-1 text-xs text-slate-500">
                tax withheld on it:{" "}
                {Number(head("interest")?.tax_withheld ?? 0) === 0 && Number(head("interest")?.amount ?? 0) > 0
                  ? "none found on the statements"
                  : money(head("interest")?.tax_withheld)}
              </div>
            </div>
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Dividends</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">{money(head("dividends")?.amount)}</div>
              <div className="mt-1 text-xs text-slate-500">tax withheld on it: {money(head("dividends")?.tax_withheld)}</div>
            </div>
            <div className="rounded border border-t-2 border-slate-200 border-t-accent bg-surface p-4 shadow-sm">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Other income</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">{money(head("other_income")?.amount)}</div>
              <div className="mt-1 text-xs text-slate-500">income categories not listed above</div>
            </div>
          </div>

          <div className="rounded border border-t-2 border-slate-200 border-t-green-700 bg-surface p-4 shadow-sm">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Total income recorded</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-green-700">{formatMoney(data.total_income)}</div>
              </div>
              <div className="text-sm text-slate-500">
                Tax withheld: {formatMoney(String(Number(head("interest")?.tax_withheld ?? 0) + Number(head("dividends")?.tax_withheld ?? 0)))}
                {Number(data.other_tax) > 0 && <> · other tax lines: {formatMoney(data.other_tax)}</>}
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Employment + interest + dividends + other income. Deposits ({money(head("deposits")?.amount)}) are cash and cheque
              deposits that may be your own money and are not added.
            </p>
          </div>

          <section>
            <h3 className="mb-1 font-medium">Month by month</h3>
            <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <tr>
                    <th className={th}>Month</th>
                    <th className={`${th} text-right`}>Employment</th>
                    <th className={`${th} text-right`}>Interest</th>
                    <th className={`${th} text-right`}>Dividends</th>
                    <th className={`${th} text-right`}>Other income</th>
                    <th className={`${th} text-right`}>Tax withheld</th>
                  </tr>
                </thead>
                <tbody>
                  {data.months.map((m) => {
                    const empty = [m.employment, m.interest, m.dividends, m.other_income, m.tax_withheld].every((v) => Number(v) === 0);
                    return (
                      <tr key={`${m.year}-${m.month}`} className={`border-b border-slate-100 last:border-0 ${empty ? "text-slate-400" : ""}`}>
                        <td className="px-3 py-1.5">
                          {MONTHS[m.month - 1]} {m.year}
                        </td>
                        {[m.employment, m.interest, m.dividends, m.other_income, m.tax_withheld].map((v, i) => (
                          <td key={i} className="px-3 py-1.5 text-right tabular-nums">
                            {Number(v) === 0 ? "–" : formatMoney(v)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot className="border-t border-slate-200 font-medium">
                  <tr>
                    <td className="px-3 py-2">{label(year)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{money(head("employment")?.amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{money(head("interest")?.amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{money(head("dividends")?.amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{money(head("other_income")?.amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {formatMoney(String(Number(head("interest")?.tax_withheld ?? 0) + Number(head("dividends")?.tax_withheld ?? 0)))}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>

          {data.banks.length > 0 && (
            <section>
              <h3 className="mb-1 font-medium">By bank</h3>
              <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
                    <tr>
                      <th className={th}>Bank</th>
                      <th className={`${th} text-right`}>Employment</th>
                      <th className={`${th} text-right`}>Interest</th>
                      <th className={`${th} text-right`}>Tax on interest</th>
                      <th className={`${th} text-right`}>Dividends</th>
                      <th className={`${th} text-right`}>Other income</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.banks.map((b) => (
                      <tr key={b.bank_code ?? "none"} className="border-b border-slate-100 last:border-0">
                        <td className="px-3 py-1.5">
                          <span className={`mr-2 rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(b.bank_code)}`}>{b.bank_code ?? "?"}</span>
                          {b.bank_name ?? "Unknown bank"}
                        </td>
                        {[b.employment, b.interest, b.interest_tax, b.dividends, b.other_income].map((v, i) => (
                          <td key={i} className="px-3 py-1.5 text-right tabular-nums">
                            {Number(v) === 0 ? "–" : formatMoney(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {data.by_category.length > 0 && (
            <section>
              <h3 className="mb-1 font-medium">Income by category</h3>
              <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-surface text-sm">
                {data.by_category.map((c) => (
                  <li key={`${c.head}-${c.category}`} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
                    <span>
                      {c.category} <span className="text-xs text-slate-500">· {data.heads.find((h) => h.key === c.head)?.label}</span>
                    </span>
                    <span className="tabular-nums">{formatMoney(c.amount)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(["employment", "interest", "dividends", "tax"] as const).map((kind) => {
            const items = data.lines.filter((l) => l.kind === kind);
            if (items.length === 0) return null;
            return (
              <details key={kind} className="rounded border border-slate-200 bg-surface">
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium hover:bg-slate-100">
                  {LINE_TITLE[kind]} <span className="font-normal text-slate-500">({items.length})</span>
                </summary>
                <ul className="divide-y divide-slate-100 border-t border-slate-200 text-sm">
                  {items.map((l, i) => (
                    <li key={i} className="flex items-baseline justify-between gap-3 px-3 py-1.5">
                      <span className="min-w-0 break-words">
                        <span className="text-xs text-slate-500">{formatDate(l.date)}</span>{" "}
                        <span className={`mx-1 rounded px-1.5 py-0.5 text-xs uppercase ${bankTint(l.bank_code)}`}>{l.bank_code ?? "?"}</span>
                        {l.account_last4 && <span className="text-xs text-slate-500">•••• {l.account_last4} </span>}
                        {l.description}
                      </span>
                      <span className="shrink-0 tabular-nums">{formatMoney(l.amount)}</span>
                    </li>
                  ))}
                </ul>
              </details>
            );
          })}
        </>
      )}
    </div>
  );
}

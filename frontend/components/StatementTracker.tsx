"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, Tracker } from "@/lib/api";
import { MONTHS, NO_ACCOUNT_HINT, bankTint, formatDate, formatMoney } from "@/lib/format";

// One small square per month. A glyph goes with each colour so the state never relies on colour alone.
const SQUARE = "inline-flex h-7 w-7 items-center justify-center rounded text-sm font-semibold";

function Legend({ glyph, cls, text }: { glyph: string; cls: string; text: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className={`inline-flex h-5 w-5 items-center justify-center rounded text-xs font-semibold ${cls}`}>
        {glyph}
      </span>
      {text}
    </span>
  );
}

/** Which months have a statement, per bank and account. `refreshKey` reloads it after uploads. */
export function StatementTracker({ refreshKey = "", bank = "" }: { refreshKey?: string; bank?: string }) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [tracker, setTracker] = useState<Tracker | null>(null);
  const chosen = useRef(false); // the user picked a year, so do not jump away from it

  useEffect(() => {
    api<Tracker>(`/tracker?year=${year}`)
      .then((result) => {
        setTracker(result);
        // First load only: if this year has nothing, open the latest year that has data.
        const empty = result.rows.every((r) => Object.keys(r.cells).length === 0);
        const latest = result.years.filter((y) => y !== year).sort((a, b) => b - a)[0];
        if (!chosen.current && empty && latest !== undefined && result.rows.length === 0) {
          chosen.current = true;
          setYear(latest);
        }
      })
      .catch(() => setTracker(null));
  }, [year, refreshKey]);

  const rows = (tracker?.rows ?? []).filter((r) => !bank || r.bank_code === bank);
  const years = tracker?.years ?? [year];
  const position = years.indexOf(year);
  function move(by: number) {
    const target = years[position + by];
    if (target !== undefined) {
      chosen.current = true;
      setYear(target);
    }
  }

  const missing = rows.reduce((n, r) => n + r.gap_months.length, 0);
  const review = rows.reduce((n, r) => n + Object.values(r.cells).filter((c) => c.status !== "ok").length, 0);
  const breaks = rows.reduce((n, r) => n + r.breaks.length, 0);

  return (
    <section id="tracker">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-medium">Statement tracker</h2>
          {rows.length > 0 && (
            <span className="flex flex-wrap gap-1.5 text-xs">
              {missing === 0 && review === 0 && breaks === 0 ? (
                <span className="rounded bg-green-50 px-2 py-0.5 text-green-800">Nothing missing</span>
              ) : (
                <>
                  {missing > 0 && (
                    <span className="rounded bg-red-50 px-2 py-0.5 text-red-700">
                      {missing} missing month{missing === 1 ? "" : "s"}
                    </span>
                  )}
                  {review > 0 && (
                    <span className="rounded bg-amber-50 px-2 py-0.5 text-amber-400">{review} to review</span>
                  )}
                  {breaks > 0 && (
                    <span className="rounded bg-amber-50 px-2 py-0.5 text-amber-400">
                      {breaks} balance break{breaks === 1 ? "" : "s"}
                    </span>
                  )}
                </>
              )}
            </span>
          )}
        </div>
        <div className="flex items-center overflow-hidden rounded border border-slate-300 text-sm">
          <button
            type="button"
            onClick={() => move(-1)}
            disabled={position <= 0}
            aria-label="Earlier year"
            className="px-2.5 py-1 hover:bg-slate-100 disabled:opacity-40"
          >
            ‹
          </button>
          <span aria-live="polite" className="border-x border-slate-300 px-3 py-1 tabular-nums">
            {year}
          </span>
          <button
            type="button"
            onClick={() => move(1)}
            disabled={position < 0 || position >= years.length - 1}
            aria-label="Later year"
            className="px-2.5 py-1 hover:bg-slate-100 disabled:opacity-40"
          >
            ›
          </button>
        </div>
      </div>

      {!tracker || rows.length === 0 ? (
        <p className="rounded border border-slate-200 bg-surface px-4 py-3 text-sm text-slate-500">
          Nothing to track yet. Each uploaded statement ticks its month here.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
          <table className="w-full text-center text-sm">
            <thead className="border-b border-slate-200 text-xs text-slate-600">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Account</th>
                {MONTHS.map((name, i) => {
                  const current = tracker.year === now.getFullYear() && i === now.getMonth();
                  return (
                    <th
                      key={name}
                      className={`px-1 py-2 font-medium ${current ? "text-accent" : ""}`}
                      aria-current={current ? "date" : undefined}
                    >
                      {name}
                    </th>
                  );
                })}
                <th className="px-3 py-2 text-right font-medium">Covered</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const covered = Object.keys(row.cells).length;
                return (
                  <tr key={index} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                    <td className="whitespace-nowrap px-3 py-2 text-left">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(row.bank_code)}`}>
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
                        <td key={name} className="px-1 py-1.5">
                          {cell ? (
                            <Link
                              href={`/documents/${cell.document_id}`}
                              title={cell.status === "ok" ? `${name}: statement reconciled` : `${name}: needs review`}
                              aria-label={`${name} ${tracker.year}: ${cell.status === "ok" ? "statement uploaded" : "needs review"}`}
                              className={`${SQUARE} hover:opacity-80 ${
                                cell.status === "ok" ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-400"
                              }`}
                            >
                              {cell.status === "ok" ? "✓" : "!"}
                            </Link>
                          ) : row.gap_months.includes(i + 1) ? (
                            <span
                              className={`${SQUARE} bg-red-50 text-red-700`}
                              title={`${name}: no statement, between two statements you have`}
                              aria-label={`${name} ${tracker.year}: missing`}
                            >
                              ✗
                            </span>
                          ) : (
                            <span
                              className={`${SQUARE} font-normal ${future ? "text-slate-200" : "text-slate-300"}`}
                              title={future ? "Not due yet" : `${name}: no statement`}
                            >
                              ·
                            </span>
                          )}
                        </td>
                      );
                    })}
                    <td className="whitespace-nowrap px-3 py-2 text-right text-xs tabular-nums text-slate-500">
                      {covered}/12
                      <div className="ml-auto mt-1 h-1 w-14 rounded bg-slate-100" aria-hidden="true">
                        <div
                          className={`h-1 rounded ${row.gap_months.length > 0 ? "bg-red-500" : "bg-green-700"}`}
                          style={{ width: `${(covered / 12) * 100}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {rows.some((r) => r.breaks.length > 0) && (
        <ul className="mt-2 space-y-1 text-sm text-amber-900">
          {rows.flatMap((row) =>
            row.breaks.map((b) => (
              <li
                key={`${b.from_document_id}-${b.to_document_id}`}
                className="rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 px-3 py-2"
              >
                <span className="font-medium uppercase">{row.bank_code ?? "?"}</span>
                {row.account_last4 ? ` •••• ${row.account_last4}` : ""}: the statement that begins{" "}
                {formatDate(b.on)} opens at {formatMoney(b.found)}, but the one before it closed at{" "}
                {formatMoney(b.expected)}.{" "}
                <Link href={`/documents/${b.from_document_id}`} className="underline">
                  Earlier
                </Link>{" "}
                ·{" "}
                <Link href={`/documents/${b.to_document_id}`} className="underline">
                  Later
                </Link>
              </li>
            )),
          )}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <Legend glyph="✓" cls="bg-green-50 text-green-700" text="uploaded and reconciled" />
        <Legend glyph="!" cls="bg-amber-50 text-amber-400" text="needs review" />
        <Legend glyph="✗" cls="bg-red-50 text-red-700" text="missing between two statements" />
        <Legend glyph="·" cls="text-slate-300" text="no statement" />
      </div>
      <p className="mt-1 text-xs text-slate-500">
        A statement counts for the month its period ends in and for every month wholly inside its period, so a long
        statement fills each month it spans.
      </p>
    </section>
  );
}

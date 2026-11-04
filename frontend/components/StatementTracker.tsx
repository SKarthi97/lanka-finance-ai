"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, Tracker } from "@/lib/api";
import { MONTHS, NO_ACCOUNT_HINT } from "@/lib/format";

const select = "rounded border border-slate-300 bg-surface px-2 py-1 text-sm";

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

  return (
    <section id="tracker">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-medium">Statement tracker</h2>
        <select
          aria-label="Tracker year"
          value={year}
          onChange={(e) => {
            chosen.current = true;
            setYear(Number(e.target.value));
          }}
          className={select}
        >
          {(tracker?.years ?? [year]).map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>

      {!tracker || rows.length === 0 ? (
        <p className="text-sm text-slate-500">
          Nothing to track yet. Each uploaded statement ticks its month here.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
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
              {rows.map((row, index) => (
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
        ✓ statement uploaded and reconciled · ! needs review · · no statement. A statement counts
        for the month its period ends in and for every month wholly inside its period, so a long
        statement fills each month it spans.
      </p>
    </section>
  );
}

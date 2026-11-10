"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";

const MESSAGES: Record<string, string> = {
  csv_no_header: "No header row found. The first rows need column names such as Date, Description, Debit, Credit, Balance.",
  csv_no_description: "No description column found (Description, Details, Narration or Particulars).",
  csv_no_amount: "No amount columns found (Debit and Credit, or one Amount column).",
  csv_bad_date: "A date could not be read (use day/month/year or year-month-day).",
  csv_bad_amount: "An amount could not be read.",
  csv_bad_balance: "A balance could not be read.",
  opening_balance_needed: "Enter the opening balance (the balance before the first row), or fill the balance of every row.",
  row_amounts_invalid: "Each row needs either a debit or a credit, not both and not neither.",
  too_many_rows: "Too many rows in one import (the limit is 5,000).",
  no_rows: "There are no rows to import.",
  duplicate: "These same rows were already imported.",
  unknown_bank: "Unknown bank.",
  too_large: "The file is too large.",
};

const BANKS = [
  { code: "", name: "Not listed / other" },
  { code: "boc", name: "Bank of Ceylon" },
  { code: "hnb", name: "Hatton National Bank" },
  { code: "commercial", name: "Commercial Bank" },
  { code: "sampath", name: "Sampath Bank" },
];

type Draft = { date: string; description: string; debit: string; credit: string; balance: string };
const blank = (): Draft => ({ date: "", description: "", debit: "", credit: "", balance: "" });
const field = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    const code = error.code ?? "";
    const row = typeof error.detail?.row === "number" ? ` (row ${error.detail.row})` : "";
    return `${MESSAGES[code] ?? "The import was refused."}${row}`;
  }
  return "Could not reach the server.";
}

export function ImportPanel({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<"csv" | "manual">("csv");
  const [bank, setBank] = useState("");
  const [account, setAccount] = useState("");
  const [opening, setOpening] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState<Draft[]>([blank(), blank(), blank()]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string; id?: number } | null>(null);

  function finish(result: { document_id: number; status: string }) {
    const review = result.status !== "reconciled";
    setMessage({
      ok: true,
      id: result.document_id,
      text: review ? "Imported, but the figures do not add up: it needs your review." : "Imported and checked: the balances add up.",
    });
    onDone();
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      if (mode === "csv") {
        if (!file) {
          setMessage({ ok: false, text: "Choose a CSV file first." });
          return;
        }
        const form = new FormData();
        form.append("file", file);
        if (bank) form.append("bank_code", bank);
        if (account.trim()) form.append("account_number", account.trim());
        if (opening.trim()) form.append("opening_balance", opening.trim().replace(/,/g, ""));
        finish(await api("/imports/csv", { method: "POST", form }));
      } else {
        const filled = rows.filter((r) => r.date || r.description || r.debit || r.credit);
        const body = {
          bank_code: bank || null,
          account_number: account.trim() || null,
          opening_balance: opening.trim() ? opening.trim().replace(/,/g, "") : null,
          rows: filled.map((r) => ({
            date: r.date,
            description: r.description,
            debit: r.debit.replace(/,/g, "") || "0",
            credit: r.credit.replace(/,/g, "") || "0",
            balance: r.balance.trim() ? r.balance.replace(/,/g, "") : null,
          })),
        };
        finish(await api("/imports/manual", { method: "POST", json: body }));
      }
    } catch (error) {
      setMessage({ ok: false, text: describe(error) });
    } finally {
      setBusy(false);
    }
  }

  const set = (i: number, key: keyof Draft, value: string) =>
    setRows((current) => current.map((r, n) => (n === i ? { ...r, [key]: value } : r)));

  return (
    <details className="rounded border border-slate-200 bg-surface p-4">
      <summary className="cursor-pointer font-medium">No PDF, or a statement the app cannot read? Import a CSV or type the rows</summary>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <p className="text-sm text-slate-600">
          The rows go through the same checks as a PDF: every balance must follow from the amount before it. If they do not, the
          statement is put in review. Dates are read day first.
        </p>
        <div className="flex gap-2 text-sm">
          {(["csv", "manual"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded px-3 py-1.5 ${mode === m ? "bg-accent text-white" : "border border-slate-300"}`}
            >
              {m === "csv" ? "CSV file" : "Type the rows"}
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-sm">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Bank</span>
            <select value={bank} onChange={(e) => setBank(e.target.value)} className={`${field} mt-1 block w-full`}>
              {BANKS.map((b) => (
                <option key={b.code} value={b.code}>{b.name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Account number (optional)</span>
            <input value={account} onChange={(e) => setAccount(e.target.value)} autoComplete="off" className={`${field} mt-1 block w-full`} />
            <span className="text-xs text-slate-500">Only the last 4 digits are kept. It links the rows to the account.</span>
          </label>
          <label className="text-sm">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Opening balance</span>
            <input value={opening} onChange={(e) => setOpening(e.target.value)} inputMode="decimal" placeholder="if the rows have no balance" className={`${field} mt-1 block w-full`} />
          </label>
        </div>

        {mode === "csv" ? (
          <div className="space-y-1 text-sm">
            <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <p className="text-xs text-slate-500">
              First row: column names, for example <code>Date, Description, Debit, Credit, Balance</code> (or one <code>Amount</code>{" "}
              column, negative for money out). Commas, semicolons and tabs all work.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr><th>Date</th><th>Description</th><th>Money out</th><th>Money in</th><th>Balance (optional)</th></tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i}>
                      <td><input type="date" value={r.date} onChange={(e) => set(i, "date", e.target.value)} className={`${field} w-full`} /></td>
                      <td><input value={r.description} onChange={(e) => set(i, "description", e.target.value)} className={`${field} w-full`} /></td>
                      <td><input inputMode="decimal" value={r.debit} onChange={(e) => set(i, "debit", e.target.value)} className={`${field} w-full`} /></td>
                      <td><input inputMode="decimal" value={r.credit} onChange={(e) => set(i, "credit", e.target.value)} className={`${field} w-full`} /></td>
                      <td><input inputMode="decimal" value={r.balance} onChange={(e) => set(i, "balance", e.target.value)} className={`${field} w-full`} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button type="button" onClick={() => setRows((c) => [...c, blank()])} className="text-sm text-accent underline">
              Add a row
            </button>
          </div>
        )}

        <button type="submit" disabled={busy} className="rounded bg-accent px-4 py-2 text-sm text-white disabled:opacity-50">
          {busy ? "Importing…" : "Import"}
        </button>
        {message && (
          <p role="status" className={`rounded px-3 py-2 text-sm ${message.ok ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
            {message.text}{" "}
            {message.id && <Link href={`/documents/${message.id}`} className="underline">Open it</Link>}
          </p>
        )}
      </form>
    </details>
  );
}

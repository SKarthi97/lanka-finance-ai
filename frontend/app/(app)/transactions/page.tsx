"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Pager } from "@/components/Pager";
import { api, ApiError, Bank, Tracker, TransactionList } from "@/lib/api";
import { MONTHS_LONG, formatAmount, formatDate, formatMoney } from "@/lib/format";

const PAGE_SIZES = [25, 50, 100];

const select = "rounded border border-slate-300 px-2 py-2 text-sm bg-white";

export default function TransactionsPage() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [bank, setBank] = useState("");
  const [year, setYear] = useState("");
  const [month, setMonth] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);

  const [banks, setBanks] = useState<Bank[]>([]);
  const [years, setYears] = useState<number[]>([]);
  const [data, setData] = useState<TransactionList | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Bank[]>("/banks").then(setBanks).catch(() => undefined);
    api<Tracker>("/tracker").then((t) => setYears(t.years)).catch(() => undefined);
  }, []);

  // Debounce typing so every keystroke does not hit the API.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String((page - 1) * pageSize),
    });
    if (query) params.set("q", query);
    if (bank) params.set("bank_code", bank);
    if (year) params.set("year", year);
    if (year && month) params.set("month", month);
    if (onlyFlagged) params.set("flagged", "true");

    let cancelled = false;
    api<TransactionList>(`/transactions?${params}`)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load transactions.");
      });
    return () => {
      cancelled = true;
    };
  }, [query, bank, year, month, onlyFlagged, pageSize, page]);

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  // Any filter change returns to the first page.
  const filter = <T,>(setter: (value: T) => void) => (value: T) => {
    setter(value);
    setPage(1);
  };

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Transactions</h1>

      <div className="flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search descriptions"
          aria-label="Search descriptions"
          className="w-56 rounded border border-slate-300 px-3 py-2 text-sm"
        />

        <select
          aria-label="Bank"
          value={bank}
          onChange={(e) => filter(setBank)(e.target.value)}
          className={select}
        >
          <option value="">All banks</option>
          {banks.map((b) => (
            <option key={b.code} value={b.code}>
              {b.name}
            </option>
          ))}
        </select>

        <select
          aria-label="Year"
          value={year}
          onChange={(e) => {
            filter(setYear)(e.target.value);
            if (!e.target.value) setMonth("");
          }}
          className={select}
        >
          <option value="">All years</option>
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>

        <select
          aria-label="Month"
          value={month}
          disabled={!year}
          onChange={(e) => filter(setMonth)(e.target.value)}
          className={`${select} disabled:opacity-50`}
        >
          <option value="">All months</option>
          {MONTHS_LONG.map((name, index) => (
            <option key={name} value={index + 1}>
              {name}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyFlagged}
            onChange={(e) => filter(setOnlyFlagged)(e.target.checked)}
          />
          Only rows needing review
        </label>
      </div>

      {error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
        <span>{total === 0 ? "No matches" : `${from}–${to} of ${total}`}</span>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2">
            Rows per page
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className={select}
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <Pager page={page} pages={pages} onChange={setPage} />
        </div>
      </div>

      {data && data.items.length === 0 ? (
        <p className="text-sm text-slate-500">No transactions found.</p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-600">
              <tr>
                <th className="px-3 py-2 font-medium">Date</th>
                <th className="px-3 py-2 font-medium">Bank</th>
                <th className="px-3 py-2 font-medium">Description</th>
                <th className="px-3 py-2 text-right font-medium">Debit</th>
                <th className="px-3 py-2 text-right font-medium">Credit</th>
                <th className="px-3 py-2 text-right font-medium">Balance</th>
                <th className="px-3 py-2 font-medium">Statement</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((t) => (
                <tr
                  key={t.id}
                  className={`border-b border-slate-100 last:border-0 ${
                    t.validation_status !== "ok" ? "bg-amber-50" : ""
                  }`}
                >
                  <td className="whitespace-nowrap px-3 py-2">{formatDate(t.transaction_date)}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span
                      className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium uppercase"
                      title={t.bank_name ?? undefined}
                    >
                      {t.bank_code ?? "?"}
                    </span>
                    {t.account_last4 && (
                      <span className="ml-1 text-xs text-slate-500">•••• {t.account_last4}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{t.description}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatAmount(t.debit)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatAmount(t.credit)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatMoney(t.running_balance)}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <Link href={`/documents/${t.document_id}`} className="underline">
                      #{t.document_id}
                    </Link>{" "}
                    <span className="text-xs text-slate-500">p{t.source_page}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex justify-end">
        <Pager page={page} pages={pages} onChange={setPage} />
      </div>
    </section>
  );
}

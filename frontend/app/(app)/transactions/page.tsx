"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useConfirm } from "@/components/ConfirmDialog";
import { Pager } from "@/components/Pager";
import { LoadError, RowsSkeleton } from "@/components/states";
import {
  api,
  ApiError,
  Bank,
  CategoryItem,
  CorrectionResult,
  Tracker,
  TransactionItem,
  TransactionList,
} from "@/lib/api";
import {
  MONTHS_LONG,
  NO_ACCOUNT_HINT,
  SOURCE_LABEL,
  formatAmount,
  formatDate,
  formatMoney,
} from "@/lib/format";

const PAGE_SIZES = [25, 50, 100];

const select = "rounded border border-slate-300 px-2 py-2 text-sm bg-surface";

export default function TransactionsPage() {
  const confirm = useConfirm();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [bank, setBank] = useState("");
  const [year, setYear] = useState("");
  const [month, setMonth] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState(""); // "" = all, "none" = uncategorised, else an id
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);

  const [banks, setBanks] = useState<Bank[]>([]);
  const [years, setYears] = useState<number[]>([]);
  const [data, setData] = useState<TransactionList | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Links from the dashboard arrive with filters in the address (?year=&month=&category_id=...).
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("bank_code")) setBank(p.get("bank_code")!);
    if (p.get("year")) setYear(p.get("year")!);
    if (p.get("year") && p.get("month")) setMonth(p.get("month")!);
    if (p.get("uncategorised")) setCategoryFilter("none");
    else if (p.get("category_id")) setCategoryFilter(p.get("category_id")!);
    if (p.get("q")) setSearch(p.get("q")!);
  }, []);

  useEffect(() => {
    api<Bank[]>("/banks").then(setBanks).catch(() => undefined);
    api<CategoryItem[]>("/categories").then(setCategories).catch(() => undefined);
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
    if (categoryFilter === "none") params.set("uncategorised", "true");
    else if (categoryFilter) params.set("category_id", categoryFilter);
    // Repeated transactions (overlapping statements) are hidden unless asked for.
    if (showDuplicates) params.set("duplicates", "show");

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
  }, [query, bank, year, month, onlyFlagged, showDuplicates, categoryFilter, pageSize, page, reloadKey]);

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  async function changeCategory(t: TransactionItem, value: string) {
    const categoryId = value ? Number(value) : null;
    try {
      const result = await api<CorrectionResult>(`/transactions/${t.id}/category`, {
        method: "PUT",
        json: { category_id: categoryId },
      });
      // Offer to learn from the correction when other transactions look the same.
      const learn =
        categoryId !== null &&
        result.similar_count > 0 &&
        (await confirm({
          title: `Use “${result.category_name}” for similar transactions?`,
          message: (
            <>
              {result.similar_count} other transaction{result.similar_count === 1 ? "" : "s"} look like{" "}
              <span className="font-medium text-slate-900">“{result.stem}”</span>. Apply this category
              to {result.similar_count === 1 ? "it" : "them"} and remember it for future statements?
            </>
          ),
          confirmLabel: "Apply to all",
          cancelLabel: "Only this one",
        }));
      if (learn) {
        await api<CorrectionResult>(`/transactions/${t.id}/category`, {
          method: "PUT",
          json: { category_id: categoryId, create_rule: true },
        });
      }
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the category.");
    }
  }

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
          aria-label="Category"
          value={categoryFilter}
          onChange={(e) => filter(setCategoryFilter)(e.target.value)}
          className={select}
        >
          <option value="">All categories</option>
          <option value="none">Uncategorised</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
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

        <label
          className="flex items-center gap-2 text-sm"
          title="A transaction that appears in two overlapping statements is counted once. Tick to see the repeated copies too."
        >
          <input
            type="checkbox"
            checked={showDuplicates}
            onChange={(e) => filter(setShowDuplicates)(e.target.checked)}
          />
          Show duplicates
        </label>
      </div>

      {error && (
        <LoadError
          message={error}
          onRetry={() => {
            setError(null);
            setReloadKey((n) => n + 1);
          }}
        />
      )}
      {!data && !error && <RowsSkeleton rows={8} />}

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
        <div className={`overflow-x-auto rounded border border-slate-200 bg-surface ${data ? "" : "hidden"}`}>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-600">
              <tr>
                <th className="px-3 py-2 font-medium">Date</th>
                <th className="px-3 py-2 font-medium">Bank</th>
                <th className="px-3 py-2 font-medium">Description</th>
                <th className="px-3 py-2 font-medium">Category</th>
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
                  } ${t.is_duplicate ? "text-slate-400" : ""}`}
                >
                  <td className="whitespace-nowrap px-3 py-2">{formatDate(t.transaction_date)}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span
                      className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium uppercase"
                      title={t.bank_name ?? undefined}
                    >
                      {t.bank_code ?? "?"}
                    </span>
                    {t.account_last4 ? (
                      <span className="ml-1 text-xs text-slate-500">•••• {t.account_last4}</span>
                    ) : (
                      <span className="ml-1 text-xs text-slate-400" title={NO_ACCOUNT_HINT}>
                        account not detected
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {t.description}
                    {t.is_duplicate && (
                      <span
                        className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600"
                        title="Also in another statement; not counted twice"
                      >
                        duplicate
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <select
                      aria-label={`Category for transaction ${t.id}`}
                      value={t.category_id ?? ""}
                      onChange={(e) => changeCategory(t, e.target.value)}
                      title={
                        t.classification_source
                          ? `${SOURCE_LABEL[t.classification_source] ?? t.classification_source}${
                              t.classification_explanation ? `: ${t.classification_explanation}` : ""
                            }`
                          : "Not categorised"
                      }
                      className="max-w-[10rem] rounded border border-slate-200 bg-surface px-1 py-0.5 text-xs"
                    >
                      <option value="">Uncategorised</option>
                      {categories.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                    {t.classification_source === "llm" && (
                      <span
                        className="ml-1 rounded bg-violet-100 px-1 py-0.5 text-xs text-violet-800"
                        title={t.classification_explanation ?? "AI suggestion"}
                      >
                        AI
                      </span>
                    )}
                  </td>
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

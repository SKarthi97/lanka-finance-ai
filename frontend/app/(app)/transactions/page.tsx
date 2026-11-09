"use client";

import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";
import { useConfirm } from "@/components/ConfirmDialog";
import { Pager } from "@/components/Pager";
import { LoadError, RowsSkeleton } from "@/components/states";
import { AiBusy } from "@/components/AiBusy";
import { AskFilters } from "@/components/AskFilters";
import { SavedViews } from "@/components/SavedViews";
import { TransactionDetail } from "@/components/TransactionDetail";
import { loadPref, savePref } from "@/lib/prefs";
import {
  api,
  ApiError,
  Bank,
  CategoryItem,
  NamingStatus,
  CorrectionResult,
  Tracker,
  TransactionItem,
  TransactionList,
  ViewFilters,
} from "@/lib/api";
import {
  MONTHS_LONG,
  NO_ACCOUNT_HINT,
  bankTint,
  SOURCE_LABEL,
  formatAmount,
  formatDate,
  formatDuration,
  formatMoney,
} from "@/lib/format";

const PAGE_SIZES = [25, 50, 100];

const select = "rounded border border-slate-300 px-2 py-2 text-sm bg-surface";

type SortKey = "date" | "amount" | "description" | "bank" | "category";

/** Column header that sorts; the arrow shows the active direction. */
// A category's tint says at a glance whether it is money in, money out or moved between your accounts.
function categoryTint(kind: "income" | "expense" | "transfer" | undefined): string {
  if (kind === "income") return "border-green-700/50 bg-green-50 text-green-800";
  if (kind === "expense") return "border-slate-200 bg-surface";
  if (kind === "transfer") return "border-sky-400/40 bg-sky-400/10 text-sky-300";
  return "border-amber-400/50 bg-amber-50 text-amber-400"; // uncategorised: needs a look
}

function monthTitle(date: string): string {
  return new Date(`${date.slice(0, 7)}-01T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function SortHeader({
  label,
  column,
  sort,
  order,
  onSort,
  align = "left",
  className = "",
}: {
  className?: string;
  label: string;
  column: SortKey;
  sort: SortKey;
  order: "asc" | "desc";
  onSort: (column: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort === column;
  return (
    <th
      className={`sticky top-0 z-10 bg-surface px-3 py-2 font-medium ${align === "right" ? "text-right" : ""} ${className}`}
      aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        onClick={() => onSort(column)}
        title={`Sort by ${label.toLowerCase()}`}
        className={`inline-flex items-center gap-1 hover:text-slate-900 ${active ? "text-slate-900" : ""}`}
      >
        {label}
        <span aria-hidden="true" className={active ? "text-accent" : "text-slate-400"}>
          {active ? (order === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

/** A removable summary of one active filter. */
function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-300 bg-surface py-0.5 pl-3 pr-1 text-xs">
      {label}
      <button
        onClick={onRemove}
        aria-label={`Remove filter: ${label}`}
        className="flex h-5 w-5 items-center justify-center rounded-full text-slate-500 hover:bg-slate-100 hover:text-slate-900"
      >
        ×
      </button>
    </span>
  );
}

export default function TransactionsPage() {
  const confirm = useConfirm();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [bank, setBank] = useState("");
  const [year, setYear] = useState("");
  const [month, setMonth] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [direction, setDirection] = useState<"" | "in" | "out">("");
  const [naming, setNaming] = useState<NamingStatus | null>(null);
  const wasNaming = useRef(false);
  const namingStarted = useRef(0);
  const [categoryFilter, setCategoryFilter] = useState(""); // "" = all, "none" = uncategorised, else an id
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortKey>("date");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkCategory, setBulkCategory] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [detail, setDetail] = useState<TransactionItem | null>(null);

  const [banks, setBanks] = useState<Bank[]>([]);
  const [years, setYears] = useState<number[]>([]);
  const [data, setData] = useState<TransactionList | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Links from the dashboard arrive with filters in the address (?year=&month=&category_id=...).
  useEffect(() => {
    // Remembered choices first; anything in the address then wins.
    const size = Number(loadPref("txPageSize"));
    if (PAGE_SIZES.includes(size)) setPageSize(size);
    const savedSort = loadPref("txSort");
    if (savedSort && ["date", "amount", "description", "bank", "category"].includes(savedSort)) {
      setSort(savedSort as SortKey);
      setOrder(loadPref("txOrder") === "asc" ? "asc" : "desc");
    }
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

  // The filters and ordering, without paging: shared by the list and the CSV export.
  const filterParams = new URLSearchParams({ sort, order });
  if (query) filterParams.set("q", query);
  if (bank) filterParams.set("bank_code", bank);
  if (year) filterParams.set("year", year);
  if (year && month) filterParams.set("month", month);
  if (onlyFlagged) filterParams.set("flagged", "true");
  if (categoryFilter === "none") filterParams.set("uncategorised", "true");
  else if (categoryFilter) filterParams.set("category_id", categoryFilter);
  // Repeated transactions (overlapping statements) are hidden unless asked for.
  if (showDuplicates) filterParams.set("duplicates", "show");
  // Only plain numbers go to the server; half-typed text waits.
  const plain = /^\d+(\.\d{1,2})?$/;
  if (plain.test(minAmount)) filterParams.set("min_amount", minAmount);
  if (plain.test(maxAmount)) filterParams.set("max_amount", maxAmount);
  if (direction) filterParams.set("direction", direction);
  const filterKey = filterParams.toString();

  // A different page or filter shows different rows, so the selection no longer applies.
  useEffect(() => {
    setSelected(new Set());
  }, [filterKey, page, pageSize]);

  useEffect(() => {
    const params = new URLSearchParams(filterKey);
    params.set("limit", String(pageSize));
    params.set("offset", String((page - 1) * pageSize));

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
  }, [filterKey, pageSize, page, reloadKey]);

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  async function changeCategory(t: TransactionItem, value: string) {
    const categoryId = value ? Number(value) : null;
    const url = `/transactions/${t.id}/category`;
    try {
      // Ask first, save after: nothing changes unless you press one of the dialog's buttons.
      const preview = await api<CorrectionResult>(url, {
        method: "PUT",
        json: { category_id: categoryId, preview: true },
      });
      let createRule = false;
      if (categoryId !== null && preview.similar_count > 0) {
        const answer = await confirm({
          title: `Use “${preview.category_name}” for similar transactions?`,
          message: (
            <>
              {preview.similar_count} other transaction{preview.similar_count === 1 ? "" : "s"} look like{" "}
              <span className="font-medium text-slate-900">“{preview.stem}”</span>. Apply this category
              to {preview.similar_count === 1 ? "it" : "them"} and remember it for future statements?
            </>
          ),
          confirmLabel: "Apply to all",
          cancelLabel: "Only this one",
        });
        // Clicking outside the dialog (or Escape) means "never mind": keep the old category.
        if (answer === null) return;
        createRule = answer;
      }
      await api<CorrectionResult>(url, {
        method: "PUT",
        json: { category_id: categoryId, create_rule: createRule },
      });
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

  function sortBy(column: SortKey) {
    let nextOrder: "asc" | "desc";
    if (column === sort) nextOrder = order === "asc" ? "desc" : "asc";
    else {
      // Text reads naturally A to Z; dates and amounts start with the newest or largest.
      nextOrder = column === "description" || column === "bank" || column === "category" ? "asc" : "desc";
    }
    setSort(column);
    setOrder(nextOrder);
    savePref("txSort", column);
    savePref("txOrder", nextOrder);
    setPage(1);
  }

  const rows = data?.items ?? [];
  const allSelected = rows.length > 0 && rows.every((t) => selected.has(t.id));

  function toggleRow(id: number) {
    const next = new Set(selected);
    if (!next.delete(id)) next.add(id);
    setSelected(next);
  }

  async function applyBulk() {
    const categoryId = bulkCategory === "none" ? null : Number(bulkCategory);
    const name = categoryId === null ? "Uncategorised" : categories.find((c) => c.id === categoryId)?.name;
    const ok = await confirm({
      title: `Set ${selected.size} transaction${selected.size === 1 ? "" : "s"} to “${name}”?`,
      message:
        "They count as set by you, so rules and the AI will not change them. No rule is learned from a selection.",
      confirmLabel: "Set category",
    });
    if (!ok) return;
    try {
      const result = await api<{ changed: number }>("/transactions/bulk-category", {
        method: "POST",
        json: { ids: [...selected], category_id: categoryId },
      });
      setNotice(`Updated ${result.changed} transaction${result.changed === 1 ? "" : "s"}.`);
      setSelected(new Set());
      setBulkCategory("");
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change the categories.");
    }
  }

  // Active filters as removable chips.
  const chips: { key: string; label: string; remove: () => void }[] = [];
  if (query) chips.push({ key: "q", label: `“${query}”`, remove: () => setSearch("") });
  if (bank)
    chips.push({
      key: "bank",
      label: banks.find((b) => b.code === bank)?.name ?? bank.toUpperCase(),
      remove: () => filter(setBank)(""),
    });
  if (categoryFilter)
    chips.push({
      key: "category",
      label:
        categoryFilter === "none"
          ? "Uncategorised"
          : (categories.find((c) => String(c.id) === categoryFilter)?.name ?? "Category"),
      remove: () => filter(setCategoryFilter)(""),
    });
  if (year)
    chips.push({
      key: "period",
      label: month ? `${MONTHS_LONG[Number(month) - 1]} ${year}` : year,
      remove: () => {
        filter(setYear)("");
        setMonth("");
      },
    });
  if (onlyFlagged) chips.push({ key: "flagged", label: "Needs review", remove: () => filter(setOnlyFlagged)(false) });
  if (plain.test(minAmount))
    chips.push({ key: "min", label: `At least ${minAmount}`, remove: () => filter(setMinAmount)("") });
  if (plain.test(maxAmount))
    chips.push({ key: "max", label: `At most ${maxAmount}`, remove: () => filter(setMaxAmount)("") });
  if (direction)
    chips.push({ key: "direction", label: direction === "out" ? "Money out" : "Money in", remove: () => filter(setDirection)("") });
  if (showDuplicates)
    chips.push({ key: "dups", label: "Including duplicates", remove: () => filter(setShowDuplicates)(false) });

  // The filters as a saved view holds them, and the way back from one.
  const currentFilters: ViewFilters = {
    q: query || null,
    bank_code: bank || null,
    category_id: categoryFilter && categoryFilter !== "none" ? Number(categoryFilter) : null,
    uncategorised: categoryFilter === "none",
    year: year ? Number(year) : null,
    month: year && month ? Number(month) : null,
    flagged: onlyFlagged,
    duplicates: showDuplicates ? "show" : "hide",
    min_amount: plain.test(minAmount) ? minAmount : null,
    max_amount: plain.test(maxAmount) ? maxAmount : null,
    direction: direction || null,
  };

  function applyView(f: ViewFilters) {
    setSearch(f.q ?? "");
    setBank(f.bank_code ?? "");
    setCategoryFilter(f.uncategorised ? "none" : f.category_id ? String(f.category_id) : "");
    setYear(f.year ? String(f.year) : "");
    setMonth(f.year && f.month ? String(f.month) : "");
    setOnlyFlagged(!!f.flagged);
    setShowDuplicates(f.duplicates === "show" || f.duplicates === "only");
    setMinAmount(f.min_amount ? String(Number(f.min_amount)) : "");
    setMaxAmount(f.max_amount ? String(Number(f.max_amount)) : "");
    setDirection(f.direction ?? "");
    setPage(1);
  }

  const namingActive = !!naming && (naming.progress.running || naming.progress.queued);

  // Follow the naming job: look now, and every few seconds while it is active.
  useEffect(() => {
    let cancelled = false;
    const look = () =>
      api<NamingStatus>("/merchants/status")
        .then((status) => {
          if (!cancelled) setNaming(status);
        })
        .catch(() => undefined);
    look();
    if (!namingActive) return () => void (cancelled = true);
    const timer = setInterval(look, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [namingActive]);

  // When the job finishes, show the new names and say how long it took.
  useEffect(() => {
    if (namingActive) {
      if (!wasNaming.current) namingStarted.current = Date.now();
      wasNaming.current = true;
    } else if (wasNaming.current) {
      wasNaming.current = false;
      setReloadKey((n) => n + 1);
      setNotice(`Merchant names updated (took ${formatDuration((Date.now() - namingStarted.current) / 1000)}).`);
    }
  }, [namingActive]);

  async function nameMerchants() {
    try {
      await api("/merchants/name", { method: "POST" });
      setNaming(await api<NamingStatus>("/merchants/status"));
    } catch {
      setNotice("Could not start naming.");
    }
  }

  function clearAll() {
    setSearch("");
    setBank("");
    setCategoryFilter("");
    setYear("");
    setMonth("");
    setOnlyFlagged(false);
    setShowDuplicates(false);
    setMinAmount("");
    setMaxAmount("");
    setDirection("");
    setPage(1);
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Transactions</h1>
        <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={nameMerchants}
          disabled={namingActive || naming?.ai_enabled === false || naming?.unnamed === 0}
          title={
            naming?.ai_enabled === false
              ? "The local AI is turned off"
              : naming?.unnamed === 0
                ? "Every merchant already has a name"
                : "Ask the local AI to propose clean merchant names. It sees only the repeated words of each description, never amounts."
          }
          className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-60"
        >
          {namingActive ? "Improving names" : naming && naming.unnamed > 0 ? `✨ Improve names (${naming.unnamed})` : "✨ Improve names"}
        </button>
        {/* A plain link: the browser downloads the file with your session cookie. */}
        <a
          href={`/api/transactions/export.csv?${filterKey}`}
          download="transactions.csv"
          title="Download every transaction matching the filters (not just this page)"
          className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
        >
          ⬇ Export CSV
        </a>
        </div>
      </div>

      {namingActive && naming && (
        <AiBusy
          label="The local AI is improving merchant names"
          elapsedS={naming.progress.elapsed_s}
          etaS={naming.progress.eta_s}
          queued={naming.progress.queued}
          detail="You can keep using the app; names appear when it finishes."
        />
      )}

      <AskFilters onApply={applyView} />

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

        <select
          aria-label="Money in or out"
          value={direction}
          onChange={(e) => filter(setDirection)(e.target.value as "" | "in" | "out")}
          className={select}
        >
          <option value="">Money in and out</option>
          <option value="out">Money out</option>
          <option value="in">Money in</option>
        </select>

        <input
          inputMode="decimal"
          value={minAmount}
          onChange={(e) => filter(setMinAmount)(e.target.value.trim())}
          placeholder="Min amount"
          aria-label="Minimum amount"
          className="w-28 rounded border border-slate-300 bg-surface px-2 py-2 text-sm"
        />
        <input
          inputMode="decimal"
          value={maxAmount}
          onChange={(e) => filter(setMaxAmount)(e.target.value.trim())}
          placeholder="Max amount"
          aria-label="Maximum amount"
          className="w-28 rounded border border-slate-300 bg-surface px-2 py-2 text-sm"
        />

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

      <SavedViews current={currentFilters} hasFilters={chips.length > 0} onApply={applyView} />

      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">
          {chips.map((c) => (
            <Chip key={c.key} label={c.label} onRemove={c.remove} />
          ))}
          <button onClick={clearAll} className="text-xs text-slate-500 underline hover:text-slate-900">
            Clear all
          </button>
        </div>
      )}

      {notice && (
        <p role="status" className="rounded bg-green-50 px-3 py-2 text-sm text-green-800">
          {notice}
        </p>
      )}

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

      {selected.size > 0 && (
        <div
          role="region"
          aria-label="Bulk actions"
          className="sticky top-16 z-10 flex flex-wrap items-center gap-3 rounded border border-accent/40 bg-surface px-3 py-2 text-sm shadow-lg"
        >
          <span className="font-medium">{selected.size} selected</span>
          <select
            aria-label="Category for the selected transactions"
            value={bulkCategory}
            onChange={(e) => setBulkCategory(e.target.value)}
            className={select}
          >
            <option value="">Choose a category…</option>
            <option value="none">Uncategorised</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <button
            onClick={applyBulk}
            disabled={!bulkCategory}
            className="rounded bg-accent px-3 py-1.5 text-accent-fg disabled:opacity-50"
          >
            Set category
          </button>
          <button onClick={() => setSelected(new Set())} className="text-slate-500 underline">
            Clear selection
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
        <span>{total === 0 ? "No matches" : `${from}–${to} of ${total}`}</span>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2">
            Rows per page
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                savePref("txPageSize", e.target.value);
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

      {data && data.items.length > 0 && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm tabular-nums" aria-label="Totals for this filter">
          <span className="text-slate-500">
            In <span className="font-medium text-green-700">+ {formatMoney(data.money_in)}</span>
          </span>
          <span className="text-slate-500">
            Out <span className="font-medium text-red-700">− {formatMoney(data.money_out)}</span>
          </span>
          <span className="text-slate-500">
            Net{" "}
            <span
              className={`font-medium ${Number(data.money_in) - Number(data.money_out) < 0 ? "text-red-700" : "text-green-700"}`}
            >
              {formatMoney(String(Number(data.money_in) - Number(data.money_out)))}
            </span>
          </span>
          <span className="text-xs text-slate-400">all {total} matching rows, transfers included</span>
        </div>
      )}

      {data && data.items.length === 0 ? (
        <p className="text-sm text-slate-500">No transactions found.</p>
      ) : (
        <div className={`max-h-[calc(100vh-11rem)] overflow-auto rounded border border-slate-200 bg-surface ${data ? "" : "hidden"}`}>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-600">
              <tr>
                <th className="sticky top-0 z-10 w-8 bg-surface px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select every transaction on this page"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((t) => t.id)))}
                  />
                </th>
                <SortHeader label="Date" column="date" sort={sort} order={order} onSort={sortBy} />
                <SortHeader label="Bank" column="bank" sort={sort} order={order} onSort={sortBy} className="hidden md:table-cell" />
                <SortHeader label="Description" column="description" sort={sort} order={order} onSort={sortBy} />
                <SortHeader label="Category" column="category" sort={sort} order={order} onSort={sortBy} />
                <SortHeader label="Debit" column="amount" sort={sort} order={order} onSort={sortBy} align="right" className="min-w-[8.5rem]" />
                <SortHeader label="Credit" column="amount" sort={sort} order={order} onSort={sortBy} align="right" className="min-w-[8.5rem]" />
                <th className="sticky top-0 z-10 hidden min-w-[9.5rem] bg-surface px-3 py-2 text-right font-medium lg:table-cell">Balance</th>
                <th className="sticky top-0 z-10 hidden bg-surface px-3 py-2 font-medium lg:table-cell">Statement</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((t, index, all) => (
                <Fragment key={t.id}>
                {sort === "date" && (index === 0 || all[index - 1].transaction_date.slice(0, 7) !== t.transaction_date.slice(0, 7)) && (
                  <tr className="bg-slate-50">
                    <td colSpan={9} className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-600">
                      {monthTitle(t.transaction_date)}
                      <span className="ml-2 font-normal normal-case text-slate-500">
                        {all.filter((x) => x.transaction_date.slice(0, 7) === t.transaction_date.slice(0, 7)).length} on this page
                      </span>
                    </td>
                  </tr>
                )}
                <tr
                  className={`border-b border-slate-100 last:border-0 hover:bg-slate-50 ${
                    t.validation_status !== "ok" ? "bg-amber-50" : selected.has(t.id) ? "" : "even:bg-white/[0.02]"
                  } ${t.is_duplicate ? "text-slate-400" : ""} ${selected.has(t.id) ? "bg-accent/10" : ""}`}
                >
                  <td
                    className={`border-l-2 px-3 py-2 ${
                      t.validation_status !== "ok"
                        ? "border-l-amber-400"
                        : Number(t.credit) > 0
                          ? "border-l-green-700"
                          : "border-l-transparent"
                    }`}
                  >
                    <input
                      type="checkbox"
                      aria-label={`Select transaction ${t.id}`}
                      checked={selected.has(t.id)}
                      onChange={() => toggleRow(t.id)}
                    />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">{formatDate(t.transaction_date)}</td>
                  <td className="hidden whitespace-nowrap px-3 py-2 md:table-cell">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(t.bank_code)}`}
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
                    <button
                      onClick={() => setDetail(t)}
                      title="Show details"
                      className="text-left font-medium text-slate-900 hover:underline"
                    >
                      {t.merchant}
                    </button>
                    {t.merchant.toLowerCase() !== t.description.toLowerCase() && (
                      <div className="max-w-[34rem] truncate text-xs text-slate-500" title={t.description}>
                        {t.description}
                      </div>
                    )}
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
                      className={`max-w-[10rem] rounded border px-1 py-0.5 text-xs ${categoryTint(
                        categories.find((c) => c.id === t.category_id)?.kind,
                      )}`}
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
                  <td className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${t.is_duplicate ? "" : "text-red-700"}`}>
                    {Number(t.debit) === 0 ? "" : `− ${formatAmount(t.debit)}`}
                  </td>
                  <td className={`whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums ${t.is_duplicate ? "" : "text-green-700"}`}>
                    {Number(t.credit) === 0 ? "" : `+ ${formatAmount(t.credit)}`}
                  </td>
                  <td className="hidden whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-400 lg:table-cell">
                    {formatMoney(t.running_balance)}
                  </td>
                  <td className="hidden whitespace-nowrap px-3 py-2 lg:table-cell">
                    <Link href={`/documents/${t.document_id}`} className="text-xs text-slate-500 underline hover:text-slate-900">
                      #{t.document_id}
                    </Link>{" "}
                    <span className="text-xs text-slate-400">p{t.source_page}</span>
                  </td>
                </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex justify-end">
        <Pager page={page} pages={pages} onChange={setPage} />
      </div>

      {detail && <TransactionDetail
          transaction={detail}
          onClose={() => setDetail(null)}
          onRenamed={(name, source) => {
            setDetail({ ...detail, merchant: name, merchant_source: source });
            setReloadKey((n) => n + 1);
          }}
        />}
    </section>
  );
}

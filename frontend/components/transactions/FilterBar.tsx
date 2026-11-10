"use client";

import { Bank, CategoryItem } from "@/lib/api";
import { MONTHS_LONG } from "@/lib/format";

const select = "rounded border border-slate-300 px-2 py-2 text-sm bg-surface";

export type FilterValues = {
  search: string;
  bank: string;
  categoryFilter: string; // "" = all, "none" = uncategorised, else an id
  year: string;
  month: string;
  direction: "" | "in" | "out";
  minAmount: string;
  maxAmount: string;
  onlyFlagged: boolean;
  showDuplicates: boolean;
};

type Changes = {
  bank: (value: string) => void;
  categoryFilter: (value: string) => void;
  year: (value: string) => void;
  month: (value: string) => void;
  direction: (value: "" | "in" | "out") => void;
  minAmount: (value: string) => void;
  maxAmount: (value: string) => void;
  onlyFlagged: (value: boolean) => void;
  showDuplicates: (value: boolean) => void;
};

/** The row of filters above the transactions table. The page owns the state; this only draws it. */
export function FilterBar({
  values,
  options,
  onSearch,
  onChange,
}: {
  values: FilterValues;
  options: { banks: Bank[]; categories: CategoryItem[]; years: number[] };
  onSearch: (value: string) => void;
  onChange: Changes;
}) {
  const { search, bank, categoryFilter, year, month, direction, minAmount, maxAmount, onlyFlagged, showDuplicates } = values;
  const { banks, categories, years } = options;
  return (
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search descriptions"
          aria-label="Search descriptions"
          className="w-56 rounded border border-slate-300 px-3 py-2 text-sm"
        />

        <select
          aria-label="Bank"
          value={bank}
          onChange={(e) => onChange.bank(e.target.value)}
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
          onChange={(e) => onChange.categoryFilter(e.target.value)}
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
            onChange.year(e.target.value);
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
          onChange={(e) => onChange.month(e.target.value)}
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
          onChange={(e) => onChange.direction(e.target.value as "" | "in" | "out")}
          className={select}
        >
          <option value="">Money in and out</option>
          <option value="out">Money out</option>
          <option value="in">Money in</option>
        </select>

        <input
          inputMode="decimal"
          value={minAmount}
          onChange={(e) => onChange.minAmount(e.target.value.trim())}
          placeholder="Min amount"
          aria-label="Minimum amount"
          className="w-28 rounded border border-slate-300 bg-surface px-2 py-2 text-sm"
        />
        <input
          inputMode="decimal"
          value={maxAmount}
          onChange={(e) => onChange.maxAmount(e.target.value.trim())}
          placeholder="Max amount"
          aria-label="Maximum amount"
          className="w-28 rounded border border-slate-300 bg-surface px-2 py-2 text-sm"
        />

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyFlagged}
            onChange={(e) => onChange.onlyFlagged(e.target.checked)}
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
            onChange={(e) => onChange.showDuplicates(e.target.checked)}
          />
          Show duplicates
        </label>
      </div>
  );
}

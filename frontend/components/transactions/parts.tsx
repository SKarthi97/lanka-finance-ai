"use client";



export type SortKey = "date" | "amount" | "description" | "bank" | "category";

/** Column header that sorts; the arrow shows the active direction. */
// A category's tint says at a glance whether it is money in, money out or moved between your accounts.
export function categoryTint(kind: "income" | "expense" | "transfer" | undefined): string {
  if (kind === "income") return "border-green-700/50 bg-green-50 text-green-800";
  if (kind === "expense") return "border-slate-200 bg-surface";
  if (kind === "transfer") return "border-sky-400/40 bg-sky-400/10 text-sky-300";
  return "border-amber-400/50 bg-amber-50 text-amber-400"; // uncategorised: needs a look
}

export function monthTitle(date: string): string {
  return new Date(`${date.slice(0, 7)}-01T00:00:00`).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

export function SortHeader({
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
export function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
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

"use client";

import { CategoryItem } from "@/lib/api";
import { KIND_LABEL } from "@/lib/format";

export const input = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";
export const primary = "rounded bg-accent px-3 py-1.5 text-sm text-accent-fg disabled:opacity-50";
export const subtle = "rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50";

export function CategorySelect({
  categories,
  value,
  onChange,
  label,
}: {
  categories: CategoryItem[];
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={input}>
      <option value="">Choose a category…</option>
      {(["income", "expense", "transfer"] as const).map((kind) => (
        <optgroup key={kind} label={KIND_LABEL[kind]}>
          {categories
            .filter((c) => c.kind === kind)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.full_name || c.name}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

export type Run = (action: () => Promise<string | void>) => Promise<void>;

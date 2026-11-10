"use client";

import { FormEvent, useState } from "react";
import { useConfirm } from "@/components/ConfirmDialog";
import { CategoryItem, RuleItem, api } from "@/lib/api";
import { ORIGIN_LABEL, formatMoney } from "@/lib/format";
import { input, primary, subtle, CategorySelect, Run } from "@/components/categories/shared";

export function RulesTab({ rules, categories, run }: { rules: RuleItem[]; categories: CategoryItem[]; run: Run }) {
  const confirm = useConfirm();
  function rerun() {
    run(async () => {
      const result = await api<{ changed: number }>("/categorization/reclassify", { method: "POST" });
      return `Rules re-run. ${result.changed} transaction${result.changed === 1 ? "" : "s"} changed. Choices you made yourself and AI suggestions were left alone.`;
    });
  }
  const [pattern, setPattern] = useState("");
  const [type, setType] = useState<"contains" | "word">("contains");
  const [category, setCategory] = useState("");
  const [direction, setDirection] = useState<"" | "in" | "out">("");
  const [minAmount, setMinAmount] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const plain = /^\d+(\.\d{1,2})?$/;

  function add(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      const result = await api<{ changed: number }>("/rules", {
        method: "POST",
        json: {
          pattern,
          pattern_type: type,
          category_id: Number(category),
          direction: direction || null,
          min_amount: plain.test(minAmount) ? minAmount : null,
          max_amount: plain.test(maxAmount) ? maxAmount : null,
        },
      });
      setPattern("");
      setMinAmount("");
      setMaxAmount("");
      setDirection("");
      return `Rule added. ${result.changed} transaction${result.changed === 1 ? "" : "s"} updated.`;
    });
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        A rule puts every transaction whose description contains the text into a category. Your rules
        and learned corrections beat the built-in ones. A transaction you set by hand is never changed.
      </p>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <button type="button" onClick={rerun} className={subtle} title="Apply every rule again to the transactions that are not set by hand">
          Re-run rules on my transactions
        </button>
        <span className="text-xs text-slate-500">Useful after adding or turning on a rule.</span>
      </div>

      <form onSubmit={add} className="flex flex-wrap items-end gap-2 rounded border border-slate-200 bg-surface p-3">
        <label className="text-sm">
          Description contains
          <input value={pattern} onChange={(e) => setPattern(e.target.value)} required minLength={2} maxLength={128} className={`${input} mt-1 block`} />
        </label>
        <label className="text-sm">
          Match
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)} className={`${input} mt-1 block`}>
            <option value="contains">anywhere</option>
            <option value="word">whole word</option>
          </select>
        </label>
        <label className="text-sm">
          Money
          <select value={direction} onChange={(e) => setDirection(e.target.value as typeof direction)} className={`${input} mt-1 block`}>
            <option value="">in or out</option>
            <option value="in">coming in (credit)</option>
            <option value="out">going out (debit)</option>
          </select>
        </label>
        <label className="text-sm">
          From amount
          <input value={minAmount} onChange={(e) => setMinAmount(e.target.value)} inputMode="decimal" placeholder="any" className={`${input} mt-1 block w-28`} />
        </label>
        <label className="text-sm">
          Up to amount
          <input value={maxAmount} onChange={(e) => setMaxAmount(e.target.value)} inputMode="decimal" placeholder="any" className={`${input} mt-1 block w-28`} />
        </label>
        <div className="text-sm">
          <span className="block">Category</span>
          <div className="mt-1">
            <CategorySelect categories={categories} value={category} onChange={setCategory} label="Rule category" />
          </div>
        </div>
        <button className={primary} type="submit" disabled={!pattern.trim() || !category}>
          Add rule
        </button>
      </form>

      <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-600">
            <tr>
              <th className="px-3 py-2 font-medium">Description contains</th>
              <th className="px-3 py-2 font-medium">Category</th>
              <th className="px-3 py-2 font-medium">Source</th>
              <th className="px-3 py-2 text-right font-medium">Used</th>
              <th className="px-3 py-2 font-medium">On</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} className={`border-b border-slate-100 last:border-0 ${r.enabled ? "" : "text-slate-400"}`}>
                <td className="px-3 py-2">
                  {r.pattern}
                  {r.pattern_type === "word" && <span className="ml-2 text-xs text-slate-400">whole word</span>}
                  {(r.direction || r.min_amount || r.max_amount) && (
                    <div className="text-xs text-slate-500">
                      only {r.direction === "in" ? "credits" : r.direction === "out" ? "debits" : "amounts"}
                      {r.min_amount ? ` from ${formatMoney(r.min_amount)}` : ""}
                      {r.max_amount ? ` up to ${formatMoney(r.max_amount)}` : ""}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2">{r.category_name}</td>
                <td className="px-3 py-2">{ORIGIN_LABEL[r.origin]}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.hit_count}</td>
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`Rule ${r.pattern} enabled`}
                    checked={r.enabled}
                    onChange={(e) =>
                      run(async () => {
                        await api(`/rules/${r.id}`, { method: "PATCH", json: { enabled: e.target.checked } });
                      })
                    }
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  {r.origin !== "system" && (
                    <button
                      className="text-xs text-red-700 hover:underline"
                      onClick={async () => {
                        const ok = await confirm({
                          title: `Delete the rule “${r.pattern}”?`,
                          message:
                            "Transactions it already categorised keep their category; new ones will no longer match it.",
                          confirmLabel: "Delete rule",
                          tone: "danger",
                        });
                        if (!ok) return;
                        run(async () => {
                          await api(`/rules/${r.id}`, { method: "DELETE" });
                          return "Rule deleted.";
                        });
                      }}
                    >
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useConfirm } from "@/components/ConfirmDialog";
import { RowsSkeleton } from "@/components/states";
import { CategoryItem, SuggestionGroup, Suggestions, api } from "@/lib/api";
import { primary, subtle, CategorySelect, Run } from "@/components/categories/shared";

export function SuggestionsTab({
  suggestions,
  categories,
  run,
}: {
  suggestions: Suggestions | null;
  categories: CategoryItem[];
  run: Run;
}) {
  const confirm = useConfirm();
  // A different category chosen for a group, instead of the model's suggestion.
  const [override, setOverride] = useState<Record<string, string>>({});
  const keyOf = (g: SuggestionGroup) => `${g.stem}|${g.category_id}`;

  if (!suggestions) return <RowsSkeleton />;

  const confidentOnly = suggestions.groups.filter((g) => g.confidence >= suggestions.confident_threshold);

  async function acceptAll(only: SuggestionGroup[]) {
    const everything = only.length === suggestions!.groups.length;
    const rows = only.reduce((n, g) => n + g.count, 0);
    const ok = await confirm({
      title: everything
        ? `Accept all ${only.length} suggestions?`
        : `Accept the ${only.length} confident suggestions?`,
      message: `${everything ? "Every" : "Each"} AI suggestion shown (${rows} transaction${rows === 1 ? "" : "s"}) becomes your choice and is remembered as a rule for future statements.${everything ? "" : " Less certain ones stay for you to check."}`,
      confirmLabel: "Accept",
    });
    if (!ok) return;
    run(async () => {
      let changed = 0;
      for (const g of only) {
        const result = await api<{ changed: number }>("/categorization/suggestions/accept", {
          method: "POST",
          json: { stem: g.stem, category_id: g.category_id },
        });
        changed += result.changed;
      }
      return `Accepted ${only.length} suggestions (${changed} transactions) and saved them as rules.`;
    });
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        What the local AI categorised on its own, grouped by description. Accept one to make it your
        choice and remember it as a rule; reject it to send those transactions back to Review. You
        can also pick a different category before accepting.
      </p>

      {suggestions.groups.length === 0 ? (
        <p className="rounded border border-slate-200 bg-surface p-4 text-sm text-slate-600">
          No AI suggestions waiting. Ask the AI from the Review tab to get some.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap justify-end gap-2">
            {confidentOnly.length > 0 && confidentOnly.length < suggestions.groups.length && (
              <button className={primary} onClick={() => acceptAll(confidentOnly)}>
                Accept confident ({confidentOnly.length}, {Math.round(suggestions.confident_threshold * 100)}%+)
              </button>
            )}
            <button
              className={confidentOnly.length < suggestions.groups.length ? subtle : primary}
              onClick={() => acceptAll(suggestions.groups)}
            >
              Accept all ({suggestions.groups.length})
            </button>
          </div>
          <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-slate-600">
                <tr>
                  <th className="px-3 py-2 font-medium">Description</th>
                  <th className="px-3 py-2 text-right font-medium">Transactions</th>
                  <th className="px-3 py-2 font-medium">AI suggested</th>
                  <th className="px-3 py-2 text-right font-medium">Confidence</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {suggestions.groups.map((g) => {
                  const chosen = override[keyOf(g)] ?? String(g.category_id);
                  const changed = chosen !== String(g.category_id);
                  return (
                    <tr key={keyOf(g)} className="border-b border-slate-100 last:border-0">
                      <td className="px-3 py-2">
                        <div className="font-medium">{g.stem}</div>
                        {g.example !== g.stem && <div className="text-xs text-slate-500">e.g. {g.example}</div>}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{g.count}</td>
                      <td className="px-3 py-2">
                        <CategorySelect
                          categories={categories}
                          value={chosen}
                          onChange={(v) => setOverride({ ...override, [keyOf(g)]: v })}
                          label={`Category for ${g.stem}`}
                        />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        <span className={g.confidence < suggestions.confident_threshold ? "text-amber-700" : ""}>
                          {Math.round(g.confidence * 100)}%
                        </span>
                      </td>
                      <td className="space-x-2 whitespace-nowrap px-3 py-2 text-right">
                        <button
                          className={primary}
                          disabled={!chosen}
                          onClick={() =>
                            run(async () => {
                              const result = await api<{ changed: number }>(
                                changed ? "/categorization/apply" : "/categorization/suggestions/accept",
                                { method: "POST", json: { stem: g.stem, category_id: Number(chosen) } },
                              );
                              return `Accepted “${g.stem}” for ${result.changed} transaction${result.changed === 1 ? "" : "s"} and saved a rule.`;
                            })
                          }
                        >
                          Accept
                        </button>
                        <button
                          className={subtle}
                          onClick={() =>
                            run(async () => {
                              const result = await api<{ changed: number }>(
                                "/categorization/suggestions/reject",
                                { method: "POST", json: { stem: g.stem, category_id: g.category_id } },
                              );
                              return `Rejected: ${result.changed} transaction${result.changed === 1 ? "" : "s"} back in Review.`;
                            })
                          }
                        >
                          Reject
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

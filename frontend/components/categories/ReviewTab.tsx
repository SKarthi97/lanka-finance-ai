"use client";

import { useState } from "react";
import { AiBusy } from "@/components/AiBusy";
import { CategoryItem, CategorizationStatus, ReviewQueue, Similarity, Suggestions, api } from "@/lib/api";
import { primary, subtle, CategorySelect, Run } from "@/components/categories/shared";

export function ReviewTab({
  queue,
  status,
  similarity,
  categories,
  run,
}: {
  queue: ReviewQueue;
  status: CategorizationStatus | null;
  similarity: Similarity | null;
  categories: CategoryItem[];
  run: Run;
}) {
  const [choice, setChoice] = useState<Record<string, string>>({});

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        These transactions matched no rule. Pick a category once for a group and it applies to every
        transaction with that description, and is remembered for future statements.
      </p>

      {status?.ai_enabled && (
        <div className="flex flex-wrap items-center gap-3 rounded border border-slate-200 bg-surface p-3 text-sm">
          <button
            className={subtle}
            disabled={status.ai_pending || queue.total === 0}
            onClick={() =>
              run(async () => {
                await api("/categorization/ai", { method: "POST" });
                return "Asking the local AI. Suggestions appear here and in Transactions marked “AI”.";
              })
            }
          >
            {status.ai_pending ? "AI is working" : "Ask the local AI to suggest"}
          </button>
          <span className="text-xs text-slate-500">
            Runs on your machine through Ollama; only the description text is used. Suggestions
            below 80% confidence are left for you.
          </span>
          {similarity && (
            <span className="w-full text-xs text-slate-500">
              {similarity.enabled
                ? similarity.labelled >= similarity.needed
                  ? `Hints from descriptions you chose before are on (${similarity.labelled} of yours to compare with).`
                  : `Hints from descriptions you chose before need ${similarity.needed} categorised by you; you have ${similarity.labelled}.`
                : "Hints from descriptions you chose before are off. Turn them on after measuring them (docs/08)."}
            </span>
          )}
          {status.ai_pending && (
            <AiBusy
              label="The local AI is suggesting categories"
              elapsedS={status.progress.elapsed_s}
              etaS={status.progress.eta_s}
              queued={status.progress.queued}
              detail={
                status.progress.waiting > 0
                  ? `${status.progress.waiting} description${status.progress.waiting === 1 ? "" : "s"} to look at; suggestions appear here as it finishes.`
                  : undefined
              }
            />
          )}
        </div>
      )}

      {queue.groups.length === 0 ? (
        <p className="rounded border border-slate-200 bg-surface p-4 text-sm text-slate-600">
          Nothing to review. Every transaction has a category.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-600">
              <tr>
                <th className="px-3 py-2 font-medium">Description</th>
                <th className="px-3 py-2 text-right font-medium">Transactions</th>
                <th className="px-3 py-2 font-medium">Category</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {queue.groups.map((g) => (
                <tr key={g.stem} className="border-b border-slate-100 last:border-0">
                  <td className="px-3 py-2">
                    <div className="font-medium">{g.stem}</div>
                    {g.example !== g.stem && <div className="text-xs text-slate-500">e.g. {g.example}</div>}
                    {g.hint_category_id !== null && !choice[g.stem] && (
                      <button
                        onClick={() => setChoice({ ...choice, [g.stem]: String(g.hint_category_id) })}
                        title={g.hint_reason ?? "The AI was not confident enough to apply this, so it only suggests it"}
                        className="mt-1 rounded bg-violet-100 px-2 py-0.5 text-xs text-violet-800 hover:opacity-90"
                      >
                        {g.hint_reason?.startsWith("Similar") ? "Like ones you chose" : "AI hunch"}: {g.hint_category_name}
                        {g.hint_confidence !== null && ` (${Math.round(g.hint_confidence * 100)}%)`} · use it
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{g.count}</td>
                  <td className="px-3 py-2">
                    <CategorySelect
                      categories={categories}
                      value={choice[g.stem] ?? ""}
                      onChange={(v) => setChoice({ ...choice, [g.stem]: v })}
                      label={`Category for ${g.stem}`}
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      className={primary}
                      disabled={!choice[g.stem]}
                      onClick={() =>
                        run(async () => {
                          const result = await api<{ changed: number }>("/categorization/apply", {
                            method: "POST",
                            json: { stem: g.stem, category_id: Number(choice[g.stem]) },
                          });
                          return `Categorised ${result.changed} transaction${result.changed === 1 ? "" : "s"} and saved a rule for “${g.stem}”.`;
                        })
                      }
                    >
                      Apply
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

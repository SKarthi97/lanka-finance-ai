"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useConfirm } from "@/components/ConfirmDialog";
import { LoadError, RowsSkeleton } from "@/components/states";
import {
  api,
  ApiError,
  CategoryItem,
  CategorizationStatus,
  RuleItem,
  ReviewQueue,
  SuggestionGroup,
  Suggestions,
} from "@/lib/api";
import { KIND_LABEL, ORIGIN_LABEL } from "@/lib/format";

type Tab = "review" | "suggestions" | "categories" | "rules";

const input = "rounded border border-slate-300 bg-surface px-2 py-1.5 text-sm";
const primary = "rounded bg-accent px-3 py-1.5 text-sm text-accent-fg disabled:opacity-50";
const subtle = "rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50";

function CategorySelect({
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
                {c.name}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

export default function CategoriesPage() {
  const [tab, setTab] = useState<Tab>("review");
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [status, setStatus] = useState<CategorizationStatus | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestions | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoadError(null);
      const [c, r, q, s, sg] = await Promise.all([
        api<CategoryItem[]>("/categories"),
        api<RuleItem[]>("/rules"),
        api<ReviewQueue>("/categorization/review"),
        api<CategorizationStatus>("/categorization/status"),
        api<Suggestions>("/categorization/suggestions"),
      ]);
      setCategories(c);
      setRules(r);
      setQueue(q);
      setStatus(s);
      setSuggestions(sg);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load categories.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // While the local AI is working, refresh so its suggestions appear.
  const aiPending = status?.ai_pending ?? false;
  useEffect(() => {
    if (!aiPending) return;
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [aiPending, load]);

  async function run(action: () => Promise<string | void>) {
    setMessage(null);
    try {
      const text = await action();
      if (text) setMessage({ kind: "ok", text });
      await load();
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Something went wrong." });
    }
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "review", label: `Review${queue ? ` (${queue.total})` : ""}` },
    { id: "suggestions", label: `AI suggestions${suggestions ? ` (${suggestions.total})` : ""}` },
    { id: "categories", label: "Categories" },
    { id: "rules", label: "Rules" },
  ];

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">Categories</h1>

      <div role="tablist" className="flex gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              tab === t.id ? "border-accent font-medium" : "border-transparent text-slate-600"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {message && (
        <p
          role={message.kind === "error" ? "alert" : "status"}
          className={`rounded px-3 py-2 text-sm ${
            message.kind === "error" ? "bg-red-50 text-red-700" : "bg-green-50 text-green-800"
          }`}
        >
          {message.text}
        </p>
      )}

      {loadError && <LoadError message={loadError} onRetry={load} />}

      {!loadError && !queue && <RowsSkeleton />}
      {queue && tab === "review" && (
        <ReviewTab queue={queue} status={status} categories={categories} run={run} />
      )}
      {queue && tab === "suggestions" && (
        <SuggestionsTab suggestions={suggestions} categories={categories} run={run} />
      )}
      {queue && tab === "categories" && <CategoriesTab categories={categories} run={run} />}
      {queue && tab === "rules" && <RulesTab rules={rules} categories={categories} run={run} />}
    </section>
  );
}

type Run = (action: () => Promise<string | void>) => Promise<void>;

// --- review ---------------------------------------------------------------------------------

function ReviewTab({
  queue,
  status,
  categories,
  run,
}: {
  queue: ReviewQueue;
  status: CategorizationStatus | null;
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
            {status.ai_pending ? "AI is working…" : "Ask the local AI to suggest"}
          </button>
          <span className="text-xs text-slate-500">
            Runs on your machine through Ollama; only the description text is used. Suggestions
            below 80% confidence are left for you.
          </span>
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

// --- AI suggestions ---------------------------------------------------------------------------

function SuggestionsTab({
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

  async function acceptAll() {
    const ok = await confirm({
      title: `Accept all ${suggestions!.groups.length} suggestions?`,
      message: `Every AI suggestion (${suggestions!.total} transaction${suggestions!.total === 1 ? "" : "s"}) becomes your choice and is remembered as a rule for future statements.`,
      confirmLabel: "Accept all",
    });
    if (!ok) return;
    run(async () => {
      let changed = 0;
      for (const g of suggestions!.groups) {
        const result = await api<{ changed: number }>("/categorization/suggestions/accept", {
          method: "POST",
          json: { stem: g.stem, category_id: g.category_id },
        });
        changed += result.changed;
      }
      return `Accepted ${suggestions!.groups.length} suggestions (${changed} transactions) and saved them as rules.`;
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
          <div className="flex justify-end">
            <button className={primary} onClick={acceptAll}>
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
                        <span className={g.confidence < 0.9 ? "text-amber-700" : ""}>
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

// --- categories -----------------------------------------------------------------------------

function CategoriesTab({ categories, run }: { categories: CategoryItem[]; run: Run }) {
  const confirm = useConfirm();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"expense" | "income" | "transfer">("expense");

  function add(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      await api("/categories", { method: "POST", json: { name, kind } });
      setName("");
      return `Added “${name}”.`;
    });
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Transfers move money between your own accounts, so they are left out of income and expense
        totals.
      </p>

      <form onSubmit={add} className="flex flex-wrap items-end gap-2 rounded border border-slate-200 bg-surface p-3">
        <label className="text-sm">
          New category
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} className={`${input} mt-1 block`} />
        </label>
        <label className="text-sm">
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className={`${input} mt-1 block`}>
            <option value="expense">Expense</option>
            <option value="income">Income</option>
            <option value="transfer">Transfer</option>
          </select>
        </label>
        <button className={primary} type="submit" disabled={!name.trim()}>
          Add
        </button>
      </form>

      <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-600">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Kind</th>
              <th className="px-3 py-2 text-right font-medium">Transactions</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c.id} className="border-b border-slate-100 last:border-0">
                <td className="px-3 py-2">
                  {c.name}
                  {c.is_system && <span className="ml-2 text-xs text-slate-400">built in</span>}
                </td>
                <td className="px-3 py-2">{KIND_LABEL[c.kind]}</td>
                <td className="px-3 py-2 text-right tabular-nums">{c.transactions}</td>
                <td className="px-3 py-2 text-right">
                  {!c.is_system && (
                    <button
                      className="text-xs text-red-700 hover:underline"
                      onClick={async () => {
                        const ok = await confirm({
                          title: `Delete “${c.name}”?`,
                          message: "Only categories with no transactions can be deleted.",
                          confirmLabel: "Delete",
                          tone: "danger",
                        });
                        if (!ok) return;
                        run(async () => {
                          await api(`/categories/${c.id}`, { method: "DELETE" });
                          return `Deleted “${c.name}”.`;
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

// --- rules -----------------------------------------------------------------------------------

function RulesTab({ rules, categories, run }: { rules: RuleItem[]; categories: CategoryItem[]; run: Run }) {
  const confirm = useConfirm();
  const [pattern, setPattern] = useState("");
  const [type, setType] = useState<"contains" | "word">("contains");
  const [category, setCategory] = useState("");

  function add(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      const result = await api<{ changed: number }>("/rules", {
        method: "POST",
        json: { pattern, pattern_type: type, category_id: Number(category) },
      });
      setPattern("");
      return `Rule added. ${result.changed} transaction${result.changed === 1 ? "" : "s"} updated.`;
    });
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        A rule puts every transaction whose description contains the text into a category. Your rules
        and learned corrections beat the built-in ones. A transaction you set by hand is never changed.
      </p>

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

"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  CategoryItem,
  CategorizationStatus,
  RuleItem,
  ReviewQueue,
} from "@/lib/api";
import { KIND_LABEL, ORIGIN_LABEL } from "@/lib/format";

type Tab = "review" | "categories" | "rules";

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
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, r, q, s] = await Promise.all([
        api<CategoryItem[]>("/categories"),
        api<RuleItem[]>("/rules"),
        api<ReviewQueue>("/categorization/review"),
        api<CategorizationStatus>("/categorization/status"),
      ]);
      setCategories(c);
      setRules(r);
      setQueue(q);
      setStatus(s);
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof ApiError ? err.message : "Could not load categories." });
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

      {tab === "review" && (
        <ReviewTab queue={queue} status={status} categories={categories} run={run} />
      )}
      {tab === "categories" && <CategoriesTab categories={categories} run={run} />}
      {tab === "rules" && <RulesTab rules={rules} categories={categories} run={run} />}
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
  queue: ReviewQueue | null;
  status: CategorizationStatus | null;
  categories: CategoryItem[];
  run: Run;
}) {
  const [choice, setChoice] = useState<Record<string, string>>({});

  if (!queue) return <p className="text-sm text-slate-500">Loading…</p>;

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

// --- categories -----------------------------------------------------------------------------

function CategoriesTab({ categories, run }: { categories: CategoryItem[]; run: Run }) {
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
                      onClick={() =>
                        window.confirm(`Delete “${c.name}”?`) &&
                        run(async () => {
                          await api(`/categories/${c.id}`, { method: "DELETE" });
                          return `Deleted “${c.name}”.`;
                        })
                      }
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
                      onClick={() =>
                        window.confirm(`Delete the rule “${r.pattern}”?`) &&
                        run(async () => {
                          await api(`/rules/${r.id}`, { method: "DELETE" });
                          return "Rule deleted.";
                        })
                      }
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

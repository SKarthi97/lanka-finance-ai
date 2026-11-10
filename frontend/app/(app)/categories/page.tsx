"use client";

import { useCallback, useEffect, useState } from "react";
import { LoadError, RowsSkeleton } from "@/components/states";
import { ApiError, CategoryItem, CategorizationStatus, RuleItem, ReviewQueue, Similarity, Suggestions, TransferSuggestions, api } from "@/lib/api";
import { ReviewTab } from "@/components/categories/ReviewTab";
import { SuggestionsTab } from "@/components/categories/SuggestionsTab";
import { CategoriesTab } from "@/components/categories/CategoriesTab";
import { RulesTab } from "@/components/categories/RulesTab";
import { TransfersTab } from "@/components/categories/TransfersTab";

type Tab = "review" | "suggestions" | "transfers" | "categories" | "rules";

export default function CategoriesPage() {
  const [tab, setTab] = useState<Tab>("review");
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [rules, setRules] = useState<RuleItem[]>([]);
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [status, setStatus] = useState<CategorizationStatus | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestions | null>(null);
  const [transferPairs, setTransferPairs] = useState<TransferSuggestions | null>(null);
  const [similarity, setSimilarity] = useState<Similarity | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoadError(null);
      api<Similarity>("/ai/similarity").then(setSimilarity).catch(() => undefined);
      const [c, r, q, s, sg, tr] = await Promise.all([
        api<CategoryItem[]>("/categories"),
        api<RuleItem[]>("/rules"),
        api<ReviewQueue>("/categorization/review"),
        api<CategorizationStatus>("/categorization/status"),
        api<Suggestions>("/categorization/suggestions"),
        api<TransferSuggestions>("/transfers/suggestions"),
      ]);
      setCategories(c);
      setRules(r);
      setQueue(q);
      setStatus(s);
      setSuggestions(sg);
      setTransferPairs(tr);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Could not load categories.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // The dashboard links here with ?tab=transfers.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tab") === "transfers") setTab("transfers");
  }, []);

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
    { id: "transfers", label: `Transfers${transferPairs ? ` (${transferPairs.total})` : ""}` },
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
            className={`-mb-px rounded-t border-b-2 px-3 py-2 text-sm hover:bg-slate-100 ${
              tab === t.id ? "border-accent font-medium text-slate-900" : "border-transparent text-slate-600"
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
        <ReviewTab queue={queue} status={status} similarity={similarity} categories={categories} run={run} />
      )}
      {queue && tab === "suggestions" && (
        <SuggestionsTab suggestions={suggestions} categories={categories} run={run} />
      )}
      {queue && tab === "transfers" && <TransfersTab data={transferPairs} run={run} />}
      {queue && tab === "categories" && <CategoriesTab categories={categories} run={run} />}
      {queue && tab === "rules" && <RulesTab rules={rules} categories={categories} run={run} />}
    </section>
  );
}

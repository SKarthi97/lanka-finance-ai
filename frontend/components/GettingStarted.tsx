"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Budgets, StorageReport } from "@/lib/api";
import { loadPref, savePref } from "@/lib/prefs";

type Step = { key: string; title: string; hint: string; href: string; action: string; done: boolean };

/**
 * A short checklist for a new install, shown on the dashboard once a first statement is in.
 * Each step ticks itself from the data (nothing to click to mark it done) and the whole card
 * disappears when everything is done or when you dismiss it.
 */
export function GettingStarted({
  needsReview,
  uncategorised,
  year,
  month,
}: {
  needsReview: number;
  uncategorised: number;
  year: number;
  month: number;
}) {
  const [hidden, setHidden] = useState(true); // until we know, show nothing rather than flash
  const [budgets, setBudgets] = useState<number | null>(null);
  const [backedUp, setBackedUp] = useState<boolean | null>(null);

  useEffect(() => {
    setHidden(loadPref("gettingStartedHidden") === "1");
    api<Budgets>(`/budgets?year=${year}&month=${month}`)
      .then((b) => setBudgets(b.items.length))
      .catch(() => setBudgets(null));
    api<StorageReport>("/system/storage")
      .then((s) => setBackedUp(s.backup.recorded))
      .catch(() => setBackedUp(null));
  }, [year, month]);

  const steps: Step[] = [
    { key: "upload", title: "Add a statement", hint: "Done: your first statement is in.", href: "/upload", action: "Upload another", done: true },
    {
      key: "review",
      title: "Check that every statement reconciled",
      hint: needsReview > 0 ? `${needsReview} waiting for your review; they are left out of every figure until then.` : "Every statement adds up.",
      href: "/upload",
      action: "Open statements",
      done: needsReview === 0,
    },
    {
      key: "categories",
      title: "Sort your transactions into categories",
      hint: uncategorised > 0 ? `${uncategorised} still uncategorised. The Review tab groups similar ones so one choice sorts many.` : "Everything is categorised.",
      href: "/categories",
      action: "Open Categories",
      done: uncategorised === 0,
    },
    {
      key: "budget",
      title: "Set a monthly budget",
      hint: "Pick a category and a limit; the dashboard and Reports show how you are doing.",
      href: "/budgets",
      action: "Open Budgets",
      done: (budgets ?? 0) > 0,
    },
    {
      key: "backup",
      title: "Make a backup",
      hint: "Your data lives only on this computer. Run backup.ps1 from the scripts folder with -Verify -Encrypt, then schedule it (docs/06).",
      href: "/system",
      action: "See backup status",
      done: backedUp === true,
    },
  ];
  const finished = steps.filter((s) => s.done).length;
  if (hidden || finished === steps.length) return null;

  return (
    <section aria-label="Getting started" className="rounded border border-slate-200 bg-surface p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">Getting started</h2>
          <p className="text-xs text-slate-500">
            {finished} of {steps.length} done. Each step ticks itself.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            savePref("gettingStartedHidden", "1");
            setHidden(true);
          }}
          className="text-xs text-slate-500 underline hover:text-slate-900"
        >
          Hide this
        </button>
      </div>
      <ol className="space-y-2 text-sm">
        {steps.map((s) => (
          <li key={s.key} className="flex items-start gap-2">
            <span
              aria-hidden="true"
              className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${
                s.done ? "bg-green-700 text-canvas" : "border border-slate-400 text-transparent"
              }`}
            >
              ✓
            </span>
            <div className="min-w-0 flex-1">
              <span className={s.done ? "text-slate-500 line-through" : "font-medium"}>{s.title}</span>
              <span className="sr-only">{s.done ? " (done)" : " (not done yet)"}</span>
              {!s.done && <p className="text-xs text-slate-600">{s.hint}</p>}
            </div>
            {!s.done && (
              <Link href={s.href} className="shrink-0 text-xs text-accent underline">
                {s.action}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

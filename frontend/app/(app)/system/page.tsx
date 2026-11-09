"use client";

import { useCallback, useEffect, useState } from "react";
import { LoadError, Skeleton } from "@/components/states";
import { AiActivity, api, HardwareReport, OllamaStatus } from "@/lib/api";
import { formatMs } from "@/lib/format";

const PURPOSE: Record<string, string> = {
  categorize: "Categorising",
  merchant: "Merchant names",
  search: "Search in plain words",
  embed: "Similarity vectors",
  summary: "Month summary",
  explain: "Flag explanations",
};

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-1 text-sm">
      <dt className="text-slate-600">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded border border-slate-200 bg-surface p-4">
      <h2 className="mb-2 font-medium">{title}</h2>
      <dl>{children}</dl>
    </section>
  );
}

export default function SystemPage() {
  const [ollama, setOllama] = useState<OllamaStatus | null>(null);
  const [hardware, setHardware] = useState<HardwareReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [warming, setWarming] = useState(false);
  const [activity, setActivity] = useState<AiActivity | null>(null);
  const [activityOpen, setActivityOpen] = useState(false); // collapsed: just the card's name

  const loadOllama = useCallback(async (warmup: boolean) => {
    setWarming(warmup);
    try {
      setOllama(await api<OllamaStatus>(`/system/ollama?warmup=${warmup}`));
    } catch {
      setError("Could not load AI status.");
    } finally {
      setWarming(false);
    }
  }, []);

  useEffect(() => {
    api<AiActivity>("/ai/activity")
      .then(setActivity)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    loadOllama(false);
    api<HardwareReport>("/system/hardware")
      .then(setHardware)
      .catch(() => setError("Could not load hardware report."));
  }, [loadOllama]);

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">System</h1>
      {error && (
        <LoadError
          message={error}
          onRetry={() => {
            setError(null);
            loadOllama(false);
            api<HardwareReport>("/system/hardware")
              .then(setHardware)
              .catch(() => setError("Could not load hardware report."));
          }}
        />
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Local AI (Ollama)">
          {ollama ? (
            <>
              <Row label="Reachable" value={ollama.reachable ? "Yes" : "No"} />
              <Row label="Configured model" value={ollama.model} />
              <Row label="Model installed" value={ollama.model_present ? "Yes" : "No"} />
              <Row label="Digest" value={ollama.digest ? ollama.digest.slice(0, 12) : "–"} />
              {ollama.warmup_ok !== null && (
                <Row
                  label="Warm-up"
                  value={ollama.warmup_ok ? `OK (${ollama.warmup_ms} ms)` : "Failed"}
                />
              )}
              {ollama.error && <p className="mt-2 text-sm text-amber-700">{ollama.error}</p>}
              <button
                onClick={() => loadOllama(true)}
                disabled={warming || !ollama.model_present}
                className="mt-3 rounded border border-slate-300 px-3 py-1 text-sm disabled:opacity-50"
              >
                {warming ? "Running…" : "Run warm-up inference"}
              </button>
            </>
          ) : (
            <div role="status" aria-label="Loading" className="space-y-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /><Skeleton className="h-4 w-3/5" /></div>
          )}
        </Card>

        <Card title="Hardware">
          {hardware ? (
            <>
              <Row
                label="CPU"
                value={`${hardware.cpu_cores ?? "?"} cores / ${hardware.cpu_threads ?? "?"} threads`}
              />
              <Row
                label="RAM"
                value={`${hardware.ram_available_gb} free / ${hardware.ram_total_gb} GB`}
              />
              <Row
                label="Disk"
                value={`${hardware.disk_free_gb} free / ${hardware.disk_total_gb} GB`}
              />
              <Row label="GPU" value={hardware.gpu.present ? (hardware.gpu.name ?? "Yes") : "None"} />
              <Row label="Suggested model size" value={hardware.recommended_model_size} />
              <p className="mt-2 text-xs text-slate-500">
                Values describe the backend container, so they may differ from the host.
              </p>
            </>
          ) : (
            <div role="status" aria-label="Loading" className="space-y-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /><Skeleton className="h-4 w-3/5" /></div>
          )}
        </Card>
      </div>

      <section className="rounded border border-slate-200 bg-surface">
        <h2>
          <button
            type="button"
            onClick={() => setActivityOpen((open) => !open)}
            aria-expanded={activityOpen}
            aria-controls="ai-activity-details"
            className="flex w-full items-center justify-between gap-3 p-4 text-left font-medium hover:bg-slate-100"
          >
            AI activity
            <span aria-hidden="true" className={`text-slate-500 transition-transform ${activityOpen ? "rotate-180" : ""}`}>
              ▾
            </span>
          </button>
        </h2>
        <div id="ai-activity-details" hidden={!activityOpen} className="px-4 pb-4">
        <p className="mb-3 text-xs text-slate-500">
          How often the local model was called in the last {activity?.window_days ?? 30} days and how
          long each call took. Only the kind of call, the model, the time and whether the reply was
          usable are kept; what was asked and answered is never stored.
        </p>
        {!activity ? (
          <Skeleton className="h-4 w-2/3" />
        ) : activity.summary.length === 0 ? (
          <p className="text-sm text-slate-500">No calls yet. Ask the AI to categorise, name merchants or search.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <tr>
                    <th className="py-1.5 pr-3 font-medium">What</th>
                    <th className="px-3 py-1.5 text-right font-medium">Calls</th>
                    <th className="px-3 py-1.5 text-right font-medium">Usable</th>
                    <th className="px-3 py-1.5 text-right font-medium">Average</th>
                    <th className="px-3 py-1.5 text-right font-medium">Slowest</th>
                    <th className="py-1.5 pl-3 text-right font-medium">Total time</th>
                  </tr>
                </thead>
                <tbody>
                  {activity.summary.map((p) => (
                    <tr key={p.purpose} className="border-b border-slate-100 last:border-0">
                      <td className="py-1.5 pr-3">{PURPOSE[p.purpose] ?? p.purpose}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{p.runs}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">
                        {p.ok_runs}/{p.runs}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatMs(p.avg_ms)}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{formatMs(p.max_ms)}</td>
                      <td className="py-1.5 pl-3 text-right tabular-nums">{formatMs(p.total_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h3 className="mb-1 mt-4 text-sm text-slate-600">Latest calls</h3>
            <ul className="divide-y divide-slate-100 text-sm">
              {activity.recent.slice(0, 10).map((r, i) => (
                <li key={`${r.at}-${i}`} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
                  <span>
                    {PURPOSE[r.purpose] ?? r.purpose}{" "}
                    <span className="text-xs text-slate-500">
                      {new Date(r.at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })} · {r.model}
                    </span>
                  </span>
                  <span className="tabular-nums">
                    {formatMs(r.duration_ms)}
                    {!r.ok && <span className="ml-2 text-xs text-amber-700">unusable reply</span>}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
        </div>
      </section>
    </section>
  );
}

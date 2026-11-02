"use client";

import { useCallback, useEffect, useState } from "react";
import { api, HardwareReport, OllamaStatus } from "@/lib/api";

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
    <section className="rounded border border-slate-200 bg-white p-4">
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
    loadOllama(false);
    api<HardwareReport>("/system/hardware")
      .then(setHardware)
      .catch(() => setError("Could not load hardware report."));
  }, [loadOllama]);

  return (
    <section className="space-y-4">
      <h1 className="text-xl font-semibold">System</h1>
      {error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

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
            <p className="text-sm text-slate-500">Loading…</p>
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
            <p className="text-sm text-slate-500">Loading…</p>
          )}
        </Card>
      </div>
    </section>
  );
}

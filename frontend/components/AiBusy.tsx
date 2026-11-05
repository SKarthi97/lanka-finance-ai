"use client";

import { useEffect, useRef, useState } from "react";
import { formatDuration } from "@/lib/format";

/**
 * Shows that the local AI is working, and for how long.
 *
 * - A live timer, so a long wait does not look like a hang.
 * - With a usual duration (`etaS`, worked out on the server from recent calls) a progress bar that
 *   fills towards it, and a note when it is taking longer than usual. Without one, an
 *   indeterminate shimmer. The bar never claims completion: it stops at 95%.
 * - `elapsedS` (from the server) keeps the timer right after a page reload; without it the timer
 *   starts when this appears. `showAfterMs` hides it for very quick answers instead of flashing.
 * - Motion is switched off for people who ask their system to reduce it; the text still says it all.
 */
export function AiBusy({
  label,
  elapsedS,
  etaS,
  queued = false,
  detail,
  compact = false,
  showAfterMs = 0,
}: {
  label: string;
  elapsedS?: number | null;
  etaS?: number | null;
  queued?: boolean;
  detail?: string;
  compact?: boolean;
  showAfterMs?: number;
}) {
  const startedAt = useRef(Date.now());
  const [now, setNow] = useState(Date.now());

  // Re-anchor whenever the server reports a fresh elapsed time.
  useEffect(() => {
    if (elapsedS !== null && elapsedS !== undefined) startedAt.current = Date.now() - elapsedS * 1000;
  }, [elapsedS]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);

  const elapsedMs = Math.max(0, now - startedAt.current);
  if (elapsedMs < showAfterMs && (elapsedS === null || elapsedS === undefined)) return null;

  const seconds = Math.floor(elapsedMs / 1000);
  const known = etaS !== null && etaS !== undefined && etaS > 0 && !queued;
  const percent = known ? Math.min(95, (seconds / (etaS as number)) * 100) : 0;
  const late = known && seconds > (etaS as number) * 1.25;

  const note = queued
    ? "Waiting for the worker to pick it up…"
    : known
      ? late
        ? `Taking longer than the usual ${formatDuration(etaS as number)}. Still working.`
        : `Usually about ${formatDuration(etaS as number)}`
      : "This can take a few minutes on a CPU.";

  const dots = (
    <span aria-hidden="true" className="inline-flex items-end gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{ animationDelay: `${i * 150}ms` }}
          className="h-1.5 w-1.5 rounded-full bg-accent motion-safe:animate-bounce"
        />
      ))}
    </span>
  );

  if (compact) {
    return (
      <p role="status" className="flex items-center gap-2 text-xs text-slate-600">
        {dots}
        <span>{label}</span>
        <span aria-hidden="true" className="tabular-nums text-slate-500">
          {formatDuration(seconds)}
        </span>
      </p>
    );
  }

  return (
    <div className="w-full rounded border border-accent/30 bg-accent/5 p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span role="status" className="flex items-center gap-2 font-medium">
          {dots}
          {label}
        </span>
        <span aria-hidden="true" className="tabular-nums text-slate-600">
          {formatDuration(seconds)}
        </span>
      </div>

      <div
        aria-hidden="true"
        className="relative mt-2 h-1.5 overflow-hidden rounded bg-slate-200"
      >
        {known ? (
          <div
            className={`h-1.5 rounded transition-[width] duration-700 ease-out ${late ? "bg-amber-400" : "bg-accent"}`}
            style={{ width: `${percent}%` }}
          />
        ) : (
          <div className="absolute inset-y-0 w-1/3 rounded bg-accent motion-safe:animate-shimmer motion-reduce:w-full motion-reduce:opacity-40" />
        )}
      </div>

      <p className="mt-1.5 text-xs text-slate-500">
        {note}
        {detail ? ` ${detail}` : ""}
      </p>
    </div>
  );
}

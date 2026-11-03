"use client";

import { STATUS_LABEL, STATUS_STYLE } from "@/lib/format";

// A shape per status, so the state reads without relying on colour alone.
const ICON: Record<string, string> = {
  queued: "◷",
  processing: "↻",
  inspected: "↻",
  reconciled: "✓",
  accepted: "✓",
  needs_review: "⚠",
  failed: "✕",
};

export function StatusBadge({ status, title }: { status: string; title?: string }) {
  const spinning = status === "processing" || status === "inspected";
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ${
        STATUS_STYLE[status] ?? STATUS_STYLE.queued
      }`}
    >
      <span aria-hidden="true" className={spinning ? "inline-block animate-spin" : undefined}>
        {ICON[status] ?? "◷"}
      </span>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

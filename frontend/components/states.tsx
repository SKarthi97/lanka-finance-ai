"use client";

/** Placeholder block shown while data loads, so the page keeps its shape. */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded bg-slate-100 ${className}`} />;
}

/** A card-shaped skeleton: a label, a figure and a hint line. */
export function CardSkeleton() {
  return (
    <div role="status" aria-label="Loading" className="space-y-3 rounded border border-slate-200 bg-surface p-4">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-6 w-32" />
      <Skeleton className="h-3 w-40" />
    </div>
  );
}

/** Table-shaped skeleton for lists. */
export function RowsSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-2 rounded border border-slate-200 bg-surface p-4">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  );
}

/** A visible failure with a way to try again (never leave a section silently blank). */
export function LoadError({
  message = "Could not load this.",
  onRetry,
}: {
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      <span>{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded border border-red-700/50 px-3 py-1 text-xs font-medium hover:bg-red-100"
        >
          Try again
        </button>
      )}
    </div>
  );
}

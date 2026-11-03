"use client";

type Props = {
  page: number; // 1-based
  pages: number;
  onChange: (page: number) => void;
};

/** First, last and the pages around the current one; gaps become an ellipsis. */
export function pageWindow(page: number, pages: number): (number | "…")[] {
  const wanted = new Set([1, pages, page - 1, page, page + 1]);
  const numbers = [...wanted].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);

  const out: (number | "…")[] = [];
  numbers.forEach((n, index) => {
    if (index > 0 && n - numbers[index - 1] > 1) out.push("…");
    out.push(n);
  });
  return out;
}

const button =
  "min-w-8 rounded border border-slate-300 px-2 py-1 text-sm disabled:opacity-40";

export function Pager({ page, pages, onChange }: Props) {
  if (pages <= 1) return null;

  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center gap-1">
      <button className={button} onClick={() => onChange(1)} disabled={page === 1} aria-label="First page">
        «
      </button>
      <button className={button} onClick={() => onChange(page - 1)} disabled={page === 1}>
        Previous
      </button>

      {pageWindow(page, pages).map((entry, index) =>
        entry === "…" ? (
          <span key={`gap-${index}`} className="px-1 text-slate-400">
            …
          </span>
        ) : (
          <button
            key={entry}
            onClick={() => onChange(entry)}
            aria-current={entry === page ? "page" : undefined}
            className={`${button} ${entry === page ? "border-accent bg-accent text-accent-fg" : ""}`}
          >
            {entry}
          </button>
        ),
      )}

      <button className={button} onClick={() => onChange(page + 1)} disabled={page === pages}>
        Next
      </button>
      <button className={button} onClick={() => onChange(pages)} disabled={page === pages} aria-label="Last page">
        »
      </button>
    </nav>
  );
}

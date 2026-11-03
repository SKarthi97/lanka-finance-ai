"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useConfirm } from "@/components/ConfirmDialog";
import { LoadError, RowsSkeleton } from "@/components/states";
import { StatusBadge } from "@/components/StatusBadge";
import {
  api,
  ApiError,
  DocumentDetail,
  DocumentItem,
  TransactionItem,
  TransactionList,
} from "@/lib/api";
import {
  ACTIVE_STATUSES,
  CHECK_LABEL,
  ISSUE_LABEL,
  WINDOW_LABEL,
  explainError,
  formatAmount,
  formatDate,
  formatMoney,
} from "@/lib/format";

const DECLARED_LABEL: Record<string, string> = {
  deposits: "Deposits",
  withdrawals: "Withdrawals",
};

const PAGE_LIMIT = 500;

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}

export default function DocumentPage() {
  const router = useRouter();
  const confirm = useConfirm();
  const { id } = useParams<{ id: string }>();

  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [rows, setRows] = useState<TransactionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedPage, setSelectedPage] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const detail = await api<DocumentDetail>(`/documents/${id}`);
      setDoc(detail);
      const list = await api<TransactionList>(
        `/transactions?document_id=${id}&duplicates=show&limit=${PAGE_LIMIT}`,
      );
      // The API lists newest first; a statement reads oldest first.
      setRows([...list.items].sort((a, b) => a.seq - b.seq));
      setTotal(list.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this document.");
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const active = doc ? ACTIVE_STATUSES.has(doc.status) : false;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [active, load]);

  const issuesBySeq = useMemo(() => {
    const map = new Map<number, string[]>();
    for (const issue of doc?.validation?.issues ?? []) {
      if (issue.seq !== null) map.set(issue.seq, [...(map.get(issue.seq) ?? []), issue.code]);
    }
    return map;
  }, [doc]);

  async function accept() {
    const ok = await confirm({
      title: "Accept this statement?",
      message:
        "It did not reconcile, so some figures may be wrong. Once accepted, its transactions count in your balances, income and expense.",
      confirmLabel: "Accept anyway",
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api<DocumentItem>(`/documents/${id}/accept`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not accept the statement.");
    } finally {
      setBusy(false);
    }
  }

  async function reprocess() {
    setBusy(true);
    setError(null);
    try {
      await api<DocumentItem>(`/documents/${id}/reprocess`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not re-run extraction.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !doc) {
    return (
      <section className="space-y-3">
        <LoadError
          message={error}
          onRetry={() => {
            setError(null);
            load();
          }}
        />
        <button onClick={() => router.push("/upload")} className="text-sm underline">
          Back to uploads
        </button>
      </section>
    );
  }
  if (!doc) return <RowsSkeleton rows={8} />;

  const checks = Object.entries(doc.validation?.checks ?? {});
  const issues = doc.validation?.issues ?? [];
  const failedReason = doc.status === "failed" ? explainError(doc.error) : null;

  return (
    <section className="space-y-6">
      <div>
        <Link href="/upload" className="text-sm text-slate-500 hover:underline">
          ← Uploads
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">{doc.original_filename}</h1>
          <StatusBadge status={doc.status} />
          {doc.file_available && ["needs_review", "failed", "reconciled"].includes(doc.status) && (
            <button
              onClick={reprocess}
              disabled={busy}
              title="Run extraction again on the stored original"
              className="rounded border border-slate-300 px-2 py-0.5 text-xs disabled:opacity-50"
            >
              Re-run extraction
            </button>
          )}
        </div>
      </div>

      {error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {failedReason && (
        <p role="alert" className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
          {failedReason} Delete this upload and try again once the cause is fixed.
        </p>
      )}

      <dl className="grid grid-cols-2 gap-4 rounded border border-slate-200 bg-surface p-4 md:grid-cols-4">
        <Fact label="Bank" value={doc.bank_code ? doc.bank_code.toUpperCase() : "–"} />
        <Fact label="Account" value={doc.account_last4 ? `•••• ${doc.account_last4}` : "Not found"} />
        <Fact
          label="Period"
          value={doc.period_start ? `${formatDate(doc.period_start)} – ${formatDate(doc.period_end)}` : formatDate(doc.period_end)}
        />
        <Fact label="Pages" value={doc.page_count ?? "–"} />
        <Fact label="Opening balance" value={formatMoney(doc.opening_balance)} />
        <Fact label="Closing balance" value={formatMoney(doc.closing_balance)} />
        <Fact label="Transactions" value={doc.transaction_count} />
        <Fact
          label="Extraction confidence"
          value={doc.extraction_confidence === null ? "–" : `${Math.round(doc.extraction_confidence * 100)}%`}
        />
      </dl>

      {doc.duplicate_count > 0 && (
        <p role="status" className="rounded bg-slate-100 px-4 py-3 text-sm text-slate-700">
          {doc.duplicate_count} row{doc.duplicate_count === 1 ? " is" : "s are"} also in another
          statement and {doc.duplicate_count === 1 ? "is" : "are"} counted only once in totals.
          They are shown below in grey.
        </p>
      )}

      {doc.status === "needs_review" && (
        <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <p className="font-medium">This statement did not reconcile.</p>
          <p className="mt-1">
            Its transactions are excluded from totals until you resolve or accept it. Compare the
            flagged rows with the original page below.
          </p>
          <button
            onClick={accept}
            disabled={busy}
            className="mt-3 rounded bg-accent px-3 py-1.5 text-accent-fg disabled:opacity-50"
          >
            {busy ? "Accepting…" : "Accept anyway"}
          </button>
        </div>
      )}

      {doc.validation?.declared && Object.keys(doc.validation.declared).length > 0 && (
        <section className="rounded border border-slate-200 bg-surface p-4">
          <h2 className="mb-1 font-medium">Statement totals</h2>
          <p className="mb-2 text-xs text-slate-500">
            What the statement prints about itself, next to what was extracted. For information
            only: it does not affect reconciliation.
          </p>
          <table className="w-full text-left text-sm">
            <thead className="text-slate-600">
              <tr>
                <th className="py-1 font-medium"></th>
                <th className="py-1 font-medium">Items (statement / found)</th>
                <th className="py-1 text-right font-medium">Total (statement / found)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(doc.validation.declared).map(([key, d]) => (
                <tr key={key} className="border-t border-slate-100">
                  <td className="py-1">{DECLARED_LABEL[key] ?? key}</td>
                  <td className="py-1">
                    {d.declared_count ?? "–"} / {d.found_count}{" "}
                    {d.count_match === null ? "" : d.count_match ? "✓" : "≠"}
                  </td>
                  <td className="py-1 text-right tabular-nums">
                    {formatMoney(d.declared_total)} / {formatMoney(d.found_total)}{" "}
                    {d.total_match === null ? "" : d.total_match ? "✓" : "≠"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {doc.validation.declared_window && (
            <p className="mt-2 text-sm text-slate-700">
              {WINDOW_LABEL(doc.validation.declared_window, doc.transaction_count)}
            </p>
          )}
        </section>
      )}

      {doc.validation && (
        <div className="grid gap-4 md:grid-cols-2">
          <section className="rounded border border-slate-200 bg-surface p-4">
            <h2 className="mb-2 font-medium">Checks</h2>
            <ul className="space-y-1 text-sm">
              {checks.map(([name, c]) => (
                <li key={name} className="flex justify-between">
                  <span>{CHECK_LABEL[name] ?? name}</span>
                  <span className={c.failed ? "font-medium text-red-700" : "text-green-700"}>
                    {c.failed ? `${c.failed} failed` : "passed"}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded border border-slate-200 bg-surface p-4">
            <h2 className="mb-2 font-medium">Issues ({issues.length})</h2>
            {issues.length === 0 ? (
              <p className="text-sm text-slate-500">No issues found.</p>
            ) : (
              <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                {issues.map((issue, index) => (
                  <li key={index}>
                    {ISSUE_LABEL[issue.code] ?? issue.code}
                    {(issue.page || issue.seq) && (
                      <span className="text-slate-500">
                        {" "}
                        ({issue.page ? `page ${issue.page}` : ""}
                        {issue.page && issue.seq ? ", " : ""}
                        {issue.seq ? `row ${issue.seq}` : ""})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <section>
          <h2 className="mb-2 font-medium">Transactions</h2>
          {rows.length === 0 ? (
            <p className="text-sm text-slate-500">
              {active ? "Processing…" : "No transactions extracted."}
            </p>
          ) : (
            <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 text-slate-600">
                  <tr>
                    <th className="px-3 py-2 font-medium">Date</th>
                    <th className="px-3 py-2 font-medium">Description</th>
                    <th className="px-3 py-2 text-right font-medium">Debit</th>
                    <th className="px-3 py-2 text-right font-medium">Credit</th>
                    <th className="px-3 py-2 text-right font-medium">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => {
                    const flagged = t.validation_status !== "ok";
                    return (
                      <tr
                        key={t.id}
                        onClick={() => setSelectedPage(t.source_page)}
                        title={
                          flagged
                            ? (issuesBySeq.get(t.seq) ?? []).map((c) => ISSUE_LABEL[c] ?? c).join(" ")
                            : "Show the source page"
                        }
                        className={`cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50 ${
                          flagged ? "bg-amber-50" : ""
                        } ${t.is_duplicate ? "text-slate-400" : ""} ${selectedPage === t.source_page ? "outline outline-1 outline-slate-300" : ""}`}
                      >
                        <td className="whitespace-nowrap px-3 py-2">{formatDate(t.transaction_date)}</td>
                        <td className="px-3 py-2">
                          {t.description}
                          {t.is_duplicate && (
                            <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                              duplicate
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatAmount(t.debit)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatAmount(t.credit)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatMoney(t.running_balance)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {total > rows.length && (
            <p className="mt-2 text-xs text-slate-500">
              Showing the first {rows.length} of {total}. Use the Transactions page to browse all.
            </p>
          )}
        </section>

        <section>
          <h2 className="mb-2 font-medium">Source page</h2>
          {!doc.file_available ? (
            <p className="rounded border border-slate-200 bg-surface p-4 text-sm text-slate-500">
              The original PDF is not stored (it is deleted after a statement reconciles). Set
              RETAIN_DOCUMENTS=true to keep originals for checking rows against the page.
            </p>
          ) : selectedPage === null ? (
            <p className="rounded border border-slate-200 bg-surface p-4 text-sm text-slate-500">
              Click a transaction to see the page it came from.
            </p>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <button
                  className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40"
                  onClick={() => setSelectedPage((p) => (p ?? 1) - 1)}
                  disabled={selectedPage <= 1}
                >
                  ‹
                </button>
                <span>
                  Page {selectedPage} of {doc.page_count ?? "?"}
                </span>
                <button
                  className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40"
                  onClick={() => setSelectedPage((p) => (p ?? 1) + 1)}
                  disabled={selectedPage >= (doc.page_count ?? 1)}
                >
                  ›
                </button>
              </div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`/api/documents/${doc.id}/pages/${selectedPage}/image`}
                alt={`Page ${selectedPage} of the original statement`}
                className="w-full rounded border border-slate-200 bg-surface"
              />
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

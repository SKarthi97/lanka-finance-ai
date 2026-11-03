"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { TransactionItem } from "@/lib/api";
import { NO_ACCOUNT_HINT, SOURCE_LABEL, formatAmount, formatDate, formatMoney } from "@/lib/format";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-200 py-2 text-sm last:border-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

/** Side panel with everything known about one transaction, including why it has its category. */
export function TransactionDetail({
  transaction: t,
  onClose,
}: {
  transaction: TransactionItem;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);

  const isDebit = Number(t.debit) > 0;
  const source = t.classification_source;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button aria-label="Close details" onClick={onClose} className="absolute inset-0 bg-black/60" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Transaction details"
        className="relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-slate-200 bg-canvas p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-500">{formatDate(t.transaction_date)}</p>
            <h2 className="mt-1 break-words text-lg font-semibold">{t.description}</h2>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            aria-label="Close"
            className="rounded p-2 text-lg leading-none text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          >
            ✕
          </button>
        </div>

        <p className={`mb-4 text-3xl font-semibold tabular-nums ${isDebit ? "text-red-700" : "text-green-700"}`}>
          {isDebit ? "−" : "+"}
          {formatAmount(isDebit ? t.debit : t.credit)}
        </p>

        <dl className="rounded border border-slate-200 bg-surface px-4">
          <Row label="Balance after">{formatMoney(t.running_balance)}</Row>
          <Row label="Bank">
            {t.bank_name ?? t.bank_code?.toUpperCase() ?? "Unknown"}
            {t.account_last4 ? (
              <span className="ml-1 text-slate-500">•••• {t.account_last4}</span>
            ) : (
              <span className="ml-1 text-slate-400" title={NO_ACCOUNT_HINT}>
                account not detected
              </span>
            )}
          </Row>
          <Row label="Statement">
            <Link href={`/documents/${t.document_id}`} className="underline">
              #{t.document_id}
            </Link>{" "}
            <span className="text-slate-500">
              page {t.source_page}, line {t.seq}
            </span>
          </Row>
          <Row label="Extraction check">
            {t.validation_status === "ok" ? (
              <span className="text-green-700">✓ Balance checks out</span>
            ) : (
              <span className="text-amber-700">⚠ Needs review</span>
            )}
          </Row>
        </dl>

        <h3 className="mb-2 mt-5 text-sm font-medium">Category</h3>
        <div className="rounded border border-slate-200 bg-surface p-4 text-sm">
          <p className="font-medium">{t.category_name ?? "Uncategorised"}</p>
          {source ? (
            <>
              <p className="mt-1 text-slate-600">
                Set by: {SOURCE_LABEL[source] ?? source}
                {source === "llm" && t.classification_confidence !== null && (
                  <> · confidence {Math.round(t.classification_confidence * 100)}%</>
                )}
              </p>
              {t.classification_explanation && (
                <p className="mt-1 text-slate-600">Why: {t.classification_explanation}</p>
              )}
              {source === "llm" && (
                <p className="mt-2 text-xs text-slate-500">
                  This is a suggestion from the local AI. Confirm or change it on the Categories page
                  (AI suggestions tab) or from the category list in the table.
                </p>
              )}
            </>
          ) : (
            <p className="mt-1 text-slate-500">No rule or AI suggestion matched this transaction.</p>
          )}
        </div>

        {t.is_duplicate && (
          <p className="mt-5 rounded bg-amber-50 px-4 py-3 text-sm text-amber-800">
            This transaction also appears in another statement
            {t.duplicate_of_id ? ` (copy of transaction #${t.duplicate_of_id})` : ""}, so it is not
            counted twice in totals.
          </p>
        )}

        <div className="mt-5 flex flex-wrap gap-3 text-sm">
          <Link href={`/documents/${t.document_id}`} className="rounded border border-slate-300 px-3 py-1.5 hover:bg-slate-100">
            Open statement
          </Link>
        </div>
      </aside>
    </div>
  );
}

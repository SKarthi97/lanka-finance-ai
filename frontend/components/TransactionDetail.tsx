"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { AiBusy } from "@/components/AiBusy";
import { api, ApiError, FlagExplanation, TransactionItem, TxFlag } from "@/lib/api";
import { NO_ACCOUNT_HINT, SOURCE_LABEL, formatAmount, formatDate, formatMoney, formatMs } from "@/lib/format";

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
  onRenamed,
}: {
  transaction: TransactionItem;
  onClose: () => void;
  onRenamed?: (name: string, source: "manual" | "llm" | "rule") => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [name, setName] = useState(t.merchant);
  const [nameMessage, setNameMessage] = useState<string | null>(null);

  useEffect(() => setName(t.merchant), [t.merchant]);

  // Why this row is flagged: fixed sentences from the app's own checks, loaded when it opens.
  const [flags, setFlags] = useState<TxFlag[]>([]);
  const [explained, setExplained] = useState<FlagExplanation | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);

  useEffect(() => {
    setExplained(null);
    setExplainError(null);
    api<{ flags: TxFlag[] }>(`/transactions/${t.id}/flags`)
      .then((result) => setFlags(result.flags))
      .catch(() => setFlags([]));
  }, [t.id]);

  async function explain() {
    setExplaining(true);
    setExplainError(null);
    try {
      setExplained(await api<FlagExplanation>(`/transactions/${t.id}/explain`, { method: "POST" }));
    } catch (err) {
      setExplainError(err instanceof ApiError ? err.message : "Could not explain this.");
    } finally {
      setExplaining(false);
    }
  }

  async function saveName(event: FormEvent) {
    event.preventDefault();
    const next = name.trim();
    if (!next || next === t.merchant) return;
    try {
      const result = await api<{ merchant: string; merchant_source: "manual" }>(`/transactions/${t.id}/merchant`, {
        method: "PUT",
        json: { name: next },
      });
      setNameMessage("Saved. Every transaction with this description now shows it.");
      onRenamed?.(result.merchant, result.merchant_source);
    } catch (err) {
      setNameMessage(err instanceof ApiError ? err.message : "Could not save the name.");
    }
  }

  async function resetName() {
    try {
      const result = await api<{ merchant: string; merchant_source: "rule" }>(`/transactions/${t.id}/merchant`, {
        method: "DELETE",
      });
      setNameMessage("Back to the tidied description.");
      onRenamed?.(result.merchant, result.merchant_source);
    } catch {
      setNameMessage("Could not reset the name.");
    }
  }

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
            <h2 className="mt-1 break-words text-lg font-semibold">{t.merchant}</h2>
            {t.merchant.toLowerCase() !== t.description.toLowerCase() && (
              <p className="break-words text-xs text-slate-500">{t.description}</p>
            )}
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

        {flags.length > 0 && (
          <section
            aria-label="Why this is flagged"
            className="mb-4 rounded border border-l-4 border-amber-200 border-l-amber-400 bg-amber-50 p-3 text-sm text-amber-900"
          >
            <h3 className="mb-1 font-medium">Why this is flagged</h3>
            <ul className="list-disc space-y-1 pl-5">
              {flags.map((f) => (
                <li key={f.code}>{f.title}</li>
              ))}
            </ul>
            <button
              type="button"
              onClick={explain}
              disabled={explaining}
              title="The local AI sees only the reasons above, the money direction and the category; never the description, amount or date."
              className="mt-3 rounded border border-amber-400 px-3 py-1 text-xs hover:bg-amber-100 disabled:opacity-60"
            >
              ✨ Explain in plain words
            </button>
            {explaining && (
              <div className="mt-2">
                <AiBusy compact showAfterMs={300} label="The local AI is explaining" />
              </div>
            )}
            {explainError && (
              <p role="alert" className="mt-2 text-xs text-red-700">
                {explainError}
              </p>
            )}
            {explained?.explanation && (
              <div className="mt-3 space-y-1 border-t border-amber-200 pt-2">
                <p>{explained.explanation}</p>
                {explained.check && (
                  <p>
                    <span className="font-medium">Check: </span>
                    {explained.check}
                  </p>
                )}
                {explained.model_ms !== null && (
                  <p className="text-xs opacity-70">Written by the local AI in {formatMs(explained.model_ms)}.</p>
                )}
              </div>
            )}
            {explained && !explained.explanation && explained.ai_note && (
              <p className="mt-2 text-xs">{explained.ai_note}</p>
            )}
          </section>
        )}

        <form onSubmit={saveName} className="mb-4 rounded border border-slate-200 bg-surface p-3 text-sm">
          <label htmlFor="merchant-name" className="mb-1 block text-xs text-slate-500">
            Merchant name{" "}
            <span className="text-slate-400">
              ({t.merchant_source === "manual" ? "set by you" : t.merchant_source === "llm" ? "suggested by the local AI" : "tidied automatically"})
            </span>
          </label>
          <div className="flex gap-2">
            <input
              id="merchant-name"
              value={name}
              maxLength={40}
              onChange={(e) => setName(e.target.value)}
              className="min-w-0 flex-1 rounded border border-slate-300 bg-surface px-2 py-1.5"
            />
            <button type="submit" disabled={!name.trim() || name.trim() === t.merchant} className="rounded bg-accent px-3 py-1.5 text-accent-fg disabled:opacity-50">
              Save
            </button>
          </div>
          {t.merchant_source !== "rule" && (
            <button type="button" onClick={resetName} className="mt-2 text-xs text-accent underline">
              Reset to the tidied description
            </button>
          )}
          {nameMessage && (
            <p role="status" className="mt-2 text-xs text-slate-600">
              {nameMessage}
            </p>
          )}
        </form>

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

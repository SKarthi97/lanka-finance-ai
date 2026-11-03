"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useConfirm } from "@/components/ConfirmDialog";
import { LoadError, RowsSkeleton } from "@/components/states";
import { StatementTracker } from "@/components/StatementTracker";
import { api, ApiError, DocumentItem } from "@/lib/api";
import { ACTIVE_STATUSES, STATUS_LABEL, STATUS_STYLE, explainError } from "@/lib/format";

const BANKS = [{ code: "boc", name: "Bank of Ceylon" }];

function formatSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function UploadPage() {
  const confirm = useConfirm();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [bank, setBank] = useState("boc");
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "ok" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [listState, setListState] = useState<"loading" | "ok" | "error">("loading");

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await api<DocumentItem[]>("/documents"));
      setListState("ok");
    } catch {
      setListState("error"); // a 401 is handled by the layout, which redirects to /login
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  // The tracker reloads whenever a statement is added, removed or changes status.
  const statusSignature = documents.map((d) => `${d.id}:${d.status}`).join(",");

  // Poll while anything is still being processed.
  const hasActive = documents.some((d) => ACTIVE_STATUSES.has(d.status));
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(loadDocuments, 3000);
    return () => clearInterval(timer);
  }, [hasActive, loadDocuments]);

  async function remove(doc: DocumentItem) {
    const ok = await confirm({
      title: "Delete this statement?",
      message: (
        <>
          <span className="font-medium text-slate-900">{doc.original_filename}</span> and every
          transaction read from it will be removed. This cannot be undone.
        </>
      ),
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api(`/documents/${doc.id}`, { method: "DELETE" });
      setMessage({ kind: "ok", text: `${doc.original_filename} deleted.` });
      await loadDocuments();
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof ApiError ? err.message : "Could not delete the document.",
      });
    }
  }

  async function rerun(doc: DocumentItem) {
    try {
      await api(`/documents/${doc.id}/reprocess`, { method: "POST" });
      setMessage({ kind: "info", text: `Re-running extraction for ${doc.original_filename}.` });
      await loadDocuments();
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof ApiError ? err.message : "Could not re-run extraction.",
      });
    }
  }

  function reset() {
    setFile(null);
    setPassword("");
    setNeedsPassword(false);
    if (fileInput.current) fileInput.current.value = "";
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setMessage(null);
    setBusy(true);

    const form = new FormData();
    form.append("file", file);
    form.append("bank_code", bank);
    if (needsPassword && password) form.append("password", password);

    try {
      await api<DocumentItem>("/documents", { method: "POST", form });
      setMessage({ kind: "ok", text: `${file.name} uploaded and queued.` });
      reset();
      await loadDocuments();
    } catch (err) {
      if (err instanceof ApiError && err.code === "password_required") {
        setNeedsPassword(true);
        setMessage({ kind: "info", text: "This PDF is password protected. Enter its password below." });
      } else if (err instanceof ApiError && err.code === "password_incorrect") {
        setNeedsPassword(true);
        setPassword("");
        setMessage({ kind: "error", text: "Incorrect password. Try again." });
      } else if (err instanceof ApiError && err.code === "duplicate") {
        const name = err.detail?.original_filename;
        const at = err.detail?.uploaded_at;
        const when = typeof at === "string" ? new Date(at).toLocaleString() : null;
        setMessage({
          kind: "error",
          text:
            `Identical file already uploaded${name ? ` as "${name}"` : ""}` +
            `${when ? ` on ${when}` : ""}. Files are compared by content, not name. ` +
            "To upload it again, delete the existing one below first.",
        });
        reset();
      } else {
        setMessage({
          kind: "error",
          text: err instanceof ApiError ? err.message : "Upload failed.",
        });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Upload statements</h1>

      <form onSubmit={onSubmit} className="space-y-4 rounded border border-slate-200 bg-surface p-4">
        <label className="block text-sm">
          Bank
          <select
            value={bank}
            onChange={(e) => setBank(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
          >
            {BANKS.map((b) => (
              <option key={b.code} value={b.code}>
                {b.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          PDF statement
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setNeedsPassword(false);
              setPassword("");
              setMessage(null);
            }}
            className="mt-1 block w-full text-sm"
          />
        </label>

        {needsPassword && (
          <label className="block text-sm">
            PDF password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="off"
              autoFocus
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
            />
            <span className="mt-1 block text-xs text-slate-500">
              Used once to open this file. It is not stored.
            </span>
          </label>
        )}

        {message && (
          <p
            role={message.kind === "error" ? "alert" : "status"}
            className={
              message.kind === "error"
                ? "rounded bg-red-50 px-3 py-2 text-sm text-red-700"
                : message.kind === "info"
                  ? "rounded bg-blue-50 px-3 py-2 text-sm text-blue-800"
                  : "rounded bg-green-50 px-3 py-2 text-sm text-green-800"
            }
          >
            {message.text}
          </p>
        )}

        <button
          type="submit"
          disabled={!file || busy || (needsPassword && !password)}
          className="rounded bg-accent px-4 py-2 text-sm text-accent-fg disabled:opacity-50"
        >
          {busy ? "Uploading…" : needsPassword ? "Unlock and upload" : "Upload"}
        </button>
      </form>

      <StatementTracker refreshKey={statusSignature} />

      <div>
        <h2 className="mb-2 font-medium">Uploaded statements</h2>
        {listState === "loading" ? (
          <RowsSkeleton />
        ) : listState === "error" && documents.length === 0 ? (
          <LoadError message="Could not load your statements." onRetry={loadDocuments} />
        ) : documents.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing uploaded yet.</p>
        ) : (
          <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-slate-600">
                <tr>
                  <th className="px-3 py-2 font-medium">File</th>
                  <th className="px-3 py-2 font-medium">Bank</th>
                  <th className="px-3 py-2 font-medium">Pages</th>
                  <th className="px-3 py-2 font-medium">Size</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr key={d.id} className="border-b border-slate-100 last:border-0">
                    <td className="px-3 py-2">
                      <Link href={`/documents/${d.id}`} className="text-slate-900 underline">
                        {d.original_filename}
                      </Link>
                      {d.is_encrypted && (
                        <span className="ml-2 text-xs text-slate-500">(was encrypted)</span>
                      )}
                    </td>
                    <td className="px-3 py-2 uppercase">{d.bank_code ?? "–"}</td>
                    <td className="px-3 py-2">{d.page_count ?? "–"}</td>
                    <td className="px-3 py-2">{formatSize(d.size_bytes)}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[d.status] ?? STATUS_STYLE.queued}`}
                        title={explainError(d.error) ?? undefined}
                      >
                        {STATUS_LABEL[d.status] ?? d.status}
                      </span>
                    </td>
                    <td className="space-x-3 whitespace-nowrap px-3 py-2 text-right">
                      {d.file_available && ["needs_review", "failed", "reconciled"].includes(d.status) && (
                        <button
                          onClick={() => rerun(d)}
                          title="Run extraction again on the stored original"
                          className="text-xs text-slate-700 hover:underline"
                        >
                          Re-run
                        </button>
                      )}
                      <button
                        onClick={() => remove(d)}
                        disabled={d.status === "processing"}
                        className="text-xs text-red-700 hover:underline disabled:opacity-40"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

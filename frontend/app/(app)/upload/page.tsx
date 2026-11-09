"use client";

import { DragEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useConfirm } from "@/components/ConfirmDialog";
import { LoadError, RowsSkeleton } from "@/components/states";
import { api, ApiError, DocumentItem } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { ACTIVE_STATUSES, bankTint, explainError } from "@/lib/format";

const BANKS = [
  { code: "", name: "Detect automatically (recommended)" },
  { code: "boc", name: "Bank of Ceylon" },
  { code: "hnb", name: "Hatton National Bank" },
  { code: "commercial", name: "Commercial Bank" },
  { code: "sampath", name: "Sampath Bank" },
];

function formatSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function UploadPage() {
  const confirm = useConfirm();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [bank, setBank] = useState(""); // "" = let the app recognise the bank
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [message, setMessage] = useState<{ kind: "error" | "ok" | "info"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
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

  // A file arrives from the picker or from a drop; only PDFs are accepted.
  function choose(picked: File | null) {
    setNeedsPassword(false);
    setPassword("");
    if (picked && !/\.pdf$/i.test(picked.name) && picked.type !== "application/pdf") {
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setMessage({ kind: "error", text: "Only PDF statements can be uploaded." });
      return;
    }
    setFile(picked);
    setMessage(null);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files?.[0] ?? null);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setMessage(null);
    setBusy(true);

    const form = new FormData();
    form.append("file", file);
    if (bank) form.append("bank_code", bank);
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

  const inProgress = documents.filter((d) => ACTIVE_STATUSES.has(d.status)).length;
  const needReview = documents.filter((d) => d.status === "needs_review").length;
  const failed = documents.filter((d) => d.status === "failed").length;

  return (
    <section className="space-y-6">
      <h1 className="text-xl font-semibold">Upload statements</h1>

      <form onSubmit={onSubmit} className="space-y-4 rounded border border-slate-200 bg-surface p-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors ${
            dragging ? "border-accent bg-accent/10" : file ? "border-green-700/50 bg-green-50" : "border-slate-300"
          }`}
        >
          <input
            ref={fileInput}
            id="statement-file"
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
            className="peer sr-only"
          />
          {file ? (
            <div className="flex flex-wrap items-center justify-center gap-3">
              <span aria-hidden="true" className="text-2xl">
                📄
              </span>
              <div className="text-left">
                <p className="font-medium text-slate-900">{file.name}</p>
                <p className="text-xs text-slate-500">{formatSize(file.size)} · PDF</p>
              </div>
              <button
                type="button"
                onClick={() => {
                  reset();
                  setMessage(null);
                }}
                className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
              >
                Remove
              </button>
            </div>
          ) : (
            <>
              <p aria-hidden="true" className="text-3xl">
                📥
              </p>
              <p className="mt-2 text-sm text-slate-900">Drop a PDF statement here</p>
              <p className="mt-1 text-xs text-slate-500">
                or{" "}
                <label htmlFor="statement-file" className="cursor-pointer text-accent underline">
                  choose a file
                </label>
                . It stays on this computer; nothing is sent anywhere.
              </p>
            </>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            Bank
            <select
              value={bank}
              onChange={(e) => setBank(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 bg-surface px-3 py-2"
            >
              {BANKS.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </select>
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
        </div>

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

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!file || busy || (needsPassword && !password)}
            className="rounded bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
          >
            {busy ? "Uploading…" : needsPassword ? "Unlock and upload" : "Upload"}
          </button>
          {busy && (
            <span
              className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-accent"
              aria-hidden="true"
            />
          )}
        </div>
      </form>

      <div>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-medium">Uploaded statements</h2>
          {documents.length > 0 && (
            <p className="text-xs text-slate-500">
              {documents.length} statement{documents.length === 1 ? "" : "s"}
              {inProgress > 0 && ` · ${inProgress} in progress`}
              {needReview > 0 && ` · ${needReview} need review`}
              {failed > 0 && ` · ${failed} failed`}
            </p>
          )}
        </div>
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
                  <th className="px-3 py-2 font-medium">Uploaded</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr
                    key={d.id}
                    className={`border-b border-slate-100 last:border-0 hover:bg-slate-50 ${
                      d.status === "failed" ? "bg-red-50" : d.status === "needs_review" ? "bg-amber-50" : ""
                    }`}
                  >
                    <td className="px-3 py-2">
                      <Link href={`/documents/${d.id}`} className="font-medium text-slate-900 hover:underline">
                        {d.original_filename}
                      </Link>
                      {d.is_encrypted && (
                        <span className="ml-2 text-xs text-slate-500">(was encrypted)</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-2 py-0.5 text-xs font-medium uppercase ${bankTint(d.bank_code)}`}>
                        {d.bank_code ?? "–"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-500">{d.page_count ?? "–"}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-500">{formatSize(d.size_bytes)}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-500">
                      {new Date(d.created_at).toLocaleDateString("en-GB", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                      })}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={d.status} title={explainError(d.error) ?? undefined} />
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

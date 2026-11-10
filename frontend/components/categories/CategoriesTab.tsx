"use client";

import { FormEvent, useState } from "react";
import { useConfirm } from "@/components/ConfirmDialog";
import { CategoryItem, api } from "@/lib/api";
import { KIND_LABEL, kindChip } from "@/lib/format";
import { input, primary, subtle, Run } from "@/components/categories/shared";

export function CategoriesTab({ categories, run }: { categories: CategoryItem[]; run: Run }) {
  const confirm = useConfirm();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"expense" | "income" | "transfer">("expense");
  const [parent, setParent] = useState("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  // A sub-category goes under a top-level category of the same kind (one level only).
  const parents = categories.filter((c) => c.kind === kind && c.parent_id === null);

  function add(event: FormEvent) {
    event.preventDefault();
    run(async () => {
      await api("/categories", { method: "POST", json: { name, kind, parent_id: parent ? Number(parent) : null } });
      setName("");
      setParent("");
      return `Added “${name}”.`;
    });
  }

  function rename(c: CategoryItem) {
    run(async () => {
      await api(`/categories/${c.id}`, { method: "PATCH", json: { name: newName } });
      setRenaming(null);
      return `Renamed “${c.name}” to “${newName}”.`;
    });
  }

  function moveUnder(c: CategoryItem, value: string) {
    run(async () => {
      await api(`/categories/${c.id}`, { method: "PATCH", json: { set_parent: true, parent_id: value ? Number(value) : null } });
      return value ? `“${c.name}” is now a sub-category.` : `“${c.name}” is a top-level category again.`;
    });
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Transfers move money between your own accounts, so they are left out of income and expense
        totals.
      </p>

      <form onSubmit={add} className="flex flex-wrap items-end gap-2 rounded border border-slate-200 bg-surface p-3">
        <label className="text-sm">
          New category
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} className={`${input} mt-1 block`} />
        </label>
        <label className="text-sm">
          Kind
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as typeof kind);
              setParent("");
            }}
            className={`${input} mt-1 block`}
          >
            <option value="expense">Expense</option>
            <option value="income">Income</option>
            <option value="transfer">Transfer</option>
          </select>
        </label>
        <label className="text-sm">
          Under (optional)
          <select value={parent} onChange={(e) => setParent(e.target.value)} className={`${input} mt-1 block`}>
            <option value="">Top level</option>
            {parents.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <button className={primary} type="submit" disabled={!name.trim()}>
          Add
        </button>
      </form>

      <div className="overflow-x-auto rounded border border-slate-200 bg-surface">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-600">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Kind</th>
              <th className="px-3 py-2 text-right font-medium">Transactions</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c.id} className="border-b border-slate-100 last:border-0">
                <td className="px-3 py-2">
                  {renaming === c.id ? (
                    <span className="flex items-center gap-2">
                      <input
                        aria-label={`New name for ${c.name}`}
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        maxLength={64}
                        autoFocus
                        className={`${input} w-48`}
                      />
                      <button className={primary} disabled={!newName.trim() || newName === c.name} onClick={() => rename(c)}>
                        Save
                      </button>
                      <button className={subtle} onClick={() => setRenaming(null)}>
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <>
                      {c.parent_id !== null && <span aria-hidden="true" className="mr-1 text-slate-400">↳</span>}
                      {c.full_name || c.name}
                      {c.is_system && <span className="ml-2 text-xs text-slate-400">built in</span>}
                    </>
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs ${kindChip(c.kind)}`}>{KIND_LABEL[c.kind]}</span>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{c.transactions}</td>
                <td className="space-x-3 whitespace-nowrap px-3 py-2 text-right">
                  {!c.is_system && renaming !== c.id && (
                    <>
                      <button
                        className="text-xs text-accent hover:underline"
                        onClick={() => {
                          setRenaming(c.id);
                          setNewName(c.name);
                        }}
                      >
                        Rename
                      </button>
                      <select
                        aria-label={`Move ${c.name} under`}
                        value={c.parent_id ?? ""}
                        onChange={(e) => moveUnder(c, e.target.value)}
                        className="max-w-[9rem] rounded border border-slate-200 bg-surface px-1 py-0.5 text-xs"
                      >
                        <option value="">Top level</option>
                        {categories
                          .filter((p) => p.kind === c.kind && p.parent_id === null && p.id !== c.id)
                          .map((p) => (
                            <option key={p.id} value={p.id}>
                              Under {p.name}
                            </option>
                          ))}
                      </select>
                    </>
                  )}
                  {!c.is_system && (
                    <button
                      className="text-xs text-red-700 hover:underline"
                      onClick={async () => {
                        const ok = await confirm({
                          title: `Delete “${c.name}”?`,
                          message: "Only categories with no transactions can be deleted.",
                          confirmLabel: "Delete",
                          tone: "danger",
                        });
                        if (!ok) return;
                        run(async () => {
                          await api(`/categories/${c.id}`, { method: "DELETE" });
                          return `Deleted “${c.name}”.`;
                        });
                      }}
                    >
                      Delete
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export type ConfirmOptions = {
  title: string;
  message?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** "danger" colours the confirm button red and focuses Cancel first. */
  tone?: "default" | "danger";
};

/** true = confirmed, false = the cancel button, null = dismissed (clicked outside or Escape).
 * Both false and null are falsy, so `if (!(await confirm(...))) return;` treats them alike. */
type Confirm = (options: ConfirmOptions) => Promise<boolean | null>;

const ConfirmContext = createContext<Confirm>(async () => false);

/** `const confirm = useConfirm(); if (!(await confirm({ title: "Delete it?" }))) return;` */
export function useConfirm(): Confirm {
  return useContext(ConfirmContext);
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = useState<{
    options: ConfirmOptions;
    resolve: (answer: boolean | null) => void;
  } | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const dialog = useRef<HTMLDivElement>(null);

  const confirm = useCallback<Confirm>(
    (options) =>
      new Promise<boolean | null>((resolve) => {
        opener.current = document.activeElement as HTMLElement | null;
        setPending({ options, resolve });
      }),
    [],
  );

  const answer = useCallback(
    (value: boolean | null) => {
      pending?.resolve(value);
      setPending(null);
      opener.current?.focus?.(); // hand focus back to what opened the dialog
    },
    [pending],
  );

  useEffect(() => {
    if (!pending) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        answer(null);
      } else if (event.key === "Tab" && dialog.current) {
        // Keep keyboard focus inside the dialog.
        const buttons = Array.from(dialog.current.querySelectorAll<HTMLElement>("button"));
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pending, answer]);

  const options = pending?.options;
  const danger = options?.tone === "danger";

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {options && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onMouseDown={(e) => e.target === e.currentTarget && answer(null)}
        >
          <div
            ref={dialog}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby={options.message ? "confirm-message" : undefined}
            className="w-full max-w-md rounded-lg border border-slate-200 bg-surface p-5 shadow-xl"
          >
            <h2 id="confirm-title" className="text-base font-semibold">
              {options.title}
            </h2>
            {options.message && (
              <div id="confirm-message" className="mt-2 text-sm text-slate-600">
                {options.message}
              </div>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                autoFocus={danger}
                onClick={() => answer(false)}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
              >
                {options.cancelLabel ?? "Cancel"}
              </button>
              <button
                autoFocus={!danger}
                onClick={() => answer(true)}
                className={
                  danger
                    ? "rounded bg-red-700 px-3 py-1.5 text-sm font-medium text-canvas hover:opacity-90"
                    : "rounded bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
                }
              >
                {options.confirmLabel ?? "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

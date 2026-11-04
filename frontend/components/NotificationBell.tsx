"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, Notifications } from "@/lib/api";

/** The header bell: what needs your attention. `refreshKey` reloads it (page changes). */
export function NotificationBell({ refreshKey }: { refreshKey: string }) {
  const [data, setData] = useState<Notifications | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<Notifications>("/notifications")
      .then(setData)
      .catch(() => setData(null));
  }, [refreshKey]);

  // Close on Escape or a click elsewhere.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  useEffect(() => setOpen(false), [refreshKey]);

  const count = data?.count ?? 0;
  const label = count === 0 ? "Notifications: nothing needs attention" : `Notifications: ${count} need attention`;

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={label}
        aria-haspopup="true"
        aria-expanded={open}
        title={label}
        className="relative rounded p-2 text-lg leading-none hover:bg-slate-100"
      >
        <span aria-hidden="true">🔔</span>
        {count > 0 && (
          <span
            aria-hidden="true"
            className="absolute right-0 top-0 min-w-[1.1rem] rounded-full bg-accent px-1 text-center text-[10px] font-bold leading-[1.1rem] text-accent-fg"
          >
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <div
          role="region"
          aria-label="Notifications"
          className="absolute right-0 top-full z-40 mt-2 w-[22rem] max-w-[calc(100vw-2rem)] rounded-lg border border-slate-200 bg-chrome shadow-xl"
        >
          <div className="border-b border-slate-200 px-4 py-2 text-sm font-medium">Needs your attention</div>
          {count === 0 ? (
            <p className="px-4 py-4 text-sm text-slate-500">You are all caught up. Statements are current.</p>
          ) : (
            <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
              {data!.items.map((n) => (
                <li key={n.key}>
                  <Link
                    href={n.href}
                    onClick={() => setOpen(false)}
                    className="flex gap-2 px-4 py-3 text-sm hover:bg-slate-100"
                  >
                    <span aria-hidden="true" className={n.severity === "warn" ? "text-amber-500" : "text-sky-500"}>
                      ●
                    </span>
                    <span>{n.text}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

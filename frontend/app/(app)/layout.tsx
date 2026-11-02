"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, ApiError, Me, OllamaStatus, setCsrfToken } from "@/lib/api";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [ollama, setOllama] = useState<OllamaStatus | null>(null);

  useEffect(() => {
    api<Me>("/auth/me")
      .then((user) => {
        setCsrfToken(user.csrf_token);
        setMe(user);
        api<OllamaStatus>("/system/ollama").then(setOllama).catch(() => setOllama(null));
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
      });
  }, [router]);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setCsrfToken(null);
    router.replace("/login");
  }

  if (!me) {
    return <p className="p-6 text-sm text-slate-500">Loading…</p>;
  }

  const aiUnavailable = ollama !== null && (!ollama.reachable || !ollama.model_present);

  const link = (href: string, label: string) => (
    <Link
      href={href}
      className={
        pathname === href ? "font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"
      }
    >
      {label}
    </Link>
  );

  return (
    <div className="mx-auto max-w-5xl px-4">
      <header className="flex items-center justify-between border-b border-slate-200 py-4">
        <nav className="flex gap-5 text-sm">
          <span className="font-semibold">Lanka Finance AI</span>
          {link("/", "Dashboard")}
          {link("/system", "System")}
        </nav>
        <div className="flex items-center gap-3 text-sm text-slate-600">
          <span>{me.username}</span>
          <button onClick={logout} className="rounded border border-slate-300 px-2 py-1">
            Sign out
          </button>
        </div>
      </header>

      {aiUnavailable && (
        <div role="status" className="mt-4 rounded bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Local AI is unavailable ({ollama?.error ?? "unknown reason"}). Extraction and
          rule-based categorization continue to work; AI features resume when the model is back.
        </div>
      )}

      <main className="py-6">{children}</main>
    </div>
  );
}

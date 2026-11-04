"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ConfirmProvider } from "@/components/ConfirmDialog";
import { NotificationBell } from "@/components/NotificationBell";
import { LoadError } from "@/components/states";
import {
  api,
  ApiError,
  CategorizationStatus,
  DocumentItem,
  Me,
  OllamaStatus,
  setCsrfToken,
} from "@/lib/api";

const NAV: { heading: string; items: { href: string; label: string; icon: string }[] }[] = [
  {
    heading: "Main",
    items: [
      { href: "/", label: "Dashboard", icon: "🏠" },
      { href: "/transactions", label: "Transactions", icon: "🧾" },
      { href: "/upload", label: "Upload", icon: "📥" },
    ],
  },
  {
    heading: "Manage",
    items: [
      { href: "/categories", label: "Categories", icon: "🏷️" },
      { href: "/system", label: "System", icon: "🖥️" },
      { href: "/settings", label: "Settings", icon: "⚙️" },
    ],
  },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [ollama, setOllama] = useState<OllamaStatus | null>(null);
  const [uncategorised, setUncategorised] = useState(0);
  const [needsReview, setNeedsReview] = useState(0);
  const [collapsed, setCollapsed] = useState(false); // icons-only sidebar on large screens
  const [drawer, setDrawer] = useState(false); // sidebar open on small screens
  const [search, setSearch] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setLoadFailed(false);
    api<Me>("/auth/me")
      .then((user) => {
        setCsrfToken(user.csrf_token);
        setMe(user);
        api<OllamaStatus>("/system/ollama").then(setOllama).catch(() => setOllama(null));
        api<CategorizationStatus>("/categorization/status")
          .then((s) => setUncategorised(s.uncategorised))
          .catch(() => undefined);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
        else setLoadFailed(true); // backend down or unreachable: say so instead of spinning
      });
  }, [router, attempt]);

  // Remember the collapsed sidebar in this browser.
  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem("sidebarCollapsed") === "1");
    } catch {
      /* storage blocked: stay expanded */
    }
  }, []);

  function toggleCollapsed() {
    setCollapsed((value) => {
      try {
        window.localStorage.setItem("sidebarCollapsed", value ? "0" : "1");
      } catch {
        /* works for this visit only */
      }
      return !value;
    });
  }

  // Badge counts refresh whenever you move between pages (after uploading, categorising...).
  useEffect(() => {
    if (!me) return;
    api<CategorizationStatus>("/categorization/status")
      .then((s) => setUncategorised(s.uncategorised))
      .catch(() => undefined);
    api<DocumentItem[]>("/documents")
      .then((docs) => setNeedsReview(docs.filter((d) => d.status === "needs_review").length))
      .catch(() => undefined);
  }, [me, pathname]);

  // Close the drawer after navigating, and on Escape.
  useEffect(() => setDrawer(false), [pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setCsrfToken(null);
    router.replace("/login");
  }

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    const q = search.trim();
    // A full navigation, so the Transactions page re-reads the filter even when already open.
    window.location.assign(q ? `/transactions?q=${encodeURIComponent(q)}` : "/transactions");
  }

  if (!me) {
    return (
      <div className="mx-auto max-w-md p-6">
        {loadFailed ? (
          <LoadError
            message="Cannot reach the server. Is the backend running?"
            onRetry={() => setAttempt((n) => n + 1)}
          />
        ) : (
          <p role="status" className="text-sm text-slate-500">
            Loading…
          </p>
        )}
      </div>
    );
  }

  const aiUnavailable = ollama !== null && (!ollama.reachable || !ollama.model_present);
  const initials = me.username.slice(0, 2).toUpperCase();

  return (
    <ConfirmProvider>
    <div className="min-h-screen">
      <a
        href="#main"
        className="sr-only z-50 rounded bg-accent px-3 py-2 text-sm font-medium text-accent-fg focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      {/* Top bar */}
      <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-chrome px-4">
        <button
          onClick={() => setDrawer((open) => !open)}
          aria-label={drawer ? "Close menu" : "Open menu"}
          aria-expanded={drawer}
          className="rounded p-2 text-lg leading-none text-slate-700 hover:bg-slate-100 lg:hidden"
        >
          ☰
        </button>
        <Link href="/" className="text-lg font-extrabold tracking-tight text-slate-900">
          Lanka<span className="text-accent">Finance</span>
          <span className="ml-1 hidden text-xs font-medium text-slate-500 sm:inline">AI</span>
        </Link>

        <form onSubmit={submitSearch} role="search" className="mx-2 max-w-md flex-1">
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-surface px-3 py-1.5 text-sm focus-within:border-accent">
            <span aria-hidden="true">🔍</span>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search transactions…"
              aria-label="Search transactions"
              className="w-full bg-transparent outline-none"
            />
          </label>
        </form>

        <div className="ml-auto flex items-center gap-2">
          <NotificationBell refreshKey={pathname} />
          <span
            title={me.username}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-sm font-bold text-accent-fg"
          >
            {initials}
          </span>
        </div>
      </header>

      {/* Overlay behind the drawer on small screens */}
      {drawer && (
        <button
          aria-label="Close menu"
          onClick={() => setDrawer(false)}
          className="fixed inset-0 top-14 z-20 bg-black/60 lg:hidden"
        />
      )}

      {/* Sidebar: always visible on large screens, a slide-in drawer on small ones */}
      <aside
        className={`fixed bottom-0 left-0 top-14 z-20 w-64 overflow-y-auto overflow-x-hidden border-r border-slate-200 bg-rail px-3 py-4 transition-all duration-200 lg:translate-x-0 ${
          collapsed ? "lg:w-16 lg:px-2" : ""
        } ${drawer ? "translate-x-0" : "-translate-x-full"}`}
      >
        <nav aria-label="Main" className="flex h-full flex-col">
          {NAV.map((group) => (
            <div key={group.heading} className="mb-4">
              <div
                className={`px-3 pb-2 text-[11px] font-bold uppercase tracking-widest text-slate-500 ${
                  collapsed ? "lg:hidden" : ""
                }`}
              >
                {group.heading}
              </div>
              <ul className="space-y-1">
                {group.items.map((item) => {
                  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                  const badge =
                    item.href === "/categories"
                      ? uncategorised
                      : item.href === "/upload"
                        ? needsReview
                        : 0;
                  const badgeHint =
                    item.href === "/upload"
                      ? `${badge} statement${badge === 1 ? "" : "s"} need review`
                      : `${badge} uncategorised`;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        title={collapsed ? item.label : undefined}
                        className={`relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${
                          active
                            ? "bg-accent/10 font-medium text-slate-900"
                            : "text-slate-500 hover:bg-slate-100 hover:text-slate-800"
                        }`}
                      >
                        <span aria-hidden="true" className="w-6 text-center text-lg leading-none">
                          {item.icon}
                        </span>
                        <span className={`flex-1 ${collapsed ? "lg:hidden" : ""}`}>{item.label}</span>
                        {badge > 0 && (
                          <span
                            title={badgeHint}
                            aria-label={badgeHint}
                            className={`rounded-full bg-accent px-2 py-0.5 text-[11px] font-bold text-accent-fg ${
                              collapsed ? "lg:absolute lg:right-1 lg:top-1 lg:px-1.5 lg:text-[10px]" : ""
                            }`}
                          >
                            {badge > 99 ? "99+" : badge}
                          </span>
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}

          <div className="mt-auto border-t border-slate-200 pt-3">
            <div className={`px-3 pb-2 text-xs text-slate-500 ${collapsed ? "lg:hidden" : ""}`}>
              Signed in as {me.username}
            </div>
            <button
              onClick={logout}
              title={collapsed ? "Sign out" : undefined}
              className="w-full whitespace-nowrap rounded-lg px-3 py-2.5 text-left text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            >
              <span aria-hidden="true" className="mr-3 inline-block w-6 text-center text-lg leading-none">
                🚪
              </span>
              <span className={collapsed ? "lg:hidden" : ""}>Sign out</span>
            </button>
            <button
              onClick={toggleCollapsed}
              aria-pressed={collapsed}
              title={collapsed ? "Expand the sidebar" : "Collapse the sidebar to icons"}
              className="mt-1 hidden w-full whitespace-nowrap rounded-lg px-3 py-2.5 text-left text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-800 lg:block"
            >
              <span aria-hidden="true" className="mr-3 inline-block w-6 text-center text-lg leading-none">
                {collapsed ? "»" : "«"}
              </span>
              <span className={collapsed ? "lg:hidden" : ""}>Collapse</span>
            </button>
          </div>
        </nav>
      </aside>

      <div className={`pt-14 transition-all duration-200 ${collapsed ? "lg:pl-16" : "lg:pl-64"}`}>
        {aiUnavailable && (
          <div role="status" className="mx-4 mt-4 rounded bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Local AI is unavailable ({ollama?.error ?? "unknown reason"}). Extraction and
            rule-based categorization continue to work; AI features resume when the model is back.
          </div>
        )}
        <main id="main" tabIndex={-1} className="mx-auto outline-none max-w-6xl px-4 py-6 sm:px-6">{children}</main>
      </div>
    </div>
    </ConfirmProvider>
  );
}

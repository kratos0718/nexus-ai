"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { isAuthenticated, logout, getMe } from "@/lib/auth";
import type { User } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [backendReady, setBackendReady] = useState(true);

  useEffect(() => {
    // Ping backend; if it's sleeping (HF Space free tier) show a warm-up banner
    fetch(`${API_BASE.replace("/api/v1", "")}/ping`)
      .then(() => setBackendReady(true))
      .catch(() => setBackendReady(false));
  }, []);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    getMe().then(setUser).catch(() => router.replace("/login"));
  }, [router]);

  const navItems = [
    { href: "/dashboard", label: "Documents", icon: "📄" },
    { href: "/chat", label: "Chat", icon: "💬" },
    { href: "/observability", label: "Observability", icon: "📊" },
    { href: "/system-prompts", label: "Personas", icon: "🎭" },
  ];

  return (
    <div className="flex flex-col h-screen overflow-hidden" style={{ background: "var(--background)" }}>
      {!backendReady && (
        <div className="w-full px-4 py-2 text-xs text-center font-medium" style={{ background: "#f59e0b", color: "#000" }}>
          Backend is warming up — requests may take 30–60 seconds on first use. Please wait…
        </div>
      )}
    <div className="flex flex-1 overflow-hidden" style={{ background: "var(--background)" }}>
      {/* Sidebar */}
      <aside
        className="w-56 flex-shrink-0 flex flex-col border-r"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="px-4 py-5 border-b" style={{ borderColor: "var(--border)" }}>
          <span className="font-bold text-lg" style={{ color: "var(--text)" }}>
            Nexus AI
          </span>
        </div>

        <nav className="flex-1 px-2 py-4 flex flex-col gap-1">
          {navItems.map(({ href, label, icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors"
                style={{
                  background: active ? "var(--surface-2)" : "transparent",
                  color: active ? "var(--text)" : "var(--text-muted)",
                }}
              >
                <span>{icon}</span>
                {label}
              </Link>
            );
          })}
        </nav>

        {/* User footer */}
        <div className="p-3 border-t" style={{ borderColor: "var(--border)" }}>
          {user && (
            <div className="flex items-center gap-2 mb-2 px-1">
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0"
                style={{ background: "var(--accent)", color: "#fff" }}
              >
                {user.full_name[0]?.toUpperCase()}
              </div>
              <div className="overflow-hidden">
                <p className="text-xs font-medium truncate" style={{ color: "var(--text)" }}>
                  {user.full_name}
                </p>
                <p className="text-xs truncate" style={{ color: "var(--text-muted)" }}>
                  {user.email}
                </p>
              </div>
            </div>
          )}
          <button
            onClick={logout}
            className="w-full text-left px-3 py-1.5 rounded-lg text-xs transition-colors"
            style={{ color: "var(--text-muted)" }}
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
    </div>
  );
}

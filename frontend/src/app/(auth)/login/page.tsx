"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Login failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--background)" }}>
      <div className="w-full max-w-sm p-8 rounded-xl border" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
        <div className="mb-8">
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>
            Nexus AI
          </h1>
          <p style={{ color: "var(--text-muted)" }}>Sign in to your account</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm mb-1.5" style={{ color: "var(--text-muted)" }}>
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border outline-none text-sm"
              style={{
                background: "var(--surface-2)",
                borderColor: "var(--border)",
                color: "var(--text)",
              }}
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label className="block text-sm mb-1.5" style={{ color: "var(--text-muted)" }}>
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border outline-none text-sm"
              style={{
                background: "var(--surface-2)",
                borderColor: "var(--border)",
                color: "var(--text)",
              }}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="text-sm px-3 py-2 rounded-lg" style={{ background: "#ef44441a", color: "var(--danger)" }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg text-sm font-medium text-white transition-opacity disabled:opacity-60"
            style={{ background: "var(--accent)" }}
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-sm text-center" style={{ color: "var(--text-muted)" }}>
          No account?{" "}
          <Link href="/register" style={{ color: "var(--accent)" }}>
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}

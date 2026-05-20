"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { register } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "", full_name: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function update(field: string, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (form.password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await register(form.email, form.password, form.full_name);
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Registration failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  const inputStyle = {
    background: "var(--surface-2)",
    borderColor: "var(--border)",
    color: "var(--text)",
  };

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--background)" }}>
      <div className="w-full max-w-sm p-8 rounded-xl border" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
        <div className="mb-8">
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>Create account</h1>
          <p style={{ color: "var(--text-muted)" }}>Get started with Nexus AI</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {[
            { label: "Full name", field: "full_name", type: "text", placeholder: "Jane Smith" },
            { label: "Email", field: "email", type: "email", placeholder: "you@example.com" },
            { label: "Password", field: "password", type: "password", placeholder: "Min 8 characters" },
          ].map(({ label, field, type, placeholder }) => (
            <div key={field}>
              <label className="block text-sm mb-1.5" style={{ color: "var(--text-muted)" }}>
                {label}
              </label>
              <input
                type={type}
                required
                value={form[field as keyof typeof form]}
                onChange={(e) => update(field, e.target.value)}
                className="w-full px-3 py-2 rounded-lg border outline-none text-sm"
                style={inputStyle}
                placeholder={placeholder}
              />
            </div>
          ))}

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
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="mt-6 text-sm text-center" style={{ color: "var(--text-muted)" }}>
          Already have an account?{" "}
          <Link href="/login" style={{ color: "var(--accent)" }}>Sign in</Link>
        </p>
      </div>
    </div>
  );
}

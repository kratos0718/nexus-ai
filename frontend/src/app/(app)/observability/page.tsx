"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface Stats {
  total_calls: number;
  error_rate_pct: number;
  avg_duration_ms: number;
  min_duration_ms: number;
  max_duration_ms: number;
  p95_duration_ms: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

interface CacheStats {
  redis_connected: boolean;
  cached_queries: number;
  hits: number;
  misses: number;
  hit_rate_pct: number;
  redis_memory_mb: number;
}

interface FeedbackStats {
  total: number;
  positive: number;
  negative: number;
  positive_rate: number;
}

interface Trace {
  trace_id: string;
  trace_type: string;
  question: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  duration_ms: number;
  error: string | null;
  created_at: string;
}

// ── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div
      className="rounded-xl border p-5 flex flex-col gap-1"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <p className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
        {label}
      </p>
      <p
        className="text-2xl font-bold"
        style={{ color: accent ? "var(--accent)" : "var(--text)" }}
      >
        {value}
      </p>
      {sub && <p className="text-xs" style={{ color: "var(--text-muted)" }}>{sub}</p>}
    </div>
  );
}

function LatencyBar({ label, ms, max }: { label: string; ms: number; max: number }) {
  const pct = max > 0 ? Math.min((ms / max) * 100, 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs w-10 text-right flex-shrink-0" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <div className="flex-1 h-2 rounded-full" style={{ background: "var(--surface-2)" }}>
        <div
          className="h-2 rounded-full"
          style={{ width: `${pct}%`, background: "var(--accent)" }}
        />
      </div>
      <span className="text-xs w-16 flex-shrink-0" style={{ color: "var(--text)" }}>
        {ms.toFixed(0)} ms
      </span>
    </div>
  );
}

function TraceRow({ trace }: { trace: Trace }) {
  const modeColors: Record<string, string> = {
    rag_hyde: "#8b5cf6",
    rag_multiquery: "#0ea5e9",
    rag_standard: "#10b981",
    rag: "#10b981",
    agent: "#f59e0b",
  };
  const color = modeColors[trace.trace_type] || "var(--text-muted)";

  return (
    <tr style={{ borderBottom: "1px solid var(--border)" }}>
      <td className="px-4 py-3 max-w-xs">
        <p className="text-sm truncate" style={{ color: "var(--text)" }}>
          {trace.question}
        </p>
      </td>
      <td className="px-4 py-3">
        <span
          className="text-xs px-2 py-0.5 rounded-full font-medium"
          style={{ background: `${color}1a`, color }}
        >
          {trace.trace_type}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-right" style={{ color: "var(--text-muted)" }}>
        {(trace.prompt_tokens + trace.completion_tokens).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-sm text-right" style={{ color: "var(--text-muted)" }}>
        {trace.duration_ms.toFixed(0)} ms
      </td>
      <td className="px-4 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
        {new Date(trace.created_at).toLocaleTimeString()}
      </td>
      <td className="px-4 py-3 text-xs" style={{ color: trace.error ? "var(--danger)" : "var(--success)" }}>
        {trace.error ? "Error" : "OK"}
      </td>
    </tr>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function ObservabilityPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [feedback, setFeedback] = useState<FeedbackStats | null>(null);
  const [cache, setCache] = useState<CacheStats | null>(null);
  const [flushing, setFlushing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function fetchData() {
    try {
      const [statsRes, tracesRes, feedbackRes, cacheRes] = await Promise.all([
        api.get<Stats>("/traces/stats"),
        api.get<{ traces: Trace[]; count: number }>("/traces/"),
        api.get<FeedbackStats>("/feedback/stats"),
        api.get<CacheStats>("/cache/stats"),
      ]);
      setStats(statsRes.data);
      setTraces(tracesRes.data.traces);
      setFeedback(feedbackRes.data);
      setCache(cacheRes.data);
    } catch {
      setError("Failed to load observability data. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  }

  async function flushCache() {
    setFlushing(true);
    try {
      await api.delete("/cache/flush");
      await fetchData();
    } finally {
      setFlushing(false);
    }
  }

  useEffect(() => {
    fetchData();
    // Refresh every 30s while on the page
    const interval = setInterval(fetchData, 30_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center h-full">
        <p style={{ color: "var(--text-muted)" }}>Loading…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p>
      </div>
    );
  }

  const s = stats!;
  const fb = feedback;
  const totalTokens = s.total_tokens.toLocaleString();
  const costStr = s.estimated_cost_usd < 0.01
    ? `< $0.01`
    : `$${s.estimated_cost_usd.toFixed(3)}`;

  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const exportUrl = `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"}/feedback/export`;

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
          Observability
        </h1>
        <div className="flex gap-2">
          {fb && fb.total > 0 && (
            <a
              href={exportUrl}
              download="feedback_export.jsonl"
              onClick={(e) => {
                e.preventDefault();
                fetch(exportUrl, { headers: { Authorization: `Bearer ${token}` } })
                  .then((r) => r.blob())
                  .then((blob) => {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = "feedback_export.jsonl";
                    a.click();
                    URL.revokeObjectURL(url);
                  });
              }}
              className="text-xs px-3 py-1.5 rounded-lg border"
              style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
            >
              Export feedback
            </a>
          )}
          <button
            onClick={fetchData}
            className="text-xs px-3 py-1.5 rounded-lg border"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            Refresh
          </button>
        </div>
      </div>
      <p className="text-sm mb-8" style={{ color: "var(--text-muted)" }}>
        LLM call metrics for your account — updated in real time
      </p>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total queries" value={s.total_calls.toString()} accent />
        <StatCard
          label="Avg latency"
          value={`${s.avg_duration_ms.toFixed(0)} ms`}
          sub={`min: ${s.min_duration_ms.toFixed(0)}ms`}
        />
        <StatCard label="Total tokens" value={totalTokens} />
        <StatCard
          label="Est. cost"
          value={costStr}
          sub="Groq free tier: ~$0"
        />
      </div>

      {/* Feedback stats */}
      {fb && (
        <div className="grid grid-cols-3 gap-4 mb-8">
          <StatCard label="Ratings collected" value={fb.total.toString()} />
          <StatCard
            label="Positive rate"
            value={fb.total > 0 ? `${fb.positive_rate}%` : "—"}
            sub={`${fb.positive} 👍  ${fb.negative} 👎`}
            accent={fb.positive_rate >= 70}
          />
          <StatCard
            label="Fine-tuning pairs"
            value={fb.total > 0 ? fb.total.toString() : "0"}
            sub="Export as JSONL above"
          />
        </div>
      )}

      {/* Cache stats */}
      {cache && (
        <div
          className="rounded-xl border p-5 mb-8"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <div className="flex items-center justify-between mb-4">
            <p className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
              Query cache (Redis)
            </p>
            <div className="flex items-center gap-3">
              <span
                className="text-xs px-2 py-0.5 rounded-full"
                style={{
                  background: cache.redis_connected ? "#10b98120" : "#ef444420",
                  color: cache.redis_connected ? "var(--success)" : "var(--danger)",
                }}
              >
                {cache.redis_connected ? "Connected" : "Disconnected"}
              </span>
              <button
                onClick={flushCache}
                disabled={flushing || cache.cached_queries === 0}
                className="text-xs px-3 py-1 rounded-lg border disabled:opacity-40 transition-opacity"
                style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
              >
                {flushing ? "Flushing…" : "Flush cache"}
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <p className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>Cached queries</p>
              <p className="text-xl font-bold" style={{ color: "var(--text)" }}>{cache.cached_queries}</p>
            </div>
            <div>
              <p className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>Hit rate</p>
              <p
                className="text-xl font-bold"
                style={{ color: cache.hit_rate_pct >= 50 ? "var(--success)" : "var(--text)" }}
              >
                {cache.hit_rate_pct}%
              </p>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {cache.hits} hits · {cache.misses} misses
              </p>
            </div>
            <div>
              <p className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>Redis memory</p>
              <p className="text-xl font-bold" style={{ color: "var(--text)" }}>{cache.redis_memory_mb} MB</p>
            </div>
            <div>
              <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>Cache efficiency</p>
              <div className="h-2 rounded-full" style={{ background: "var(--surface-2)" }}>
                <div
                  className="h-2 rounded-full transition-all"
                  style={{
                    width: `${Math.min(cache.hit_rate_pct, 100)}%`,
                    background: cache.hit_rate_pct >= 50 ? "var(--success)" : "var(--accent)",
                  }}
                />
              </div>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                {cache.hit_rate_pct >= 50 ? "Good" : cache.hit_rate_pct > 0 ? "Building up" : "No data yet"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Error rate + latency range */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
        <div
          className="rounded-xl border p-5"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <p className="text-xs font-medium uppercase tracking-wide mb-4" style={{ color: "var(--text-muted)" }}>
            Latency range
          </p>
          <div className="flex flex-col gap-3">
            <LatencyBar label="Min" ms={s.min_duration_ms} max={s.max_duration_ms} />
            <LatencyBar label="Avg" ms={s.avg_duration_ms} max={s.max_duration_ms} />
            <LatencyBar label="P95" ms={s.p95_duration_ms} max={s.max_duration_ms} />
            <LatencyBar label="Max" ms={s.max_duration_ms} max={s.max_duration_ms} />
          </div>
        </div>

        <div
          className="rounded-xl border p-5"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <p className="text-xs font-medium uppercase tracking-wide mb-4" style={{ color: "var(--text-muted)" }}>
            Token breakdown
          </p>
          <div className="flex flex-col gap-3">
            <div className="flex justify-between text-sm">
              <span style={{ color: "var(--text-muted)" }}>Prompt tokens</span>
              <span style={{ color: "var(--text)" }}>{s.total_prompt_tokens.toLocaleString()}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span style={{ color: "var(--text-muted)" }}>Completion tokens</span>
              <span style={{ color: "var(--text)" }}>{s.total_completion_tokens.toLocaleString()}</span>
            </div>
            <div
              className="flex justify-between text-sm font-medium pt-2 border-t"
              style={{ borderColor: "var(--border)" }}
            >
              <span style={{ color: "var(--text)" }}>Total</span>
              <span style={{ color: "var(--accent)" }}>{s.total_tokens.toLocaleString()}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span style={{ color: "var(--text-muted)" }}>Error rate</span>
              <span
                style={{ color: s.error_rate_pct > 5 ? "var(--danger)" : "var(--success)" }}
              >
                {s.error_rate_pct.toFixed(1)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Recent traces table */}
      <div
        className="rounded-xl border overflow-hidden"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
            Recent queries
          </p>
        </div>
        {traces.length === 0 ? (
          <div className="p-8 text-center">
            <p style={{ color: "var(--text-muted)" }}>No queries yet — ask something in Chat.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Question", "Mode", "Tokens", "Latency", "Time", "Status"].map((h, i) => (
                  <th
                    key={h}
                    className={`px-4 py-3 font-medium text-xs uppercase tracking-wide ${i >= 2 ? "text-right" : "text-left"}`}
                    style={{ color: "var(--text-muted)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {traces.map((trace) => (
                <TraceRow key={trace.trace_id} trace={trace} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

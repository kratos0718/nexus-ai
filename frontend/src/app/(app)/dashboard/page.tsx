"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Document } from "@/types";

function StatusBadge({ status }: { status: Document["status"] }) {
  const cfg = {
    ready:      { color: "var(--success)", bg: "#10b9811a", label: "Ready" },
    processing: { color: "var(--warning)", bg: "#f59e0b1a", label: "Processing…" },
    pending:    { color: "var(--text-muted)", bg: "var(--surface-2)", label: "Pending" },
    failed:     { color: "var(--danger)", bg: "#ef44441a", label: "Failed" },
  }[status];
  return (
    <span
      className="px-2 py-0.5 rounded text-xs font-medium"
      style={{ color: cfg.color, background: cfg.bg }}
    >
      {cfg.label}
    </span>
  );
}

function formatBytes(bytes: number) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

type ChunkStrategy = "recursive" | "semantic" | "fixed";

const STRATEGY_LABELS: Record<ChunkStrategy, string> = {
  recursive: "Recursive (default)",
  semantic:  "Semantic (topic-aware)",
  fixed:     "Fixed size",
};

export default function DashboardPage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [uploading, setUploading] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [urlLoading, setUrlLoading] = useState(false);
  const [error, setError] = useState("");
  const [chunkStrategy, setChunkStrategy] = useState<ChunkStrategy>("recursive");
  const fileRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchDocs() {
    const { data } = await api.get<{ documents: Document[] }>("/documents/");
    setDocs(data.documents);
  }

  useEffect(() => {
    fetchDocs();
    // Poll every 3s while any doc is processing
    pollRef.current = setInterval(() => {
      fetchDocs();
    }, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    form.append("chunking_strategy", chunkStrategy);
    try {
      await api.post("/documents/upload", form);
      await fetchDocs();
    } catch (err: unknown) {
      setError(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "Upload failed"
      );
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleUrlSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!urlInput.trim()) return;
    setUrlLoading(true);
    setError("");
    try {
      await api.post("/documents/url", { url: urlInput.trim() });
      setUrlInput("");
      await fetchDocs();
    } catch (err: unknown) {
      setError(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "URL indexing failed"
      );
    } finally {
      setUrlLoading(false);
    }
  }

  async function handleDelete(docId: string) {
    if (!confirm("Delete this document from the knowledge base?")) return;
    await api.delete(`/documents/${docId}`);
    setDocs((d) => d.filter((x) => x.document_id !== docId));
  }

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>
        Documents
      </h1>
      <p className="mb-8 text-sm" style={{ color: "var(--text-muted)" }}>
        Upload files or index URLs — they become your searchable knowledge base
      </p>

      {/* Upload area */}
      <div
        className="rounded-xl border p-6 mb-8 flex flex-col gap-4"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="flex gap-3 flex-wrap items-center">
          <select
            value={chunkStrategy}
            onChange={(e) => setChunkStrategy(e.target.value as ChunkStrategy)}
            className="text-xs px-2 py-1.5 rounded-lg border outline-none"
            style={{ background: "var(--surface-2)", borderColor: "var(--border)", color: "var(--text)" }}
            title="Chunking strategy for this document"
          >
            {(Object.keys(STRATEGY_LABELS) as ChunkStrategy[]).map((s) => (
              <option key={s} value={s}>{STRATEGY_LABELS[s]}</option>
            ))}
          </select>
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity disabled:opacity-60"
            style={{ background: "var(--accent)" }}
          >
            {uploading ? "Uploading…" : "Upload file"}
          </button>
          <span className="text-xs self-center" style={{ color: "var(--text-muted)" }}>
            PDF · TXT · MD · DOCX · max 50 MB
          </span>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.txt,.md,.docx"
          className="hidden"
          onChange={handleFileUpload}
        />

        <form onSubmit={handleUrlSubmit} className="flex gap-2">
          <input
            type="url"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder="https://example.com/article"
            className="flex-1 px-3 py-2 rounded-lg border outline-none text-sm"
            style={{
              background: "var(--surface-2)",
              borderColor: "var(--border)",
              color: "var(--text)",
            }}
          />
          <button
            type="submit"
            disabled={urlLoading}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity disabled:opacity-60"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
          >
            {urlLoading ? "Indexing…" : "Index URL"}
          </button>
        </form>

        {error && (
          <p className="text-sm" style={{ color: "var(--danger)" }}>
            {error}
          </p>
        )}
      </div>

      {/* Document table */}
      {docs.length === 0 ? (
        <div
          className="rounded-xl border p-12 text-center"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <p className="text-4xl mb-3">📄</p>
          <p style={{ color: "var(--text-muted)" }}>No documents yet. Upload one to get started.</p>
        </div>
      ) : (
        <div
          className="rounded-xl border overflow-hidden"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Name", "Type", "Size", "Chunks", "Status", "", ""].map((h) => (
                  <th
                    key={h}
                    className="text-left px-4 py-3 font-medium"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr
                  key={doc.document_id}
                  className="transition-colors"
                  style={{ borderBottom: "1px solid var(--border)" }}
                >
                  <td className="px-4 py-3 max-w-xs truncate" style={{ color: "var(--text)" }}>
                    {doc.filename}
                  </td>
                  <td className="px-4 py-3 uppercase" style={{ color: "var(--text-muted)" }}>
                    {doc.source_type}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--text-muted)" }}>
                    {formatBytes(doc.file_size_bytes)}
                  </td>
                  <td className="px-4 py-3" style={{ color: "var(--text-muted)" }}>
                    {doc.chunks_count || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={doc.status} />
                  </td>
                  <td className="px-4 py-3">
                    {doc.status === "ready" && (
                      <Link
                        href={`/dashboard/${doc.document_id}`}
                        className="text-xs"
                        style={{ color: "var(--accent)" }}
                      >
                        Explore
                      </Link>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => handleDelete(doc.document_id)}
                      className="text-xs transition-colors"
                      style={{ color: "var(--text-muted)" }}
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
  );
}

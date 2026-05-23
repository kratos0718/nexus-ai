"use client";
import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface Chunk {
  chunk_id: string;
  chunk_index: number;
  text: string;
  source: string;
  page: number | null;
  char_count: number;
}

interface ChunksResponse {
  document_id: string;
  filename: string;
  total_chunks: number;
  offset: number;
  limit: number;
  chunks: Chunk[];
}

interface SearchChunk {
  chunk_id: string;
  text: string;
  score: number;
  source: string;
  page: number | null;
  chunk_index: number;
}

interface SearchResponse {
  query: string;
  retrieval_mode: string;
  chunks: SearchChunk[];
  total: number;
}

const PAGE_SIZE = 10;

// ── Sub-components ───────────────────────────────────────────────────────────

function ChunkCard({ chunk, rank, score }: { chunk: Chunk | SearchChunk; rank?: number; score?: number }) {
  const [expanded, setExpanded] = useState(false);
  const preview = chunk.text.slice(0, 200);
  const hasMore = chunk.text.length > 200;

  return (
    <div
      className="rounded-xl border p-4 flex flex-col gap-2"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          {rank !== undefined && (
            <span
              className="text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              {rank}
            </span>
          )}
          <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
            chunk #{chunk.chunk_index}
          </span>
          {chunk.page !== null && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              · p.{chunk.page}
            </span>
          )}
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            · {"char_count" in chunk ? chunk.char_count : chunk.text.length} chars
          </span>
        </div>
        {score !== undefined && (
          <span
            className="text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0"
            style={{ background: "#6366f11a", color: "var(--accent)" }}
          >
            {(score * 100).toFixed(1)}% match
          </span>
        )}
      </div>

      <p className="text-sm leading-relaxed" style={{ color: "var(--text)", whiteSpace: "pre-wrap" }}>
        {expanded ? chunk.text : preview}
        {hasMore && !expanded && "…"}
      </p>

      {hasMore && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-xs self-start"
          style={{ color: "var(--accent)" }}
        >
          {expanded ? "Show less" : "Show full chunk"}
        </button>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function DocumentDetailPage() {
  const params = useParams();
  const documentId = params.documentId as string;
  const router = useRouter();

  const [docName, setDocName] = useState("");
  const [totalChunks, setTotalChunks] = useState(0);
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);

  // Search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMode, setSearchMode] = useState<"standard" | "hyde" | "multiquery">("standard");
  const [searchResults, setSearchResults] = useState<SearchChunk[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  const fetchChunks = useCallback(async (pageNum: number) => {
    setLoading(true);
    try {
      const { data } = await api.get<ChunksResponse>(
        `/documents/${documentId}/chunks?offset=${pageNum * PAGE_SIZE}&limit=${PAGE_SIZE}`
      );
      setDocName(data.filename);
      setTotalChunks(data.total_chunks);
      setChunks(data.chunks);
    } catch {
      router.replace("/dashboard");
    } finally {
      setLoading(false);
    }
  }, [documentId, router]);

  useEffect(() => { fetchChunks(page); }, [fetchChunks, page]);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchError("");
    setSearchResults(null);
    try {
      const { data } = await api.post<SearchResponse>("/search/", {
        query: searchQuery.trim(),
        document_id: documentId,
        top_k: 5,
        retrieval_mode: searchMode,
      });
      setSearchResults(data.chunks);
    } catch {
      setSearchError("Search failed. Make sure the pipeline is initialized.");
    } finally {
      setSearching(false);
    }
  }

  const totalPages = Math.ceil(totalChunks / PAGE_SIZE);

  return (
    <div className="p-8 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-2 mb-1">
        <Link
          href="/dashboard"
          className="text-sm"
          style={{ color: "var(--text-muted)" }}
        >
          ← Documents
        </Link>
      </div>
      <h1 className="text-2xl font-bold mb-1 truncate" style={{ color: "var(--text)" }}>
        {docName || "Document"}
      </h1>
      <p className="text-sm mb-8" style={{ color: "var(--text-muted)" }}>
        {totalChunks} indexed chunks · click any chunk to expand
      </p>

      {/* Semantic search panel */}
      <div
        className="rounded-xl border p-5 mb-8"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <p className="text-sm font-medium mb-3" style={{ color: "var(--text)" }}>
          Semantic search within this document
        </p>
        <form onSubmit={handleSearch} className="flex gap-2 flex-wrap">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search for relevant chunks…"
            className="flex-1 min-w-0 px-3 py-2 rounded-lg border text-sm outline-none"
            style={{ background: "var(--surface-2)", borderColor: "var(--border)", color: "var(--text)" }}
          />
          <select
            value={searchMode}
            onChange={(e) => setSearchMode(e.target.value as typeof searchMode)}
            className="text-xs px-2 py-2 rounded-lg border outline-none"
            style={{ background: "var(--surface-2)", borderColor: "var(--border)", color: "var(--text)" }}
          >
            <option value="standard">Standard</option>
            <option value="hyde">HyDE</option>
            <option value="multiquery">Multi-query</option>
          </select>
          <button
            type="submit"
            disabled={searching || !searchQuery.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {searching ? "Searching…" : "Search"}
          </button>
        </form>

        {searchError && (
          <p className="text-sm mt-3" style={{ color: "var(--danger)" }}>{searchError}</p>
        )}

        {searchResults && (
          <div className="flex flex-col gap-3 mt-4">
            <p className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
              Top {searchResults.length} results for "{searchQuery}"
            </p>
            {searchResults.map((chunk, i) => (
              <ChunkCard key={chunk.chunk_id} chunk={chunk} rank={i + 1} score={chunk.score} />
            ))}
            <button
              onClick={() => { setSearchResults(null); setSearchQuery(""); }}
              className="text-xs self-start"
              style={{ color: "var(--text-muted)" }}
            >
              Clear results
            </button>
          </div>
        )}
      </div>

      {/* Chunk browser */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
          All chunks
          <span className="ml-2 font-normal" style={{ color: "var(--text-muted)" }}>
            (page {page + 1} of {totalPages || 1})
          </span>
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || loading}
            className="text-xs px-3 py-1.5 rounded-lg border disabled:opacity-40"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            ← Prev
          </button>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1 || loading}
            className="text-xs px-3 py-1.5 rounded-lg border disabled:opacity-40"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            Next →
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading chunks…</p>
      ) : chunks.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>No chunks found.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {chunks.map((chunk) => (
            <ChunkCard key={chunk.chunk_id} chunk={chunk} />
          ))}
        </div>
      )}
    </div>
  );
}

"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChatMessage, Document, SourceReference, Conversation } from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// ── Helpers ─────────────────────────────────────────────────────────────────

function SourceCard({ source }: { source: SourceReference }) {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded"
      style={{ background: "var(--surface-2)", color: "var(--text-muted)" }}
    >
      📄 {source.source}
      {source.page && <span>, p.{source.page}</span>}
      <span style={{ color: "var(--accent)" }}>{(source.score * 100).toFixed(0)}%</span>
    </span>
  );
}

interface AgentMeta {
  route?: string;
  subQuestions?: string[];
  contextChunks?: number;
  steps?: string[];
}

function AgentBadge({ meta }: { meta: AgentMeta }) {
  if (!meta.route) return null;
  return (
    <div className="flex flex-col gap-1 mt-2 mb-1">
      <div className="flex flex-wrap gap-1.5 items-center">
        <span
          className="text-xs px-2 py-0.5 rounded-full font-medium"
          style={{
            background: meta.route === "complex" ? "#6366f11a" : "#10b9811a",
            color: meta.route === "complex" ? "var(--accent)" : "var(--success)",
          }}
        >
          {meta.route === "complex" ? "⚡ Multi-step" : "⚡ Direct RAG"}
        </span>
        {meta.contextChunks !== undefined && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {meta.contextChunks} chunks
          </span>
        )}
      </div>
      {meta.subQuestions && meta.subQuestions.length > 0 && (
        <div className="flex flex-col gap-0.5 mt-1">
          <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
            Sub-questions:
          </span>
          {meta.subQuestions.map((q, i) => (
            <span key={i} className="text-xs pl-2" style={{ color: "var(--text-muted)" }}>
              • {q}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg, agentMeta }: { msg: ChatMessage; agentMeta?: AgentMeta }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      {!isUser && (
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center text-xs mr-2 flex-shrink-0 mt-0.5"
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          N
        </div>
      )}
      <div className={`max-w-[75%] flex flex-col ${isUser ? "items-end" : "items-start"}`}>
        {!isUser && agentMeta?.route && <AgentBadge meta={agentMeta} />}
        <div
          className="px-4 py-3 rounded-2xl text-sm leading-relaxed"
          style={{
            background: isUser ? "var(--accent)" : "var(--surface)",
            color: isUser ? "#fff" : "var(--text)",
            borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
            whiteSpace: "pre-wrap",
          }}
        >
          {msg.streaming ? (
            <span>
              {msg.content}
              <span
                className="inline-block w-0.5 h-4 ml-0.5 align-middle animate-pulse"
                style={{ background: "var(--accent)" }}
              />
            </span>
          ) : (
            msg.content || (
              <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Thinking…</span>
            )
          )}
        </div>
        {msg.sources && msg.sources.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1.5">
            {msg.sources.map((s) => (
              <SourceCard key={s.chunk_id} source={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Step indicator shown while agent runs ────────────────────────────────────

function StepIndicator({ steps }: { steps: string[] }) {
  if (steps.length === 0) return null;
  const labels: Record<string, string> = {
    router: "Classifying query…",
    planner: "Planning sub-questions…",
    researcher: "Researching…",
    rag: "Retrieving context…",
    synthesizer: "Generating answer…",
  };
  return (
    <div className="flex items-center gap-2 text-xs px-4 mb-2" style={{ color: "var(--text-muted)" }}>
      <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "var(--accent)" }} />
      {labels[steps[steps.length - 1]] || steps[steps.length - 1]}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [agentMetas, setAgentMetas] = useState<Record<string, AgentMeta>>({});
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [docs, setDocs] = useState<Document[]>([]);
  const [selectedDoc, setSelectedDoc] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [agentMode, setAgentMode] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.get<{ documents: Document[] }>("/documents/").then(({ data }) =>
      setDocs(data.documents.filter((d) => d.status === "ready"))
    );
    api.get<Conversation[]>("/conversations/").then(({ data }) =>
      setConversations(data)
    );
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, steps]);

  async function loadConversation(convId: string) {
    const { data } = await api.get<Conversation>(`/conversations/${convId}`);
    setActiveConvId(convId);
    setMessages(
      (data.messages || []).map((m) => ({
        id: m.message_id,
        role: m.role,
        content: m.content,
      }))
    );
  }

  async function send() {
    const question = input.trim();
    if (!question || sending) return;
    setInput("");
    setSending(true);
    setSteps([]);

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: question };
    setMessages((m) => [...m, userMsg]);

    const assistantId = crypto.randomUUID();
    setMessages((m) => [...m, { id: assistantId, role: "assistant", content: "", streaming: true }]);

    try {
      let convId = activeConvId;
      if (!convId) {
        const { data } = await api.post<Conversation>("/conversations/", {
          title: question.slice(0, 60),
          document_id: selectedDoc || null,
        });
        convId = data.conversation_id;
        setActiveConvId(convId);
        setConversations((c) => [data, ...c]);
      }

      const endpoint = agentMode ? "agent/stream" : "chat/stream";
      const token = localStorage.getItem("access_token");
      const res = await fetch(`${BASE_URL}/${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question,
          document_id: selectedDoc || null,
          conversation_id: convId,
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      let sources: SourceReference[] = [];
      const meta: AgentMeta = {};

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value, { stream: true });

        for (const line of text.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);

          if (payload === "[DONE]") break;
          if (payload.startsWith("[SOURCES]")) {
            sources = JSON.parse(payload.slice(9));
          } else if (payload.startsWith("[STEP]")) {
            const step = payload.slice(6);
            setSteps((s) => [...s, step]);
          } else if (payload.startsWith("[ROUTE]")) {
            meta.route = payload.slice(7);
          } else if (payload.startsWith("[PLAN]")) {
            meta.subQuestions = JSON.parse(payload.slice(6));
          } else if (payload.startsWith("[CONTEXT]")) {
            meta.contextChunks = parseInt(payload.slice(9));
          } else if (!payload.startsWith("[")) {
            accumulated += payload;
            setMessages((msgs) =>
              msgs.map((m) =>
                m.id === assistantId ? { ...m, content: accumulated, streaming: true } : m
              )
            );
          }
        }
      }

      setMessages((msgs) =>
        msgs.map((m) =>
          m.id === assistantId ? { ...m, content: accumulated, streaming: false, sources } : m
        )
      );
      if (agentMode) {
        setAgentMetas((prev) => ({ ...prev, [assistantId]: meta }));
      }
    } catch {
      setMessages((msgs) =>
        msgs.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Something went wrong. Please try again.", streaming: false }
            : m
        )
      );
    } finally {
      setSending(false);
      setSteps([]);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex h-full">
      {/* Conversation sidebar */}
      <div
        className="w-52 flex-shrink-0 flex flex-col border-r overflow-y-auto"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="p-3 border-b" style={{ borderColor: "var(--border)" }}>
          <button
            onClick={() => { setActiveConvId(null); setMessages([]); setAgentMetas({}); }}
            className="w-full py-1.5 rounded-lg text-xs font-medium border"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
          >
            + New chat
          </button>
        </div>
        <div className="flex-1 p-2 flex flex-col gap-0.5">
          {conversations.map((c) => (
            <button
              key={c.conversation_id}
              onClick={() => loadConversation(c.conversation_id)}
              className="text-left w-full px-2 py-2 rounded-lg text-xs truncate"
              style={{
                background: activeConvId === c.conversation_id ? "var(--surface-2)" : "transparent",
                color: activeConvId === c.conversation_id ? "var(--text)" : "var(--text-muted)",
              }}
            >
              {c.title}
            </button>
          ))}
        </div>
      </div>

      {/* Main chat */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div
          className="px-4 py-2.5 border-b flex items-center gap-3 flex-wrap"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <select
            value={selectedDoc}
            onChange={(e) => setSelectedDoc(e.target.value)}
            className="text-xs px-2 py-1.5 rounded-lg border outline-none"
            style={{ background: "var(--surface-2)", borderColor: "var(--border)", color: "var(--text)" }}
          >
            <option value="">All documents</option>
            {docs.map((d) => (
              <option key={d.document_id} value={d.document_id}>{d.filename}</option>
            ))}
          </select>

          {/* Agent mode toggle */}
          <button
            onClick={() => setAgentMode((a) => !a)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors"
            style={{
              borderColor: agentMode ? "var(--accent)" : "var(--border)",
              background: agentMode ? "#6366f11a" : "transparent",
              color: agentMode ? "var(--accent)" : "var(--text-muted)",
            }}
          >
            ⚡ {agentMode ? "Agent mode ON" : "Agent mode OFF"}
          </button>

          {agentMode && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Routes simple vs complex queries automatically
            </span>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center">
              <p className="text-4xl mb-3">💬</p>
              <p className="font-medium mb-1" style={{ color: "var(--text)" }}>
                Ask your knowledge base
              </p>
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                {agentMode
                  ? "Agent mode: complex questions are automatically decomposed"
                  : "Direct RAG mode"}
              </p>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              agentMeta={agentMetas[msg.id]}
            />
          ))}
          <StepIndicator steps={steps} />
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div
          className="px-4 py-4 border-t"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <div
            className="flex gap-3 items-end rounded-xl border px-4 py-3"
            style={{ background: "var(--surface-2)", borderColor: "var(--border)" }}
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="Ask a question… (Enter to send)"
              disabled={sending}
              className="flex-1 resize-none bg-transparent outline-none text-sm"
              style={{ color: "var(--text)", maxHeight: "120px" }}
            />
            <button
              onClick={send}
              disabled={sending || !input.trim()}
              className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-opacity disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="white">
                <path d="M2 21l21-9L2 3v7l15 2-15 2z" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

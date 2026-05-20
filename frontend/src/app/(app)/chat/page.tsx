"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChatMessage, Document, SourceReference, Conversation } from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

// ── Rendering helpers ───────────────────────────────────────────────────────

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

function MessageBubble({ msg }: { msg: ChatMessage }) {
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
        <div
          className="px-4 py-3 rounded-2xl text-sm leading-relaxed prose"
          style={{
            background: isUser ? "var(--accent)" : "var(--surface)",
            color: isUser ? "#fff" : "var(--text)",
            borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
          }}
        >
          {msg.streaming ? (
            <span>
              {msg.content}
              <span className="inline-block w-0.5 h-4 ml-0.5 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
            </span>
          ) : (
            msg.content
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

// ── Main page ───────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [docs, setDocs] = useState<Document[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<string>("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Fetch ready documents and conversations on mount
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
  }, [messages]);

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

  async function newConversation() {
    setActiveConvId(null);
    setMessages([]);
  }

  async function send() {
    const question = input.trim();
    if (!question || sending) return;

    setInput("");
    setSending(true);

    // Add user message immediately
    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: question };
    setMessages((m) => [...m, userMsg]);

    // Placeholder assistant message that will stream into
    const assistantId = crypto.randomUUID();
    setMessages((m) => [
      ...m,
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);

    try {
      // If no conversation yet, create one
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

      // Stream the response
      const token = localStorage.getItem("access_token");
      const res = await fetch(`${BASE_URL}/chat/stream`, {
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

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text = decoder.decode(value, { stream: true });
        // Each SSE event: "data: <content>\n\n"
        const lines = text.split("\n");
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);

          if (payload === "[DONE]") break;

          if (payload.startsWith("[SOURCES]")) {
            sources = JSON.parse(payload.slice(9));
          } else {
            accumulated += payload;
            setMessages((msgs) =>
              msgs.map((m) =>
                m.id === assistantId ? { ...m, content: accumulated, streaming: true } : m
              )
            );
          }
        }
      }

      // Finalise: mark not streaming, attach sources
      setMessages((msgs) =>
        msgs.map((m) =>
          m.id === assistantId
            ? { ...m, content: accumulated, streaming: false, sources }
            : m
        )
      );
    } catch (err) {
      setMessages((msgs) =>
        msgs.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Something went wrong. Please try again.", streaming: false }
            : m
        )
      );
    } finally {
      setSending(false);
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
      {/* Conversation list sidebar */}
      <div
        className="w-52 flex-shrink-0 flex flex-col border-r overflow-y-auto"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="p-3 border-b" style={{ borderColor: "var(--border)" }}>
          <button
            onClick={newConversation}
            className="w-full py-1.5 rounded-lg text-xs font-medium border transition-colors"
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
              className="text-left w-full px-2 py-2 rounded-lg text-xs truncate transition-colors"
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

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div
          className="px-4 py-2.5 border-b flex items-center gap-3"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <select
            value={selectedDoc}
            onChange={(e) => setSelectedDoc(e.target.value)}
            className="text-xs px-2 py-1.5 rounded-lg border outline-none max-w-xs"
            style={{
              background: "var(--surface-2)",
              borderColor: "var(--border)",
              color: "var(--text)",
            }}
          >
            <option value="">All documents</option>
            {docs.map((d) => (
              <option key={d.document_id} value={d.document_id}>
                {d.filename}
              </option>
            ))}
          </select>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {selectedDoc ? "Searching selected doc only" : "Searching all documents"}
          </span>
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
                Upload documents first, then ask questions and get cited answers
              </p>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
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
              placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
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

"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SystemPrompt } from "@/types";

const EMPTY_FORM = { name: "", description: "", content: "" };

export default function SystemPromptsPage() {
  const [prompts, setPrompts] = useState<SystemPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const { data } = await api.get<SystemPrompt[]>("/system-prompts/");
      setPrompts(data);
    } catch {
      // silently ignore — backend may be warming up
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function startNew() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError("");
    setShowForm(true);
  }

  function startEdit(p: SystemPrompt) {
    setEditingId(p.id);
    setForm({ name: p.name, description: p.description ?? "", content: p.content });
    setError("");
    setShowForm(true);
  }

  function cancelForm() {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    setError("");
  }

  async function save() {
    if (!form.name.trim() || !form.content.trim()) {
      setError("Name and content are required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        content: form.content.trim(),
      };
      if (editingId !== null) {
        await api.put(`/system-prompts/${editingId}`, payload);
      } else {
        await api.post("/system-prompts/", payload);
      }
      cancelForm();
      await load();
    } catch {
      setError("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this persona?")) return;
    try {
      await api.delete(`/system-prompts/${id}`);
      setPrompts((prev) => prev.filter((p) => p.id !== id));
    } catch {
      alert("Failed to delete.");
    }
  }

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold" style={{ color: "var(--text)" }}>
            Personas
          </h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
            Custom system prompts — give the assistant a role, tone, or domain focus
          </p>
        </div>
        <button
          onClick={startNew}
          className="px-4 py-2 rounded-lg text-sm font-medium"
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          + New persona
        </button>
      </div>

      {/* Inline form */}
      {showForm && (
        <div
          className="mb-6 p-5 rounded-xl border"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <h2 className="text-sm font-semibold mb-4" style={{ color: "var(--text)" }}>
            {editingId !== null ? "Edit persona" : "New persona"}
          </h2>
          <div className="flex flex-col gap-3">
            <div>
              <label className="text-xs font-medium mb-1 block" style={{ color: "var(--text-muted)" }}>
                Name *
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Legal expert"
                maxLength={100}
                className="w-full px-3 py-2 rounded-lg border text-sm outline-none"
                style={{ background: "var(--surface-2)", borderColor: "var(--border)", color: "var(--text)" }}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block" style={{ color: "var(--text-muted)" }}>
                Description
              </label>
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="Short hint shown in the selector"
                maxLength={500}
                className="w-full px-3 py-2 rounded-lg border text-sm outline-none"
                style={{ background: "var(--surface-2)", borderColor: "var(--border)", color: "var(--text)" }}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block" style={{ color: "var(--text-muted)" }}>
                System prompt *
              </label>
              <textarea
                value={form.content}
                onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="You are a concise legal assistant. Answer only using information from the provided documents…"
                rows={6}
                className="w-full px-3 py-2 rounded-lg border text-sm outline-none resize-y"
                style={{ background: "var(--surface-2)", borderColor: "var(--border)", color: "var(--text)" }}
              />
            </div>
            {error && (
              <p className="text-xs" style={{ color: "var(--danger)" }}>
                {error}
              </p>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={cancelForm}
                className="px-4 py-1.5 rounded-lg text-sm border"
                style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
              >
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-1.5 rounded-lg text-sm font-medium disabled:opacity-50"
                style={{ background: "var(--accent)", color: "#fff" }}
              >
                {saving ? "Saving…" : editingId !== null ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* List */}
      {loading ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>Loading…</p>
      ) : prompts.length === 0 ? (
        <div
          className="text-center py-16 rounded-xl border border-dashed"
          style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          <p className="text-3xl mb-2">🎭</p>
          <p className="text-sm">No personas yet. Create one to give the assistant a custom role.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {prompts.map((p) => (
            <div
              key={p.id}
              className="p-4 rounded-xl border"
              style={{ background: "var(--surface)", borderColor: "var(--border)" }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium text-sm truncate" style={{ color: "var(--text)" }}>
                    {p.name}
                  </p>
                  {p.description && (
                    <p className="text-xs mt-0.5 truncate" style={{ color: "var(--text-muted)" }}>
                      {p.description}
                    </p>
                  )}
                  <p
                    className="text-xs mt-2 line-clamp-2 font-mono leading-relaxed"
                    style={{ color: "var(--text-muted)", background: "var(--surface-2)", padding: "6px 8px", borderRadius: "6px" }}
                  >
                    {p.content}
                  </p>
                </div>
                <div className="flex gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => startEdit(p)}
                    className="text-xs px-2.5 py-1 rounded border"
                    style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => remove(p.id)}
                    className="text-xs px-2.5 py-1 rounded border"
                    style={{ borderColor: "var(--border)", color: "var(--danger)" }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { api } from "./api";
import type { AssistantChatMessage, AssistantContext } from "./api";

// AI Assistant panel (paid-tier differentiator): a machinist asks questions
// about the CURRENT plan ("Why 5 setups?", "How do I reduce cycle time?").
// Collapsible, docked next to the 3D viewer — toggled from the topbar.
// Conversation is client-side only (cleared whenever `context` changes to a
// different part, via the contextKey effect below) — nothing persists.

const SUGGESTED_PROMPTS = [
  "Why these setups?",
  "How can I cut cycle time?",
  "Explain the estimate simply",
];

export function AssistantPanel({
  open,
  onToggle,
  context,
  contextKey,
}: {
  open: boolean;
  onToggle: () => void;
  // Compact plan summary — null until a part has been analysed.
  context: AssistantContext | null;
  // Changes when the user switches parts — clears the conversation.
  contextKey: string | null;
}) {
  const [messages, setMessages] = useState<AssistantChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Part change (or part cleared) — start a fresh conversation.
  useEffect(() => {
    setMessages([]);
    setInput("");
    setError(null);
    setUnavailable(null);
  }, [contextKey]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, loading]);

  async function ask(question: string) {
    const q = question.trim();
    if (!q || loading || !context) return;
    setInput("");
    setError(null);
    const history = messages;
    setMessages((m) => [...m, { role: "user", content: q }]);
    setLoading(true);
    try {
      const r = await api.assistant(q, context, history);
      if (!r.available) {
        setUnavailable(r.message || "The assistant is not available right now.");
        // Drop the just-added question — there's no answer to pair it with.
        setMessages((m) => m.slice(0, -1));
        return;
      }
      setMessages((m) => [...m, { role: "assistant", content: r.answer || "" }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assistant request failed.");
      setMessages((m) => m.slice(0, -1));
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(input);
    }
  }

  if (!open) return null;

  return (
    <div className="assistant-panel">
      <div className="assistant-head">
        <span className="assistant-title">Assistant</span>
        <button type="button" className="assistant-close" title="Collapse" onClick={onToggle}>
          ✕
        </button>
      </div>

      {!context && (
        <div className="assistant-empty">Analyse a part to ask about its plan.</div>
      )}

      {context && unavailable && (
        <div className="assistant-nokey">{unavailable}</div>
      )}

      {context && !unavailable && (
        <>
          <div className="assistant-list" ref={listRef}>
            {messages.length === 0 && !loading && (
              <div className="assistant-hint">
                Ask about the current plan — setups, cycle time, or the estimate.
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`assistant-bubble ${m.role}`}>
                {m.content}
              </div>
            ))}
            {loading && (
              <div className="assistant-bubble assistant loading">Thinking…</div>
            )}
          </div>

          {error && <div className="assistant-error">{error}</div>}

          {messages.length === 0 && (
            <div className="assistant-chips">
              {SUGGESTED_PROMPTS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="assistant-chip"
                  disabled={loading}
                  onClick={() => void ask(p)}
                >
                  {p}
                </button>
              ))}
            </div>
          )}

          <div className="assistant-input-row">
            <textarea
              className="assistant-input"
              placeholder="Ask about this plan…"
              rows={1}
              value={input}
              disabled={loading}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <button
              type="button"
              className="btn primary assistant-send"
              disabled={loading || !input.trim()}
              onClick={() => void ask(input)}
            >
              Send
            </button>
          </div>
        </>
      )}
    </div>
  );
}

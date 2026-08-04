import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { api } from "./api";
import type { AssistantChatMessage, AssistantContext, AssistantTask } from "./api";

// AI Assistant panel (paid-tier differentiator). Two modes, one thread:
//  - copilot chat: a machinist asks questions about the CURRENT plan
//  - one-click generators: quote cover letter / DFM note / cost advisor,
//    grounded in the same plan context, output posted into the thread.
// Conversation is client-side only (cleared whenever `context` changes to a
// different part, via the contextKey effect below) — nothing persists.

const SUGGESTED_PROMPTS = [
  "Why these setups?",
  "How can I cut cycle time?",
  "Explain the estimate simply",
];

// Output language for the generators (letters/notes go to THEIR customer).
const LANGUAGES = ["English", "Hindi", "Kannada", "Tamil"];

const ACTIONS: { task: AssistantTask; label: string; title: string }[] = [
  {
    task: "cover_letter",
    label: "📄 Quote letter",
    title: "Draft a quotation letter for your customer — type any extras (delivery, terms) in the box first",
  },
  {
    task: "dfm_note",
    label: "🔧 DFM note",
    title: "Draft a design-feedback note your customer's engineer can act on",
  },
  {
    task: "cost_advisor",
    label: "💰 Reduce cost",
    title: "Ask how to hit a target price — type the target in the box first (e.g. 'under ₹2,000')",
  },
];

const ACTION_ECHO: Record<AssistantTask, string> = {
  cover_letter: "Draft the quotation letter",
  dfm_note: "Draft the design feedback note",
  cost_advisor: "How can I reduce the cost of this job?",
};

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
  const [language, setLanguage] = useState(LANGUAGES[0]);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
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

  // One-click generators. Whatever is typed in the box rides along as notes
  // (delivery terms for the letter, the target price for the advisor).
  async function generate(task: AssistantTask) {
    if (loading || !context) return;
    const notes = input.trim();
    setInput("");
    setError(null);
    const echo = notes ? `${ACTION_ECHO[task]} — ${notes}` : ACTION_ECHO[task];
    setMessages((m) => [...m, { role: "user", content: echo }]);
    setLoading(true);
    try {
      const r = await api.assistantGenerate(task, context, language, notes || undefined);
      if (!r.available) {
        setUnavailable(r.message || "The assistant is not available right now.");
        setMessages((m) => m.slice(0, -1));
        return;
      }
      setMessages((m) => [...m, { role: "assistant", content: r.text || "" }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed.");
      setMessages((m) => m.slice(0, -1));
    } finally {
      setLoading(false);
    }
  }

  async function copyMessage(i: number, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(i);
      setTimeout(() => setCopied((c) => (c === i ? null : c)), 1500);
    } catch {
      /* clipboard unavailable (http origin) — silently skip */
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
        <select
          className="assistant-lang"
          value={language}
          title="Output language for letters & notes"
          onChange={(e) => setLanguage(e.target.value)}
        >
          {LANGUAGES.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
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
                Ask about the current plan — or use the buttons below to draft a
                quote letter, a design-feedback note, or cost-reduction ideas.
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`assistant-bubble ${m.role}`}>
                {m.content}
                {m.role === "assistant" && m.content && (
                  <button
                    type="button"
                    className="assistant-copy"
                    title="Copy to clipboard"
                    onClick={() => void copyMessage(i, m.content)}
                  >
                    {copied === i ? "✓ Copied" : "⧉ Copy"}
                  </button>
                )}
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

          <div className="assistant-actions">
            {ACTIONS.map((a) => (
              <button
                key={a.task}
                type="button"
                className="assistant-chip action"
                title={a.title}
                disabled={loading}
                onClick={() => void generate(a.task)}
              >
                {a.label}
              </button>
            ))}
          </div>

          <div className="assistant-input-row">
            <textarea
              className="assistant-input"
              placeholder="Ask about this plan… (or type notes, then click a button above)"
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

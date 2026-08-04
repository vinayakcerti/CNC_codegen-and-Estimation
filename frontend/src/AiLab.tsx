import { useEffect, useState } from "react";

// AI Lab — the platform-admin surface for pluggable LLMs:
//   - store API keys per provider (server-side, never round-tripped)
//   - route each AI task (copilot / letters / advisor / extraction) to a
//     provider + model
//   - TEST BENCH: run a chat sanity check on any provider, or run the
//     bundled test drawing through extraction and score it vs ground truth.
// No auth yet — with accounts this becomes platform-admin-only.

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

interface ProviderPreset {
  label: string;
  type: string;
  base_url: string | null;
  models: string[];
  key_optional?: boolean;
  pdf_extraction?: boolean;
  data_note?: string;
}

interface ProviderState {
  base_url?: string | null;
  model?: string | null;
  key_set: boolean;
  key_last4: string;
}

interface AiConfig {
  providers: Record<string, ProviderState>;
  routing: Record<string, { provider: string; model: string }>;
  presets: Record<string, ProviderPreset>;
}

const TASK_LABELS: Record<string, string> = {
  copilot: "Plan copilot (chat)",
  generate_light: "Quote letters & DFM notes",
  advisor: "Cost advisor",
  extraction: "Drawing extraction (PDF)",
};

async function jfetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(d.detail ?? `Request failed: ${res.status}`);
  }
  return res.json();
}

export function AiLab() {
  const [cfg, setCfg] = useState<AiConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  // Draft key inputs per provider (cleared after save; never re-populated)
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [models, setModels] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, {
    ok: boolean; latency_ms: number; text?: string; error?: string;
    score?: string; checks?: { name: string; ok: boolean; got: string }[];
  }>>({});

  useEffect(() => {
    jfetch<AiConfig>("/api/admin/ai/config").then(setCfg).catch((e) => setError(e.message));
  }, []);

  if (error) return <div style={{ padding: 24 }} className="assistant-error">{error}</div>;
  if (!cfg) return <div style={{ padding: 24, color: "var(--text-2)" }}>Loading AI Lab…</div>;

  const effUrl = (pid: string) =>
    urls[pid] ?? cfg.providers[pid]?.base_url ?? cfg.presets[pid].base_url ?? "";
  const effModel = (pid: string) =>
    models[pid] ?? cfg.providers[pid]?.model ?? cfg.presets[pid].models[0] ?? "";

  async function saveProvider(pid: string) {
    setSaving(pid);
    setError(null);
    try {
      const body: Record<string, unknown> = { id: pid };
      if (urls[pid] !== undefined) body.base_url = urls[pid];
      if (models[pid] !== undefined) body.model = models[pid];
      if (keys[pid] !== undefined && keys[pid] !== "") body.api_key = keys[pid];
      const next = await jfetch<AiConfig>("/api/admin/ai/provider", {
        method: "POST", body: JSON.stringify(body),
      });
      setCfg(next);
      setKeys((k) => ({ ...k, [pid]: "" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(null);
    }
  }

  async function clearKey(pid: string) {
    setSaving(pid);
    try {
      const next = await jfetch<AiConfig>("/api/admin/ai/provider", {
        method: "POST", body: JSON.stringify({ id: pid, api_key: "" }),
      });
      setCfg(next);
    } finally {
      setSaving(null);
    }
  }

  async function setRoute(task: string, value: string) {
    const routing = { ...cfg!.routing } as Record<string, { provider: string; model: string } | undefined>;
    if (!value) {
      delete routing[task];
    } else {
      routing[task] = { provider: value, model: effModel(value) };
    }
    const next = await jfetch<AiConfig>("/api/admin/ai/routing", {
      method: "POST", body: JSON.stringify({ routing }),
    });
    setCfg(next);
  }

  async function runTest(pid: string, test: "chat" | "extraction") {
    setTesting(`${pid}:${test}`);
    setError(null);
    try {
      const r = await jfetch<typeof results[string]>("/api/admin/ai/test", {
        method: "POST",
        body: JSON.stringify({ provider: pid, model: effModel(pid), test }),
      });
      setResults((m) => ({ ...m, [pid]: r }));
    } catch (e) {
      setResults((m) => ({
        ...m,
        [pid]: { ok: false, latency_ms: 0, error: e instanceof Error ? e.message : "failed" },
      }));
    } finally {
      setTesting(null);
    }
  }

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "28px 36px" }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 6px" }}>AI Lab</h1>
      <div style={{ fontSize: 12.5, color: "var(--text-2)", marginBottom: 20, maxWidth: 640 }}>
        Plug in any LLM, store its key here (server-side — keys never return to the
        browser), route each AI task to a model, and test providers against a known
        drawing. Anthropic is the reference the product's prompts are tuned on.
      </div>

      {/* Task routing */}
      <div className="project-group" style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>Task routing</div>
        <div style={{ display: "grid", gridTemplateColumns: "220px 260px", gap: 8, alignItems: "center" }}>
          {Object.entries(TASK_LABELS).map(([task, label]) => (
            <div key={task} style={{ display: "contents" }}>
              <span style={{ fontSize: 12.5 }}>{label}</span>
              <select
                className="mini-select"
                value={cfg.routing[task]?.provider ?? ""}
                onChange={(e) => void setRoute(task, e.target.value)}
              >
                <option value="">Default (Anthropic)</option>
                {Object.entries(cfg.presets).map(([pid, p]) => (
                  <option key={pid} value={pid} disabled={task === "extraction" && !p.pdf_extraction}>
                    {p.label}{task === "extraction" && !p.pdf_extraction ? " — no PDF input" : ""}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 8 }}>
          A routed task uses that provider's saved model & key. Unrouted tasks use the
          Anthropic defaults.
        </div>
      </div>

      {/* Providers */}
      <div className="project-group">
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>Providers</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {Object.entries(cfg.presets).map(([pid, preset]) => {
            const st = cfg.providers[pid];
            const res = results[pid];
            return (
              <div key={pid} className="ai-provider">
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{preset.label}</span>
                  <span style={{ fontSize: 11, color: "var(--text-2)" }}>{preset.data_note}</span>
                  {st?.key_set && (
                    <span className="ai-key-chip">key saved ····{st.key_last4}</span>
                  )}
                </div>
                <div className="ai-provider-grid">
                  <input
                    className="text-input"
                    placeholder={preset.key_optional ? "API key (optional for local)" : "API key — stored server-side"}
                    type="password"
                    value={keys[pid] ?? ""}
                    onChange={(e) => setKeys((k) => ({ ...k, [pid]: e.target.value }))}
                  />
                  <input
                    className="text-input"
                    placeholder="Model"
                    list={`models-${pid}`}
                    value={effModel(pid)}
                    onChange={(e) => setModels((m) => ({ ...m, [pid]: e.target.value }))}
                  />
                  <datalist id={`models-${pid}`}>
                    {preset.models.map((m) => <option key={m} value={m} />)}
                  </datalist>
                  {(pid === "custom" || pid === "ollama") && (
                    <input
                      className="text-input"
                      style={{ gridColumn: "1 / -1" }}
                      placeholder="Base URL (OpenAI-compatible, e.g. http://localhost:11434/v1)"
                      value={effUrl(pid)}
                      onChange={(e) => setUrls((u) => ({ ...u, [pid]: e.target.value }))}
                    />
                  )}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  <button className="btn primary" disabled={saving === pid} onClick={() => void saveProvider(pid)}>
                    {saving === pid ? "Saving…" : "Save"}
                  </button>
                  {st?.key_set && (
                    <button className="btn" onClick={() => void clearKey(pid)}>Clear key</button>
                  )}
                  <button
                    className="btn"
                    disabled={testing !== null}
                    onClick={() => void runTest(pid, "chat")}
                  >
                    {testing === `${pid}:chat` ? "Testing…" : "🧪 Chat test"}
                  </button>
                  <button
                    className="btn"
                    disabled={testing !== null || !preset.pdf_extraction}
                    title={preset.pdf_extraction ? "Run the bundled test drawing and score vs ground truth" : "This provider cannot read PDFs yet"}
                    onClick={() => void runTest(pid, "extraction")}
                  >
                    {testing === `${pid}:extraction` ? "Extracting…" : "📐 Drawing test"}
                  </button>
                </div>
                {res && (
                  <div className={`ai-test-result ${res.ok ? "ok" : "fail"}`}>
                    {res.ok ? (
                      <>
                        <div style={{ fontSize: 11, color: "var(--text-2)" }}>
                          {res.latency_ms} ms{res.score ? ` · score ${res.score}` : ""}
                        </div>
                        {res.checks && (
                          <div style={{ margin: "4px 0" }}>
                            {res.checks.map((c, i) => (
                              <div key={i} style={{ fontSize: 11.5 }}>
                                {c.ok ? "✅" : "❌"} {c.name} <span style={{ color: "var(--text-2)" }}>({c.got})</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {res.text && <div style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{res.text}</div>}
                      </>
                    ) : (
                      <div style={{ fontSize: 12 }}>✗ {res.error}</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

"""Pluggable LLM providers for the AI Lab.

One adapter, two wire protocols:
  - "anthropic":          the Anthropic SDK (reference implementation — the
                          product's prompts are tuned and red-teamed on it)
  - "openai_compatible":  POST {base_url}/chat/completions — covers OpenAI,
                          Google Gemini (OpenAI-compat endpoint), Moonshot
                          (Kimi), Groq, local Ollama, and any custom server.

Config (provider keys + per-task routing) lives in ai_providers.json next to
this file — GITIGNORED, keys never leave the server, GET responses mask them.
When accounts land this file's contents move into the platform-admin settings
store; the adapter API stays the same.
"""
from __future__ import annotations

import json
import os
from typing import Any

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_providers.json")

# Suggested starting points — model lists move fast; every field is editable
# in the AI Lab, so stale suggestions cost nothing.
PRESETS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic (Claude)", "type": "anthropic", "base_url": None,
        "models": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-4-8"],
        "pdf_extraction": True,
        "data_note": "US processing · the reference provider the product is tuned on",
    },
    "openai": {
        "label": "OpenAI", "type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "pdf_extraction": False,
        "data_note": "US processing",
    },
    "gemini": {
        "label": "Google Gemini", "type": "openai_compatible",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-2.0-flash", "gemini-1.5-pro"],
        "pdf_extraction": False,
        "data_note": "US processing (OpenAI-compatible endpoint)",
    },
    "moonshot": {
        "label": "Moonshot (Kimi)", "type": "openai_compatible",
        "base_url": "https://api.moonshot.ai/v1",
        "models": ["kimi-k2-0711-preview", "moonshot-v1-32k"],
        "pdf_extraction": False,
        "data_note": "China processing — check customer data-residency requirements",
    },
    "groq": {
        "label": "Groq", "type": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile"],
        "pdf_extraction": False,
        "data_note": "US processing · open-weights models, hosted",
    },
    "ollama": {
        "label": "Ollama (local)", "type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.1", "qwen2.5", "mistral"],
        "key_optional": True,
        "pdf_extraction": False,
        "data_note": "Runs on YOUR machine — nothing leaves the server",
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)", "type": "openai_compatible",
        "base_url": "", "models": [],
        "pdf_extraction": False,
        "data_note": "Any server speaking the /chat/completions protocol",
    },
}

# Tasks that can be routed to a provider/model.
TASKS = ("copilot", "generate_light", "advisor", "extraction")


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}
    cfg.setdefault("providers", {})
    cfg.setdefault("routing", {})
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)


def masked_config() -> dict:
    """Config for the UI: keys never round-trip — only set/last4."""
    cfg = load_config()
    out = {"providers": {}, "routing": cfg.get("routing", {}), "presets": PRESETS}
    for pid, p in cfg["providers"].items():
        key = p.get("api_key") or ""
        out["providers"][pid] = {
            "base_url": p.get("base_url"),
            "model": p.get("model"),
            "key_set": bool(key),
            "key_last4": key[-4:] if len(key) >= 8 else "",
        }
    return out


def update_provider(pid: str, base_url: str | None, model: str | None,
                    api_key: str | None) -> None:
    """api_key=None means 'keep the stored key'; empty string clears it."""
    cfg = load_config()
    p = cfg["providers"].setdefault(pid, {})
    if base_url is not None:
        p["base_url"] = base_url
    if model is not None:
        p["model"] = model
    if api_key is not None:
        if api_key == "":
            p.pop("api_key", None)
        else:
            p["api_key"] = api_key
    save_config(cfg)


def update_routing(routing: dict) -> None:
    cfg = load_config()
    clean = {k: v for k, v in routing.items() if k in TASKS and v}
    cfg["routing"] = clean
    save_config(cfg)


def resolve_task(task: str) -> tuple[str, str] | None:
    """(provider_id, model) for a routed task, or None → caller's default."""
    cfg = load_config()
    route = cfg.get("routing", {}).get(task)
    if not route or not isinstance(route, dict):
        return None
    pid, model = route.get("provider"), route.get("model")
    if not pid or not model:
        return None
    return pid, model


def provider_settings(pid: str) -> dict:
    """Effective settings: stored config over preset defaults."""
    preset = PRESETS.get(pid, PRESETS["custom"])
    stored = load_config()["providers"].get(pid, {})
    return {
        "id": pid,
        "type": preset["type"],
        "base_url": stored.get("base_url") or preset.get("base_url") or "",
        "api_key": stored.get("api_key") or "",
        "key_optional": bool(preset.get("key_optional")),
        "pdf_extraction": bool(preset.get("pdf_extraction")),
    }


def complete(pid: str, model: str, system: str, messages: list[dict],
             max_tokens: int) -> dict:
    """Run one completion on any configured provider.
    Returns {ok, text?, error?, latency_ms}."""
    import time

    p = provider_settings(pid)
    t0 = time.monotonic()
    try:
        if p["type"] == "anthropic":
            import anthropic

            client = anthropic.Anthropic(
                api_key=p["api_key"] or os.environ.get("ANTHROPIC_API_KEY"))
            resp = client.messages.create(
                model=model, max_tokens=max_tokens,
                system=system, messages=messages,
            )
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            ).strip()
        else:
            if not p["base_url"]:
                return {"ok": False, "error": "No base URL configured.", "latency_ms": 0}
            if not p["api_key"] and not p["key_optional"]:
                return {"ok": False, "error": "No API key configured.", "latency_ms": 0}
            import httpx

            headers = {"Content-Type": "application/json"}
            if p["api_key"]:
                headers["Authorization"] = f"Bearer {p['api_key']}"
            r = httpx.post(
                p["base_url"].rstrip("/") + "/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, *messages],
                },
                timeout=120.0,
            )
            if r.status_code != 200:
                detail = r.text[:300]
                return {"ok": False, "error": f"HTTP {r.status_code}: {detail}",
                        "latency_ms": int((time.monotonic() - t0) * 1000)}
            body = r.json()
            text = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except Exception as e:  # network, auth, SDK — the Lab reports, never crashes
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "latency_ms": int((time.monotonic() - t0) * 1000)}
    return {"ok": True, "text": text.strip(),
            "latency_ms": int((time.monotonic() - t0) * 1000)}

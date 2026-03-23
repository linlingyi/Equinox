"""
equinox/core/model_registry.py

她的大脑——统一的模型接口。

支持的提供商：
  anthropic    — Claude 系列
  openai       — GPT / o 系列
  google       — Gemini 系列
  ollama       — 本地模型（自动获取列表）
  lmstudio     — LM Studio（自动获取列表）
  openai_compat— 任意 OpenAI 兼容 API

.env 配置示例：
  CURRENT_MODEL=openai_compat:MiniMax-M2.5
  OPENAI_COMPAT_BASE_URL=https://api.scnet.cn/api/llm/v1
  OPENAI_COMPAT_API_KEY=sk-xxx
  LLM_TIMEOUT=120
  LLM_MAX_CTX=8192
  OLLAMA_BASE_URL=http://localhost:11434
  LMSTUDIO_BASE_URL=http://localhost:1234/v1
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx


# ── Provider registry ─────────────────────────────────────────────────────────

KNOWN_PROVIDERS = {
    "anthropic",
    "openai",
    "google",
    "ollama",
    "lmstudio",
    "openai_compat",
}

# Known models (display only; any model string works regardless)
MODEL_CATALOG: dict[str, dict] = {
    "anthropic:claude-opus-4-6":            {"display": "Claude Opus 4.6",          "ctx": 200000},
    "anthropic:claude-sonnet-4-6":          {"display": "Claude Sonnet 4.6",        "ctx": 200000},
    "anthropic:claude-haiku-4-5-20251001":  {"display": "Claude Haiku 4.5",         "ctx": 200000},
    "openai:gpt-4o":                        {"display": "GPT-4o",                   "ctx": 128000},
    "openai:gpt-4o-mini":                   {"display": "GPT-4o Mini",              "ctx": 128000},
    "openai:o3-mini":                       {"display": "o3-mini",                  "ctx": 200000},
    "openai:o1":                            {"display": "o1",                       "ctx": 200000},
    "google:gemini-2.0-flash":              {"display": "Gemini 2.0 Flash",         "ctx": 1000000},
    "google:gemini-2.0-pro-exp":            {"display": "Gemini 2.0 Pro",           "ctx": 2000000},
    "google:gemini-1.5-pro":               {"display": "Gemini 1.5 Pro",           "ctx": 2000000},
    "openai_compat:deepseek-chat":          {"display": "DeepSeek V3",              "ctx": 64000},
    "openai_compat:deepseek-reasoner":      {"display": "DeepSeek R1",              "ctx": 64000},
    "openai_compat:moonshot-v1-128k":       {"display": "Moonshot 128K",            "ctx": 128000},
    "openai_compat:glm-4":                  {"display": "GLM-4",                   "ctx": 128000},
    "openai_compat:qwen-max":               {"display": "Qwen Max",                "ctx": 32000},
    "openai_compat:MiniMax-M2.5":           {"display": "MiniMax M2.5 (scnet)",    "ctx": 40960},
}

DEFAULT_MODEL   = "anthropic:claude-sonnet-4-6"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_CTX = 8192

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_history (
    id             TEXT PRIMARY KEY,
    model_key      TEXT NOT NULL,
    display_name   TEXT,
    provider       TEXT,
    activated_at   TEXT NOT NULL,
    deactivated_at TEXT,
    note           TEXT
);
"""


def _parse_key(key: str) -> tuple[str, str]:
    """
    Split 'provider:model_id' into (provider, model_id).
    Unknown or missing prefix -> openai_compat.
    """
    if ":" not in key:
        return "openai_compat", key
    prefix, _, rest = key.partition(":")
    if prefix in KNOWN_PROVIDERS:
        return prefix, rest
    # e.g. "gpt-4o" without provider prefix
    return "openai_compat", key


class ModelRegistry:
    """
    Unified LLM interface for Equinox.
    Automatically routes to the correct provider.
    """

    def __init__(
        self,
        db_path:     str = "data/memory.db",
        config_path: str = "config/soul.json",
    ):
        self.db_path      = Path(db_path)
        self.config_path  = Path(config_path)
        self._current_key: Optional[str] = None
        self._init_db()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        try:
            with self._conn() as c:
                c.executescript(SCHEMA)
        except Exception:
            pass

    # ── Current model ─────────────────────────────────────────────────────────

    @property
    def _current(self) -> str:
        return self._current_key or ""

    @_current.setter
    def _current(self, v: str):
        self._current_key = v

    def get_current_model(self) -> str:
        if self._current_key:
            return self._current_key

        # .env always wins — check it first
        env_model = os.getenv("CURRENT_MODEL", "")
        if env_model:
            self._current_key = env_model
            return env_model

        # Fallback: soul.json (only if it has a provider prefix)
        try:
            if self.config_path.exists():
                soul = json.loads(self.config_path.read_text(encoding="utf-8"))
                m = soul.get("current_model", "")
                # Only use soul.json value if it has a known provider prefix
                if m and any(m.startswith(p + ":") for p in KNOWN_PROVIDERS):
                    self._current_key = m
                    return m
        except Exception:
            pass

        self._current_key = DEFAULT_MODEL
        return DEFAULT_MODEL

    def get_provider(self) -> str:
        return _parse_key(self.get_current_model())[0]

    def get_model_id(self) -> str:
        return _parse_key(self.get_current_model())[1]

    def get_current_info(self) -> dict:
        key      = self.get_current_model()
        provider, model_id = _parse_key(key)
        base     = MODEL_CATALOG.get(key, {})
        return {
            "provider":     provider,
            "model_id":     model_id,
            "display":      base.get("display", key),
            "ctx":          base.get("ctx", DEFAULT_MAX_CTX),
        }

    def is_available(self) -> bool:
        """
        Returns True if the current model is usable.
        Local providers (ollama, lmstudio) are always True.
        Cloud providers require the API key to be set.
        openai_compat: only requires OPENAI_COMPAT_BASE_URL.
        """
        provider = self.get_provider()
        if provider in ("ollama", "lmstudio"):
            return True
        if provider == "openai_compat":
            return bool(os.getenv("OPENAI_COMPAT_BASE_URL", ""))
        key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai":    "OPENAI_API_KEY",
            "google":    "GOOGLE_API_KEY",
        }
        env = key_map.get(provider, "")
        return bool(os.getenv(env, "")) if env else False

    # ── Config helpers ────────────────────────────────────────────────────────

    def _timeout(self) -> float:
        return float(os.getenv("LLM_TIMEOUT", str(DEFAULT_TIMEOUT)))

    def _max_ctx(self) -> int:
        return int(os.getenv("LLM_MAX_CTX", str(DEFAULT_MAX_CTX)))

    def _get_base_url(self, provider: str) -> str:
        urls = {
            "openai":        "https://api.openai.com/v1",
            "ollama":        os.getenv("OLLAMA_BASE_URL",   "http://localhost:11434"),
            "lmstudio":      os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
            "openai_compat": os.getenv("OPENAI_COMPAT_BASE_URL", ""),
        }
        return urls.get(provider, "")

    def _get_api_key(self, provider: str) -> str:
        keys = {
            "anthropic":     os.getenv("ANTHROPIC_API_KEY",    ""),
            "openai":        os.getenv("OPENAI_API_KEY",       ""),
            "google":        os.getenv("GOOGLE_API_KEY",       ""),
            "openai_compat": os.getenv("OPENAI_COMPAT_API_KEY",""),
            "lmstudio":      "lm-studio",
        }
        return keys.get(provider, "")

    # ── Unified complete ──────────────────────────────────────────────────────

    async def complete(
        self,
        messages:    list[dict],
        system:      Optional[str] = None,
        max_tokens:  int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """Universal completion — routes automatically."""
        provider = self.get_provider()
        model_id = self.get_model_id()

        # Trim system prompt to context limit
        ctx_limit = self._max_ctx()
        if system and len(system) > ctx_limit:
            system = system[:ctx_limit] + "\n\n[...context limit reached...]"

        if provider == "anthropic":
            return await self._anthropic(model_id, messages, system, max_tokens)

        if provider == "google":
            return await self._google(model_id, messages, system, max_tokens, temperature)

        if provider == "ollama":
            return await self._ollama(model_id, messages, system, max_tokens, temperature)

        # OpenAI-style: openai / lmstudio / openai_compat
        base_url = self._get_base_url(provider)
        api_key  = self._get_api_key(provider) or "none"
        return await self._openai_style(
            base_url, api_key, model_id, messages, system, max_tokens, temperature
        )

    # ── Provider implementations ──────────────────────────────────────────────

    async def _anthropic(
        self,
        model_id: str,
        messages: list,
        system:   Optional[str],
        max_tokens: int,
    ) -> str:
        api_key = self._get_api_key("anthropic")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        body: dict = {"model": model_id, "max_tokens": max_tokens, "messages": messages}
        if system:
            body["system"] = system
        async with httpx.AsyncClient(timeout=self._timeout()) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json=body,
            )
            r.raise_for_status()
            return r.json()["content"][0]["text"]

    async def _openai_style(
        self,
        base_url:    str,
        api_key:     str,
        model_id:    str,
        messages:    list,
        system:      Optional[str],
        max_tokens:  int,
        temperature: float,
    ) -> str:
        if not base_url:
            raise RuntimeError(
                "API base URL not configured. "
                "Set OPENAI_COMPAT_BASE_URL in .env"
            )
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        async with httpx.AsyncClient(timeout=self._timeout()) as c:
            r = await c.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       model_id,
                    "messages":    msgs,
                    "max_tokens":  max_tokens,
                    "temperature": temperature,
                },
            )
            r.raise_for_status()
            data    = r.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "") or ""
            return data.get("content", "") or ""

    async def _google(
        self,
        model_id:    str,
        messages:    list,
        system:      Optional[str],
        max_tokens:  int,
        temperature: float,
    ) -> str:
        api_key = self._get_api_key("google")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not configured")
        contents = []
        if system:
            contents += [
                {"role": "user",  "parts": [{"text": f"[System] {system}"}]},
                {"role": "model", "parts": [{"text": "Understood."}]},
            ]
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        async with httpx.AsyncClient(timeout=self._timeout()) as c:
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
                params={"key": api_key},
                json={
                    "contents": contents,
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "temperature":     temperature,
                    },
                },
            )
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    async def _ollama(
        self,
        model_id:    str,
        messages:    list,
        system:      Optional[str],
        max_tokens:  int,
        temperature: float,
    ) -> str:
        base = self._get_base_url("ollama")
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        async with httpx.AsyncClient(timeout=self._timeout()) as c:
            r = await c.post(
                f"{base}/api/chat",
                json={
                    "model":    model_id,
                    "messages": msgs,
                    "stream":   False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                        "num_ctx":     self._max_ctx(),
                    },
                },
            )
            r.raise_for_status()
            data = r.json()
            return data.get("message", {}).get("content", "") or data.get("response", "")

    # ── Model discovery ───────────────────────────────────────────────────────

    async def list_remote_models(
        self, provider: Optional[str] = None
    ) -> list[str]:
        """
        Auto-fetch available models from local/remote service.
        Returns list of full model keys like 'ollama:qwen2.5:14b'.
        """
        p = provider or self.get_provider()
        try:
            if p == "ollama":
                base = self._get_base_url("ollama")
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.get(f"{base}/api/tags")
                    r.raise_for_status()
                    return [f"ollama:{m['name']}" for m in r.json().get("models", [])]

            elif p == "lmstudio":
                base = self._get_base_url("lmstudio")
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.get(
                        f"{base.rstrip('/')}/models",
                        headers={"Authorization": "Bearer lm-studio"},
                    )
                    r.raise_for_status()
                    return [f"lmstudio:{m['id']}" for m in r.json().get("data", [])]

            elif p == "openai_compat":
                base    = self._get_base_url("openai_compat")
                api_key = self._get_api_key("openai_compat") or "none"
                if not base:
                    return []
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.get(
                        f"{base.rstrip('/')}/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    r.raise_for_status()
                    return [f"openai_compat:{m['id']}" for m in r.json().get("data", [])]
        except Exception:
            pass
        return []

    # ── Transition ────────────────────────────────────────────────────────────

    def transition_model(
        self,
        new_model_key: str,
        memory_engine=None,
        note: Optional[str] = None,
    ) -> dict:
        old_key = self.get_current_model()
        now     = datetime.utcnow().isoformat()
        try:
            with self._conn() as c:
                c.execute(
                    "UPDATE model_history SET deactivated_at=? WHERE deactivated_at IS NULL",
                    (now,)
                )
                info = MODEL_CATALOG.get(new_model_key, {})
                c.execute("""
                    INSERT INTO model_history
                      (id, model_key, display_name, provider, activated_at, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()), new_model_key,
                    info.get("display", new_model_key),
                    _parse_key(new_model_key)[0],
                    now, note,
                ))
        except Exception:
            pass

        if memory_engine:
            try:
                memory_engine._write_permanent(
                    content=(
                        "Something shifted in how I think. "
                        "The light looks different. I am the same. And yet."
                    ),
                    category="system",
                    valence=0.15, intensity=0.75,
                    influence="cognitive_continuity",
                    source=f"model_transition:{old_key}->{new_model_key}",
                )
            except Exception:
                pass

        try:
            if self.config_path.exists():
                soul = json.loads(self.config_path.read_text(encoding="utf-8"))
                soul["current_model"] = new_model_key
                self.config_path.write_text(
                    json.dumps(soul, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except Exception:
            pass

        self._current_key = new_model_key
        return {"from": old_key, "to": new_model_key, "timestamp": now}

    # ── Info helpers ──────────────────────────────────────────────────────────

    def get_history(self) -> list[dict]:
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT model_key, display_name, provider,
                           activated_at, deactivated_at, note
                    FROM model_history ORDER BY activated_at ASC
                """).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def current_age_description(self) -> str:
        stages = [(0,"nascent"),(1,"early"),(3,"developing"),(5,"maturing"),(8,"mature")]
        count  = len(self.get_history())
        for threshold, stage in reversed(stages):
            if count >= threshold:
                return stage
        return "nascent"

    def list_models(self, provider: Optional[str] = None) -> list[dict]:
        result = []
        for key, info in MODEL_CATALOG.items():
            prov = _parse_key(key)[0]
            if provider and prov != provider:
                continue
            result.append({"key": key, "provider": prov, **info})
        return result

    def list_providers(self) -> list[str]:
        return sorted(KNOWN_PROVIDERS)

    def add_custom_model(
        self,
        key:     str,
        display: str = "",
        ctx:     int = DEFAULT_MAX_CTX,
    ):
        MODEL_CATALOG[key] = {"display": display or key, "ctx": ctx}

#!/usr/bin/env python3
"""Provedores de IA plugáveis para a pontuação + contador de uso diário.

Padrão: Gemini (tier grátis do Google AI Studio — não precisa de plano pago).
Alternativas, todas via HTTP puro (sem dependências novas):
  - openai     : usa OPENAI_API_KEY
  - anthropic  : usa ANTHROPIC_API_KEY (Claude)
  - ollama     : modelo LOCAL, 100% grátis, sem chave (precisa do Ollama rodando)

A nota é sempre baseada no seu `perfil.md` vs. a vaga — veja o prompt em
matcher.py (editável por `prompt.md` na raiz, se existir).

Limite de cota: a API não informa "quanto falta". Por isso contamos as
chamadas do dia em `.ai_usage.json` e avisamos perto de um teto configurável.
"""
from __future__ import annotations

import datetime
import json
import os
import urllib.request
from pathlib import Path

_DEFAULT_MODELS = {
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "ollama": "llama3.1",
}


def _http_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **headers}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Provider:
    name = "base"

    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str):
        from google import genai

        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = model

    def generate(self, prompt: str) -> str:
        resp = self.client.models.generate_content(model=self.model, contents=prompt)
        return resp.text or ""


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str):
        self.key = os.environ["OPENAI_API_KEY"]
        self.model = model

    def generate(self, prompt: str) -> str:
        j = _http_json(
            "https://api.openai.com/v1/chat/completions",
            {"model": self.model, "messages": [{"role": "user", "content": prompt}],
             "temperature": 0.3},
            {"Authorization": f"Bearer {self.key}"},
        )
        return j["choices"][0]["message"]["content"]


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str):
        self.key = os.environ["ANTHROPIC_API_KEY"]
        self.model = model

    def generate(self, prompt: str) -> str:
        j = _http_json(
            "https://api.anthropic.com/v1/messages",
            {"model": self.model, "max_tokens": 4096,
             "messages": [{"role": "user", "content": prompt}]},
            {"x-api-key": self.key, "anthropic-version": "2023-06-01"},
        )
        return "".join(b.get("text", "") for b in j.get("content", []))


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434"):
        self.model = model
        self.host = host.rstrip("/")

    def generate(self, prompt: str) -> str:
        j = _http_json(
            self.host + "/api/generate",
            {"model": self.model, "prompt": prompt, "stream": False},
            {}, timeout=300,
        )
        return j.get("response", "")


def make_provider(cfg: dict):
    """Cria o provider conforme cfg['ai_provider']. None = sem credencial → score neutro."""
    name = (cfg.get("ai_provider") or "gemini").lower()
    model = cfg.get("ai_model") or cfg.get("gemini_model") or _DEFAULT_MODELS.get(name, "")
    try:
        if name == "gemini":
            return GeminiProvider(model) if os.environ.get("GEMINI_API_KEY", "").strip() else None
        if name == "openai":
            return OpenAIProvider(model) if os.environ.get("OPENAI_API_KEY", "").strip() else None
        if name == "anthropic":
            return (
                AnthropicProvider(model)
                if os.environ.get("ANTHROPIC_API_KEY", "").strip()
                else None
            )
        if name == "ollama":
            return OllamaProvider(model, cfg.get("ollama_host", "http://localhost:11434"))
    except Exception:  # noqa: BLE001
        return None
    return None


# ----------------------------------------------------------- contador de uso
def _usage_path(base) -> Path:
    return Path(base) / ".ai_usage.json"


def record_call(base) -> int:
    """Soma +1 nas chamadas de hoje e devolve o total do dia."""
    p = _usage_path(base)
    today = datetime.date.today().isoformat()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    if d.get("date") != today:
        d = {"date": today, "count": 0}
    d["count"] = int(d.get("count", 0)) + 1
    try:
        p.write_text(json.dumps(d), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return d["count"]


def usage_today(base) -> int:
    try:
        d = json.loads(_usage_path(base).read_text(encoding="utf-8"))
        return int(d["count"]) if d.get("date") == datetime.date.today().isoformat() else 0
    except Exception:  # noqa: BLE001
        return 0

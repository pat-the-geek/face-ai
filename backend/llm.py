"""Client LLM local Ollama (v030) — synthèses de veille.

Ollama expose une API OpenAI-compatible sur `:11434/v1/chat/completions`,
sans authentification. On réutilise la **même instance que WUDD.ai**
(`qwen2.5:7b` par défaut). Résolution d'hôte alignée sur WUDD :
`host.docker.internal` en conteneur, `localhost` sur l'hôte, surchargeable
par `OLLAMA_HOST_DOCKER` / `OLLAMA_HOST_LOCAL` / `OLLAMA_HOST`.

`chat()` ne lève jamais : en cas d'indisponibilité d'Ollama il renvoie None,
et l'appelant retombe sur une synthèse déterministe.
"""
from __future__ import annotations

import logging
import os

import requests

import config

log = logging.getLogger("llm")


def _running_in_docker() -> bool:
    return os.path.exists("/.dockerenv") or os.environ.get("RUNNING_IN_DOCKER") == "1"


def _ollama_host() -> str:
    if _running_in_docker():
        return (
            os.environ.get("OLLAMA_HOST_DOCKER", "").strip()
            or os.environ.get("OLLAMA_HOST", "").strip()
            or "host.docker.internal"
        )
    return (
        os.environ.get("OLLAMA_HOST_LOCAL", "").strip()
        or os.environ.get("OLLAMA_HOST", "").strip()
        or "localhost"
    )


def _url() -> str:
    return f"http://{_ollama_host()}:11434/v1/chat/completions"


def chat(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 300,
    temperature: float = 0.3,
    timeout: int | None = None,
) -> str | None:
    """Appel non-stream OpenAI-compatible. Renvoie le texte, ou None si échec."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        resp = requests.post(
            _url(), json=payload, timeout=timeout or config.OLLAMA_TIMEOUT
        )
        resp.raise_for_status()
        choices = resp.json().get("choices") or []
        if not choices:
            return None
        content = ((choices[0].get("message") or {}).get("content") or "").strip()
        return content or None
    except Exception:
        log.warning("Ollama injoignable (%s) — repli synthèse déterministe", _url())
        return None

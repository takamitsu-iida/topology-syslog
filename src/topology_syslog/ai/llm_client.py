"""LLM クライアント抽象化 — OpenAI / Ollama を環境変数で切り替え。"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    def ask(self, prompt: str) -> str: ...


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import OpenAI  # lazy import — optional dep
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def ask(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""


class OllamaClient(LLMClient):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3") -> None:
        import httpx  # already in deps
        self._client = httpx.Client(base_url=base_url, timeout=120.0)
        self._model = model

    def ask(self, prompt: str) -> str:
        resp = self._client.post(
            "/api/generate",
            json={"model": self._model, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        return resp.json().get("response", "")


def create_llm_client() -> LLMClient:
    """環境変数 LLM_PROVIDER から適切なクライアントを生成する。"""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "ollama":
        return OllamaClient(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "llama3"),
        )
    return OpenAIClient(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )

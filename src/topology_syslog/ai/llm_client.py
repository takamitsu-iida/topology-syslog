"""LLM クライアント抽象化 — OpenAI / Ollama を環境変数で切り替え。"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    def ask(self, prompt: str) -> str: ...

    @abstractmethod
    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> dict:
        """ツール呼び出しをサポートするチャット API。

        Returns:
            {
                "content": str | None,
                "finish_reason": "stop" | "tool_calls",
                "tool_calls": [{"id": str, "function": {"name": str, "arguments": str}}] | None,
            }
        """
        ...


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

    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> dict:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.1,
        )
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        return {
            "content": msg.content,
            "finish_reason": choice.finish_reason,
            "tool_calls": tool_calls,
        }


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

    def chat_with_tools(self, messages: list[dict], tools: list[dict]) -> dict:
        """Ollama chat API 経由のツール呼び出し (llama3.1 / qwen2.5 等の対応モデル必須)。"""
        resp = self._client.post(
            "/api/chat",
            json={"model": self._model, "messages": messages, "tools": tools, "stream": False},
        )
        resp.raise_for_status()
        message = resp.json().get("message", {})
        raw_calls = message.get("tool_calls")
        tool_calls = None
        if raw_calls:
            tool_calls = [
                {
                    "id": f"call_{i}",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": json.dumps(tc["function"]["arguments"], ensure_ascii=False),
                    },
                }
                for i, tc in enumerate(raw_calls)
            ]
        return {
            "content": message.get("content"),
            "finish_reason": "tool_calls" if tool_calls else "stop",
            "tool_calls": tool_calls,
        }


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

"""Ollama and OpenAI-compatible local HTTP LLM providers with JSON Schema enforcement."""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from memelang.ir.schema import SynthesisResult
from memelang.llm.base import (
    LLMProviderError,
    build_compiler_messages,
    has_executable_content,
)


class OllamaProvider:
    def __init__(
        self,
        model: str = "qwen2.5-coder:3b",
        host: str = "http://127.0.0.1:11434",
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self._client = client
        self._timeout = timeout
        self.name = f"ollama:{model}"

    def synthesize(self, source_text: str) -> SynthesisResult:
        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        payload = {
            "model": self.model,
            "messages": build_compiler_messages(source_text),
            "stream": False,
            "format": SynthesisResult.model_json_schema(),
            "options": {"temperature": 0.0, "seed": 42},
        }
        try:
            if self._client is not None:
                resp = self._client.post(f"{self.host}/api/chat", json=payload)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(f"{self.host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"]
            return SynthesisResult.model_validate_json(content)
        except (httpx.HTTPError, KeyError, ValueError, ValidationError) as exc:
            raise LLMProviderError(
                f"Ollama provider (`{self.model}` at {self.host}) failed: {exc}"
            ) from exc


class OpenAILocalProvider:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "local",
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = client
        self._timeout = timeout
        self.name = f"openai-local:{model}"

    def synthesize(self, source_text: str) -> SynthesisResult:
        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        payload = {
            "model": self.model,
            "messages": build_compiler_messages(source_text),
            "temperature": 0.0,
            "seed": 42,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "SynthesisResult",
                    "strict": True,
                    "schema": SynthesisResult.model_json_schema(),
                },
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            if self._client is not None:
                resp = self._client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=headers
                    )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return SynthesisResult.model_validate_json(content)
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
            raise LLMProviderError(
                f"OpenAI-compatible local provider (`{self.model}` at {self.base_url}) failed: {exc}"
            ) from exc

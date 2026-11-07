"""Ollama and OpenAI-compatible local HTTP LLM providers with JSON Schema enforcement."""

from __future__ import annotations

from pathlib import Path
import httpx
from pydantic import ValidationError

from memelang.ir.schema import FuncDefStmt, SynthesisItem, SynthesisResult
from memelang.llm.base import (
    LLMProviderError,
    build_compiler_messages,
    has_executable_content,
    split_compilation_units,
)


class OllamaProvider:
    def __init__(
        self,
        model: str = "qwen2.5-coder:3b",
        host: str = "http://127.0.0.1:11434",
        client: httpx.Client | None = None,
        timeout: float = 120.0,
        retriever: object = None,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self._client = client
        self._timeout = timeout
        self.retriever = retriever
        self.name = f"ollama:{model}"

    def synthesize(
        self, source_text: str, source_path: Path | None = None
    ) -> SynthesisResult:
        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        units = split_compilation_units(source_text)
        if not units:
            return SynthesisResult(items=[])

        all_items: list[SynthesisItem] = []
        defined_funcs: list[FuncDefStmt] = []
        schema = SynthesisResult.model_json_schema()

        try:
            for unit in units:
                payload = {
                    "model": self.model,
                    "messages": build_compiler_messages(
                        unit.text,
                        line_numbers=unit.line_numbers,
                        available_functions=defined_funcs if defined_funcs else None,
                        source_path=source_path,
                        retriever=self.retriever,
                    ),
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0.0, "seed": 42},
                }
                if self._client is not None:
                    resp = self._client.post(f"{self.host}/api/chat", json=payload)
                else:
                    with httpx.Client(timeout=self._timeout) as client:
                        resp = client.post(f"{self.host}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["message"]["content"]
                part = SynthesisResult.model_validate_json(content)
                for it in part.items:
                    if isinstance(it, FuncDefStmt):
                        if it.source_line is None and unit.line_numbers:
                            it.source_line = unit.line_numbers[0]
                        defined_funcs.append(it)
                    all_items.append(it)
            return SynthesisResult(items=all_items)
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
        retriever: object = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = client
        self._timeout = timeout
        self.retriever = retriever
        self.name = f"openai-local:{model}"

    def synthesize(
        self, source_text: str, source_path: Path | None = None
    ) -> SynthesisResult:
        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        units = split_compilation_units(source_text)
        if not units:
            return SynthesisResult(items=[])

        all_items: list[SynthesisItem] = []
        defined_funcs: list[FuncDefStmt] = []
        schema = SynthesisResult.model_json_schema()
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            for unit in units:
                payload = {
                    "model": self.model,
                    "messages": build_compiler_messages(
                        unit.text,
                        line_numbers=unit.line_numbers,
                        available_functions=defined_funcs if defined_funcs else None,
                        source_path=source_path,
                        retriever=self.retriever,
                    ),
                    "temperature": 0.0,
                    "seed": 42,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "SynthesisResult",
                            "schema": schema,
                        },
                    },
                }
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
                part = SynthesisResult.model_validate_json(content)
                for it in part.items:
                    if isinstance(it, FuncDefStmt):
                        if it.source_line is None and unit.line_numbers:
                            it.source_line = unit.line_numbers[0]
                        defined_funcs.append(it)
                    all_items.append(it)
            return SynthesisResult(items=all_items)
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
            raise LLMProviderError(
                f"OpenAI-compatible local provider (`{self.model}` at {self.base_url}) failed: {exc}"
            ) from exc

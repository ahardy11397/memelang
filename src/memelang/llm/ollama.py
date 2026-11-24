"""Ollama and OpenAI-compatible local HTTP LLM providers with JSON Schema enforcement.

Both providers share one local-HTTP plumbing base class
(:class:`_LocalHTTPProvider`); they differ only in endpoint URL, request
payload shape, response extraction, and auth headers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from memelang.ir.schema import FuncDefStmt, SynthesisItem, SynthesisResult
from memelang.llm.base import (
    LLMProviderError,
    build_compiler_messages,
    has_executable_content,
    split_compilation_units,
)


class _LocalHTTPProvider:
    """Shared plumbing for local HTTP chat providers (Ollama, OpenAI-compatible).

    Subclasses parameterize the provider on ``endpoint``, the request
    payload shape (:meth:`_build_payload`), response content extraction
    (:meth:`_extract_content`), and auth headers (:meth:`_headers`).
    """

    #: Full URL the chat request is POSTed to.
    endpoint: str
    #: Human-readable label used in error messages.
    error_label: str

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
        retriever: object = None,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self.retriever = retriever

    def _headers(self) -> dict[str, str]:
        return {}

    def _build_payload(
        self,
        unit: Any,
        defined_funcs: list[FuncDefStmt],
        source_path: Path | None,
        schema: dict,
    ) -> dict:
        raise NotImplementedError

    def _extract_content(self, data: dict) -> str:
        raise NotImplementedError

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
        headers = self._headers()

        try:
            for unit in units:
                payload = self._build_payload(unit, defined_funcs, source_path, schema)
                if self._client is not None:
                    resp = self._client.post(self.endpoint, json=payload, headers=headers)
                else:
                    with httpx.Client(timeout=self._timeout) as client:
                        resp = client.post(self.endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                content = self._extract_content(resp.json())
                part = SynthesisResult.model_validate_json(content)
                for it in part.items:
                    if isinstance(it, FuncDefStmt):
                        if it.source_line is None and unit.line_numbers:
                            it.source_line = unit.line_numbers[0]
                        defined_funcs.append(it)
                    all_items.append(it)
            return SynthesisResult(items=all_items)
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError) as exc:
            raise LLMProviderError(f"{self.error_label} failed: {exc}") from exc


class OllamaProvider(_LocalHTTPProvider):
    def __init__(
        self,
        model: str = "qwen2.5-coder:3b",
        host: str = "http://127.0.0.1:11434",
        client: httpx.Client | None = None,
        timeout: float = 120.0,
        retriever: object = None,
    ) -> None:
        super().__init__(client=client, timeout=timeout, retriever=retriever)
        self.model = model
        self.host = host.rstrip("/")
        self.endpoint = f"{self.host}/api/chat"
        self.error_label = f"Ollama provider (`{self.model}` at {self.host})"
        self.name = f"ollama:{model}"

    def _build_payload(
        self,
        unit: Any,
        defined_funcs: list[FuncDefStmt],
        source_path: Path | None,
        schema: dict,
    ) -> dict:
        return {
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

    def _extract_content(self, data: dict) -> str:
        return data["message"]["content"]


class OpenAILocalProvider(_LocalHTTPProvider):
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "local",
        client: httpx.Client | None = None,
        timeout: float = 120.0,
        retriever: object = None,
    ) -> None:
        super().__init__(client=client, timeout=timeout, retriever=retriever)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.endpoint = f"{self.base_url}/chat/completions"
        self.error_label = (
            f"OpenAI-compatible local provider (`{self.model}` at {self.base_url})"
        )
        self.name = f"openai-local:{model}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _build_payload(
        self,
        unit: Any,
        defined_funcs: list[FuncDefStmt],
        source_path: Path | None,
        schema: dict,
    ) -> dict:
        return {
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

    def _extract_content(self, data: dict) -> str:
        return data["choices"][0]["message"]["content"]

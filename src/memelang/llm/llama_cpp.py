"""Optional in-process GGUF local LLM provider via `llama-cpp-python`."""

from __future__ import annotations

from pathlib import Path
from pydantic import ValidationError

from memelang.ir.schema import SynthesisResult
from memelang.llm.base import (
    LLMProviderError,
    build_compiler_messages,
    has_executable_content,
)


class LlamaCppProvider:
    def __init__(
        self,
        model_path: str,
        n_gpu_layers: int = -1,
        n_ctx: int = 4096,
    ) -> None:
        self.model_path = Path(model_path)
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.name = f"llama-cpp:{self.model_path.name}"
        self._llm = None

    def _get_llm(self):
        if not self.model_path.exists():
            raise LLMProviderError(f"GGUF model file not found: {self.model_path}")
        if self._llm is None:
            try:
                from llama_cpp import Llama  # type: ignore[import-not-found]
            except ImportError as exc:
                raise LLMProviderError(
                    "llama-cpp-python is not installed. Install with: `uv sync --extra local-gguf`"
                ) from exc
            self._llm = Llama(
                model_path=str(self.model_path),
                n_gpu_layers=self.n_gpu_layers,
                n_ctx=self.n_ctx,
                verbose=False,
            )
        return self._llm

    def synthesize(self, source_text: str) -> SynthesisResult:
        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        llm = self._get_llm()
        try:
            resp = llm.create_chat_completion(
                messages=build_compiler_messages(source_text),
                temperature=0.0,
                seed=42,
                response_format={
                    "type": "json_object",
                    "schema": SynthesisResult.model_json_schema(),
                },
            )
            content = resp["choices"][0]["message"]["content"]
            return SynthesisResult.model_validate_json(content)
        except (KeyError, IndexError, ValueError, ValidationError, RuntimeError) as exc:
            raise LLMProviderError(f"llama.cpp synthesis failed: {exc}") from exc

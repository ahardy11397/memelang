"""Optional Google Gemini cloud API provider via `google-genai`."""

from __future__ import annotations

import os
from pydantic import ValidationError

from memelang.ir.schema import SynthesisResult
from memelang.llm.base import (
    LLMProviderError,
    SYSTEM_PROMPT,
    build_compiler_messages,
    has_executable_content,
)


class GeminiProvider:
    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        api_key: str | None = None,
        retriever: object = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.retriever = retriever
        self.name = f"gemini:{model}"

    def synthesize(self, source_text: str) -> SynthesisResult:
        resolved_key = (
            self.api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not resolved_key:
            raise LLMProviderError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable is required for `--provider gemini`."
            )

        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        try:
            from google import genai  # type: ignore[import-not-found]
            from google.genai import types  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMProviderError(
                "google-genai SDK is not installed. Install with: `uv sync --extra gemini`"
            ) from exc

        msgs = build_compiler_messages(source_text, retriever=self.retriever)
        try:
            client = genai.Client(api_key=resolved_key)
            resp = client.models.generate_content(
                model=self.model,
                contents=msgs[-1]["content"],
                config=types.GenerateContentConfig(
                    system_instruction=msgs[0]["content"],
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_json_schema=SynthesisResult.model_json_schema(),
                ),
            )
            if not resp.text:
                raise LLMProviderError("Gemini API returned an empty response.")
            return SynthesisResult.model_validate_json(resp.text)
        except LLMProviderError:
            raise
        except ValidationError as exc:
            raise LLMProviderError(f"Gemini output failed IR schema validation: {exc}") from exc
        except Exception as exc:
            raise LLMProviderError(f"Gemini API call failed: {exc}") from exc

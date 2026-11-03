"""Pluggable LLM frontend registry for Memelang."""

from __future__ import annotations

import os
import httpx

from memelang.llm.base import LLMProvider, LLMProviderError, build_compiler_messages
from memelang.llm.gemini import GeminiProvider
from memelang.llm.heuristic import HeuristicProvider
from memelang.llm.llama_cpp import LlamaCppProvider
from memelang.llm.ollama import OllamaProvider, OpenAILocalProvider


def _probe_local_ollama(host: str) -> str | None:
    try:
        with httpx.Client(timeout=0.3) as client:
            resp = client.get(f"{host.rstrip('/')}/api/tags")
            if resp.status_code != 200:
                return None
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            for preferred in ("qwen2.5-coder:3b", "llama3.2:3b"):
                if preferred in models:
                    return preferred
            return models[0] if models else None
    except Exception:
        return None


def get_provider(spec: str = "auto") -> LLMProvider:
    effective = spec
    if effective == "auto":
        env_spec = os.environ.get("MEME_PROVIDER", "").strip()
        if env_spec and env_spec != "auto":
            effective = env_spec
        else:
            host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
            detected_model = _probe_local_ollama(host)
            if detected_model:
                return OllamaProvider(model=detected_model, host=host)
            return HeuristicProvider()

    if effective == "heuristic":
        return HeuristicProvider()

    if effective == "ollama" or effective.startswith("ollama:"):
        _, _, model = effective.partition(":")
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        return OllamaProvider(model=model or "qwen2.5-coder:3b", host=host)

    if effective.startswith("openai-local:"):
        _, _, model = effective.partition(":")
        base_url = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1")
        if not model:
            raise LLMProviderError("Specify model name as `openai-local:<model>`.")
        return OpenAILocalProvider(model=model, base_url=base_url)

    if effective.startswith("llama-cpp:"):
        _, _, path = effective.partition(":")
        if not path:
            raise LLMProviderError("Specify GGUF model path as `llama-cpp:/path/to/model.gguf`.")
        return LlamaCppProvider(model_path=path)

    if effective == "gemini" or effective.startswith("gemini:"):
        _, _, model = effective.partition(":")
        return GeminiProvider(model=model or "gemini-2.5-flash")

    raise LLMProviderError(
        f"Unknown LLM provider `{spec}`. Supported: auto, heuristic, ollama[:model], "
        "openai-local:<model>, llama-cpp:<path.gguf>, gemini[:model]."
    )


__all__ = [
    "GeminiProvider",
    "HeuristicProvider",
    "LLMProvider",
    "LLMProviderError",
    "LlamaCppProvider",
    "OllamaProvider",
    "OpenAILocalProvider",
    "build_compiler_messages",
    "get_provider",
]

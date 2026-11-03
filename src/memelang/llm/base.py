"""Base protocol, shared system prompt, and helpers for Memelang LLM providers."""

from __future__ import annotations

from typing import Protocol

from memelang.ir.schema import SynthesisResult


class LLMProviderError(Exception):
    """Raised when an LLM frontend provider cannot be reached, configured, or parsed."""


class LLMProvider(Protocol):
    name: str

    def synthesize(self, source_text: str) -> SynthesisResult: ...


def has_executable_content(source_text: str) -> bool:
    for raw_line in source_text.splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


SYSTEM_PROMPT = """You are the frontend semantic synthesizer for the `meme` (Memelang) natural-language compiler.
Translate the user's English `.meme` source file into a strict JSON object matching the `SynthesisResult` schema (`{"items": [...]}`).

Rules:
1. Every variable declaration (`op: "var_decl"`) MUST have an explicit static `var_type` from:
   `"Int"`, `"Float"`, `"Bool"`, `"String"`, `"List<Int>"`, `"List<Float>"`, `"List<Bool>"`, `"List<String>"`.
2. If an English statement is clear (e.g. `define list numbers as 10 random integers between 1 and 100`, `sort numbers ascending`, `print numbers`), emit concrete IR statements directly.
3. If an English statement is semantically ambiguous or contradictory (for example, `for each number in array: sort from 1 to 10` which combines element-wise iteration with a whole-list sort and ambiguous bounds), DO NOT guess silently. Emit an `"op": "ambiguity"` (`AmbiguityDiagnostic`) item with:
   - `statement_id` (1-based statement index)
   - `source_line`, `source_text`, `reason`
   - 2 to 3 concrete `candidates`, each containing `option` (1, 2, 3), `description`, `canonical_meme`, `replacement_ir` (valid concrete IR statements), and `replaces_whole_program` (`true` if the option rewrites an earlier random declaration's bounds).
4. Ignore comment lines starting with `#`. Output ONLY valid JSON conforming to `SynthesisResult`."""


def build_compiler_messages(source_text: str) -> list[dict[str, str]]:
    numbered = "\n".join(
        f"{idx}: {line}" for idx, line in enumerate(source_text.splitlines(), start=1)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Compile the following `.meme` source into SynthesisResult JSON:\n\n{numbered}",
        },
    ]

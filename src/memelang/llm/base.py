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
1. Every variable declaration (`"op": "var_decl"`) MUST include `"op"` and an explicit static `var_type` from:
   `"Int"`, `"Float"`, `"Bool"`, `"String"`, `"List<Int>"`, `"List<Float>"`, `"List<Bool>"`, `"List<String>"`.
   Every expression MUST include `"expr_type"`.
2. Clear English example:
   Input:
     1: define list numbers as 10 random integers between 1 and 100
     2: sort numbers ascending
   Output:
     {"items": [
       {"op": "var_decl", "name": "numbers", "var_type": "List<Int>", "source_line": 1,
        "value": {"expr_type": "random_list", "count": {"expr_type": "literal", "value": 10, "data_type": "Int"},
                  "min_val": {"expr_type": "literal", "value": 1, "data_type": "Int"},
                  "max_val": {"expr_type": "literal", "value": 100, "data_type": "Int"}, "implicit_bounds": false}},
       {"op": "sort_collection", "target": "numbers", "direction": "ascending", "source_line": 2}
     ]}
3. Ambiguous English example: if phrasing has conflicting interpretations (e.g., `for each number in array: sort from 1 to 10`), DO NOT guess silently. Emit `"op": "ambiguity"`:
     {"op": "ambiguity", "statement_id": 2, "source_line": 2,
      "source_text": "for each number in array sort from 1 to 10",
      "reason": "Looping over `array` while sorting `array` with bounds is ambiguous.",
      "candidates": [
        {"option": 1, "description": "Sort `array` ascending", "canonical_meme": "sort array ascending",
         "replacement_ir": [{"op": "sort_collection", "target": "array", "direction": "ascending"}],
         "replaces_whole_program": false}
      ]}
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

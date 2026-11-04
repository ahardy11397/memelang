"""Base protocol, shared system prompt, and helpers for Memelang LLM providers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Protocol

from memelang.ir.schema import FuncDefStmt, SynthesisResult
from memelang.llm.retriever import ExamplePair, ExampleRetriever


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


BASE_PROMPT_PREFIX = """You are the frontend semantic synthesizer for the `meme` (Memelang) natural-language compiler.
Translate the user's English `.meme` source file into a strict JSON object matching `SynthesisResult`: `{"items": [...]}`.

### Allowed Static Types (`MemeType`)
`"Int"`, `"Float"`, `"Bool"`, `"String"`, `"List<Int>"`, `"List<Float>"`, `"List<Bool>"`, `"List<String>"`, `"List<List<Int>>"`, `"List<List<Float>>"`, `"List<List<Bool>>"`, `"List<List<String>>"`, `"Void"`.

### Allowed Expressions (`expr_type` REQUIRED on every expression)
- `{"expr_type": "literal", "value": 10, "data_type": "Int"}` (also `"Float"`, `"Bool"`, `"String"`)
- `{"expr_type": "list_literal", "elements": [...], "element_type": "Int"}`
- `{"expr_type": "var_ref", "name": "x"}`
- `{"expr_type": "random_int", "min_val": <expr>, "max_val": <expr>}`
- `{"expr_type": "random_list", "count": <expr>, "min_val": <expr>, "max_val": <expr>, "implicit_bounds": false}`
- `{"expr_type": "binary_op", "op": "+", "left": <expr>, "right": <expr>}` (`op` in `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `and`, `or`)
- `{"expr_type": "unary_op", "op": "-", "operand": <expr>}` (`op` in `-`, `not`)
- `{"expr_type": "list_length", "target": <expr>}`
- `{"expr_type": "list_index", "target": <expr>, "index": <expr>}`
- `{"expr_type": "string_length", "target": <expr>}`
- `{"expr_type": "string_slice", "target": <expr>, "start": <Int expr>, "end": <Int expr>}`
- `{"expr_type": "call", "func_name": "fn", "args": [...]}`
- `{"expr_type": "read_input", "prompt": "Enter x: ", "target_type": "Float"}` (`target_type` in `"Int"`, `"Float"`, `"Bool"`, `"String"`)
- `{"expr_type": "str_ends_with", "target": <String expr>, "suffix": <String expr>}` (case-insensitive suffix check, e.g. `if filepath is json` -> `suffix` `".json"`, returns `"Bool"`)
- `{"expr_type": "read_json_list", "filepath": <String expr>}` (loads a JSON array of numbers from `filepath` as `"List<Float>"`)

### Allowed Statements (`op` REQUIRED on every statement)
- `{"op": "var_decl", "name": "x", "var_type": "Float", "value": <expr>, "source_line": 1}`
- `{"op": "assign", "name": "x", "value": <expr>}`
- `{"op": "sort_collection", "target": "nums", "direction": "ascending"}` (`"ascending"` or `"descending"`)
- `{"op": "clamp_collection", "target": "nums", "min_val": <expr>, "max_val": <expr>}`
- `{"op": "filter_collection", "target": "nums", "item_var": "n", "predicate": <expr>}`
- `{"op": "list_append", "target": "nums", "value": <expr>}`
- `{"op": "list_insert", "target": "nums", "index": <Int expr>, "value": <expr>}` (inserts at 0-based `index`, shifting elements right)
- `{"op": "list_set_index", "target": "nums", "index": <Int expr>, "value": <expr>}` (sets element at 0-based `index` in-place)
- `{"op": "fail_stmt", "message": <String expr>}` (prints error message and exits cleanly; counts as returning on that branch!)
- `{"op": "print_stmt", "expressions": [<expr>, ...]}`
- `{"op": "if_stmt", "condition": <expr>, "then_body": [...], "else_body": [...]}`
- `{"op": "for_each", "item_var": "n", "collection": "nums", "body": [...]}`
- `{"op": "for_range", "loop_var": "i", "start": <expr>, "end": <expr>, "body": [...]}`
- `{"op": "while_loop", "condition": <expr>, "body": [...]}`
- `{"op": "func_def", "name": "f", "params": [{"name": "a", "param_type": "Int"}], "return_type": "Int", "body": [...]}`
- `{"op": "return_stmt", "value": <expr>}`

### Rules
1. Ignore ONLY `#` comment lines, pure narrative header lines (`this runs in the shell`), and the `class <name>` header line itself. You MUST emit EVERY helper `define function <name>` inside a `class` as a top-level `{"op": "func_def", ...}` BEFORE the main statements, and inline `define function main`'s body as top-level statements at the end!
2. Auto-heal obvious human typos and variable-name mismatches (`from use` -> `read_input`, `sorterd` -> `sorted`, `findLagest` -> `findLargest`; if `define list as fromFile from filepath` is followed by `return fromFile`, return the declared variable `list` so every `var_ref` matches a declared variable in scope).
3. Default numeric type: whenever `Int` vs `Float` is unspecified — including untyped function parameters (`define function findLargest with list`), empty lists (`define sorted as empty`), user inputs, or JSON number lists — ALWAYS use `"List<Float>"` and `"Float"` (use `"Int"` / `"List<Int>"` ONLY when `"integer"` / `"integers"` is explicitly written or for 0-based loop/list indices!). Append a trailing space to prompt strings (`"Filepath? "`).
4. Static return types & error branches: a `func_def` has a single static `return_type`. If one branch returns `"List<Float>"` and an `else` branch returns an error string like `else return "Wrong File Type"`, emit `{"op": "fail_stmt", "message": {"expr_type": "literal", "value": "Wrong File Type", "data_type": "String"}}` on the `else` branch!
5. 1-based English positions, `"sort A into B"`, & single-statement `list_insert`:
   - `item 1` -> index `0`; `item 2` -> index `1`; `item last` or `largest from <asc_sorted>` -> `{"expr_type": "binary_op", "op": "-", "left": {"expr_type": "list_length", "target": ...}, "right": {"expr_type": "literal", "value": 1, "data_type": "Int"}}`.
   - `sort_collection` mutates ONE list variable IN-PLACE (`"target"`). Whenever English says `"sort A into B ascending"` (where `B` was declared `empty`), you MUST emit `"assign"` BEFORE `"sort_collection"`:
     `{"op": "assign", "name": "B", "value": {"expr_type": "var_ref", "name": "A"}}, {"op": "sort_collection", "target": "B", "direction": "ascending"}`
     NEVER sort `A` and leave `B` empty!
   - `list_insert` ALREADY shifts all existing elements up by 1! So `"move each item in sorted up 1 and copy item x to sorted item 1"` is ONE `list_insert` statement at index `0` (`{"op": "list_insert", "target": "sorted", "index": {"expr_type": "literal", "value": 0, "data_type": "Int"}, "value": {"expr_type": "var_ref", "name": "x"}}`) — NEVER write an inner loop to shift elements!
   - `"else check next item x"` means do nothing in `else` (`"else_body": []`)!
   - Ignore English invariant lines like `"stop when ... every other item ..."` right before `return`; end the function's `"body"` directly with `"return_stmt"`.
6. `"if_stmt"` is a top-level STATEMENT, NEVER an expression inside `"print_stmt"`! When printing a dynamic operator read into a `"String"` variable (e.g., `print result of num1 operator num2`), emit a top-level `"if_stmt"` statement chain (`operator == "+"`, `"-"`, `"*"`, `"/"` with a nested `num2 != 0.0` check) and put `{"op": "print_stmt", ...}` inside each `then_body` / `else_body`:
   `{"op": "if_stmt", "condition": {"expr_type": "binary_op", "op": "==", "left": {"expr_type": "var_ref", "name": "operator"}, "right": {"expr_type": "literal", "value": "+", "data_type": "String"}}, "then_body": [{"op": "print_stmt", "expressions": [{"expr_type": "binary_op", "op": "+", "left": {"expr_type": "var_ref", "name": "num1"}, "right": {"expr_type": "var_ref", "name": "num2"}}]}], "else_body": [...]}`"""

BASE_ANCHOR_EXAMPLES = """7. Example 1 (Structured):
   Input:
     1: define list numbers as 10 random integers between 1 and 100
     2: sort numbers ascending
   Output:
     {"items": [
       {"op": "var_decl", "name": "numbers", "var_type": "List<Int>",
        "value": {"expr_type": "random_list", "count": {"expr_type": "literal", "value": 10, "data_type": "Int"},
                  "min_val": {"expr_type": "literal", "value": 1, "data_type": "Int"},
                  "max_val": {"expr_type": "literal", "value": 100, "data_type": "Int"}, "implicit_bounds": false},
        "source_line": 1},
       {"op": "sort_collection", "target": "numbers", "direction": "ascending", "source_line": 2}
     ]}
8. Example 2 (Class with Helper Functions & JSON File Loading):
   Input:
     1: class demo
     2:   define function load with path
     3:     if path is json
     4:       define nums as fromFile from path
     5:       return nums
     6:     else return "Wrong File Type"
     7:   define function main
     8:     print load "a.json"
   Output:
     {"items": [
       {"op": "func_def", "name": "load", "params": [{"name": "path", "param_type": "String"}], "return_type": "List<Float>",
        "body": [{"op": "if_stmt",
                  "condition": {"expr_type": "str_ends_with", "target": {"expr_type": "var_ref", "name": "path"}, "suffix": {"expr_type": "literal", "value": ".json", "data_type": "String"}},
                  "then_body": [{"op": "var_decl", "name": "nums", "var_type": "List<Float>", "value": {"expr_type": "read_json_list", "filepath": {"expr_type": "var_ref", "name": "path"}}},
                                {"op": "return_stmt", "value": {"expr_type": "var_ref", "name": "nums"}}],
                  "else_body": [{"op": "fail_stmt", "message": {"expr_type": "literal", "value": "Wrong File Type", "data_type": "String"}}]}]},
       {"op": "print_stmt", "expressions": [{"expr_type": "call", "func_name": "load", "args": [{"expr_type": "literal", "value": "a.json", "data_type": "String"}]}]}
     ]}
9. Example 3 (1-Based List Comparison & Front Insertion):
   Input:
     1: define function stepSort with arr
     2:   define raw as arr
     3:   define out as empty
     4:   check raw item 1 against raw item 2
     5:     copy smaller item to out item 1
     6:     foreach other item x in raw starting at item 2
     7:       check item x against out item 1
     8:         if item x is smaller
     9:           move each item in out up 1 and copy item x to out item 1
     10:        else
     11:          check next item x
     12:    return out item last
   Output:
     {"items": [
       {"op": "func_def", "name": "stepSort", "params": [{"name": "arr", "param_type": "List<Float>"}], "return_type": "Float",
        "body": [
          {"op": "var_decl", "name": "raw", "var_type": "List<Float>", "value": {"expr_type": "var_ref", "name": "arr"}},
          {"op": "var_decl", "name": "out", "var_type": "List<Float>", "value": {"expr_type": "list_literal", "elements": [], "element_type": "Float"}},
          {"op": "if_stmt",
           "condition": {"expr_type": "binary_op", "op": "<=", "left": {"expr_type": "list_index", "target": {"expr_type": "var_ref", "name": "raw"}, "index": {"expr_type": "literal", "value": 0, "data_type": "Int"}}, "right": {"expr_type": "list_index", "target": {"expr_type": "var_ref", "name": "raw"}, "index": {"expr_type": "literal", "value": 1, "data_type": "Int"}}},
           "then_body": [{"op": "list_append", "target": "out", "value": {"expr_type": "list_index", "target": {"expr_type": "var_ref", "name": "raw"}, "index": {"expr_type": "literal", "value": 0, "data_type": "Int"}}}],
           "else_body": [{"op": "list_append", "target": "out", "value": {"expr_type": "list_index", "target": {"expr_type": "var_ref", "name": "raw"}, "index": {"expr_type": "literal", "value": 1, "data_type": "Int"}}}]},
          {"op": "for_range", "loop_var": "idx", "start": {"expr_type": "literal", "value": 1, "data_type": "Int"},
           "end": {"expr_type": "binary_op", "op": "-", "left": {"expr_type": "list_length", "target": {"expr_type": "var_ref", "name": "raw"}}, "right": {"expr_type": "literal", "value": 1, "data_type": "Int"}},
           "body": [
             {"op": "var_decl", "name": "x", "var_type": "Float", "value": {"expr_type": "list_index", "target": {"expr_type": "var_ref", "name": "raw"}, "index": {"expr_type": "var_ref", "name": "idx"}}},
             {"op": "if_stmt",
              "condition": {"expr_type": "binary_op", "op": "<", "left": {"expr_type": "var_ref", "name": "x"}, "right": {"expr_type": "list_index", "target": {"expr_type": "var_ref", "name": "out"}, "index": {"expr_type": "literal", "value": 0, "data_type": "Int"}}},
              "then_body": [{"op": "list_insert", "target": "out", "index": {"expr_type": "literal", "value": 0, "data_type": "Int"}, "value": {"expr_type": "var_ref", "name": "x"}}],
              "else_body": []}]},
          {"op": "return_stmt", "value": {"expr_type": "list_index", "target": {"expr_type": "var_ref", "name": "out"}, "index": {"expr_type": "binary_op", "op": "-", "left": {"expr_type": "list_length", "target": {"expr_type": "var_ref", "name": "out"}}, "right": {"expr_type": "literal", "value": 1, "data_type": "Int"}}}}
        ]}
     ]}
10. Example 4 (Genuine Semantic Contradiction -> `"op": "ambiguity"`):
   Only emit `"op": "ambiguity"` when phrasing is genuinely contradictory (e.g., `for each number in array: sort from 1 to 10`):
     {"op": "ambiguity", "statement_id": 2, "source_line": 2,
      "source_text": "for each number in array sort from 1 to 10",
      "reason": "Looping over `array` while sorting `array` with bounds is ambiguous.",
      "candidates": [
        {"option": 1, "description": "Sort `array` ascending", "canonical_meme": "sort array ascending",
         "replacement_ir": [{"op": "sort_collection", "target": "array", "direction": "ascending"}],
         "replaces_whole_program": false}
      ]}"""

PROMPT_FOOTER = "Output ONLY valid JSON matching `SynthesisResult`."

SYSTEM_PROMPT = f"{BASE_PROMPT_PREFIX}\n{BASE_ANCHOR_EXAMPLES}\n{PROMPT_FOOTER}"


def format_dynamic_example(example: ExamplePair) -> str:
    lines = example.source_text.splitlines()
    numbered_lines = "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines, start=1))
    ir_payload = example.locked_ir.get("ir") if isinstance(example.locked_ir, dict) else None
    if ir_payload is None and isinstance(example.locked_ir, dict) and "entries" in example.locked_ir:
        for entry in example.locked_ir["entries"].values():
            if isinstance(entry, dict):
                if entry.get("ir") is not None:
                    ir_obj = entry["ir"]
                    if isinstance(ir_obj, dict) and "statements" in ir_obj:
                        ir_payload = {"items": ir_obj["statements"]}
                    else:
                        ir_payload = ir_obj
                    break
                elif entry.get("draft_items") is not None:
                    ir_payload = {"items": entry["draft_items"]}
                    break
    if ir_payload is None:
        ir_payload = example.locked_ir
    json_ir = json.dumps(ir_payload, indent=2)
    return (
        f"### Relevant Syntactic Example: {example.slug}\n"
        f"Input:\n"
        f"{numbered_lines}\n"
        f"Output:\n"
        f"{json_ir}"
    )


def build_compiler_messages(
    source_text: str,
    line_numbers: list[int] | Path | None = None,
    available_functions: list[FuncDefStmt] | ExampleRetriever | None = None,
    source_path: Path | None = None,
    retriever: ExampleRetriever | None = None,
    top_k: int = 2,
) -> list[dict[str, str]]:
    if isinstance(line_numbers, Path):
        source_path = line_numbers
        line_numbers = None
    if isinstance(available_functions, ExampleRetriever):
        retriever = available_functions
        available_functions = None

    lines = source_text.splitlines()
    if line_numbers and len(line_numbers) == len(lines):
        numbered = "\n".join(f"{ln}: {line}" for ln, line in zip(line_numbers, lines, strict=True))
    else:
        numbered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines, start=1))

    sig_header = ""
    if available_functions:
        sigs = []
        for fn in available_functions:
            ps = ", ".join(f"{p.name}: {p.param_type}" for p in fn.params)
            sigs.append(f"{fn.name}({ps}) -> {fn.return_type}")
        sig_header = (
            "Already-defined helper functions in scope (use these exact names & types when calling):\n"
            + "\n".join(f"- `{s}`" for s in sigs)
            + "\n\n"
        )

    examples: list[ExamplePair] = []
    if retriever is not None:
        examples = retriever.retrieve(
            query_text=source_text,
            top_k=top_k,
            exclude_path=source_path,
        )

    if examples:
        dynamic_block = "\n\n".join(format_dynamic_example(ex) for ex in examples)
        system_content = f"{BASE_PROMPT_PREFIX}\n\n{dynamic_block}\n\n{PROMPT_FOOTER}"
    else:
        system_content = SYSTEM_PROMPT

    return [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": f"{sig_header}Compile the following `.meme` source into SynthesisResult JSON:\n\n{numbered}",
        },
    ]


@dataclass
class CompilationUnit:
    is_func: bool
    text: str
    line_numbers: list[int]


_FUNC_HEADER_RE = re.compile(r"^(?:define\s+function|function)\s+([A-Za-z_][A-Za-z0-9_-]*)\b")
_CLASS_HEADER_RE = re.compile(r"^class\s+[A-Za-z_][A-Za-z0-9_-]*\s*:?\s*$")


def split_compilation_units(source_text: str) -> list[CompilationUnit]:
    raw_lines = source_text.splitlines()
    indexed: list[tuple[int, int, str]] = []
    for ln, raw in enumerate(raw_lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower() == "this runs in the shell" or _CLASS_HEADER_RE.match(stripped):
            continue
        indent = len(raw) - len(raw.lstrip(" \t"))
        indexed.append((ln, indent, raw))

    if not indexed:
        return []

    func_indents = [
        ind for _, ind, raw in indexed if _FUNC_HEADER_RE.match(raw.strip())
    ]
    if not func_indents:
        return [
            CompilationUnit(
                is_func=False,
                text="\n".join(raw for _, _, raw in indexed),
                line_numbers=[ln for ln, _, _ in indexed],
            )
        ]

    base_indent = min(func_indents)
    func_units: list[CompilationUnit] = []
    main_lines: list[tuple[int, str]] = []

    i = 0
    while i < len(indexed):
        ln, ind, raw = indexed[i]
        m = _FUNC_HEADER_RE.match(raw.strip()) if ind == base_indent else None
        if m:
            fn_name = m.group(1)
            block: list[tuple[int, str]] = [(ln, raw[base_indent:] if len(raw) >= base_indent else raw.strip())]
            i += 1
            while i < len(indexed) and indexed[i][1] > base_indent:
                bln, _, braw = indexed[i]
                dedented = braw[base_indent:] if len(braw) >= base_indent else braw.lstrip()
                block.append((bln, dedented))
                i += 1

            if fn_name == "main":
                # Unwrap `main` body lines as top-level executable lines
                body = block[1:]
                if body:
                    body_ind = min(len(r) - len(r.lstrip(" \t")) for _, r in body)
                    for bln, br in body:
                        main_lines.append((bln, br[body_ind:] if len(br) >= body_ind else br.lstrip()))
            else:
                if (
                    len(block) >= 3
                    and block[-1][1].lstrip().lower().startswith("return ")
                    and block[-2][1].lstrip().lower().startswith("stop when ")
                ):
                    block = [*block[:-2], block[-1]]
                func_units.append(
                    CompilationUnit(
                        is_func=True,
                        text="\n".join(r for _, r in block),
                        line_numbers=[b_ln for b_ln, _ in block],
                    )
                )
        else:
            ded = raw[base_indent:] if len(raw) >= base_indent else raw.lstrip()
            main_lines.append((ln, ded))
            i += 1

    units = list(func_units)
    if main_lines:
        units.append(
            CompilationUnit(
                is_func=False,
                text="\n".join(r for _, r in main_lines),
                line_numbers=[m_ln for m_ln, _ in main_lines],
            )
        )
    return units

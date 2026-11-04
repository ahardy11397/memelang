# Specification: Dynamic Few-Shot Retrieval, Backend IR Expansion & Empirical Corpus Gap Analysis

**Status:** Draft / Pending Review  
**Date:** 2026-11-03  
**Target Version:** v0.0.1alpha1  
**Scope:** Two-Axis Extensibility (Axis 1: `examples/` syntax knowledge base; Axis 2: `src/` IR & backend targets)

---

## 1. Executive Summary

Memelang's architecture distinguishes between two extensibility axes (the two this gap analysis measures; the compiler's third extension axis — its own LLM frontend — is documented in `2026-11-03-memelang-design.md` §9):
1. **Axis 1 (Syntax & Library Extensibility — `examples/`):** Whatever is in `examples/` defines what Memelang already knows. Instead of hardcoding all English grammatical forms in compiler system prompts, the compiler dynamically retrieves verified `.meme` + `.meme.lock` pairs matching the input code to serve as few-shot in-context learning demonstrations.
2. **Axis 2 (Language Backend Extensibility — `src/`):** The typed intermediate representation (IR), static verifier, and multi-target code generation backends (`python`, `rust`, `cpp`).

This specification formalizes:
- A pure-Python, zero-dependency BM25 retriever in `src/memelang/llm/retriever.py` that indexes `examples/` and injects top-scoring verified few-shot demonstrations into synthesis prompts.
- Backend IR expansions for fundamental Computer Science idioms: in-place list element assignment (`ListSetIndexStmt`), 2D matrix/nested list indexing (`ListIndexExpr` chaining over `List<List<T>>`), and string operations (`string_length`, `string_slice`).
- Verification in `verifier.py` and codegen parity across Python, Rust, and C++.
- An automated corpus gap analysis loop via `scripts/run_corpus.py` that attributes compile and runtime gaps along both axes and generates `gap_report.json`.

---

## 2. Dynamic BM25 Few-Shot Retriever (`src/memelang/llm/retriever.py`)

### 2.1 Problem & Motivation
Currently, `SYSTEM_PROMPT` in `src/memelang/llm/base.py` contains 4 static examples. As users write diverse programs across CS 101–103, fixed prompt examples cannot demonstrate all idioms (matrix traversal, string slicing, dictionary lookup, sorting variants). Dynamic retrieval allows the compiler to scale its vocabulary linearly with the `examples/` standard library without context-window explosion.

### 2.2 Algorithm & Indexing
- **Ranker:** Pure-Python Okapi BM25 ($k_1 = 1.5, b = 0.75$).
- **Tokenization:**
  - Lowercase, strip punctuation except structural symbols (`[`, `]`, `+`, `-`, `*`, `/`).
  - Extract n-grams and unigrams for domain identifiers and keyword phrases (`define`, `fromfile`, `sort ascending`, `matrix`, `insert`, `slice`, `reverse`, `swap`).
- **Document Catalog:**
  - Scans `examples/` recursively (`examples/cs101/`, `examples/cs102/`, `examples/cs103/`, user scripts).
  - A document qualifies as a full few-shot demonstration if and only if both `<name>.meme` and `<name>.meme.lock` exist.
  - The lockfile provides the verified `SynthesisResult` or `ProgramIR`.
- **Query & Selection:**
  - Given an input `.meme` text $Q$, compute BM25 scores against all locked documents $D \in \text{examples}$.
  - Exclude identical file path if compiling a file inside `examples/`.
  - Select top $K$ candidates (default $K = 2$, max $K = 3$).
  - If no candidate exceeds relevance score threshold $T_{\min} = 1.0$, fall back to canonical base seed demonstrations.

### 2.3 Prompt Composition
In `src/memelang/llm/base.py:build_compiler_messages(source_text: str)`:
```
System Prompt: Base rules, allowed types, allowed expressions, allowed statements.
Dynamically Injected Demonstration 1 (from examples/...):
  Input: <numbered source lines>
  Output: <JSON SynthesisResult>
Dynamically Injected Demonstration 2 (from examples/...):
  Input: <numbered source lines>
  Output: <JSON SynthesisResult>
User Message:
  Input source code to compile.
```

---

## 3. Backend & IR Expansion (`src/memelang/`)

### 3.1 `ListSetIndexStmt` (In-Place Element Assignment)
- **IR Schema (`schema.py`):**
  ```python
  class ListSetIndexStmt(IRNode):
      op: Literal["list_set_index"] = "list_set_index"
      target: str
      index: IRExpr
      value: IRExpr
      source_line: int | None = None
  ```
- **Static Verifier (`verifier.py`):**
  - Verify `target` exists in the local environment and is a `List<T>`.
  - Verify `index` has inferred type `Int`.
  - Verify `value` has inferred type compatible with `T` (e.g. `Int` for `List<Int>`, `Float` or `Int` promoting to `Float` for `List<Float>`).
  - Mark `target` as modified/populated in scope.
- **Codegen Backends:**
  - **Python (`python_gen.py`):** `{target}[int({index})] = {value}`
  - **Rust (`rust_gen.py`):** `{target}[{index} as usize] = {value};`
  - **C++ (`cpp_gen.py`):** `{target}.at(static_cast<size_t>({index})) = {value};`

### 3.2 2D Matrix / Nested List Indexing
- **Type Schema:** Add `List<List<Int>>`, `List<List<Float>>`, `List<List<String>>`, `List<List<Bool>>` to `MemeType`.
- **Expression Chaining:**
  - `ListIndexExpr` allows arbitrary nested `target: IRExpr`.
  - When `target` evaluates to `List<List<T>>` and `index` is `Int`, the result type is `List<T>`.
  - Chaining a second `ListIndexExpr` yields `T`.
- **Codegen Backends:**
  - **Python:** `matrix[int(r)][int(c)]`
  - **Rust:** `matrix[r as usize][c as usize]`
  - **C++:** `matrix.at(static_cast<size_t>(r)).at(static_cast<size_t>(c))`

### 3.3 String Fundamentals (`string_length` & `string_slice`)
- **IR Schema (`schema.py`):**
  ```python
  class StringLengthExpr(IRNode):
      expr_type: Literal["string_length"] = "string_length"
      target: IRExpr

  class StringSliceExpr(IRNode):
      expr_type: Literal["string_slice"] = "string_slice"
      target: IRExpr
      start: IRExpr
      end: IRExpr
  ```
- **Static Verifier (`verifier.py`):**
  - `StringLengthExpr.target` must have type `String`; returns `Int`.
  - `StringSliceExpr`: `target` must have type `String`; `start` and `end` must have type `Int`; returns `String`.
- **Codegen Backends:**
  - **Python:**
    - Length: `len({target})`
    - Slice: `{target}[int({start}):int({end})]`
  - **Rust:**
    - Length: `({target}.chars().count() as i64)`
    - Slice: `{target}.chars().skip({start} as usize).take(({end} - {start}) as usize).collect::<String>()`
  - **C++:**
    - Length: `static_cast<int64_t>({target}.length())`
    - Slice: `{target}.substr(static_cast<size_t>({start}), static_cast<size_t>(({end}) - ({start})))`

---

## 4. Corpus Gap Analysis & Benchmarking Workflow

### 4.1 Runner Enhancements (`scripts/run_corpus.py`)
- Support `--retriever` flag (enabled by default) to activate the dynamic retriever when calling LLM providers.
- When generating reports (`--report gap_report.json`), aggregate metrics across:
  - Total scripts evaluated.
  - Pass / Ambiguous Expected / Syntax Error / Verifier Gap / Codegen Error.
  - Axis 1 Gaps: Phrases/idioms lacking few-shot coverage in `examples/`.
  - Axis 2 Gaps: Missing IR statements, expressions, or target-language codegen constructs.

### 4.2 Golden Seed Initializer
- Create an initial curated set of locked golden examples across CS 101, 102, and 103 (e.g. `001_hello_banner`, `002_celsius_to_fahrenheit`, `051_bubble_sort`, `052_selection_sort`, `101_linear_search`, `102_binary_search`, `201_matrix_transpose`).
- These locked scripts immediately serve as dynamic few-shot donors for all related programs in the test corpus and user projects.

---

## 5. Non-Functional Requirements & Verification
- **Test Suite Runtime:** Full unit test suite (`pytest`) must remain under 25 seconds.
- **Zero External Retrieval Dependencies:** BM25 implementation must be pure Python standard library (`math`, `re`, `collections`, `pathlib`).
- **Target Parity:** Any valid program utilizing `list_set_index`, nested indexing, or string operations must produce identical execution results across Python, Rust, and C++.
- **Backward Compatibility:** All existing tests in `test_codegen_targets.py`, `test_static_verifier.py`, `test_cli_e2e.py`, and `test_corpus_manifest.py` must continue to pass 100%.

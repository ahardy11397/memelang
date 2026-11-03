# Memelang Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `meme` (`memelang`) natural-language compiler CLI that translates structured or freeform English `.meme` files via pluggable local/cloud LLMs into a verified, lockfile-cached Intermediate Representation (IR) and compiles/executes deterministic Python 3, Rust, and C++20 code.

**Architecture:** A two-phase compiler implemented in Python 3.13+ with Pydantic v2. Phase 1 passes `.meme` source through a pluggable LLM frontend (`auto`, `ollama`, `openai-local`, `llama-cpp`, `gemini`, or zero-dependency `heuristic`) constrained by JSON Schema to produce a `SynthesisResult`, runs a deterministic static type/scope/structural-ambiguity verifier (`verify_synthesis`), and caches verified `ProgramIR` or pending ambiguities in `build.lock`. Phase 2 uses pure deterministic AST backends to emit and optionally execute Python, standalone `rustc` Rust, and `g++ -std=c++20` C++.

**Tech Stack:** Python 3.13 (`uv`), Pydantic v2, `httpx` (local Ollama/OpenAI HTTP client), `pytest`, plus optional extras `google-genai` and `llama-cpp-python`; system targets `python3`, `rustc`, and `g++`.

**Spec:** `docs/superpowers/specs/2026-11-03-memelang-design.md`

## Global Constraints

- Source files use `.meme` extension; CLI executable is named `meme`; Python package is `memelang` under `src/memelang/`.
- Pin `.python-version` to `3.13` and `requires-python = ">=3.13"` so binary wheels (`pydantic`, `httpx`) install without source builds.
- Static types (`MemeType`) are strictly: `"Int"`, `"Float"`, `"Bool"`, `"String"`, `"List<Int>"`, `"List<Float>"`, `"List<Bool>"`, `"List<String>"`, `"Void"`.
- Target languages (`TargetLang`) are strictly: `"python"`, `"rust"`, `"cpp"`.
- Rust codegen MUST emit standalone zero-external-crate Rust (including a built-in splitmix64 PRNG helper when random nodes are present) so single-file `rustc` builds succeed offline.
- CLI exit codes: `0` success, `1` static verification / usage / resolution error, `2` unresolved semantic ambiguity (`AmbiguityError`), `3` unreachable/unconfigured explicit LLM provider (`LLMProviderError`).
- LLM temperature MUST be `0.0` (with `seed: 42` where supported) and never invoked during Phase 2 codegen or when `build.lock` hits cache / resolves a cached ambiguity.

## Review Focus

1. **Empty or comment-only `.meme` source files (`# comment` or whitespace):** Must produce `ProgramIR(statements=[])` and compile/run cleanly with empty stdout across `python`, `rust`, and `cpp` instead of failing in synthesis or emitting invalid syntax. (Tested in Tasks 4 & 5)
2. **Literal division/modulo by zero (`10 / 0`, `10 % 0`) and mismatched binary operand types (`"hi" + 5`):** Must raise `StaticVerificationError` during static verification before emitting code that panics or fails `rustc`/`g++` compilation. (Tested in Task 2)
3. **Out-of-range or unknown `--resolve` flags (`--resolve 99=1` or `--resolve 2=9`):** Must raise `LockfileResolutionError` (exit code `1`) listing valid statement IDs and option numbers rather than crashing with `KeyError`/`IndexError`. (Tested in Task 3)
4. **Reassigning a variable with an incompatible static type (`assign` `"text"` to `Int` variable `x`):** Must raise `StaticVerificationError` in `verify_synthesis` so strongly-typed Rust/C++ backends never emit invalid assignments. (Tested in Task 2)
5. **String literals with quotes/newlines (`"say \"hi\"\n"`) and empty list literals (`ListLiteralExpr(elements=[], element_type="Int")`):** Must emit properly escaped literals and explicit container types (`Vec::<i64>::new()`, `std::vector<long long>{}`) so `rustc` and `g++` type inference succeeds. (Tested in Task 5)

---

### Task 1: Project Scaffolding, IR Schema & Canonical Meme Decompiler

**Files:**
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `src/memelang/__init__.py`
- Create: `src/memelang/ir/__init__.py`
- Create: `src/memelang/ir/schema.py`
- Create: `src/memelang/ir/canonical.py`
- Test: `tests/test_ir_and_canonical.py`

**Interfaces:**
- Consumes: None (foundational package)
- Produces:
  - `MemeType = Literal["Int", "Float", "Bool", "String", "List<Int>", "List<Float>", "List<Bool>", "List<String>", "Void"]`
  - `IRExpr` discriminated union on `expr_type`: `LiteralExpr`, `ListLiteralExpr`, `VarRefExpr`, `RandomIntExpr`, `RandomListExpr`, `BinaryOpExpr`, `UnaryOpExpr`, `ListLengthExpr`, `ListIndexExpr`, `CallExpr`, `ReadInputExpr`
  - `IRStatement` discriminated union on `op`: `VarDeclStmt`, `AssignStmt`, `SortCollectionStmt`, `ClampCollectionStmt`, `FilterCollectionStmt`, `ListAppendStmt`, `PrintStmt`, `IfStmt`, `ForEachStmt`, `ForRangeStmt`, `WhileStmt`, `FuncDefStmt`, `ReturnStmt`
  - `FuncParam(name: str, param_type: MemeType)`
  - `AmbiguityCandidate(option: int, description: str, canonical_meme: str, replacement_ir: list[IRStatement], replaces_whole_program: bool = False)`
  - `AmbiguityDiagnostic(op: Literal["ambiguity"] = "ambiguity", statement_id: int, source_line: int = 1, source_text: str, reason: str, candidates: list[AmbiguityCandidate])`
  - `SynthesisItem = Annotated[IRStatement | AmbiguityDiagnostic, Field(discriminator="op")]`
  - `SynthesisResult(items: list[SynthesisItem])`
  - `ProgramIR(statements: list[IRStatement])`
  - `to_canonical_meme(program: ProgramIR) -> str` in `src/memelang/ir/canonical.py`

- [ ] **Step 1: Initialize `uv` project configuration and write failing IR/canonical tests**

Create `.python-version` (`3.13`), `pyproject.toml` (dependencies: `pydantic>=2.9`, `httpx>=0.27`; optional-dependencies: `gemini = ["google-genai>=1.0"]`, `local-gguf = ["llama-cpp-python>=0.3"]`; dev: `pytest>=8.0`; `[project.scripts] meme = "memelang.cli:main"`), and empty `src/memelang/__init__.py`. Then write `tests/test_ir_and_canonical.py`:

```python
from memelang.ir.schema import (
    AmbiguityCandidate,
    AmbiguityDiagnostic,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    RandomListExpr,
    SortCollectionStmt,
    SynthesisResult,
    VarDeclStmt,
    VarRefExpr,
)
from memelang.ir.canonical import to_canonical_meme


def test_program_ir_roundtrip_and_canonical():
    prog = ProgramIR(
        statements=[
            VarDeclStmt(
                name="numbers",
                var_type="List<Int>",
                value=RandomListExpr(
                    count=LiteralExpr(value=10, data_type="Int"),
                    min_val=LiteralExpr(value=1, data_type="Int"),
                    max_val=LiteralExpr(value=100, data_type="Int"),
                    implicit_bounds=False,
                ),
            ),
            SortCollectionStmt(target="numbers", direction="ascending"),
            PrintStmt(expressions=[VarRefExpr(name="numbers")]),
        ]
    )
    dumped = prog.model_dump_json()
    restored = ProgramIR.model_validate_json(dumped)
    assert restored == prog
    assert to_canonical_meme(restored) == (
        "define list numbers as 10 random integers between 1 and 100\n"
        "sort numbers ascending\n"
        "print numbers"
    )


def test_synthesis_result_discriminates_ambiguity_and_exports_json_schema():
    res = SynthesisResult(
        items=[
            AmbiguityDiagnostic(
                statement_id=2,
                source_line=2,
                source_text="for each number in array sort from 1 to 10",
                reason="Contradictory loop and sort",
                candidates=[
                    AmbiguityCandidate(
                        option=1,
                        description="Sort array ascending",
                        canonical_meme="sort array ascending",
                        replacement_ir=[SortCollectionStmt(target="array", direction="ascending")],
                    )
                ],
            )
        ]
    )
    schema = SynthesisResult.model_json_schema()
    assert "items" in schema["properties"]
    assert SynthesisResult.model_validate_json(res.model_dump_json()) == res
```

- [ ] **Step 2: Sync environment and run tests to verify failure**

Run: `uv sync --dev && uv run pytest tests/test_ir_and_canonical.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memelang.ir'`

- [ ] **Step 3: Implement `src/memelang/ir/schema.py`, `src/memelang/ir/canonical.py`, and `src/memelang/ir/__init__.py`**

Define all Pydantic v2 models in `schema.py` matching Spec Section 3 (call `model_rebuild()` for recursive expression/statement unions). Implement `to_canonical_meme(program: ProgramIR) -> str` in `canonical.py` formatting every `IRStatement` and `IRExpr` into deterministic, indented Structured English (`define <name> as ...`, `define list <name> as <count> random integers between <min> and <max>`, `sort <target> <direction>`, `clamp <target> between <min> and <max>`, `filter <target> where <item> ...`, `if <cond>:` / `else:`, `for each <item> in <collection>:`, `for <var> from <start> to <end>:`, `while <cond>:`, `function <name>(<params>) -> <ret>:`, `return ...`, `print ...`).

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_ir_and_canonical.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .python-version pyproject.toml uv.lock src/memelang tests/test_ir_and_canonical.py
git commit -m "feat(ir): scaffold project and add Pydantic IR schema and canonical formatter"
```

---

### Task 2: Deterministic Static Verifier & Structural Ambiguity Safety Net

**Files:**
- Create: `src/memelang/analyzer/__init__.py`
- Create: `src/memelang/analyzer/verifier.py`
- Test: `tests/test_static_verifier.py`

**Interfaces:**
- Consumes: `SynthesisResult`, `ProgramIR`, `IRStatement`, `IRExpr`, `AmbiguityDiagnostic`, `AmbiguityCandidate`, `MemeType` from `memelang.ir.schema`; `to_canonical_meme` from `memelang.ir.canonical`
- Produces:
  - `StaticVerificationError(Exception)` (attributes: `message: str`, `statement_index: int | None`)
  - `VerificationOutcome(program: ProgramIR | None, ambiguities: list[AmbiguityDiagnostic])` (property `is_unambiguous -> bool`)
  - `verify_synthesis(result: SynthesisResult) -> VerificationOutcome`
  - `verify_program(program: ProgramIR) -> ProgramIR`

- [ ] **Step 1: Write failing tests for type/scope verification, zero-division, incompatible reassignment, and structural loop+sort collision**

Create `tests/test_static_verifier.py` testing:
1. `test_valid_program_verifies`: Valid `VarDeclStmt` + `SortCollectionStmt` + `PrintStmt` returns `outcome.is_unambiguous is True` and `outcome.program is not None`.
2. `test_undeclared_variable_raises`: `SortCollectionStmt(target="missing", direction="ascending")` raises `StaticVerificationError`.
3. `test_incompatible_reassignment_raises` (Review Focus #4): Declaring `x: Int = 5` then `AssignStmt(name="x", value=LiteralExpr(value="oops", data_type="String"))` raises `StaticVerificationError`.
4. `test_division_by_zero_and_mismatched_binop_raise` (Review Focus #2): `BinaryOpExpr(op="/", left=10, right=0)` and `BinaryOpExpr(op="+", left="hi", right=5)` both raise `StaticVerificationError`.
5. `test_naive_loop_sort_collision_upgraded_to_ambiguity`: When a small LLM emits `VarDeclStmt(name="array", var_type="List<Int>", value=RandomListExpr(count=10, min_val=1, max_val=100, implicit_bounds=True))` followed by `ForEachStmt(item_var="number", collection="array", body=[SortCollectionStmt(target="array", direction="ascending")])`, `verify_synthesis` catches the loop/collection-mutation collision and returns `outcome.is_unambiguous is False` with an `AmbiguityDiagnostic` containing 3 candidates (sort in-place, clamp `[1, 10]` + sort, or restrict random bounds `[1, 10]` + sort with `replaces_whole_program=True`).

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_static_verifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memelang.analyzer'`

- [ ] **Step 3: Implement `src/memelang/analyzer/verifier.py`**

Implement lexical symbol table scopes (global, function parameters/return type, loop item/range variables), expression type inference (`infer_expr_type`), literal `/ 0` and `% 0` rejection, assignment/collection type checks, and the structural semantic collision detector that inspects `ForEachStmt` bodies for whole-collection mutations (`SortCollectionStmt`, `FilterCollectionStmt`, `ClampCollectionStmt`, `ListAppendStmt` targeting `stmt.collection`) and converts them into `AmbiguityDiagnostic` entries with valid `replacement_ir` candidates. If any `AmbiguityDiagnostic` exists (either emitted by the LLM or synthesized by the structural pass), return `VerificationOutcome(program=None, ambiguities=...)`; otherwise validate all statements and return `VerificationOutcome(program=ProgramIR(statements=...), ambiguities=[])`.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_static_verifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memelang/analyzer tests/test_static_verifier.py
git commit -m "feat(analyzer): add static type/scope verifier and loop-mutation ambiguity detector"
```

---

### Task 3: Lockfile Manager (`build.lock`) & Zero-LLM Ambiguity Resolution

**Files:**
- Create: `src/memelang/lockfile/__init__.py`
- Create: `src/memelang/lockfile/manager.py`
- Test: `tests/test_lockfile_and_resolve.py`

**Interfaces:**
- Consumes: `ProgramIR`, `SynthesisResult`, `AmbiguityDiagnostic`, `IRStatement` from `memelang.ir.schema`; `to_canonical_meme` from `memelang.ir.canonical`; `verify_synthesis`, `VerificationOutcome` from `memelang.analyzer.verifier`
- Produces:
  - `LockfileResolutionError(Exception)`
  - `LockEntry(source_sha256: str, provider: str, resolutions: dict[str, int], pending_ambiguities: list[AmbiguityDiagnostic], canonical_meme: str | None, ir: ProgramIR | None)`
  - `LockfileManager(lockfile_path: Path)` with methods:
    - `compute_source_hash(source_text: str) -> str` (normalizes `\r\n` -> `\n` and trailing newline)
    - `get_cached_program(source_key: str, source_text: str, requested_resolutions: dict[int, int] | None = None) -> ProgramIR | None`
    - `record_outcome(source_key: str, source_text: str, provider_name: str, synthesis: SynthesisResult, outcome: VerificationOutcome, requested_resolutions: dict[int, int] | None = None) -> VerificationOutcome`
    - `apply_resolutions(source_key: str, source_text: str, resolutions: dict[int, int]) -> VerificationOutcome`

- [ ] **Step 1: Write failing tests for lockfile caching, zero-LLM ambiguity resolution, and invalid resolution flags**

Create `tests/test_lockfile_and_resolve.py` testing:
1. `test_cache_hit_returns_locked_program_until_source_changes`: Unambiguous outcome writes `build.lock`; `get_cached_program` returns `ProgramIR` on identical source and `None` when source text changes.
2. `test_pending_ambiguity_resolved_without_llm`: Recording an ambiguous `VerificationOutcome` saves `pending_ambiguities` + original `SynthesisResult` items in `build.lock`; calling `apply_resolutions("main.meme", source, {2: 1})` produces a verified `ProgramIR`, updates `resolutions={"2": 1}`, clears `pending_ambiguities`, and persists `canonical_meme`. Also test a candidate with `replaces_whole_program=True` (option 3).
3. `test_invalid_resolution_id_or_option_raises` (Review Focus #3): Calling `apply_resolutions` with `{99: 1}` or `{2: 9}` raises `LockfileResolutionError` whose message lists valid statement IDs and option numbers.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_lockfile_and_resolve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memelang.lockfile'`

- [ ] **Step 3: Implement `src/memelang/lockfile/manager.py`**

Persist `lockfile_version: 1` and `entries: dict[str, LockEntry]` (storing `draft_items: list[SynthesisItem]` alongside `pending_ambiguities` when unresolved so `apply_resolutions` can splice `candidate.replacement_ir` into the exact statement slot—or replace all items when `candidate.replaces_whole_program` is `True`—and run `verify_synthesis` without calling any LLM). Validate `resolutions` keys and option numbers before splicing, raising `LockfileResolutionError` with actionable valid choices if mismatched.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_lockfile_and_resolve.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memelang/lockfile tests/test_lockfile_and_resolve.py
git commit -m "feat(lockfile): implement build.lock caching and zero-LLM ambiguity resolution"
```

---

### Task 4: Pluggable LLM Frontend (`heuristic`, `ollama`/`openai-local`, `llama-cpp`, `gemini`)

**Files:**
- Create: `src/memelang/llm/__init__.py`
- Create: `src/memelang/llm/base.py`
- Create: `src/memelang/llm/heuristic.py`
- Create: `src/memelang/llm/ollama.py`
- Create: `src/memelang/llm/llama_cpp.py`
- Create: `src/memelang/llm/gemini.py`
- Test: `tests/test_llm_providers.py`

**Interfaces:**
- Consumes: `SynthesisResult`, `IRStatement`, `IRExpr`, `AmbiguityDiagnostic`, `AmbiguityCandidate` from `memelang.ir.schema`
- Produces:
  - `LLMProviderError(Exception)`
  - `LLMProvider(Protocol)` with `name: str` and `synthesize(self, source_text: str) -> SynthesisResult`
  - `build_compiler_messages(source_text: str) -> list[dict[str, str]]` in `base.py`
  - `HeuristicProvider` (`name = "heuristic"`)
  - `OllamaProvider(model: str = "qwen2.5-coder:3b", host: str = "http://127.0.0.1:11434")`
  - `OpenAILocalProvider(model: str, base_url: str = "http://127.0.0.1:8080/v1", api_key: str = "local")`
  - `LlamaCppProvider(model_path: str, n_gpu_layers: int = -1, n_ctx: int = 4096)`
  - `GeminiProvider(model: str = "gemini-2.5-flash", api_key: str | None = None)`
  - `get_provider(spec: str = "auto") -> LLMProvider` in `src/memelang/llm/__init__.py` (supports `"auto"`, `"heuristic"`, `"ollama"`, `"ollama:<model>"`, `"openai-local:<model>"`, `"llama-cpp:<path.gguf>"`, `"gemini"`, `"gemini:<model>"`)

- [ ] **Step 1: Write failing tests for `HeuristicProvider`, `OllamaProvider` HTTP contract, empty/comment inputs, and provider error handling**

Create `tests/test_llm_providers.py` testing:
1. `test_empty_and_comment_only_source` (Review Focus #1): `HeuristicProvider().synthesize("# just a comment\n\n")` returns `SynthesisResult(items=[])`.
2. `test_heuristic_structured_and_control_flow`: Synthesizes `define list numbers as 10 random integers between 1 and 100\nsort numbers ascending\nprint numbers` and a FizzBuzz `for i from 1 to 15:` / `if` / `else` / `function` snippet into valid `SynthesisResult`s that pass `verify_synthesis`.
3. `test_heuristic_ambiguous_prompt_example`: Synthesizes `array = 10.random numbers\nfor each number in array\n    sort from 1 to 10` into a `SynthesisResult` containing an `AmbiguityDiagnostic` at `statement_id=2` with 3 concrete candidates matching the spec.
4. `test_ollama_provider_sends_schema_and_parses_response`: Using `httpx.MockTransport`, verifies `OllamaProvider` posts `temperature: 0.0`, `seed: 42`, and `format: SynthesisResult.model_json_schema()` to `/api/chat` and parses the JSON content into `SynthesisResult`; verifies unreachable server raises `LLMProviderError`.
5. `test_missing_gemini_key_or_gguf_raises_provider_error`: Requesting `get_provider("gemini")` without `GEMINI_API_KEY` or `get_provider("llama-cpp:/nonexistent.gguf")` raises `LLMProviderError`.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_llm_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memelang.llm'`

- [ ] **Step 3: Implement `base.py`, `heuristic.py`, `ollama.py`, `llama_cpp.py`, `gemini.py`, and `__init__.py`**

- In `base.py`: Build compact few-shot system instructions tailored for 1.5B–3B models showing (a) structured English -> `IRStatement`s and (b) ambiguous loop+sort English -> `AmbiguityDiagnostic` with `replacement_ir`. Short-circuit empty/comment-only input (`#` comments stripped) before calling network/model inference so all providers return `SynthesisResult(items=[])` deterministically.
- In `heuristic.py`: Parse indentation blocks and support Canonical Structured English plus natural-language synonyms (`array = 10.random numbers`, `set x to ...`, `define ...`, `sort ...`, `clamp ...`, `filter ...`, `append ...`, `for each ... in ...`, `for ... from ... to ...`, `while ...`, `if ...` / `else if ...` / `else`, `function ...`, `return ...`, `print ...`, arithmetic/comparison expressions, and detecting `for each <x> in <col>` paired with `sort [from A to B]` as `AmbiguityDiagnostic`).
- In `ollama.py`: Implement `OllamaProvider` (`/api/chat` with `options={"temperature": 0.0, "seed": 42}`, `format=SynthesisResult.model_json_schema()`, `stream=False`, custom `httpx.Client` injectable for tests) and `OpenAILocalProvider` (`/chat/completions` with `response_format={"type": "json_schema", "json_schema": {"name": "SynthesisResult", "schema": SynthesisResult.model_json_schema()}}`). Catch `httpx.HTTPError` and validation errors as `LLMProviderError`.
- In `llama_cpp.py` & `gemini.py`: Lazy-import `llama_cpp` and `google.genai` (using `GenerateContentConfig(temperature=0.0, response_mime_type="application/json", response_json_schema=SynthesisResult.model_json_schema())`), raising `LLMProviderError` with install/config instructions if missing.
- In `__init__.py`: Implement `get_provider(spec)`. For `"auto"`, probe `MEME_PROVIDER` env var first, then check local Ollama `/api/tags` with a 0.3s timeout if running, otherwise fall back cleanly to `HeuristicProvider`.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_llm_providers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memelang/llm tests/test_llm_providers.py
git commit -m "feat(llm): add pluggable LLM providers and zero-dependency heuristic frontend"
```

---

### Task 5: Deterministic Target Code Generators & Runner (`python`, `rust`, `cpp`)

**Files:**
- Create: `src/memelang/codegen/__init__.py`
- Create: `src/memelang/codegen/python_gen.py`
- Create: `src/memelang/codegen/rust_gen.py`
- Create: `src/memelang/codegen/cpp_gen.py`
- Create: `src/memelang/runner/__init__.py`
- Create: `src/memelang/runner/executor.py`
- Test: `tests/test_codegen_targets.py`

**Interfaces:**
- Consumes: `ProgramIR`, `IRStatement`, `IRExpr`, `MemeType` from `memelang.ir.schema`
- Produces:
  - `TargetLang = Literal["python", "rust", "cpp"]`
  - `generate_code(ir: ProgramIR, target: TargetLang) -> str` in `src/memelang/codegen/__init__.py` (`generate_python`, `generate_rust`, `generate_cpp`)
  - `ExecutionResult(stdout: str, stderr: str, returncode: int, generated_code: str)`
  - `execute_ir(ir: ProgramIR, target: TargetLang, timeout_sec: float = 15.0) -> ExecutionResult` in `src/memelang/runner/executor.py`

- [ ] **Step 1: Write failing multi-target compilation & execution tests**

Create `tests/test_codegen_targets.py` parameterizing `target` across `["python", "rust", "cpp"]`:
1. `test_empty_program_compiles_and_runs` (Review Focus #1): `ProgramIR(statements=[])` executes with `returncode == 0` and `stdout == ""`.
2. `test_escaped_strings_and_empty_typed_list` (Review Focus #5): Program declaring `empty: List<Int> = []`, appending `42`, printing `empty` and `'say "hi"\nline2'` compiles cleanly under `python3`, `rustc`, and `g++ -std=c++20` and produces identical normalized output across all 3 targets.
3. `test_random_clamp_sort_and_functions_across_targets`: Program generating 10 random ints in `[1, 100]`, clamping to `[10, 50]`, sorting ascending, and calling a helper function `add_one(x: Int) -> Int` compiles and executes across all 3 targets with 10 sorted integers all within `10..=50`.
4. `test_filter_and_loops_parity`: Program filtering a list `[1, 2, 3, 4, 5, 6]` where `item % 2 == 0` and summing via `for_each` prints `12` identically in Python, Rust, and C++20.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_codegen_targets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memelang.codegen'`

- [ ] **Step 3: Implement `python_gen.py`, `rust_gen.py`, `cpp_gen.py`, and `executor.py`**

Ensure consistent list formatting across all three targets (e.g., `[1, 2, 3]` when printing lists via helper formatting functions in Rust/C++ so stdout matches across targets), proper string escaping (`json.dumps` / language-specific escape helper), explicit container types on empty list literals (`Vec::<i64>::new()`, `std::vector<long long>{}`), standalone splitmix64 PRNG seeded from `SystemTime` in `rust_gen.py` when random expressions are present, and `tempfile.TemporaryDirectory` compilation/execution in `executor.py` (`python3 script.py`, `rustc -O main.rs -o app && ./app`, `g++ -std=c++20 -O2 main.cpp -o app && ./app`).

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_codegen_targets.py -v`
Expected: PASS (all parameterized `python`, `rust`, and `cpp` execution tests succeed)

- [ ] **Step 5: Commit**

```bash
git add src/memelang/codegen src/memelang/runner tests/test_codegen_targets.py
git commit -m "feat(codegen): add deterministic Python, Rust, and C++20 backends and runner"
```

---

### Task 6: `meme` CLI, Example Programs, Documentation & End-to-End Tests

**Files:**
- Create: `src/memelang/cli.py`
- Create: `examples/random_sort_structured.meme`
- Create: `examples/random_sort_ambiguous.meme`
- Create: `examples/fizzbuzz.meme`
- Create: `README.md`
- Test: `tests/test_cli_e2e.py`

**Interfaces:**
- Consumes: `get_provider`, `LLMProviderError` from `memelang.llm`; `verify_synthesis`, `StaticVerificationError` from `memelang.analyzer.verifier`; `LockfileManager`, `LockfileResolutionError` from `memelang.lockfile.manager`; `generate_code`, `TargetLang` from `memelang.codegen`; `execute_ir` from `memelang.runner.executor`; `to_canonical_meme` from `memelang.ir.canonical`
- Produces:
  - `main(argv: list[str] | None = None) -> int` in `src/memelang/cli.py` supporting subcommands:
    - `meme compile <file.meme> --target <python|rust|cpp> [-o <out>] [--provider <spec>] [--lockfile <path>] [--resolve <id=opt> ...] [--interactive]`
    - `meme run <file.meme> [--target <python|rust|cpp>] [--provider <spec>] [--lockfile <path>] [--resolve <id=opt> ...] [--interactive]`
    - `meme check <file.meme> [--provider <spec>] [--lockfile <path>]`
    - `meme explain <file.meme> [--provider <spec>] [--lockfile <path>]`

- [ ] **Step 1: Write failing E2E CLI tests**

Create `tests/test_cli_e2e.py` testing `main(argv)` (and `capsys` stdout/stderr):
1. `test_cli_structured_compile_and_run_all_targets`: Runs `meme run examples/random_sort_structured.meme --target python`, `--target rust`, and `--target cpp` using a temporary `--lockfile`, asserting exit code `0`, `build.lock` creation, and sorted 10-element list output.
2. `test_cli_ambiguous_workflow_and_lock_resolution`:
   - Runs `meme compile examples/random_sort_ambiguous.meme --target rust --lockfile <tmp>` -> exits with code `2` and prints `[Compiler Warning: Ambiguous Intent` plus `--resolve 2=1`.
   - Re-runs with `--resolve 2=1` -> exits with code `0` without calling LLM again, emits valid Rust, and subsequent `meme explain` prints the resolved Canonical Meme source.
3. `test_cli_exit_codes_for_static_and_provider_errors`: Verifies exit code `1` on undeclared variable or bad `--resolve 99=1`, and exit code `3` on `--provider gemini` when `GEMINI_API_KEY` is unset.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_cli_e2e.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'memelang.cli'`

- [ ] **Step 3: Implement `src/memelang/cli.py`, `examples/*.meme`, and `README.md`**

Implement `argparse`-based `cli.py` handling lockfile lookup first, running provider + `verify_synthesis` on cache miss, formatting `AmbiguityDiagnostic` tables to stderr (supporting both `--resolve <id>=<opt>` and `--interactive` stdin prompt), emitting code to `-o` or stdout (`compile`) or running via `execute_ir` (`run`), and returning exact exit codes (`0`, `1`, `2`, `3`). Create `examples/random_sort_structured.meme`, `examples/random_sort_ambiguous.meme` (containing the exact `array = 10.random numbers` / `for each number in array` / `    sort from 1 to 10` example), `examples/fizzbuzz.meme`, and `README.md` documenting CLI usage, architecture, and running a 3B model locally on 6GB VRAM via Ollama or GGUF.

- [ ] **Step 4: Run full test suite and CLI smoke check**

Run: `uv run pytest -v && uv run meme run examples/random_sort_structured.meme --target rust`
Expected: All test suites PASS and `meme run` compiles & prints a sorted 10-element integer list.

- [ ] **Step 5: Commit**

```bash
git add src/memelang/cli.py examples README.md tests/test_cli_e2e.py
git commit -m "feat(cli): add meme CLI, example programs, docs, and end-to-end tests"
```

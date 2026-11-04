# Dynamic Few-Shot Retrieval, Backend IR Expansion & Empirical Corpus Gap Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement dynamic BM25 few-shot example retrieval from `examples/`, expand the typed IR and verifier with in-place list mutation, 2D matrix indexing, and string operations across Python, Rust, and C++, and upgrade `scripts/run_corpus.py` to benchmark and attribute compiler gaps along both axes.

**Architecture:** A pure-Python zero-dependency Okapi BM25 engine indexes paired `.meme` and `.meme.lock` files in `examples/` and injects top-2 relevant demonstrations into LLM compiler prompts. Core IR schema, type analyzer, and all three backends (`python_gen`, `rust_gen`, `cpp_gen`) are augmented with `ListSetIndexStmt`, nested 2D `ListIndexExpr`, `StringLengthExpr`, and `StringSliceExpr`. The CS corpus runner benchmarks empirical pass rates and exports a structured 2-axis gap attribution report.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, Rust (`rustc`), C++ (`g++`), BM25 standard math.

**Spec:** [`docs/superpowers/specs/2026-11-03-few-shot-ir-expansion-gap-analysis-design.md`](file:///mnt/ssd/projects/meme/docs/superpowers/specs/2026-11-03-few-shot-ir-expansion-gap-analysis-design.md)

## Global Constraints

- Full test suite runtime (`uv run pytest`) must stay under 25 seconds.
- Zero extra external runtime dependencies (pure standard library BM25: `math`, `re`, `collections`, `pathlib`).
- Absolute 3-target codegen parity: any valid program using new IR primitives must produce identical standard output across Python, Rust, and C++.
- Backward compatibility: all existing tests in `test_codegen_targets.py`, `test_static_verifier.py`, `test_cli_e2e.py`, and `test_corpus_manifest.py` must pass 100%.

## Review Focus

1. **Zero locked examples match query:** Fallback returns minimal default canonical anchors without raising an exception.
2. **Self-retrieval exclusion:** When compiling an existing example file (e.g. `examples/cs101/001_hello_banner.meme`), the retriever excludes the file itself from its few-shot demonstration candidates.
3. **Out-of-bounds or mismatched type in `list_set_index`:** Verifier catches type mismatches (e.g. assigning string into `List<Float>`) and non-integer indices before codegen.
4. **Rust UTF-8 character slicing safety:** String slicing in Rust must use character iterator bounds (`.chars().skip().take()`) to avoid panicking on multibyte UTF-8 boundaries.
5. **C++ `substr` length argument:** C++ `std::string::substr(pos, count)` takes count (length), not end index; codegen must pass `(end - start)`.

---

### Task 1: Pure-Python BM25 Indexer & Retriever

**Files:**
- Create: `src/memelang/llm/retriever.py`
- Create: `tests/test_retriever.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class ExamplePair:
      slug: str
      source_path: Path
      source_text: str
      locked_ir: dict[str, Any]
      score: float = 0.0

  class ExampleRetriever:
      def __init__(self, examples_dir: Path | None = None)
      def index_corpus(self) -> int
      def retrieve(self, query_text: str, top_k: int = 2, exclude_path: Path | None = None, min_score: float = 0.5) -> list[ExamplePair]
  ```

- [ ] **Step 1: Write failing tests for tokenizer, BM25 scoring, and example discovery**

```python
# tests/test_retriever.py
from pathlib import Path
from memelang.llm.retriever import ExampleRetriever, bm25_tokenize

def test_bm25_tokenize_extracts_clean_tokens():
    tokens = bm25_tokenize('define list as [1, 2] # comment\nsort list ascending')
    assert "define" in tokens
    assert "sort" in tokens
    assert "ascending" in tokens
    assert "comment" not in tokens

def test_retriever_discovers_locked_examples(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    meme_file = ex_dir / "demo.meme"
    meme_file.write_text("print 42\n")
    lock_file = ex_dir / "demo.meme.lock"
    lock_file.write_text('{"ir": {"items": [{"op": "print_stmt", "expressions": [{"expr_type": "literal", "value": 42, "data_type": "Int"}]}]}}')

    retriever = ExampleRetriever(examples_dir=ex_dir)
    count = retriever.index_corpus()
    assert count == 1

    results = retriever.retrieve("print something", top_k=2)
    assert len(results) == 1
    assert results[0].slug == "demo"
    assert "print_stmt" in str(results[0].locked_ir)

def test_retriever_excludes_self(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    meme_file = ex_dir / "demo.meme"
    meme_file.write_text("print 42\n")
    lock_file = ex_dir / "demo.meme.lock"
    lock_file.write_text('{"ir": {"items": []}}')

    retriever = ExampleRetriever(examples_dir=ex_dir)
    retriever.index_corpus()
    results = retriever.retrieve("print 42", top_k=2, exclude_path=meme_file)
    assert len(results) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retriever.py -v`  
Expected: FAIL (ModuleNotFoundError: No module named 'memelang.llm.retriever')

- [ ] **Step 3: Implement `ExampleRetriever` in `src/memelang/llm/retriever.py`**

Implement `bm25_tokenize`, document frequency indexing, Okapi BM25 calculation ($k_1=1.5, b=0.75$), directory scanning for `.meme` + `.meme.lock` pairs, and exclusion filter.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_retriever.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memelang/llm/retriever.py tests/test_retriever.py
git commit -m "feat(retriever): implement pure-Python BM25 few-shot example indexer"
```

---

### Task 2: Dynamic Few-Shot Compiler Prompt Integration

**Files:**
- Modify: `src/memelang/llm/base.py`
- Modify: `src/memelang/llm/__init__.py`
- Create: `tests/test_dynamic_prompt.py`

**Interfaces:**
- Consumes: `ExampleRetriever`, `ExamplePair` from Task 1.
- Produces:
  ```python
  def build_compiler_messages(
      source_text: str,
      source_path: Path | None = None,
      retriever: ExampleRetriever | None = None,
      top_k: int = 2,
  ) -> list[dict[str, str]]
  ```

- [ ] **Step 1: Write failing tests for dynamic prompt construction**

```python
# tests/test_dynamic_prompt.py
from pathlib import Path
from memelang.llm.base import build_compiler_messages
from memelang.llm.retriever import ExampleRetriever

def test_build_compiler_messages_with_retriever(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    (ex_dir / "binary_search.meme").write_text("define function binarySearch with list and target\n")
    (ex_dir / "binary_search.meme.lock").write_text('{"ir": {"items": [{"op": "func_def", "name": "binarySearch", "params": [], "return_type": "Int", "body": []}]}}')

    retriever = ExampleRetriever(examples_dir=ex_dir)
    retriever.index_corpus()

    messages = build_compiler_messages("binarySearch in array for key", retriever=retriever, top_k=1)
    prompt_content = messages[0]["content"]
    assert "binarySearch" in prompt_content
    assert "Relevant Syntactic Example: binary_search" in prompt_content

def test_build_compiler_messages_fallback_when_no_match(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    retriever = ExampleRetriever(examples_dir=ex_dir)
    retriever.index_corpus()

    messages = build_compiler_messages("some completely novel query", retriever=retriever)
    prompt_content = messages[0]["content"]
    assert "Example 1 (Structured):" in prompt_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dynamic_prompt.py -v`  
Expected: FAIL (unexpected keyword argument or missing dynamic example section)

- [ ] **Step 3: Update `build_compiler_messages` in `src/memelang/llm/base.py`**

Incorporate dynamic demonstrations formatted as numbered lines and JSON IR into system prompt when retrieved, falling back to base canonical examples when list is empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dynamic_prompt.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memelang/llm/base.py tests/test_dynamic_prompt.py
git commit -m "feat(llm): integrate dynamic few-shot example retrieval into compiler prompts"
```

---

### Task 3: IR Schema & Static Verifier Expansion

**Files:**
- Modify: `src/memelang/ir/schema.py`
- Modify: `src/memelang/analyzer/verifier.py`
- Modify: `tests/test_static_verifier.py`

**Interfaces:**
- Produces:
  - `ListSetIndexStmt(op="list_set_index", target=str, index=IRExpr, value=IRExpr)`
  - `StringLengthExpr(expr_type="string_length", target=IRExpr)`
  - `StringSliceExpr(expr_type="string_slice", target=IRExpr, start=IRExpr, end=IRExpr)`
  - `MemeType` supporting `List<List<Int>>`, `List<List<Float>>`, `List<List<String>>`, `List<List<Bool>>`

- [ ] **Step 1: Write failing tests for new IR nodes and verification checks**

```python
# in tests/test_static_verifier.py
def test_verify_list_set_index_success():
    program = ProgramIR(items=[
        VarDeclStmt(name="arr", var_type="List<Int>", value=ListLiteralExpr(elements=[LiteralExpr(value=10, data_type="Int")], element_type="Int"), source_line=1),
        ListSetIndexStmt(target="arr", index=LiteralExpr(value=0, data_type="Int"), value=LiteralExpr(value=20, data_type="Int"), source_line=2),
    ])
    outcome = verify_synthesis(program)
    assert outcome.passed

def test_verify_list_set_index_type_mismatch():
    program = ProgramIR(items=[
        VarDeclStmt(name="arr", var_type="List<Int>", value=ListLiteralExpr(elements=[LiteralExpr(value=10, data_type="Int")], element_type="Int"), source_line=1),
        ListSetIndexStmt(target="arr", index=LiteralExpr(value=0, data_type="Int"), value=LiteralExpr(value="bad", data_type="String"), source_line=2),
    ])
    with pytest.raises(StaticVerificationError, match="Cannot assign String to element of List<Int>"):
        verify_synthesis(program)

def test_verify_string_slice_and_length():
    program = ProgramIR(items=[
        VarDeclStmt(name="msg", var_type="String", value=LiteralExpr(value="hello world", data_type="String"), source_line=1),
        VarDeclStmt(name="n", var_type="Int", value=StringLengthExpr(target=VarRefExpr(name="msg")), source_line=2),
        VarDeclStmt(name="sub", var_type="String", value=StringSliceExpr(target=VarRefExpr(name="msg"), start=LiteralExpr(value=0, data_type="Int"), end=LiteralExpr(value=5, data_type="Int")), source_line=3),
    ])
    outcome = verify_synthesis(program)
    assert outcome.passed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_static_verifier.py -k "list_set_index or string_slice" -v`  
Expected: FAIL (cannot import `ListSetIndexStmt`, `StringLengthExpr`, `StringSliceExpr`)

- [ ] **Step 3: Implement new nodes in `schema.py` and verification in `verifier.py`**

Add nodes to `schema.py`, add them to discriminated union `IRStatement` and `IRExpr`.
In `verifier.py`, implement type checking and variable mutation tracking for `list_set_index`, nested `list_index` resolution on 2D lists, and `string_length`/`string_slice` typing.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_static_verifier.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memelang/ir/schema.py src/memelang/analyzer/verifier.py tests/test_static_verifier.py
git commit -m "feat(ir): add list_set_index, 2D indexing, and string length/slice to IR and verifier"
```

---

### Task 4: Codegen Expansion across Python, Rust, and C++

**Files:**
- Modify: `src/memelang/codegen/python_gen.py`
- Modify: `src/memelang/codegen/rust_gen.py`
- Modify: `src/memelang/codegen/cpp_gen.py`
- Modify: `tests/test_codegen_targets.py`

**Interfaces:**
- Consumes: new IR nodes from Task 3.
- Produces: Executable Python, Rust, and C++ code for `list_set_index`, nested 2D matrix indexing, and string operations.

- [ ] **Step 1: Write failing e2e tests for Python, Rust, and C++ codegen execution**

```python
# in tests/test_codegen_targets.py
@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
def test_codegen_list_set_index_and_strings_parity(target):
    program = ProgramIR(items=[
        VarDeclStmt(name="nums", var_type="List<Int>", value=ListLiteralExpr(elements=[LiteralExpr(value=1, data_type="Int"), LiteralExpr(value=2, data_type="Int")], element_type="Int")),
        ListSetIndexStmt(target="nums", index=LiteralExpr(value=0, data_type="Int"), value=LiteralExpr(value=99, data_type="Int")),
        PrintStmt(expressions=[ListIndexExpr(target=VarRefExpr(name="nums"), index=LiteralExpr(value=0, data_type="Int"))]),
        VarDeclStmt(name="word", var_type="String", value=LiteralExpr(value="abcdef", data_type="String")),
        PrintStmt(expressions=[StringLengthExpr(target=VarRefExpr(name="word"))]),
        PrintStmt(expressions=[StringSliceExpr(target=VarRefExpr(name="word"), start=LiteralExpr(value=1, data_type="Int"), end=LiteralExpr(value=4, data_type="Int"))]),
    ])
    output = _run_target(program, target)
    assert output.strip().splitlines() == ["99", "6", "bcd"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_codegen_targets.py -k "test_codegen_list_set_index_and_strings_parity" -v`  
Expected: FAIL (unsupported statement or expression type in generators)

- [ ] **Step 3: Implement codegen handlers in `python_gen.py`, `rust_gen.py`, and `cpp_gen.py`**

- `python_gen.py`:
  - `list_set_index` -> `{target}[int({index})] = {value}`
  - `string_length` -> `len({target})`
  - `string_slice` -> `{target}[int({start}):int({end})]`
- `rust_gen.py`:
  - `list_set_index` -> `{target}[{index} as usize] = {value};`
  - `string_length` -> `({target}.chars().count() as i64)`
  - `string_slice` -> `{target}.chars().skip({start} as usize).take((({end}) - ({start})) as usize).collect::<String>()`
- `cpp_gen.py`:
  - `list_set_index` -> `{target}.at(static_cast<size_t>({index})) = {value};`
  - `string_length` -> `static_cast<int64_t>({target}.length())`
  - `string_slice` -> `{target}.substr(static_cast<size_t>({start}), static_cast<size_t>(({end}) - ({start})))`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_codegen_targets.py -k "test_codegen_list_set_index_and_strings_parity" -v`  
Expected: PASS for all 3 targets

- [ ] **Step 5: Run full test suite to ensure no regressions**

Run: `uv run pytest -v`  
Expected: 100% PASS

- [ ] **Step 6: Commit**

```bash
git add src/memelang/codegen/*.py tests/test_codegen_targets.py
git commit -m "feat(codegen): implement list_set_index, 2D indexing, and strings across Python, Rust, and C++"
```

---

### Task 5: Golden Seeds & Corpus Runner Gap Attribution Upgrade

**Files:**
- Create: Seed lockfiles `examples/cs101/001_hello_banner.meme.lock`, `002_celsius_to_fahrenheit.meme.lock`, `051_bubble_sort.meme.lock`, `101_linear_search.meme.lock`, `201_matrix_transpose.meme.lock`
- Modify: `scripts/run_corpus.py`
- Modify: `tests/test_corpus_manifest.py`

**Interfaces:**
- Produces:
  - Command-line flag `--retriever` in `scripts/run_corpus.py`
  - Command-line flag `--report <path>` exporting detailed JSON gap report with Axis 1 vs Axis 2 gap rankings
  - Validated seed lockfiles tested by `test_corpus_manifest.py`

- [ ] **Step 1: Write test verifying that seed lockfiles are valid and indexed by retriever**

```python
# in tests/test_corpus_manifest.py
def test_seed_examples_have_valid_lockfiles_and_are_retrievable():
    from memelang.llm.retriever import ExampleRetriever
    retriever = ExampleRetriever()
    count = retriever.index_corpus()
    assert count >= 5
    results = retriever.retrieve("hello student name", top_k=1)
    assert len(results) == 1
    assert "001_hello_banner" in results[0].slug
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_corpus_manifest.py -k "test_seed_examples" -v`  
Expected: FAIL

- [ ] **Step 3: Generate seed lockfiles and update `scripts/run_corpus.py`**

- Create verified lockfiles for the seed scripts using the lockfile manager.
- Update `scripts/run_corpus.py` to instantiate and pass `ExampleRetriever` to `build_compiler_messages` when compiling corpus scripts.
- Enhance `--report` to output structured counts of Axis 1 vs Axis 2 gaps.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_corpus_manifest.py -v`  
Expected: PASS

- [ ] **Step 5: Run full test suite and smoke test corpus runner**

Run: `uv run pytest -v`  
Run: `uv run python scripts/run_corpus.py --provider heuristic --limit 5 --report gap_report_sample.json`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add examples/**/*.lock tests/corpus/**/*.lock scripts/run_corpus.py tests/test_corpus_manifest.py
git commit -m "feat(corpus): add seed lockfiles and upgrade 2-axis gap attribution runner"
```

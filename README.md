# Memelang (`meme`)

**Memelang** (`meme`) is an experimental natural-language programming language and compiler pipeline. You write programs in structured or casual plain English (`.meme`), and the compiler uses a small local LLM (or optional cloud API / zero-dependency heuristic parser) to synthesize a **strictly-typed Intermediate Representation (IR)**, verify types & semantic unambiguity, lock the AST into **`build.lock`** for 100% deterministic rebuilds, and emit **Python 3**, **Rust**, **C++20**, **Go**, **C (C11)**, or **TypeScript (Node.js)**.

---

## Why Memelang

Memelang is the first "meme language": **modern English as a modular expressive language**. Designing software still takes someone who knows how to design software — that never changes. What changes is the ceremony: the job of a programming language has always been to make writing complex software as easy as possible, and Memelang takes that further than any mainstream language by letting you write the program in plain English. The compiler's LLM turns that non-deterministic input into determinism: a strictly-typed IR, a static verifier that halts on ambiguity instead of guessing, and a lockfile that makes every rebuild byte-identical.

---

## Architecture

```text
[English Source (.meme)]
        │
        ▼  (Cache miss only)
[Pluggable LLM Frontend] ──(JSON Schema Constrained, T=0.0)
        │
        ▼
[Deterministic Static Verifier & Ambiguity Detector]
        │
        ├──► (If ambiguous) Halt with numbered `--resolve` candidates
        ▼
[Deterministic Lockfile (build.lock)] ──(SHA-256 + Resolved IR + Canonical Meme)
        │
        ▼  (0ms LLM latency on rebuilds)
[Target Codegen: Python 3 | Rust | C++20 | Go | C11 | TypeScript]
```

---

## Quick Start

New to the language? Start with **[docs/WRITING_GUIDE.md](docs/WRITING_GUIDE.md)** — a practical guide to writing Memelang programs in both voices.

Requires Python 3.13+ and [`uv`](https://docs.astral.sh/uv/) (plus `rustc`, `g++`, `go`, `gcc`, or `tsc`/`node` if running native targets).

```bash
# Install with built-in local GGUF inference (`llama-cpp-python` + `huggingface-hub`):
uv sync --dev --extra local-gguf

# Download the default ~2 GB local 3B compiler model (`Qwen2.5-Coder-3B-Instruct` Q4_K_M):
uv run meme pull

# Run plain-English programs across Python 3, Rust, C++20, Go, C, and TypeScript:
uv run meme run examples/hello.meme --target rust
uv run meme run examples/calc.meme --target cpp
uv run meme run examples/random_sort_structured.meme --target python
uv run meme run examples/hello.meme --target go
uv run meme run examples/hello.meme --target c
uv run meme run examples/hello.meme --target ts
uv run meme run examples/hello.meme --target python -- arg1 arg2  # forwards argv after -- to program

# Compile standalone Go source (package main, func main):
uv run meme compile examples/hello.meme --target go -o hello.go
go build -o hello hello.go && ./hello

# Compile standalone C11 source and run:
uv run meme compile examples/hello.meme --target c -o hello.c
gcc -std=c11 -O2 hello.c -o hello -lm && ./hello

# Build standalone native binary via C11 backend:
uv run meme build examples/hello.meme -o hello
./hello

# Compile standalone TypeScript source and run:
uv run meme compile examples/hello.meme --target ts -o hello.ts
tsc hello.ts --outDir dist --target es2022 --module node16 && node dist/hello.js

# Compile & run multi-function JSON file processing:
uv run meme compile examples/find-largest.meme --target rust
printf "examples/numbers.json\n" | uv run meme run examples/find-largest.meme --target rust

# Run FizzBuzz compiled to native C++20:
uv run meme run examples/fizzbuzz.meme --target cpp

# Run multi-file module example with transitive lockfile verification:
uv run meme run examples/advanced/521_modules/main.meme --target go
```

### Handling Ambiguous English

Try compiling `examples/random_sort_ambiguous.meme`:

```meme
array = 10.random numbers

for each number in array
    sort from 1 to 10
```

```bash
uv run meme compile examples/random_sort_ambiguous.meme --target rust
```

Instead of silently guessing, `meme` flags the semantic collision (exit code `2`) and saves the candidate ASTs to `build.lock`:

```text
[Compiler Warning: Ambiguous Intent at Statement 2 (Line 3)]
  Did you mean:
    (1) Mutate `array` by sorting all elements in ascending order
        Canonical: sort array ascending
    (2) Clamp each item in `array` between bounds and sort ascending
        Canonical: clamp array between 1 and 10
                   sort array ascending
    (3) Generate random integers restricted to the specified range for `array` and sort ascending
        Canonical: define list array as 10 random integers between 1 and 10
                   sort array ascending

  Run with `--resolve 2=1` (or `--interactive`) to lock this choice into build.lock.
```

Lock your choice with zero extra LLM calls:

```bash
uv run meme compile examples/random_sort_ambiguous.meme --target rust --resolve 2=3
uv run meme explain examples/random_sort_ambiguous.meme
```

### Native Binaries: `meme build`

Compile a `.meme` program directly into a native binary via the C11 backend:

```bash
uv run meme build EX.meme -o out [--resolve ID=OPT ...] [--cc COMPILER] [--cflags "..."]
```

- **Usage:** Point `meme build` at any `.meme` file and provide the `-o/--output` binary destination.
- **Compiler Requirements:** Invokes a standard C compiler (`cc` by default, falling back to `gcc`). Override the compiler with `--cc <bin>` and compilation flags with `--cflags "..."` (default flags: `-std=c11 -O2`).
- **Frontend Provider Default:** Defaults to the built-in deterministic `heuristic` provider (zero-LLM by default). Override with `--provider <provider>` if needed.
- **Exit-Code Semantics:** Programs using `exit with code N` propagate the exit status directly to the operating system process exit code.
- **Zero-LLM Lockfile Contract:** Building an already locked program runs 100% deterministically offline with 0ms inference latency, honoring the exact same zero-LLM lockfile contract as `meme compile`.
- **Modules & Multi-File Linking:** Programs using `use <module>` (such as `examples/advanced/521_modules/`) compile into a single self-contained native binary with all dependencies linked.

### Test Runner: `meme test`

Execute test suites across `.meme` files with isolated process execution:

```bash
uv run meme test [PATH] [--target python|rust|cpp|go|c|ts]
```

- **Usage:** Point `meme test` at a directory (defaults to `tests/`) or specific `.meme` test file.
- **Frontend Provider Default:** Defaults to the built-in `heuristic` provider (zero-LLM by default); `--provider` still overrides. Lockfiles are treated as advisory: if a test file's lock hash does not match current source, it recompiles silently and prints `note: lock stale for <file>, recompiled` to stderr.
- **Cross-Target Parity:** Runs isolated test blocks (`test <name>: ...`) across any of the six backends.
- **Reporting:** Reports per-case `PASS` / `FAIL` status with source line attribution and exits 0 on all pass, 1 on failure.

---

## Beta Features (v0.2.0-beta)

- **Assertions (`assert`):** First-class runtime invariant assertions with status-1 termination and deterministic diagnostics.
- **Test Blocks (`test`) & Test Runner (`meme test`):** Isolated test blocks and a built-in cross-target test runner.
- **Native Binaries (`meme build`):** Direct-to-native binary compilation via the C11 backend with zero runtime dependencies.
- **Float Formatting & Conversions:** Deterministic float formatting with specified decimal precision (`format x with N decimals`), plus `float of <int>` for Int→Float conversion — money-in-cents programs can render dollars directly.
- **Character Code Conversions:** `number of <char>` (codepoint) and `character of <int>` round-trip single characters.
- **JSON Record Read/Write:** Strongly-typed record serialization and deserialization (`write r as json to file path`, `read json record R from file path or else nothing`).
- **System Clock & Environment Variables:** Built-in POSIX epoch seconds (`current epoch seconds`) and environment variable lookup (`environment variable name`).
- **Optional File Readers:** Null-safe file readers returning `Optional<T>` without panicking on missing files.
- **Error Output (`print error`):** First-class stderr printing with `print`-identical formatting — error diagnostics land on the right stream on all six targets.
- **Sets (`Set<T>`):** First-class generic sets with O(1) membership, idempotent addition, and deterministic sorted iteration.
- **Two-Dimensional Lists (`List<List<T>>`):** Generic nested lists supporting literals `[[1, 2], [3, 4]]`, indexing `g[i][j]`, and mutation `set g[i][j] to v`.
- **Uniform Iteration:** `for each` accepts any expression evaluating to a collection — record fields, call results, nested index expressions — with sorted deterministic order for maps and sets.
- **Mutual Recursion:** Functions can forward-reference functions defined later in the same module.
- **Parent-Relative Modules:** `use ../<module>` resolves modules in parent directories — test files import repo-root modules without symlinks.
- **Records Hold Collections:** Record fields of type `List<T>`, `Map<K, V>`, and `Set<T>` (including self-referential records through `List`) work across all six targets.

### Project Ecosystem (`projects/`)

Real programs built with Memelang, each its own repo linked as a submodule, each with a `meme test` suite green on all six targets:

| Project | What it is | Test cases |
|---|---|---|
| [projects/card-inventory](projects/card-inventory) | Trading-card inventory CLI (photo organizing, CSV) | 6-target parity |
| [projects/ledger](projects/ledger) | Banking ledger: accounts, transfers, JSON persistence, monthly statements | 36 × 6 targets |
| [projects/library-system](projects/library-system) | Library management: loans, holds queues, overdue fines | 27 × 6 targets |
| [projects/payroll](projects/payroll) | Payroll: marginal tax brackets, overtime, payslips | 58 × 6 targets |
| [projects/flight-reservation](projects/flight-reservation) | Seat-grid reservations, best-seat search, FIFO waitlists | 10 × 6 targets |
| [projects/spreadsheet-engine](projects/spreadsheet-engine) | Formula evaluation, topological re-eval, cycle detection | 42 × 6 targets |
| [projects/maze-solver](projects/maze-solver) | BFS shortest path + recursive DFS on 2D grids | 19 × 6 targets |
| [projects/huffman-compressor](projects/huffman-compressor) | Canonical Huffman file compression with exact round-trip | 34 × 6 targets |
| [projects/markdown-to-html](projects/markdown-to-html) | Markdown parser/renderer with inline markup and escaping | 31 × 6 targets |
| [projects/expense-splitter](projects/expense-splitter) | Shared expenses: equal/exact/shares splits, min-cash-flow settle | 28 × 6 targets |
| [projects/project-tracker](projects/project-tracker) | DAG tasks: topo order, critical path, cycle rejection | 29 × 6 targets |
| [projects/csv-analytics](projects/csv-analytics) | RFC-4180 CSV engine: joins, group-by, aggregations | 41 × 6 targets |

**335 test cases across 12 programs, 0 failures, every one green on all six targets.**

### Release Gate

```bash
# Full corpus + meme test across all six targets, one verdict line each:
uv run python scripts/run_corpus.py --all-targets
```

### CLI Commands

| Command | Description | Example |
|---|---|---|
| `meme run` | Synthesize/load lockfile, compile, and execute on target | `uv run meme run app.meme --target python` |
| `meme compile` | Compile program to target source code | `uv run meme compile app.meme --target rust -o app.rs` |
| `meme build` | Compile program to standalone native binary via C11 | `uv run meme build app.meme -o app` |
| `meme test` | Run test suites across `.meme` files on any target | `uv run meme test tests/meme --target go` |
| `meme check` | Static type checking and verification | `uv run meme check app.meme` |
| `meme explain` | Inspect canonical form and lock status | `uv run meme explain app.meme` |
| `meme pull` | Download recommended local compiler model | `uv run meme pull` |


---

## Local & Cloud LLM Providers (`--provider`)

For `meme compile`, `meme run`, `meme check`, and `meme explain`, the default is `--provider auto`: `meme` checks `MEME_PROVIDER`, auto-discovers any cached GGUF model in `~/.cache/memelang/models/` (or `MEME_MODEL_DIR`), probes local Ollama (`http://127.0.0.1:11434`), and falls back cleanly to the built-in zero-dependency `heuristic` frontend.

For `meme build` and `meme test`, the default is `heuristic` (zero-LLM by default). `--provider` can still be specified explicitly to override in both commands.

* **Zero-Config In-Process GGUF (Recommended — ~2 GB VRAM / CPU):**
  ```bash
  uv sync --extra local-gguf
  uv run meme pull
  uv run meme run examples/calc.meme --target rust
  # Or pass a custom GGUF path explicitly:
  uv run meme compile app.meme --provider llama-cpp:/path/to/model.gguf --target python
  ```
* **Local Ollama:**
  ```bash
  ollama pull qwen2.5-coder:3b
  uv run meme run examples/fizzbuzz.meme --provider ollama:qwen2.5-coder:3b --target rust
  ```
* **OpenAI-Compatible Local Server (`llama-server`, LM Studio, vLLM):**
  ```bash
  OPENAI_BASE_URL=http://127.0.0.1:8080/v1 uv run meme compile app.meme --provider openai-local:qwen2.5-coder-3b --target cpp
  ```
* **Cloud Fallback (Google Gemini API):**
  ```bash
  uv sync --extra gemini
  GEMINI_API_KEY=... uv run meme compile app.meme --provider gemini:gemini-2.5-flash --target rust
  ```

---

## Extensibility: Three Axes

Memelang is designed to evolve along **three distinct axes**:

1. **`examples/` Axis (Syntax & Idiom Extensibility):**
   `.meme` files in `examples/` (including shipped foundational examples and the pre-installed CS 101–103 standard library under `examples/cs101/`, `examples/cs102/`, `examples/cs103/`) act as the language's living syntax and idiom bank ("Memelang is as smart as you make it"). Adding new idiomatic patterns or reference programs here teaches the language new phrasing conventions and capabilities so real programs can be written and learned from.
2. **`src/` Language Axis (IR & Output Target Extensibility):**
   The typed Intermediate Representation (`src/memelang/ir/`), static verifier (`src/memelang/analyzer/`), and codegen backends (`src/memelang/codegen/`) define core computational primitives and target languages (`python`, `rust`, `cpp`, `go`, `c`, `ts`). Ships with six runtime targets.
3. **Compiler LLM Axis (Frontend Extensibility):**
   The compiler's own intelligence is an extension point. Every frontend implements the same `LLMProvider` protocol (`auto`, `ollama`, `openai-local`, `llama-cpp`, `gemini`, `heuristic`), and because synthesis output is JSON-schema-constrained to `SynthesisResult`, a stronger or smarter model can be dropped in without touching the verifier, lockfile, or any codegen backend. Long-term (the golang model of a self-extending toolchain), the goal is a compiler that is extendable **at runtime** — the language growing its own capabilities through its LLM frontend.

The `.meme` files under `tests/corpus/` are the benchmark harness's test suite (containing clean, typo-injected, and deliberately ambiguous stress scripts) and are mirrored into `examples/cs101..103/`, where verified `.meme.lock` files turn curated scripts into live few-shot demonstrations for the retriever.

To benchmark compiler robustness across university Computer Science curricula, Memelang includes an unfiltered **300-script stress corpus** mirroring the curriculum (`tests/corpus/` and `examples/` covering CS 101, CS 102, and CS 103):

```bash
# Smoke test a slice of CS 101 programs using the fast built-in heuristic provider:
uv run python scripts/run_corpus.py --course cs101 --limit 10

# Run evaluation with the local compiler model and generate a 2-axis gap attribution report:
uv run python scripts/run_corpus.py --report gap_report.json

# Filter by course, style, or specific script IDs:
uv run python scripts/run_corpus.py --course cs102 --style clean --ids 101-125
```

The runner attributes non-passing scripts into ranked **Axis 1 (`examples/`)** vs **Axis 2 (`src/`)** gaps, identifying exactly which new reference examples or IR operations will unlock the most student programs.


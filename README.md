# Memelang (`meme`)

**Memelang** (`meme`) is an experimental natural-language programming language and compiler pipeline, currently at **v0.3.0-beta.2**. You write programs in plain English (`.meme`), and the compiler parses that English into a **strictly-typed Intermediate Representation (IR)**, statically verifies types & semantic unambiguity, locks the result into **`build.lock`** for 100% deterministic rebuilds, and emits **Python 3**, **Rust**, **C++20**, **Go**, **C (C11)**, or **TypeScript (Node.js)**.

---

## Why Memelang

Memelang is the first "meme language": **modern English as a modular expressive language**. Designing software still takes someone who knows how to design software — that never changes. What changes is the ceremony: the job of a programming language has always been to make writing complex software as easy as possible, and Memelang takes that further than any mainstream language by letting you write the program in plain English. The compiler's job is to turn that non-deterministic input into determinism: a strictly-typed IR, a static verifier that halts on ambiguity instead of guessing, and a lockfile that makes every rebuild byte-identical.

### What makes it different

1. **The deterministic heuristic parser is the single source of truth.** Every language construct parses offline with the zero-dependency `heuristic` provider — no model download, no API key, no network. LLM frontends (local GGUF, Ollama, OpenAI-compatible servers, Gemini) are an optional *dictation layer* on top for looser conversational source, never a requirement. Every feature must parse offline or it doesn't ship.
2. **The verifier halts on ambiguity instead of guessing.** If an English sentence has two readings, the compiler exits with code `2`, prints numbered candidate interpretations, and locks nothing. You resolve once with `--resolve ID=OPT`; the choice is then locked forever.
3. **SHA-256 lockfiles make rebuilds zero-LLM and byte-identical.** `build.lock` records the source hash plus the fully-resolved IR plus the **Canonical Structured English** decompilation of your program. Rebuilds read the lockfile — 0ms inference latency, fully offline — so the same source always produces the same output, even if it was originally dictated to an LLM.
4. **Six targets, one behavior.** The same program emits to Python 3, Rust, C++20, Go, C11, and TypeScript with **byte-identical stdout across all six targets** — sorted map iteration, deterministic float formatting, identical exit-code semantics, identical error text.

---

## Architecture

```text
[English Source (.meme)]
        │
        ▼
[Deterministic Heuristic Parser]  ←── optional: LLM dictation frontend
   (zero-LLM, offline)                 (JSON-schema constrained, T=0.0)
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

New to the language? Start with **[docs/WRITING_GUIDE.md](docs/WRITING_GUIDE.md)** — a practical guide to writing Memelang programs in both voices. There is also a **[Tutorial](docs/TUTORIAL.md)** (build your first real app with modules and file I/O) and a **[Cookbook](docs/COOKBOOK.md)** (copy-paste recipes).

Requires Python 3.13+ and [`uv`](https://docs.astral.sh/uv/) (plus `rustc`, `g++`, `go`, `gcc`, or `tsc`/`node` if running native targets). Core dependencies are just `pydantic` and `httpx` — nothing else to download for offline use.

```bash
uv sync  # core install — zero-LLM, zero-model

# Compile & run fully offline with the heuristic parser:
uv run meme run examples/fizzbuzz.meme --provider heuristic --target python
uv run meme compile examples/hello.meme --provider heuristic --target rust -o hello.rs
rustc -O hello.rs -o hello && ./hello

# Native binary via the C11 backend (`meme build` defaults to the heuristic provider):
uv run meme build examples/fizzbuzz.meme -o fizzbuzz
./fizzbuzz

# Cross-target parity, by hand — same program, same stdout on every backend:
uv run meme compile examples/fizzbuzz.meme --provider heuristic --target cpp -o fizzbuzz.cpp
g++ -std=c++20 -O2 fizzbuzz.cpp -o fizzbuzz_cpp && ./fizzbuzz_cpp

# Run .meme test suites across targets:
uv run meme test tests/meme --target go

# Forward program arguments after --:
uv run meme run examples/hello.meme --target python -- arg1 arg2
```

### Two Voices

Memelang accepts two dialects, both compiling to the same IR:

- **Canonical Structured English** — typed, colon-terminated blocks (`function name(param: Type) -> RetType:`). Works fully offline with the `heuristic` parser.
- **Conversational Memelang** — looser English with `this runs in the shell` / `define function ... with ...` layout. Requires an LLM provider (local GGUF, Ollama, or Gemini — see [Providers](#local--cloud-llm-providers---provider)).

You can mix them in one file. See the writing guide for the full surface.

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

## Six Targets, One Program

Every program compiles to all six backends, and the guarantee is behavioral, not aspirational: **byte-identical stdout across all six targets**, enforced by the release gate on every run. That includes sorted deterministic map/set iteration, half-away-from-zero float rounding (`format x with N decimals`), identical exit-code truncation semantics, and identical error text for runtime failures.

| Flag | Target | Notes |
|---|---|---|
| `--target python` | Python 3 | reference backend |
| `--target rust` | Rust | standalone `rustc`-compilable source |
| `--target cpp` | C++20 | `g++ -std=c++20` |
| `--target go` | Go | `package main` / `func main` |
| `--target c` | C11 | `gcc -std=c11 -O2`, optional `-lm` |
| `--target ts` | TypeScript (Node.js) | `tsc --target es2022 --module node16` |

---

## The Examples Corpus

The `examples/` tree is the language's living idiom bank: **544 `.meme` programs, 237 of them with committed `.meme.lock` build artifacts** (zero-LLM rebuilds, verifiable freshness via `meme explain`).

Behind it sits a **491-script six-course stress corpus** (`tests/corpus/`, mirrored into `examples/cs101..cs106`), each script in three styles — clean, typo-injected, and deliberately ambiguous:

| Course | Scripts | Coverage |
|---|---|---|
| CS 101 | 100 | conditionals, I/O & math, lists, loops |
| CS 102 | 100 | classes & state, files & JSON, recursion & strings, search & sort |
| CS 103 | 100 | stacks & queues, maps & sets, trees, graphs & DP |
| CS 104 | 70 | text & log parsing |
| CS 105 | 60 | validation & checksums (Luhn, card prefixes) |
| CS 106 | 61 | small reusable libraries (statistics) |

Plus **32 advanced module examples** (`examples/advanced/`, ids 501–537) exercising `use` modules, records, and JSON persistence across components, and root demos including `examples/524_build/` for `meme build`.

Verified `.meme.lock` files double as live few-shot demonstrations for the LLM retriever, and the corpus runner attributes non-passing scripts into ranked **Axis 1 (`examples/`)** vs **Axis 2 (`src/`)** gaps — identifying exactly which new reference examples or IR operations unlock the most student programs:

```bash
# Smoke test a slice of CS 101 using the fast built-in heuristic provider:
uv run python scripts/run_corpus.py --course cs101 --limit 10

# Filter by course, style, or specific script IDs:
uv run python scripts/run_corpus.py --course cs102 --style clean --ids 101-125
```

---

## Project Ecosystem (`projects/`)

Real programs built with Memelang, each its own repo linked as a git submodule, each with a `meme test` suite green on all six targets:

| Project | What it is | Test cases |
|---|---|---|
| [projects/card-inventory](projects/card-inventory) | Trading-card inventory CLI (photo organizing, CSV) | shell parity harness |
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
| [projects/meme-tokenizer](projects/meme-tokenizer) | .meme source tokenizer — self-hosting step 1, tokenizes its own source | 23 × 6 targets |
| [projects/meme-canonical-checker](projects/meme-canonical-checker) | Lockfile freshness checker (FRESH / CANONICAL TOKENS / STALE) — self-hosting step 2 | 22 × 6 targets |
| [projects/meme-canonical-fixer](projects/meme-canonical-fixer) | Lexical layout canonicalizer (`fix` / `preview`) — self-hosting step 3 | 20 × 6 targets |
| [projects/meme-lock-check](projects/meme-lock-check) | Exact lockfile freshness (LOCKED-FRESH / DRIFTED) via sha256 — self-hosting step 4 | 20 × 6 targets |
| [projects/meme-parser](projects/meme-parser) | Recursive-descent parser + canonical emitter — self-hosting steps 5 & 6, parses and re-emits its own source | 47 × 6 targets |

**487 `meme test` cases across the 16 test-suite projects — plus card-inventory's shell-based parity/acceptance harnesses — all green on all six targets.**

---

## The Self-Hosting Ladder

Instead of a big-bang rewrite, the compiler grows out of Python one component at a time — each rung a working, shipped Memelang program (see [docs/roadmap.md](docs/roadmap.md)). The language itself closed its known limits on 2026-11-24 (recursive `Optional` records, JSON record I/O with collections & nested records): nothing in the language needs a workaround.

| Rung | Component | Proof |
|---|---|---|
| 1 | **Tokenizer** — [projects/meme-tokenizer](projects/meme-tokenizer) | 23 × 6 green; tokenizes its own source |
| 2 | **Canonical-form checker** — [projects/meme-canonical-checker](projects/meme-canonical-checker) | 22 × 6 green; reads real lockfiles |
| 3 | **Canonical fixer** — [projects/meme-canonical-fixer](projects/meme-canonical-fixer) | 20 × 6 green; `fix`/`preview` with a round-trip invariant |
| 4 | **Lockfile freshness checker** — [projects/meme-lock-check](projects/meme-lock-check) | 20 × 6 green; all 39 real locks report `LOCKED-FRESH` |
| 5 | **Parser** — [projects/meme-parser](projects/meme-parser) | precedence-climbing expression grammar; parses its own source |
| 6 | **Canonical emitter** — meme-parser `emit` | 47 × 6 green; `parse(emit(parse(x))) == parse(x)` + idempotence, byte-identical output on all six targets |
| 7 | **Unified pipeline CLI** — [projects/meme-tools](projects/meme-tools) | 24 × 6 green; `parse` / `emit` / `check` / `hash` in one zero-dependency binary; `LOCKED-FRESH` / `LEXICAL-FRESH` / `DRIFTED` verdicts, hash verified against an independent oracle |

The **lexer → parser → emitter chain is now fully Memelang**, and v0.3.0-beta.2 ships it as a tool. Next rungs: copy-on-write list codegen (clearing the deep-clone perf debt), a canonical re-emitter from IR, then single-binary compiler distribution — the end state is a compiler shippable as a single native file, with the Python core reduced to the optional (swappable) LLM-dictation frontend.

---

## Releases

### v0.3.0-beta.2 (2026-11-25)

- **Language: known limits closed.** Recursive records via `Optional<Record>` (heap indirection per target: `Option<Box<T>>` on rust, pointers on cpp/c — surface syntax identical everywhere) and JSON record I/O with collection fields (`List<T>`, `Set<T>`, `Map<K,V>`, including record-valued maps), nested record fields, and `Optional` of either. All-or-nothing reads, deterministic sorted ordering, byte-identical across targets.
- **New builtin: `sha256 of <text>`** — lowercase hex digest, UTF-8 bytes hashed uniformly, byte-identical on all six targets (stdlib on python/go/ts, self-contained on rust/cpp/c).
- **Self-hosting ladder, 7 rungs shipped** (see the table above) — 113 new test cases, every component byte-parity across six targets, composed into the `meme-tools` pipeline binary that ships with this release.
- **Compiler fixes surfaced by the ladder**: Go record `_meme_less` used `!=` on slice-containing structs (compile error for recursive records) — now `reflect.DeepEqual`; test harness compiled rust/cpp without optimization — now rust `-O` / cpp `-O2`, matching the documented hand-compile contract.
- **Toolchain health**: 940 tests green, release gate 230 programs × 6 targets, 0 failures. 18 projects in the ecosystem.

---

## Release Gate

```bash
# Full test suite (~940 tests):
uv run pytest -q

# Full corpus + meme test across all six targets, one verdict line each:
uv run python scripts/run_corpus.py --all-targets
```

The all-targets gate evaluates **230 locked programs across 6 targets plus `meme test`** — every six-target program in the corpus manifests.

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
   `.meme` files in `examples/` (the six-course corpus under `examples/cs101..cs106/`, the advanced module examples under `examples/advanced/`, and the shipped foundational demos) act as the language's living syntax and idiom bank ("Memelang is as smart as you make it"). Adding new idiomatic patterns or reference programs here teaches the language new phrasing conventions and capabilities so real programs can be written and learned from.
2. **`src/` Language Axis (IR & Output Target Extensibility):**
   The typed Intermediate Representation (`src/memelang/ir/`), static verifier (`src/memelang/analyzer/`), and codegen backends (`src/memelang/codegen/`) define core computational primitives and target languages (`python`, `rust`, `cpp`, `go`, `c`, `ts`). Ships with six runtime targets.
3. **Compiler LLM Axis (Frontend Extensibility):**
   The compiler's own intelligence is an extension point. Every frontend implements the same `LLMProvider` protocol (`auto`, `ollama`, `openai-local`, `llama-cpp`, `gemini`, `heuristic`), and because synthesis output is JSON-schema-constrained to `SynthesisResult`, a stronger or smarter model can be dropped in without touching the verifier, lockfile, or any codegen backend. Long-term (the golang model of a self-extending toolchain), the goal is a compiler that is extendable **at runtime** — the language growing its own capabilities through its LLM frontend.

The `.meme` files under `tests/corpus/` are the benchmark harness's test suite (containing clean, typo-injected, and deliberately ambiguous stress scripts) and are mirrored into `examples/cs101..cs106/`.

To benchmark compiler robustness across the six-course curriculum, run the corpus through the 2-axis gap-attribution reporter:

```bash
# Run evaluation with the local compiler model and generate a 2-axis gap attribution report:
uv run python scripts/run_corpus.py --report gap_report.json
```

The runner attributes non-passing scripts into ranked **Axis 1 (`examples/`)** vs **Axis 2 (`src/`)** gaps, identifying exactly which new reference examples or IR operations will unlock the most student programs.

---

## Language Surface (v0.3.0-beta.2)

- **Assertions (`assert`):** First-class runtime invariant assertions with status-1 termination and deterministic diagnostics.
- **Test Blocks (`test`) & Test Runner (`meme test`):** Isolated test blocks and a built-in cross-target test runner.
- **Native Binaries (`meme build`):** Direct-to-native binary compilation via the C11 backend with zero runtime dependencies.
- **Float Formatting & Conversions:** Deterministic float formatting with specified decimal precision (`format x with N decimals`), plus `float of <int>` for Int→Float conversion — money-in-cents programs can render dollars directly.
- **Character Code Conversions:** `number of <char>` (codepoint) and `character of <int>` round-trip single characters.
- **SHA-256:** `sha256 of <text>` — byte-identical lowercase hex digests on all six targets.
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
- **Recursive Records (`Optional<T>` self-reference):** Records can reference themselves through `Optional<T>` fields (`record Node: parent: Optional<Node>`) — indirection is handled per-target (`Option<Box<T>>` on rust, pointers on cpp/c), user code stays identical across all six targets.
- **JSON Records with Collections & Nested Records:** `write ... as json` / `read json record ...` serialize record fields of type `List<T>`, `Set<T>`, `Map<K, V>` (including record-valued maps), nested record fields, and `Optional` of either — all-or-nothing reads, deterministic sorted ordering, byte-identical output on all six targets.

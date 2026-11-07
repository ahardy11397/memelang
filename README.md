# Memelang (`meme`)

**Memelang** (`meme`) is an experimental natural-language programming language and compiler pipeline. You write programs in structured or casual plain English (`.meme`), and the compiler uses a small local LLM (or optional cloud API / zero-dependency heuristic parser) to synthesize a **strictly-typed Intermediate Representation (IR)**, verify types & semantic unambiguity, lock the AST into **`build.lock`** for 100% deterministic rebuilds, and emit **Python 3**, **Rust**, or **C++20**.

---

## Why Memelang

Memelang is the first "meme language": **modular English as a modern expression language**. Designing software still takes someone who knows how to design software — that never changes. What changes is the ceremony: the job of a programming language has always been to make writing complex software as easy as possible, and Memelang takes that further than any mainstream language by letting you write the program in plain English. The compiler's LLM turns that non-deterministic input into determinism: a strictly-typed IR, a static verifier that halts on ambiguity instead of guessing, and a lockfile that makes every rebuild byte-identical.

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
[Target Codegen: Python 3 | Standalone Rust | C++20]
```

---

## Quick Start

New to the language? Start with **[docs/WRITING_GUIDE.md](docs/WRITING_GUIDE.md)** — a practical guide to writing Memelang programs in both voices.

Requires Python 3.13+ and [`uv`](https://docs.astral.sh/uv/) (plus `rustc` and `g++` if running Rust/C++ targets).

```bash
# Install with built-in local GGUF inference (`llama-cpp-python` + `huggingface-hub`):
uv sync --dev --extra local-gguf

# Download the default ~2 GB local 3B compiler model (`Qwen2.5-Coder-3B-Instruct` Q4_K_M):
uv run meme pull

# Run plain-English programs across Python 3, Rust, and C++20:
uv run meme run examples/hello.meme --target rust
uv run meme run examples/calc.meme --target cpp
uv run meme run examples/random_sort_structured.meme --target python

# Compile & run multi-function JSON file processing:
uv run meme compile examples/find-largest.meme --target rust
printf "examples/numbers.json\n" | uv run meme run examples/find-largest.meme --target rust

# Run FizzBuzz compiled to native C++20:
uv run meme run examples/fizzbuzz.meme --target cpp
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

---

## Local & Cloud LLM Providers (`--provider`)

By default (`--provider auto`), `meme` checks `MEME_PROVIDER`, auto-discovers any cached GGUF model in `~/.cache/memelang/models/` (or `MEME_MODEL_DIR`), probes local Ollama (`http://127.0.0.1:11434`), and falls back cleanly to the built-in zero-dependency `heuristic` frontend.

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
   The typed Intermediate Representation (`src/memelang/ir/`), static verifier (`src/memelang/analyzer/`), and codegen backends (`src/memelang/codegen/`) define core computational primitives and target languages (`python`, `rust`, `cpp`). Ship today with three runtime languages; more targets are on the roadmap.
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


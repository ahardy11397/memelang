# Memelang (`meme`)

**Memelang** (`meme`) is an experimental natural-language programming language and compiler pipeline. You write programs in structured or casual plain English (`.meme`), and the compiler uses a small local LLM (or optional cloud API / zero-dependency heuristic parser) to synthesize a **strictly-typed Intermediate Representation (IR)**, verify types & semantic unambiguity, lock the AST into **`build.lock`** for 100% deterministic rebuilds, and emit **Python 3**, **Rust**, or **C++20**.

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

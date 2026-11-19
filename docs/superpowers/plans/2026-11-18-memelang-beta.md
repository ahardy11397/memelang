# Memelang Beta Implementation Plan (Batches 1–3 + 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Memelang the language features a fresh-CS-grad backend program needs (tests, JSON, clock/env, sets, 2D lists, float formatting) plus a one-command release gate for v0.2.0-beta.

**Architecture:** Every feature follows the repo's 7-artifact rule: IR schema node → verifier rules → canonical decompiler → all six codegens (python, rust, cpp, go, c, ts) → cross-target parity tests → parser/prompt rules → docs + locked example. The deterministic heuristic parser is the single source of truth; every construct must parse offline.

**Tech Stack:** Python 3.13+/uv, Pydantic-strict IR, pytest. No new runtime dependencies.

**Spec:** docs/superpowers/specs/2026-11-18-memelang-beta-design.md (read together with this plan; the spec carries the user-locked decisions).

## Global Constraints

- All six targets byte-identical stdout on parity tests (hard gate, every task).
- Zero-LLM lockfile contract: locked files never trigger synthesis; lock source keys are CWD-relative — re-lock from repo root only.
- Error channel is `Optional<T>` — no Result, no try/catch (user-locked, Phase 2B).
- Existing examples must not change output or lockfiles.
- `uv run pytest -q` fully green after EVERY task.
- No LLM-provider code changes; features are heuristic-parseable.
- Delegated runs (agy): NO commits — coordinator verifies then commits. Steps below show the commit gate the coordinator applies.
- C target hand-compile contract: `cc -std=c11 -O2`.

## Review Focus

Inputs the spec implies but feature-happy tests may miss — each line is pinned by a test in the owning task:

1. **Float formatting rounding ties** (e.g. 2.345 with 2 decimals; negative halves) — one shared half-up rule, byte-identical in all six targets. Pinned in Task 4.
2. **JSON float serialization** (e.g. 10.5, 10.0, 1e9) — same formatting rule as Task 4 inside JSON output, not native repr. Pinned in Task 6.
3. **Set iteration order across targets** (insertion order ≠ sorted order; mixed-case strings) — sorted, bytewise. Pinned in Task 9.
4. **2D list jagged rows and out-of-range `[i][j]`** — clean error, same message shape everywhere. Pinned in Task 10.
5. **Test-block lockfile stability** — a test file's lock must hash test blocks (renaming a block changes the lock; reordering does not). Pinned in Task 2.
6. **Malformed JSON / type mismatch in new readers** — Optional nothing, never a traceback, never an exit. Pinned in Task 5.

---

### Task 1: `assert` statement

**Files:**
- Modify: `src/memelang/ir/schema.py` (add `AssertStmt`), `src/memelang/analyzer/verifier.py`, `src/memelang/ir/canonical.py`, all six `src/memelang/codegen/*_gen.py`, parser rules module, prompt rules
- Test: `tests/test_parity_assert.py`
- Create: `examples/advanced/525_assert_statement.meme` (+ lock, from repo root)

**Interfaces:**
- Produces: `AssertStmt` IR node (`op="assert_stmt"`, `condition: Expr`). Surface: `assert <condition>` — statement; failure prints `ASSERT FAILED line <n>: <source text of condition>` to stderr and exits 1. Exit-code path is identical to `exit with code 1`.

- [ ] **Step 1: Write failing parity test** — example asserts `1 is 1` then `2 > 3` on line 2 of a fixture; test runs python+rust+cpp+go+c+ts binaries, expects all exit 1 with stderr exactly `ASSERT FAILED line 2: 2 > 3`.
- [ ] **Step 2: Run** `uv run pytest tests/test_parity_assert.py -v` — expected FAIL (parse error).
- [ ] **Step 3: Implement** schema node, heuristic parse of `assert <cond>`, verifier (condition must be Bool), decompiler, 6 codegens.
- [ ] **Step 4: pytest green + spot-check** — `uv run pytest -q` all green; compile fixture to all 6 targets, diff stderr byte-for-byte.
- [ ] **Step 5: Lock example from repo root; commit** `feat(language): assert statement with cross-target failure reporting`.

### Task 2: `test <name>:` blocks in the IR

**Files:**
- Modify: schema.py (`TestBlockStmt`), verifier, canonical.py, all 6 codegens, parser/prompt rules
- Test: `tests/test_test_blocks_ir.py`
- Create: `examples/fixtures/test_block_demo.meme` (fixture, not a locked example)

**Interfaces:**
- Produces: `TestBlockStmt` (`op="test_block_stmt"`, `name: str`, `body: list[Stmt]`). Surface: top-level `test <name>:` block, name = `[a-z_][a-z0-9_]*`. Semantics: `meme run`/plain execution runs top-level code and SKIPS test blocks; compiled output exposes a dispatch hook: running the binary with argv[1] `--meme-test <name>` runs only that block. Test blocks are IR nodes: they appear in canonical decompiler output and in lockfile hashing (rename changes hash, reorder does not — hash is keyed by name). Verifier: `exit with code` inside a test block is a static error (use `assert`).

- [ ] **Step 1: Failing tests** — (a) decompiler round-trips a file with 2 blocks; (b) lock hash changes on rename, not on reorder; (c) plain compiled run skips blocks; (d) dispatch arg runs one block; (e) `exit with code` in a block fails the verifier with a clear message.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** schema/verifier/decompiler/codegens — codegens emit blocks into the dispatch table, not the main path.
- [ ] **Step 4: pytest green + 6-target spot-check of (c)+(d).**
- [ ] **Step 5: Commit** `feat(language): test blocks as IR nodes with dispatch hook`.

### Task 3: `meme test` runner

**Files:**
- Modify: `src/memelang/cli.py` (new `test` subcommand), `src/memelang/runner/executor.py` (block-dispatch helper)
- Test: `tests/test_cli_meme_test.py`
- Create: `tests/meme/` directory convention: `tests/meme/*.meme` test files (use `use`-able fixtures), plus `.gitignore` entry if the runner stages artifacts

**Interfaces:**
- Produces: `meme test [DIR] [--target T]`. Default DIR = `tests/meme/`. For each `*.meme` file: compile once (heuristic provider, honoring its lockfile), then run each test block as its own process via the Task 2 dispatch hook. Print per case: `PASS <file>::<name>` or `FAIL <file>::<name> (line n)`; final line `Ran N cases, M failed`; exit 1 if M > 0. `--target` runs the suite on one non-python target (default python).

- [ ] **Step 1: Failing tests** — 2 fixture files / 4 cases with one failing assert: expect exact stdout ordering, exit 1, and `FAIL` line containing the failing line number. Include one file with zero blocks (counts as 0 cases, file passes).
- [ ] **Step 2: Run, expect FAIL** (no `test` subcommand).
- [ ] **Step 3: Implement** the subcommand + executor dispatch.
- [ ] **Step 4: pytest green; manual `uv run meme test` prints the full report.**
- [ ] **Step 5: Commit** `feat(cli): meme test runner with per-case reporting`.

### Task 4: Float formatting

**Files:**
- Modify: schema.py (`FormatFloatExpr`), verifier, canonical.py, 6 codegens, parser/prompt rules
- Test: `tests/test_parity_float_format.py`
- Create: `examples/advanced/526_float_formatting.meme` (+ lock)

**Interfaces:**
- Produces: `format <float-expr> with <int-expr> decimals` → `String`. One shared rule for all targets: round half away from zero (half-up on magnitude), fixed N digits, no exponent, `-0.00` normalized to `0.00`. N range 0–10 (verifier static-bounds on literal N; non-literal N = verifier error).

- [ ] **Step 1: Failing parity test** — values: `2.345→2 decimals`, `2.5→0`, `-2.5→0`, `0.005→2`, `10.0→2` (`10.00`), `1e9→0`; all 6 targets byte-identical stdout.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — C/Go/TS lack fixed formatting: implement round-then-place-value-digits manually (integer + fractional digit extraction), do NOT use printf `%.Nf` on C (differs from Rust's rounding) — one algorithm, six transcriptions.
- [ ] **Step 4: pytest green + 6-target diff.**
- [ ] **Step 5: Commit** `feat(language): fixed-decimal float formatting, one rounding rule, six targets`.

### Task 5: JSON record readers (Optional failure semantics)

**Files:**
- Modify: schema.py (`ReadJsonRecordExpr`, `ReadJsonRecordsExpr`), verifier, canonical.py, 6 codegens, parser/prompt rules
- Test: `tests/test_parity_json_records.py`
- Create: `examples/advanced/527_json_records.meme` (+ lock)

**Interfaces:**
- Produces:
  - `read json record <RecordName> from file <path> or else nothing` → `Optional<RecordName>`
  - `read json records <RecordName> from file <path> or else nothing` → `Optional<List<RecordName>>` (JSON array of objects)
  - Both also accept `or else <fallback-expr>`.
- Failure contract (user-locked Optional channel): malformed JSON, missing required field, wrong field type, JSON null in a non-Optional field, non-object element → `nothing`. Unknown/extra JSON fields are IGNORED. Field matching is by exact record field name. Nested records and maps-of-records NOT supported in beta (verifier error if a record field is a record/List/Map type — flat records + containers of records only).

- [ ] **Step 1: Failing parity test** — happy path record + list-of-records round-trip; five failure fixtures (malformed, missing field, wrong type, null, array-of-scalars) each yielding `nothing` then printing `is nothing` — identical stdout, exit 0, all 6 targets.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — per-target JSON parsing is native (python json, serde-less Rust: hand-rolled minimal object parser or ordered field extraction; C: extend the existing JSON-list reader; keep one shared field-extraction contract). Optional wrap on any failure.
- [ ] **Step 4: pytest green + 6-target diff.**
- [ ] **Step 5: Commit** `feat(language): JSON record readers with Optional failure semantics`.

### Task 6: JSON record writers

**Files:**
- Modify: schema.py (`WriteJsonStmt`), verifier, canonical.py, 6 codegens, parser/prompt rules
- Test: `tests/test_parity_json_write.py`
- Create: `examples/advanced/528_json_roundtrip.meme` (+ lock)

**Interfaces:**
- Produces: `write <record-expr> as json to file <path>` and `write <list-expr> as json to file <path>` (List<Record>). Output: compact single-line JSON, fields in record-definition order (NOT sorted — record fields are ordered, unlike map keys). Floats serialize via the Task 4 rule (`10.0` → `10.0`, never `1e1`). Path write failure behaves like `write file` today (exit 1).

- [ ] **Step 1: Failing parity test** — round-trip Task 5's happy path: write, read back, assert equality, print canonical form; then direct file-content comparison across all 6 target outputs (byte-identical JSON).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** (float serialization via shared rule — Review Focus 2).
- [ ] **Step 4: pytest green + byte-diff the JSON files across targets.**
- [ ] **Step 5: Commit** `feat(language): JSON record writers, ordered fields, shared float rule`.

### Task 7: Clock + environment variables

**Files:**
- Modify: schema.py (`CurrentEpochExpr`, `EnvVarExpr`), verifier, canonical.py, 6 codegens, parser/prompt rules
- Test: `tests/test_parity_clock_env.py`
- Create: `examples/advanced/529_clock_and_env.meme` (+ lock, no exact-clock assertions)

**Interfaces:**
- Produces:
  - `current epoch seconds` → `Int` (wall clock, UTC).
  - `environment variable "<NAME>"` → `Optional<String>` (unset → nothing).
  - `environment variable "<NAME>" or else <fallback>` → `String`.
- Parity note: targets without stdlib epoch helpers (C) use `time(NULL)`. Tests must not assert exact values — they assert type behavior: epoch is positive and monotone-ish (two reads, second ≥ first), env fallback string round-trips, unset var → `is nothing` prints true.

- [ ] **Step 1: Failing parity test** per above (clock assertions are relational, not absolute).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: pytest green + 6-target run (stdout may differ only in the epoch digits — the test asserts relational properties, and the coordinator spot-checks manually).**
- [ ] **Step 5: Commit** `feat(language): current epoch seconds + environment variables (Optional)`.

### Task 8: Optional file readers

**Files:**
- Modify: schema.py (`or else` variants of `read_file_string`, `read_file_lines`, existing `read json list`), verifier, canonical.py, 6 codegens, parser/prompt rules
- Test: `tests/test_parity_optional_io.py`
- Create: `examples/advanced/530_optional_file_io.meme` (+ lock)

**Interfaces:**
- Produces: `read string from file <path> or else nothing` → `Optional<String>`; `read lines from file <path> or else nothing` → `Optional<List<String>>`; same for `or else <fallback>`. Missing file / permission error → nothing. Malformed JSON in the json-list reader → nothing (aligns with Task 5 contract).

- [ ] **Step 1: Failing parity test** — missing file → `is nothing` true; existing file → value + `is nothing` false; fallback variant returns the fallback. 6 targets.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** (mirror the Task 5 Optional wrapping; do not change the hard-fail legacy forms).
- [ ] **Step 4: pytest green + diff.**
- [ ] **Step 5: Commit** `feat(language): Optional file readers (or else nothing / fallback)`.

### Task 9: Sets

**Files:**
- Modify: schema.py (`SetType`, `EmptySetExpr`, `SetAddStmt`, `SetContainsExpr`, `SetLengthExpr`, `SetRemoveStmt`), verifier, canonical.py, 6 codegens, parser/prompt rules
- Test: `tests/test_parity_sets.py`
- Create: `examples/advanced/531_sets.meme` (+ lock)

**Interfaces:**
- Produces: first-class `Set<T>` (T = scalar or record type — same universe as `Map` values). Surface: `define s as empty set of String` / `Set<Int>`; `add <v> to <set>` (statement; idempotent); `remove <v> from <set>` (statement); `<set> contains <v>` → Bool; `length of <set>` → Int; iteration `for each v in s:` yields elements in sorted order (bytewise for String, numeric for Int/Float — same comparator family as map keys). C target: sorted array-backed set (same pattern as its sorted maps).

- [ ] **Step 1: Failing parity test** — add 5 strings in non-sorted order incl. duplicates, iterate and print: sorted, deduped, all 6 targets identical. Contains/remove/length cases. Set of records (contains by record equality).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: pytest green + diff.**
- [ ] **Step 5: Commit** `feat(language): first-class Set<T> with sorted deterministic iteration`.

### Task 10: 2D lists (`List<List<T>>`)

**Files:**
- Modify: schema.py (nested list type + `ListLiteralExpr` nesting + indexing), verifier, canonical.py, 6 codegens, parser/prompt rules
- Test: `tests/test_parity_2d_lists.py`
- Create: `examples/advanced/532_2d_lists.meme` (+ lock)

**Interfaces:**
- Produces: `List<List<T>>` generic in T. Surface: `define g as empty List<List<Int>>`; literal `[[1, 2], [3, 4]]`; index `g[i][j]`; `set g[i][j] to v`; `length of g` → row count, `length of g[i]` → that row's length (jagged rows allowed). Out-of-range `[i][j]` → same error shape as 1D out-of-range, message mentions both indices.

- [ ] **Step 1: Failing parity test** — build a 3x3 literal, transpose by index writes, print rows; jagged 2-row case; out-of-range case (exit 1, same stderr all targets).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: pytest green + diff.**
- [ ] **Step 5: Commit** `feat(language): generic 2D lists with jagged rows`.

### Task 11: Release gate + docs + version bump

**Files:**
- Modify: `scripts/run_corpus.py` (add `--all-targets` mode covering cs1xx + advanced + examples + `meme test`), `README.md`, `docs/TUTORIAL.md`, `docs/WRITING_GUIDE.md` (sections for every feature above), `pyproject.toml` (version → `0.2.0b0`)
- Test: `tests/test_release_gate.py` (gate runs on a small fixture subset; full corpus runs are manual/coordinator)

**Interfaces:**
- Produces: `uv run python scripts/run_corpus.py --all-targets` → runs every example + test suite across all 6 targets, prints one verdict line per target, exit 1 on any failure.

- [ ] **Step 1: Failing test** — gate with `--all-targets` on the 524–532 subset exits 0 and reports 6 target verdicts.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement + write all feature docs (one WRITING_GUIDE section per feature, matching existing section style).**
- [ ] **Step 4: Full gate run** — `uv run python scripts/run_corpus.py --all-targets` green; `uv run pytest -q` green.
- [ ] **Step 5: Commit** `feat(release): all-target corpus gate + beta docs + version 0.2.0b0`. (Tagging v0.2.0-beta happens after the capstone lands — final batch 5 step, coordinator's job.)

---

## Coordinator Verification Checklist (applies after every delegated task)

1. `git log --oneline -2` — no agent commits.
2. `git status --short` — only expected files.
3. `uv run pytest -q` — full green (run it yourself, don't trust the report).
4. 6-target spot-check on the task's new example: compile each target, run, `diff` stdout.
5. Repo-root hygiene: no stray output files in the repo root; locks regenerated from root only.

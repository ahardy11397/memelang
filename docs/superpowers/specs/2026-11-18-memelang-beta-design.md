# Memelang Beta Design — "Grad-Bar" Backend Capability

Date: 2026-11-18
Status: Approved by user (brainstorming session). Next step: implementation plan.

## Intent and Why

Memelang is at v0.1.0-alpha (559 tests, ~490 course examples in cs101–cs106,
advanced contracts 501–524, six compile targets with byte parity, native
binaries via `meme build`). The user wants a **solid beta** with a concrete
bar: whatever a fresh CS graduate would be expected to build on their own —
complete backend-style programs and scripting — Memelang should handle end to
end, and the beta release should carry a suite of tests and examples that run
on it.

## The Bar (decided)

A "backend" for beta purposes means backend-style programs: state, records,
persistence, JSON, reporting, a CLI entry point, and a test suite — the way
undergrad "build a system" assignments are graded. **Networking/HTTP is
explicitly OUT of beta** and becomes a post-beta chapter. This was the user's
call.

Success looks like: a grad-level capstone program (the banking ledger, below)
written in Memelang itself, tested with Memelang's own test facility, compiled
to a native binary, running green across all six targets.

## Goals

1. **Test subsystem** — both sizes (user-locked "big and small"):
   - Small: an `assert` statement usable in any program. Failing assert
     prints the failing line and exits 1.
   - Big: a `meme test` command that discovers test files under `tests/`,
     runs them, and reports pass/fail per case.
2. **Data interchange** — JSON objects in both directions (read a JSON object
   from a file into a record; write a record out as JSON; lists of records
   included), plus float formatting so reports can print "12.50".
3. **Environment access** — real wall-clock time (epoch seconds at minimum),
   environment variables, and file-open failures that return Optional instead
   of killing the process (missing file becomes a checkable value).
4. **Collection gaps** — sets (deterministic iteration) and 2D lists
   (`List<List<Int>>` with `[i][j]` indexing).
5. **Capstone proof** — a banking ledger built in Memelang (below).
6. **Release gate** — one command runs the full corpus (course examples,
   advanced contracts, test suite) across targets; docs updated; tag
   v0.2.0-beta.

## Non-Goals / Anti-Goals

- **No networking, sockets, or HTTP in beta.** (User decision; post-beta.)
- No closures/first-class functions/lambdas in beta.
- No nested records requirement in beta (flat records + typed containers
  `List<Record>` / `Map<Int, Record>` are the beta bar; nested records are a
  bonus if cheap).
- No try/catch — the error channel stays `Optional<T>` (user-locked decision
  from Phase 2B, restated here so it is not relitigated).
- Anti-goal: any feature that cannot be parsed by the deterministic heuristic
  parser. The deterministic parser is the single source of truth; LLM voice
  is a dictation frontend. Every new feature MUST be offline-parseable and
  MUST ship the full artifact set per repo convention (schema, verifier,
  canonical decompiler, all codegens, parity tests, parser/prompt rules,
  docs + locked example).
- Anti-goal: breaking existing examples or their lockfiles.

## Constraints

- All six targets (python, rust, cpp, go, c, ts) at byte parity, as today.
- Zero-LLM lockfile contract holds: locked files never trigger synthesis.
- `uv run pytest -q` green after every batch; agent runs do not commit
  (coordinator verifies then commits, per the established delegation
  workflow).
- Determinism: clock values are runtime values and do not affect compilation,
  but corpus examples and tests must not assert exact wall-clock values
  (coordinator call: tests avoid exact-clock assertions; a fixed fake-clock
  env override is a bonus, not a requirement).

## Feature Design Sketches (calls marked mine)

### 1. Assert + meme test
- `assert <condition>` — statement; on failure prints
  `ASSERT FAILED line <n>: <condition text>` and exits 1.
- `meme test [DIR]` — runs every `*.meme` in `tests/`. Test files may contain
  top-level `test <name>:` blocks (executable, may contain asserts) alongside
  normal code. Runner compiles the file once per target (default: python;
  `--target` to override), executes each test block, prints `PASS <name>` /
  `FAIL <name> (line n)`, exits 1 if anything failed. Mechanism (dispatch arg
  vs generated runner) is the builder's call. My call: per-case granularity
  is required, not per-file.

### 2. JSON records
- Read: `read json record <RecordName> from file <path>` → record value
  (field-name matching, type-checked). Write: `write <record> as json to
  file <path>`. Lists of records both directions. Exact surface phrasing
  follows house style per WRITING_GUIDE; the contract is: records ↔ JSON
  objects, `List<Record>` ↔ JSON arrays of objects. Nested records and
  maps-of-records in JSON: builder's call, document whatever ships.
- Float formatting: `format <float-expr> with <n> decimals` → String
  (half-up rounding; byte-identical across targets — this is the hard part,
  see builder notes).

### 3. Environment
- `current epoch seconds` → Int (wall clock).
- `environment variable "<NAME>"` → Optional<String>.
- File ops gain Optional channels, e.g. `read string from file <path> or else
  nothing` → Optional<String>; same pattern for the other readers. Errors
  stay silent-by-Optional; the existing hard-fail forms stay unchanged.

### 4. Collections
- Sets: `empty set of String`, `add <v> to <set>`, `contains`,
  iteration in sorted order (mirrors the map sorted-key rule).
- 2D lists: `List<List<Int>>` declarations, `[i][j]` indexing, row-major
  literals. Minimal verbs: create/empty, index, set index; builder may ship
  more if cheap.

### 5. Capstone: banking ledger (user-approved)
Standalone repo (like card-inventory): accounts, transactions, deposits,
withdrawals, transfers with validation (insufficient funds, unknown account,
negative amounts), JSON persistence, monthly statement reports using float
formatting, CLI command router via argv, tested with `meme test`, shipped as
a native binary via `meme build`. Acceptance: its full `meme test` suite
green on all targets it claims, plus an end-to-end demo session.

### 6. Release gate
A `scripts/run_corpus.py`-style single command (or make target) that runs
every example and every test across all six targets and reports one verdict.
README + TUTORIAL updated; version bumped; tag v0.2.0-beta.

## Sequencing (agreed batch structure)

One agy run per batch (~3 features each), verify + commit between runs:

1. Batch 1 — assert + `meme test`
2. Batch 2 — JSON records + float formatting
3. Batch 3 — clock + env vars + Optional file errors + sets + 2D lists
4. Batch 4 — capstone ledger app (may go to a second agent; coordinator
   verifies adversarially)
5. Batch 5 — release gate + docs + tag v0.2.0-beta

## What's Left to the Builder

- Exact surface-syntax phrasing for every new construct (house style,
  unambiguous English rules, canonical decompiler output).
- Cross-target float formatting strategy (the byte-parity trap).
- `meme test` execution mechanism and output format details.
- JSON depth decisions (nested records, maps of records).
- Whether the release gate extends `scripts/run_corpus.py` or is new.
- Standard artifact work per feature (schema, verifier, decompiler, 6
  codegens, parity tests, docs, locked examples).

## Builder-Check Resolutions (2026-11-19)

The builder-check reviewer raised six questions. Dispositions:

1. **JSON reader failure semantics** (malformed JSON, missing/unknown fields,
   null, type mismatch) — ANSWERED by the user-locked error-channel decision:
   everything fallible takes the Optional channel. New readers return
   Optional with `or else` support, exactly like the safe-parse and file
   readers; the hard-fail legacy forms stay unchanged. No per-field policy.
2. **JSON output byte-parity + float repr in JSON** — ANSWERED by repo
   convention: byte parity across all six targets is a hard constraint, so
   JSON floats serialize through the same fixed-decimal formatting strategy
   as `format ... with N decimals`. The codegens must share one formatting
   rule; this is flagged as the second parity trap alongside report floats.
3. **Capstone target matrix** — USER DECIDED: ALL SIX targets. The ledger
   and its full `meme test` suite must run green on python, rust, cpp, go,
   c, and ts. The release gate covers the capstone on all six.
4. **Test files reaching code under test** — MY CALL, settled: thin-main +
   logic module. The capstone (like card-inventory) is a standalone repo
   whose CLI entry is a thin argv router over `use`-able logic modules;
   test files `use` those modules. No module-system extension in beta.
5. **Set<T> / List<List<T>> first-class status** — MY CALL, settled:
   first-class, matching the existing type system — `Map<K,V>` is already
   first-class (params, returns, fields), so `Set<T>` matches it, and
   `List<List<T>>` is generic in `T` (2D grids of any type). Set iteration
   is sorted for determinism. C target implements sets as sorted-key
   structures (same pattern as its maps).
6. **Test execution isolation + IR/lockfile participation** — MY CALL,
   settled: one process per test block, selected by a dispatch argument
   generated at compile time; plain `meme run` of a test file executes
   top-level code and skips test blocks. `test <name>:` blocks are real IR
   nodes: they participate in the canonical decompiler and lockfile hashing
   per the 7-artifact rule (this is forced by existing conventions, not
   new policy).
7. **Monthly statements without date builtins** — ANSWERED: beta ships
   epoch-seconds only (UTC). Month bucketing/leap-year math is done
   in-language in the capstone — that arithmetic is squarely inside the
   grad bar and needs no new builtins.

## Open Questions for the User

None — all scoping decisions are resolved. (Capstone target matrix: all six,
user-decided 2026-11-19.)

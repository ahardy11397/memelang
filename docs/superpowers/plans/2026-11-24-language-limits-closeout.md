# Close Out Remaining Language Limits — Implementation Plan

> **For agentic workers:** This plan executes via the Memelang delegation workflow
> (memelang-dev skill): ONE agy run for all three features, coordinator verifies
> everything before commit. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the last two known language limits — JSON record I/O with
collection and nested-record fields, and recursive records via Optional — so
the known-limits list is empty and nothing needs a workaround.

**Architecture:** Three features, each shipping the full 7-artifact set
(schema/verifier, canonical decompiler, six codegens, parity tests,
parser/prompt rules, docs, locked example). Feature 1 fixes struct layout for
recursive Optional records on rust/cpp/c via target-side indirection. Features
2–3 relax the verifier's four JSON rejection sites and extend the twelve
per-target JSON record reader/writer emitters.

**Tech Stack:** Python 3.13, uv, pytest; native toolchains rustc/g++/go/gcc/tsc.

**Spec:** this document (design approved in chat 2026-11-24; scope: collections
AND nested records both included per user decision).

## Global Constraints

- USER-LOCKED (verbatim, never relitigate): error channel = Optional<T>, NOT
  Result<T,E>; deterministic heuristic parser is the single source of truth
  (every construct must parse offline); C++ contract is g++ -std=c++20.
- `uv run pytest -q` green after EVERY task. NO commits by the agent.
- Existing examples must not change output. All JSON writes must be
  byte-identical across all six targets (deterministic sorted iteration).
- All-or-nothing reads (existing semantics): if ANY field fails to parse at any
  depth, `read json record ... or else nothing` returns nothing. No partial records.
- One compile of a program must produce identical stdout/stderr on all six targets.

## Review Focus (failure modes that must get pinned tests)

1. Optional field present-as-null vs absent in JSON — both must yield None/empty
   Optional, matching existing Optional<scalar> behavior.
2. Type mismatch deep inside a nested structure (e.g. List field containing a
   String where Int declared, wrong record shape 3 levels down) — whole read
   returns nothing, not a partial record.
3. Deterministic ordering — Map and Set fields serialize in sorted order,
   byte-identical across all six targets. Int-keyed Maps serialize keys as JSON
   strings (my call; JSON requires string keys) and readers accept string keys
   for Int-keyed maps.
4. Empty collections — empty List/Set/Map fields round-trip as `[]` / `{}`,
   never as null or missing.
5. Recursive record in JSON — data is tree-shaped (JSON text cannot cycle), so
   readers recurse structurally and terminate; writer on a recursive record with
   none-parent chain terminates and round-trips.

---

### Task 1: Recursive records via Optional (indirection on rust/cpp/c)

**Files:**
- Modify: `src/memelang/codegen/rust_gen.py` (record struct emission ~line 1262),
  `src/memelang/codegen/cpp_gen.py` (~line 1268), `src/memelang/codegen/c_gen.py`
  (record emission + copy/eq/fmt helpers)
- Test: `tests/test_parity_recursive_records.py` (new)
- Example: `examples/advanced/5xx_recursive_optional.meme` (next free number)

**Interfaces:**
- Produces: a record like `record Node: name: String, parent: Optional<Node>,
  children: List<Node>` compiles and runs on ALL SIX targets. User surface
  syntax and IR are UNCHANGED — indirection is a codegen-only detail.

- [ ] **Step 1:** Write the parity test first: build/run a recursive-Optional
  example on all six targets, assert identical stdout and exit 0. Run:
  `uv run pytest tests/test_parity_recursive_records.py -v`. Expected: FAIL
  (rust E0072 infinite size; cpp incomplete type; c error).
- [ ] **Step 2:** Implement indirection. My call, binding: on rust, an
  `Optional<record>` field emits `Option<Box<Ident>>`; on cpp, a
  `std::unique_ptr<Ident>` wrapped so Optional semantics (present flag, unwrap,
  unwrap-or-else) are preserved; on c, the Optional struct's `value` becomes a
  pointer with present flag, and copy/eq/fmt helpers deep-follow the pointer.
  go/ts/python need no change (reference semantics already). ALWAYS box
  Optional<record> fields (uniform rule — not only when the record is
  self-recursive; simpler and future-proof for mutual recursion).
- [ ] **Step 3:** `uv run pytest tests/test_parity_recursive_records.py -v` → PASS.
- [ ] **Step 4:** Confirm no existing example changed behavior:
  `uv run pytest -q` → all green.

### Task 2: JSON record fields — collections

**Files:**
- Modify: `src/memelang/analyzer/verifier.py` — relax the List/Map rejection at
  BOTH sites: write site lines ~2117-2121, read site lines ~1215-1219. Allow
  `List<T>`, `Set<T>`, `Map<K,V>` where element/key/value types are
  JSON-representable (Int, Float, String, Bool, or another record — Task 3 — or
  Optional of those). NOTE: Set is currently NOT rejected by the verifier but is
  also unhandled by the emitters — the new check must accept Set only once the
  emitters handle it (same task).
- Modify: all twelve `_emit_*_json_record_reader/writer` functions in
  `src/memelang/codegen/{python,rust,cpp,go,c,ts}_gen.py` to serialize/deserialize
  collection fields per the Review Focus rules.
- Test: `tests/test_parity_json_collections.py` (new)

- [ ] **Step 1:** Failing parity test: record with `List<Int>`, `Set<String>`,
  `Map<String, Int>` fields, write as JSON, read back, print — six-target byte
  parity. Expected: FAIL (verifier rejects).
- [ ] **Step 2:** Relax verifier (both sites) + extend all twelve emitters.
- [ ] **Step 3:** Parity test PASS; `uv run pytest -q` green.

### Task 3: JSON record fields — nested records

**Files:**
- Modify: `src/memelang/analyzer/verifier.py` — remove the nested-record
  rejection at both sites (~2110-2116 write, ~1208-1214 read); allow field types
  that are records, `Optional<record>`, and collections of records
  (`List<Record>`, `Set<Record>`, `Map<String, Record>`).
- Modify: the same twelve emitters — nested record fields emit/read a nested
  JSON object by delegating to the target's existing per-record reader/writer
  (they are already named functions like `_meme_parse_record_<ident>`, so this
  is composition, not new machinery). Optional<nested record> maps to
  JSON null/absent.
- Test: `tests/test_parity_json_nested_records.py` (new)

- [ ] **Step 1:** Failing parity test: `Order` record containing a `Customer`
  record field plus `List<Item>` record collection; write/read/print round-trip,
  six-target parity. Expected: FAIL (verifier rejects).
- [ ] **Step 2:** Relax verifier + compose emitters.
- [ ] **Step 3:** Parity PASS; `uv run pytest -q` green.
- [ ] **Step 4:** Capstone: recursive Node from Task 1 (name, Optional<Node>
  parent, List<Node> children) written to JSON and read back — proves recursion
  and nested records compose. Six-target byte parity.

### Task 4: Artifact completion — parser/prompt rules, decompiler, docs, locks, gates

- [ ] **Step 1:** Parser/prompt rules in `src/memelang/llm/heuristic.py` +
  few-shot examples (agent: follow existing pattern for the JSON-record rules).
- [ ] **Step 2:** Canonical decompiler handles the new field types in
  `src/memelang/ir/canonical.py`.
- [ ] **Step 3:** Docs: update `docs/WRITING_GUIDE.md` (JSON + records sections)
  and `references/language-limitations.md` in the memelang-dev skill dir —
  strike the two closed limitations.
- [ ] **Step 4:** Locked example(s) committed with regenerated `.meme.lock`
  (regenerate from repo root — lock keys are CWD-relative).
- [ ] **Step 5:** Full gate: `uv run pytest -q` AND
  `uv run python scripts/run_corpus.py --all-targets` → 230 programs x 6
  targets, 0 failures.

## Coordinator Verification (me, not the agent)

Before commit: git log unchanged, full pytest, live spot-check of each feature
via the proven cross-target commands (compile one new example per feature,
run python/rust/cpp/go/c/ts binaries, diff stdout byte-for-byte), confirm
generated rust struct shows Box indirection, `git status --short` swept clean,
then single commit + `git push origin master:main`.

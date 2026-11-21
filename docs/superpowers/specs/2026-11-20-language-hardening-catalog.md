# Language Hardening Catalog — post-beta gap analysis

Date: 2026-11-20. Source: findings from building 12 real programs
(ledger, library-system, payroll, flight-reservation, spreadsheet-engine,
maze-solver, huffman-compressor, markdown-to-html, expense-splitter +
project-tracker, csv-analytics in flight).

Comparison baseline: what a solid v0.2-stage language needs — reliable
error output, basic numeric conversions, uniform iteration, records that
work everywhere, and tooling that respects the zero-LLM contract.

## Confirmed limitations (all observed in real programs)

### Error / IO surface
1. **No stderr print.** `fail with` is the only built-in error channel and
   prints to STDOUT; only `assert` writes stderr. Every demo either
   accepted stdout errors or appended to `/dev/stderr` (Linux-only hack).
   → ADD: `print error <expr>` statement — one line to stderr, all targets.
2. **No Int→Float conversion.** `format <x> with N decimals` requires a
   Float; money-in-cents programs (payroll, ledger, expense-splitter,
   flight, library) all hand-rolled `dollars_text` integer renderers.
   → ADD: `float of <int-expr>` conversion.
3. **No char→Int / Int→char.** `char at i of s` returns a String; Huffman
   needed char codes as ints and had no `ord`/`chr`. → ADD: `number of
   <string-1>` → Int (codepoint) and `character of <int>` → String.
4. **`meme run` cannot forward program argv.** CLI programs can only be
   exercised via compiled artifacts. → CHANGE: `meme run prog.meme -- arg1
   arg2` passes args through (all targets' runners).

### Iteration / expression uniformity
5. **`for each` iterates VARIABLES only.** `for each x in some_list_field`
   or `in get_items()` fails to parse; every demo used temp-variable
   workarounds. → FIX: for-each accepts any expression evaluating to a
   collection.
6. **No mutual recursion.** Spreadsheet's eval + helper had to merge into
   one function. → FIX: allow forward references between functions of the
   same module (two-pass definition resolution).

### Records / type system (C target gaps)
7. [IMPLEMENTED] **Records with List fields don't compile on C** (huffman workaround:
   parallel scalar lists).
   → FIX: c_gen emits copy/eq/fmt for collection fields (List, Map, Set) and supports recursive records through List (`record Node: children: List<Node>`).
8. [IMPLEMENTED] **`Optional<Map<K,V>>` and `Optional<List<...>>` don't compile on C**
   (missing eq/copy helpers for those inner types).
   → FIX: c_gen emits copy/eq/fmt helpers for Optional-of-collection.
9. [IMPLEMENTED] **Rust: Set-valued function args not cloned** (spreadsheet workaround:
   List<String> instead).
   → FIX: rust_gen clones Set-valued args on reference; value semantics preserved across all 6 targets.

### Tooling contract
10. **`meme build`/`meme test` default to the LLM provider** and silently
    mis-synthesize past llama.cpp's context window; EVERY demo brief had to
    say `--provider heuristic` everywhere. → CHANGE: build/test default to
    `heuristic` (zero-LLM by default; `--provider` still overrides). This
    matches the language's positioning: deterministic parser is the source
    of truth.
11. **Stale `.meme.lock` sidecars** after source edits change results;
    meme test needed explicit lock deletion. → CHANGE: meme test treats
    lockfiles as advisory (hash mismatch = recompile, report it) rather
    than authoritative.
12. **`function main() -> Int` silently produces a no-op binary** (huffman
    ruling). → CHANGE: verifier error if a program defines `main()` at top
    level (Memelang programs ARE top-level statements; a main() function
    is always a mistake).

### Module system
13. [IMPLEMENTED] **`use` resolves only in the importing file's directory** — tests
    needed symlinks to root modules (library-system, ledger). → ADD:
    `use ../<module>` relative parent resolution.

## Prioritized batches (each = one agy run, ~3 items, full pytest between)

- **Run A (tooling + errors):** items 10, 11, 12, 1, 4 — tooling contract
  first (smallest, highest day-to-day impact).
- **Run B (core types):** items 2, 3, 5, 6 — numeric conversions +
  iteration uniformity + mutual recursion.
- **Run C (C backend records):** items 7, 8, 9, 13 — records work
  everywhere; module parent paths.

## Retrofit plan (after Runs A-C)

Update all 12 programs to exercise the new features where they had
workarounds: replace `/dev/stderr` hacks and stdout `fail with` with
`print error`; replace `dollars_text` with `float of` + `format`; iterate
expressions directly; delete test symlinks (use `../module`); huffman gains
real char codes (smaller table); spreadsheet keeps merged eval (works, but
documents mutual recursion now allowed); remove `--provider heuristic`
boilerplate (default now). Re-run `meme test` × 6 targets in all 12 repos +
the release gate before committing.

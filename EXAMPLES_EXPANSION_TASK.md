# TASK: Expand examples/ + corpus to ~500 verified examples

You are working in /mnt/ssd/projects/meme (Memelang). Do NOT commit anything — leave all
changes uncommitted for the user to review.

## Current state (verified 2026-11-06)

- 309 `.meme` examples: examples/cs101 (101), cs102 (101), cs103 (107 total incl. fixtures).
  Every corpus example has a paired verified `.meme.lock` sidecar.
- Lockfiles pin deterministic behavior: generate with
  `uv run meme check <example.meme> --lockfile <example.meme.lock>`.
- Corpus runner: scripts/run_corpus.py, manifest at tests/corpus/manifest.json
  (corpus_version, total_scripts, scripts[...]). Tests: 94 passing in ~21s via `uv run pytest -q`.
- Retriever few-shot learning only uses LOCKED examples — every new example must get its lock.

## Goal

Grow from ~309 to ~500 examples (~190-200 new). Theme: real-world common coding tasks, not
more textbook algorithms. Organize into new axes following the existing cs101/102/103 pattern
(same numbering style: NNN_snake_case_name.meme + .meme.lock):

- examples/cs104/ — everyday text & data tasks (~70): log-line parsing, CSV row handling,
  key=value config parsing, word frequency, dedupe, flatten/chunk lists, top-N selection,
  string cleanup (trim/case/pad/replace), simple report formatting, comma-grouped numbers,
  word wrap, initials/acronym extraction, title case, vowel/consonant counts, etc.
- examples/cs105/ — validation & checksums (~60): Luhn card check, ISBN-10/13, email shape
  checks, password rule checks, phone formatting, date validity (leap years, days-in-month),
  UUID-shape checks, simple checksums, parity, range/sanity validation, form-field checks.
- examples/cs106/ — small "libraries" (reusable classes) (~60): statistics (mean/median/
  mode/variance/stddev), finance (simple+compound interest already partly in cs101 — do loan
  amortization, savings growth, break-even), date/time arithmetic (age in days, day-of-week,
  countdowns), unit conversion library (temps done — add lengths, weights, volumes),
  inventory/cart/ledger classes, queue/stack wrappers for real workflows (print jobs, support
  tickets), timer/stopwatch, rating/aggregation helpers.

Adjust the split as you learn what the language expresses well — the counts above are a
target distribution, not a quota. Total across all axes should land near 500.

## Constraints and rules

1. Read docs/WRITING_GUIDE.md first, especially: two voices, determinism & lockfiles
   (§10), the examples axis (§12), and the type-matching tip in §13 (Int vs Float at call
   boundaries). Prefer the Structured English voice unless the task needs classes —
   cs106 "library" examples use the class layout like cs103 does.
2. Stay inside the IR feature set you know works (see scripts/run_corpus.py imports for the
   statement/expression inventory). Do NOT invent syntax. If an idiom is unfamiliar to the
   compiler, fix by adding the idiom as a small locked example first (per §12), or simplify
   the task.
3. Work in small batches (~10 examples), then verify the batch:
   `uv run meme check examples/csXXX/NNN_name.meme --lockfile examples/csXXX/NNN_name.meme.lock`
   for each, before writing the next batch. If the heuristic provider can't handle a program,
   simplify it — no network/LLM calls needed for lockfile generation.
4. Update tests/corpus/manifest.json (and corpus_version only if the schema requires it) so
   `uv run pytest tests/test_corpus_manifest.py` passes with the new scripts included.
5. Deliberately-typo/ambiguous corpus scripts exist under tests/corpus/ — never copy their
   phrasing; new examples must be clean, canonical, and deterministic.
6. Keep names meaningful and real-world ("014_parse_apache_log_line.meme", not "test17.meme").
7. Watch total runtime: `uv run pytest -q` must stay well under 60s. If it grows, flag it
   instead of silently slowing the suite.
8. Progress notes: append one line per completed batch to EXAMPLES_EXPANSION_LOG.md at repo
   root (batch #, axis, count, verify result). Final report: exact counts per axis, total,
   pytest result.

## Definition of done

- `find examples -name '*.meme' | wc -l` reports ~500 (excluding fixtures).
- Every new example has a verified .meme.lock sidecar.
- tests/corpus/manifest.json includes all new scripts; `uv run pytest -q` fully green.
- Nothing committed; EXAMPLES_EXPANSION_LOG.md documents what was added.

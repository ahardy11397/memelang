# AGENTS.md — {{NAME}} (Memelang demo program)

Rules for coding agents working in this repo. This is a 100% Memelang demo
program, graded on the beta bar (grad-capstone complexity), compiled by the
umbrella compiler at /mnt/ssd/projects/meme. If a delegated brief or
PLAN.md exists, it wins on scope — never on the non-negotiables below.

## What lives here

- `*.meme` at the root — the program source (records, modules, main).
  Modules are imported with `use <module>` and resolve relative to the
  importing file's directory.
- `tests/meme/` — test cases discovered by `meme test` (symlinks to root
  modules where needed).
- `PLAN.md` — the approved plan (Domain, CLI surface, Tests sections).
- `data/` — runtime JSON state, created on demand; never write outside
  the repo.

## Verify — all of these, before claiming done

Run the compiler from the umbrella repo (this repo has no venv of its own):

```bash
cd /mnt/ssd/projects/meme
for t in python rust cpp go c ts; do
  uv run meme test <full path to this repo>/main.meme --target $t   # 0 failed each
done
uv run meme build <repo>/main.meme --target <t> -o <repo>/<name>_bin  # build the binary
```

Then run the end-to-end demo yourself (argv-routed commands from
PLAN.md/README) and check exit codes and stderr. A passing test suite with
a broken demo is NOT done.

## Non-negotiables

1. **100% Memelang.** No Python/shell glue implementing program logic.
2. **The deterministic heuristic parser is the only parser:** every
   construct must parse with `--provider heuristic`.
3. **Agents never commit.** Leave all changes uncommitted for coordinator
   review. The coordinator runs the six-target suite, builds the binary,
   runs the demo, and commits.
4. **USER-LOCKED language decisions** (from the umbrella AGENTS.md):
   error channel is `Optional<T>`, NOT `Result<T, E>`; C++ contract is
   `g++ -std=c++20`.
5. **Design around open limitations — do not relitigate them.** Check
   `/mnt/ssd/projects/meme/references/language-limitations.md` (or ask the
   coordinator) before designing around a missing feature. If a workaround
   is unavoidable, NAME it explicitly in PLAN.md so a later retrofit wave
   can find and replace it.
6. **Determinism:** tests must not assert exact wall-clock values — assert
   relational properties only.

## Pitfalls

- Run tests in the FOREGROUND and wait for them. Backgrounding a suite and
  idling burns the run's timeout budget.
- Programs write cwd-relative files — run each compiled binary in its own
  scratch subdirectory when comparing targets.
- Money-like values: integer smallest-unit (cents), floats only for
  rendered output via `format <float> with N decimals`.
- Validation failures print one clear line to stderr and exit `1`; reports
  go to stdout.

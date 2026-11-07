# Memelang Core — Design Document

**Date:** 2026-11-07
**Status:** Draft for review
**Companion report:** `docs/2026-11-07-language-completeness-report.md` (grounded current-state inventory with file:line citations — read alongside this document)

---

## 1. Intent and the Why

Memelang is the better version of the promise Ruby made: *the language should
read the way you think*. Ruby got close on philosophy but kept a syntax
surface, and syntax accrues cleverness — real Ruby is dense idiom-bargaining
that only reads easily after years of convention internalization. Memelang's
insight is that the fix is not better syntax but **no syntax**: the source is
prose itself, so the writer's cost and the reader's cost are the same words.

The next phase of the project is to make Memelang a **complete core language
at Ruby's level of capability**. A language you could carry a real utility,
tool, or application in — the current Memelang pipeline (English → typed IR →
verified → locked → Python/Rust/C++ codegen) stays exactly as the backbone;
what changes is the completeness of the vocabulary and the *layer* where
exactness lives.

**The layering principle (the philosophical center of this design):**

> Exactness is a property of the compiler. Looseness is a property of the
> authoring experience. Exactness must never surface as a tax on the writer,
> and looseness must never undermine the determinism guarantees underneath.

Concretely:

- The **writer** says rough English and gets correct, deterministic output.
  The writer should not have to shape their English to satisfy a parser.
- The **compiler** stays strictly typed, ambiguity-resolving, and
  lockfile-deterministic underneath. Nobody surrenders those properties —
  they are what makes English a viable program source.
- Where today the pipeline halts to ask the writer, the default should move
  from "halt on any collision" to "auto-resolve what any reasonable reader
  would agree on; halt only when the readings differ in *what the program
  does*."

### The two verdicts that shape everything below

1. **Ruby, not Rails — for now.** The core language is the scope of this
   design. A Rails-alternative convention/batteries layer (web servers, ORM
   conventions, migrations, UI slots) is a *later phase* and is explicitly
   out of scope here. The core must be finished enough that the Rails layer
   has something to stand on.
2. **The todo utility is the acceptance criterion.** A terminal todo app is
   designated as the standing probe: at the end of every phase below, the
   question is not "were nodes added?" but "does a todo app written in rough
   English do the obvious thing?" It is this project's "blog in 15 minutes"
   demo — whichever phase finally makes it possible is the phase that ends
   the probe-driven development.

---

## 2. Goals

1. **Ruby-parity core.** Every capability a real Ruby program relies on has a
   natural English expression that successfully compiles (success checklist
   in §5, mapped from Ruby constructs).
2. **Idea-first authoring.** A program is written the way it comes into
   your head, and the compiler meets the writer. (Today the drift is real —
   the WRITING_GUIDE documents idioms the offline heuristic cannot parse,
   see report §5.1 — and this design dissolves it by making the local model
   the single frontend, §6.1.)
3. **Programs that touch the world.** File read/write/detect, command-line
   arguments, environment, clock, meaningful exit codes. A Memelang program
   must be able to *be* the CLI tool it describes.
4. **Complete control flow.** Early loop exit, selective dispatch, and an
   error channel — the three things that make programs *behave* like programs
   rather than like batch scripts.
5. **Determinism preserved and strengthened.** Lockfile rebuilds stay
   zero-LLM and byte-identical; cross-target output parity (Python/Rust/C++)
   becomes *tested for the whole covered surface*, not "approximate except
   known gaps."

## 3. Non-Goals

- **A Rails alternative.** No web framework, ORM, migrations, routing, or
  UI framework in this design. (Future phase; noted so the core leaves
  clean seams: e.g., record types and maps must be strong enough that a
  future convention layer can define its own schemas on top.)
- **Object model expansion beyond what prose needs.** Memelang does not aim
  for Ruby's metaprogramming (`method_missing`, `define_method`, monkey
  patching, open classes). The prose-to-IR contract makes much of Ruby's
  metaprogramming unnecessary *by construction* — English goes in, IR comes
  out; there is no reflective surface to patch.
- **New target runtimes** (Go, JS, C, etc., per the repo roadmap) — out of
  scope; the three existing targets remain the parity obligation.
- **The ambiguity/lockfile *mechanism* itself.** The capture-and-resolve-and-lock
  mechanism stays; only its *triggers* and *defaults* are adjusted (§4).
  **Decided exception:** the lockfile's *addressing* deliberately changes —
  it locks a **set of source files** (a program with modules), not a single
  file (§6, decision 2). That rework is in scope and planned, not accidental.
- **Offline authoring.** There is no offline mode. The compiler's frontend
  is the small local GGUF model (`uv run meme pull`, llama.cpp, T=0). More
  on this in §6, decision 1 — the design works *regardless*, but the
  product contract is: the local model is the compiler.

## 4. Anti-Goals (what would be failure even if it "worked")

- **More syntax.** Adding punctuation-heavy forms, sigils, or DSL-shaped
  structures to "satisfy the parser" would be the exact opposite of the
  intent. Every new capability ships as *phrasings a human would produce*,
  verified and taught to the frontends.
- **Taxes that leave ideas out.** Expressiveness must not demand
  type-annotation ceremony in prose. If a writer must write types to be
  understood (rather than for clarity's sake), the frontend is broken.
- **Silent wrong guessing.** "Less exact" must never become "silently wrong."
  Loose authoring + auto-resolution is fine; *plausible-looking* wrong
  interpretations are the failure mode this project cannot afford, because
  the reader is presumably the writer and won't re-verify semantics line by
  line.
- **Invisible exactness monsters.** If any phase's features deploy with
  silent type defaults (like today's `Int`/`List<Int>`/`Map<String,String>`
  parse-time catch-alls — report §5.2), it's phase failure. Vibrancy at the
  prose layer must come with the *specifics* being surfaced, not hidden.
- **Strings-parsed-by-regex as a product.** Keeping the heuristic regex
  frontend as a user-facing mode would freeze the language's vocabulary to
  whatever regular expressions can model — the exact opposite of the
  idea-first intent. The frontend is the model (§6, decision 1); the
  heuristic's only remaining jobs are internal (§6.1).

## 5. Ruby-Parity Decoded: Construct Mapping

This section is the scope contract. Each row is a Ruby capability, and the
Memelang prose surface that must exist for it. Implementation specifics are
left on purpose to the builder's plan; what's fixed here is the *meaning*.

| Ruby capability | Memelang core obligation |
|---|---|
| `puts`, `print`, `p` | `print` exists; must support formatting (see strings row) and prompt-free output |
| `gets`, ARGV, `STDIN`, exit codes | `read input` exists. Must add: argument access ("the first command line argument"), environment read, `exit with code N` / a `fail` that exits non-zero |
| Files (`File.read`, `File.write`, `File.exist?`, delete/rename, append) | Natural prose verbs; the one existing `read_json_list` gets a generalized text/JSON sibling set |
| Strings (`include?`, `start_with?`, interpolation, `gsub`, `upcase`, `split`, `strip`, `chars`, array-style slicing, `to_i`/`to_f`) | A real string toolbox as prose verbs — "does the title contain X", "replace every X with Y in the line", "in capital letters", "split the line on commas", "trim the input" |
| Symbols (`:id`) | No Rust-style symbols; strings serve everywhere a symbol would |
| Enumerable (`map`, `select`, `reject`, `each_with_index`, `find`, `reduce`, `any?`, `all?`, `sort_by`, `group_by`, `uniq`, `min_by`, `max_by`, `count…`) | Whole-collection verbs. **Decided surface rule:** verbs act on named lists/maps **in place** (matching today's verb family) *and* prose supports a copy-flavor ("define the doubles as every number in the scores times two") where the natural reading is declarative |
| Arrays/Hashes (incl. set ops, `each`, `keys`, `values`, ordering, negative index, ranges) | Lists and maps exist; add: iteration over maps, mapping over (key, value) pairs together, negative indices admitted as 1-based English ("second from the end"), list slicing |
| Blocks & Procs & Lambdas (first-class functions, closures) | Natural English function literals: "define double with n, return n times two" usable as *values* passed to and returned from functions; result: `map`, `select`, `find` gain predicate/action arguments in the authoring voice |
| Classes & modules (namespaces, mixins, inheritance) | Records exist; namespaced units are the core obligation ("module Inventory" = scoping + import surface). Mixins/inheritance: **not required for core parity** — record construction + module composition must suffice to express real utilities |
| Exceptions (`begin/rescue/ensure/raise/retry`) | Error channel: `raise`-like failure with typed values (not strings) and a `rescue`-shape at statement level. **Decided shape:** introduce a `Try`/`Either`-style result type with prose verbs ("try" / "otherwise handle") while keeping simple programs one-line-safe (English error strings still work as sugar) |
| `case/when` | "Given the choice, when it is X do Y" or a shape approximating natural English dispatch |
| Duck typing / dynamic dispatch | **Reinterpreted as:** strong inference at the authoring layer. The writer should almost never need to write a type; the compiler derives it. Where Ruby's duck typing would be silent, Memelang *auto-resolves*; where real ambiguity exists, the verifier still halts — with better default heuristics (§6) |
| `sprintf`/interpolation AND formatted output | Prose composition of strings with embedded values ("print the greeting plus the name") is already idiomatic; the new part is a controlled multi-slot form that decompiles canonically and prints identically on all three targets |
| Optional/nil handling (`foo&.bar`, `|| default`) | The existing `m>>[k] default v` precedent generalizes: "or the default" and "if it is there" available as prose; record-optional fields and none-checking get explicit language ("none", "is missing") |
| Garbage collection, memory management | Non-issue — targets own this |
| Recursion, module constants, ` froze?`-immutability preferences | Recursion works; constants-as-declarations ("always", "never changes…") is sugar decided during build; mutation culture of Ruby (values by default) to match Memelang's verbs |

### Explicitly *not* in Ruby-parity scope

- Metaprogramming (`define_method`, `send`, method_missing, monkey patching;
  typically impossible with prose anyway, and correctly a non-goal)
- Eigenclasses/singleton classes, refinements
- Threads and fibers (concurrency is a post-core question)
- Frozen-string-literals semantics theater (records/types decide this)

---

## 6. Core Architectural Decisions

### Decided in conversation with the human

1. **The small local GGUF model is *the* compiler frontend. There is no
   offline mode.** The `llama-cpp` provider (`uv run meme pull`, T=0,
   grammar-constrained) is the product. The zero-dependency heuristic
   parser is demoted from "a voice" to an internal tool: it remains useful
   for fuzz/property tests and as a fast sanity path in CI for the IR-
   and codegen-side test suites (which don't need the frontend at all,
   since those tests construct IR directly). It must never be the thing
   that dictates which phrasings are legal, and WRITING_GUIDE text pinned
   to "heuristic-parseable" phrasing gets rewritten to the real contract:
   *phrasing humans produce*. This dissolves the report's §5.1 two-voices
   problem: there is one authoring voice (free English), one canonical
   form (the decompiled Structured English already in `build.lock` —
   which remains the layer for teaching/diffs/explaining), and one
   frontend (the GGUF model, seeded with the locked examples as few-shot
   curriculum, BM25-retrieved as today).
   **Consequence for the roadmap:** the builder's biggest projected
   workstream — "expand the regex parser to the documented voice" — is
   deleted. Frontend effort goes to system-prompt curriculum, retrieval
   examples, and ambiguity-trigger tuning instead.
   **Consequence for tests:** any test of the *language surface* (as
   opposed to IR verifiers/codegen) runs with the local model available;
   determinism at T=0 and locked IRs keeps this sane.

2. **The lockfile locks a set of files, not one file.** Modules are
   first-class: a program is a file set with an import graph,
   `build.lock` keys on that set (per-file SHA-256s plus a combined
   program hash), and resolution choices bind to the combined lock. This
   deliberately supersedes the earlier draft's "no lockfile architecture
   change" bar: the *mechanism* (resolve-once, replay forever, zero-LLM
   rebuild) is untouched; what changes is what it covers. Ambiguity
   resolution for shared units is persisted such that two programs
   importing the same unit with different resolutions stay independent.
   This is the seam the future Rails layer (schemas, controllers, models
   as separate files) actually needs, so doing it at core-phase E rather
   than late is the point.

3. **Locked-surface compatibility is by regeneration, not immutability**
   *(call made under delegation — the human chose "whichever is better
   for workflow")*. Semantics-improving changes (RNG unification,
   `fail` exit codes, silent-defaults rework, module lockfiles) trigger a
   one-time regeneration of all `build.lock`s, corpus sidecars, and
   expected outputs, with the diffs reviewed as part of the phase's
   checklist. No compat shims, no per-entry schema versioning, no frozen
   locks: this is a language under construction whose examples are the
   compiler's curriculum — keeping stale semantics to honor old locks
   would poison the retriever and the docs. The lockfile manager gains a
   schema version field solely so regeneration can be detected, not to
   support dual semantics.

4. **JSON persistence decodes into user-defined records from the start.**
   The file-I/O surface (Phase A) is designed once for the real need:
   reading a JSON file of typed records (field names verified against the
   record definition, deterministic error behavior on missing/mistyped
   fields, identical across targets) and writing records/lists/maps back
   out. Persisting scalars-only would have Phase A's surface redesigned
   twice. The todo probe's save-file is the acceptance case: a list of
   task records round-trips on all three targets byte-identically.

5. **The todo probe is co-written, spec-first.** Before Phase A's verbs
   are built, the human and builder settle (a) the command surface of the
   todo app and (b) its save-file path-and-format — as a short spec the
   human approves. The human writes the *first* draft `.meme` source in
   their own rough English (that's the point of idea-first authoring);
   the builder refactors it into the canonical teaching example, locked
   into `examples/` so its phrasings join the retriever curriculum.
   Phase acceptance = the human's phrasings compile and behave; the
   builder re-authoring the probe on the human's behalf is the failure
   mode this sequencing exists to prevent.

6. **Envelope: months.** Sequenced as a deliberate multi-phase effort with
   the todo probe as the recurring acceptance gate, not a sprint.

### Decided earlier (kept, may be challenged if planning surfaces trouble)

7. **Ambiguity default softens to auto-resolve-then-must-ask.** Candidate
   halting stays for true semantic forks (the README example remains a
   legit case). But *layout* choices with no behavioral difference
   (e.g., copy-versus-in-place when only one reading typechecks at all,
   or the sort-into normalization case) become silent auto-resolutions
   recorded in the lockfile like anything else, not interruptions.
   Rationale: the writer's tax must go to zero for interpretations
   a reader would never fight over.

8. **No writer-facing typing ceremony.** Where Ruby already relies on
   inference, Memelang relies on inference *harder*. Type annotations
   stay available for clarity in canonical form and for functions, but
   the compiler should handle prose programs with zero annotations.

9. **The silent exactness debt is fixed, not regretted.** Silent defaults
   (`Int`, `List<Int>`, `Map<String,String>` parse-time catch-alls —
   report §5.2) become *deterministic derivations with visible canonical
   form* — the `meme explain` surface already shows canonical; that's
   where the writer verifies what was understood. The verifier's *checks*
   on those derived types get stricter, not looser.

10. **Exit code semantics are part of the language contract.** `fail` gets
    a proper failure exit code on all targets (today it exits 0 — report
    §5 and codegen refs). Exit-code parity is a cross-target parity test,
    full stop.

11. **Random sees a seed.** The three RNGs (Python `random`, hand-rolled
    xorshift, `mt19937_64`) get one shared deterministic algorithm —
    optional reseeding as a verb ("seed the randomness with N") — so tests
    can pin behavior and todo saves reproduce.

12. **Every feature is the 7-artifact bundle.** From the report's §8, any
    core feature must land as: IR node(s) + verifier rules + canonical
    decompiler + Python/Rust/C++ codegen + parity test + frontend
    (system prompt + retrieval examples) + locked example + docs. A
    feature missing any of these is not done. The `examples/advanced/501-509`
    records batch is the standing model of what "done" looks like.

### Cross-target parity surface (pinned so the builder isn't guessing)

- **Byte-identical across Python/Rust/C++, always:** successful-program
  stdout; `fail` message text and its exit code; file/JSON error message
  text; formatted-output rendering of bool/list/map/record values (the
  `_meme_fmt` family — already true today, extended to every new node).
- **Deliberately not parity obligations:** RNG sequences without an
  explicit seed (obligation only when reseeded); wall-clock-dependent
  output; toolchain-specific panic/traceback text for cases the verifier
  rules out anyway.
- **Prompt text** (from `read input`) stays on stdout with the existing
  semantics — a corpus-runner concern, not a language one — but gains a
  documented suppression switch for script composition and testing.

---

## 7. Phased Scope

Sequencing is the builder's call except where acceptance criteria pin it.
The phases exist so the todo-probe gets the question "can it persist and be
a real CLI?" answered as early as possible.

### Phase A — The driver surface (Tier 0: make programs able to touch the world)

- File I/O verbs: write, append, read-as-text, read-as-typed-JSON
  (generalizing the existing `read_json_list` — **including decoding into
  user-defined records**, verified against the record definition with
  deterministic cross-target error text, per §6.4), file existence,
  delete/rename
- Command-line arguments ("the first argument", "the argument after X")
- Environment variable read
- Clock/date (at minimum: current time as seconds; leap-year isn't core)
- `fail` = non-zero exit; explicit `exit with code N`
- Prompt-free input option (suppression or one flag nobody has to type)
- *(Prerequisite for this phase, settled before the first verb ships: the
  co-written todo spec — command surface and save-file format — per §6.5)*

**Phase A acceptance:** the todo program can read its own save-file, mutate
it, write it back, exit non-zero on malformed input, and take arguments.

### Phase B — Control-flow completeness

- `break`/`continue` (IR nodes + verifier loop rules + 3 codegens)
- `switch`/dispatch form
- Error channel: raise/rescue-shape with typed values ( decidated §6.5's
  contract), decompiles canonically
- Loop-with-index and negative indices as 1-based English
- Compound assignment where prose suggests it ("add 3 to the counter,"
  "double the length")

**Phase B acceptance:** a todo app can early-exit its menus, dispatch on
commands cleanly, and handle a missing save-file as a *value* not a halt.

### Phase C — The batteries: strings, collections, formatting

- The full string toolbox (§5 string row)
- Map iteration; (key, value) pairing verbs; the copy-flavor of
  collection verbs; list slicing
- Controlled multi-slot formatted output (`print the line where the N is
  replaced by the count` shape or equally natural)
- Optional/none-checking shape (generalized `default`)

**Phase C acceptance:** todo output is pretty enough to want (aligned
columns, done/undone markers), tasks shaped as records have full
string/toolbox ability to describe what happened to them.

### Phase D — Functions as values

- Function literals in prose ("define double with n, return n times two")
- Function-typed values passed to/returned from functions
- The Enumerable verbs gain predicate/action arguments in the authoring
  voice (`map`, `select`, `find`, `count`, `min_by`, `sort_by`)

**Not in scope for D:** full closures (capturing outer locals) unless
planning determines otherwise; function *references* are the core parity
need. The reason: Ruby core utilities rarely need closures-capturing-state
once `map`/`select` etc. accept literals.

**Phase D acceptance:** a todo app body reads *like* Ruby idioms rather
than like index-juggling.

### Phase E — Modules and the file-set lockfile

- Module surface with imports; scoping hygiene so utilities can be
  organized as real projects
- The **file-set lockfile rework** (§6.3, decided): `build.lock` covers a
  program's file set (per-file SHA-256s + combined program hash),
  resolutions bind program-wide, rebuilds stay zero-LLM, and two programs
  importing the same unit with different resolutions stay independent
- Record/module composition seam (clean base for the future Rails layer)
- The shared type-grammar story (the closed prose type vocabulary grows
  enough to cover function values, the error channel, and optionals —
  report §2.2's `MemeType = str` housekeeping)

**Phase E acceptance:** a todo app organized as modules reads like a
multi-file project and rebuilds from its lockfile with zero LLM calls.

### Phase F — Hygiene, honesty, and determinism hardening (runs throughout, lands at end)

- WRITING_GUIDE rewritten to the single-frontend contract (§6.1):
  human-produced phrasing is language; the "heuristic-parseable" voice
  stops being the documented authoring path; Quick Rules Card idioms
  become real-language examples with locked sidecars
- Heuristic regex frontend demoted to internal test/fuzz use only
- System-prompt curriculum and BM25 retrieved-example families grown per
  phase, so each new feature ships with teaching examples
  (part of the 7-artifact bundle, §6.12)
- Silent-defaults rework (§6.9)
- Inline comments tokenization
- The 8 known cross-target divergences from report §5.3 (NaN spelling,
  ±2^53 float print cutoff, sort stability, clamp-with-variable-bounds,
  foreach-with-append, negative slices, mixed-type `+` handholds, JSON
  bool handling) — each must either be fixed or made *explicitly part of
  the language's documented semantics*, and parity tests must forbid
  silent regressions
- One RNG story (§6.11)
- Ambiguity-resolution prose UX (the candidate that describes bounds
  `[1,10]` while the writer meant other numbers — report §5.4)
- One-time lockfile/corpus regeneration executed under §6.3's policy,
  diffs reviewed as a phase checklist item

**Phase F acceptance:** the report's Tier 2 findings list resolves to zero
open items or standing documented decisions.

---

## 8. What is Left to the Builder

Deliberately given to the builder's plan (do not come back to the human
for these):

- Exact IR node designs and prose-to-node mapping patterns for each phase
- Verifier rule implementations, the precise auto-resolution heuristics
  and their ordering
- How the demoted heuristic (§6.1) stays useful as a fuzz/property-test
  fixture, and how IR-side tests stay model-free
- The file-set lockfile redesign internals (hash strategy, per-program vs.
  per-unit resolution binding — design decided in §6.3; representation is
  the builder's)
- The canonical decompiler layouts for each new node family
- Codegen decisions per target (e.g., `Try`/`Either` representation in
  Python vs. Rust vs. C++ internals)
- The `MemeType` type-grammar implementation (SOX-JSON Schema vs. custom)
- Test-strategy consolidation for cross-target parity (currently
  `tests/test_codegen_targets.py` parametrizes ~15 property tests; how do
  the new features' parity tests live alongside unlocked vs. locked
  examples?)
- Bookmarking phrasing families for the BM25 retriever as locked examples
- Whether each of Phase F's items lands with their phases or at the end

## 9. Open to the Human (only if planning forces the question)

Anticipated but not blocking:

- Whether the **constant/mutable distinction** should exist (Ruby freezes
  nothing by default; Memelang's verbs make whole-list mutation honest) —
  deferred to build
- If Phase D discovers the return-path/type-checker overflow ("does not
  return on all control paths", nested-bans) whether closures change the
  verifier's architecture enough to matter — raise only if it changes
  *what gets built*
- Naming of any new prose constructs in user-facing docs (implementation
  may choose neutral-thought working names internally)

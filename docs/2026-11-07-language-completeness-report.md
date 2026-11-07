# Memelang Language Completeness Report

**Date:** 2026-11-07
**Question:** What can Memelang express today, and what must be implemented for it to be a *complete* language?
**Method:** Full read of the compiler pipeline (`src/memelang/`, ~7,900 lines), test corpus, and docs. Every gap below is grounded in a specific file:line — nothing here is speculative.

---

## 1. Executive Summary

Memelang is a working end-to-end compiler that reliably turns two dialects of English into a strictly-typed IR and emits byte-parity Python/Rust/C++ for a large documented surface. The core loop — synthesize, verify, lock, codegen — is genuinely solid, and the ambiguity-halt contract is the project's most distinctive and valuable idea.

But measured against "a complete language," the gap inventory falls into three tiers:

1. **Tier 0 — driver-level I/O.** A program cannot *respond to its environment*: no file writing, no reading text files, no command-line arguments, no environment variables, no clock, no meaningful exit codes (`fail` exits **0**). Because of this, a terminal todo utility — @-user's planned test vehicle — **cannot persist state or accept flags today.** This is the single biggest completeness gap.
2. **Tier 1 — construct-level gaps.** No `break`/`continue`, no first-class functions/closures, no error channel (`try`/`catch`/`Result`), no modules/imports, no string toolbox (`contains`, `replace`, `upper`, `split`…), no `switch`, no Optional, no generics beyond `List`/`Map`, no map iteration, no compound assignment.
3. **Tier 2 — honesty and parity debt.** The documented "Quick Rules Card" promises conversational idioms the offline heuristic parser cannot handle (`define x from user`, `item last`, `sort A into B`, `empty` bareword, `set x as y`, inline comments). Silent type defaults (`Int`, `List<Int>`, `Map<String,String>`) exist without warnings, and eight known output divergences between the three targets are sidestepped rather than fixed.

One structural observation runs through everything below: **completeness in Memelang is a three-way contract** — IR schema *and* verifier *and* three codegens (+ canonical decompiler + both voices of the parser) must all agree. Every new feature is 3-7 artifacts, not one. This should be planned for explicitly.

---

## 2. Where the Language Stands

### 2.1 What works and works well

- **The pipeline as designed.** English → JSON-schema-constrained synthesis (T=0, deterministic providers: heuristic offline / ollama / openai-local / llama-cpp / gemini) → Pydantic-strict IR (`extra="forbid"`) → static verifier → SHA-256 lockfile with zero-LLM rebuilds → codegen. Exactly as the README promises.
- **Type system.** `Int`/`Float`/`Bool`/`String`/`Void`, recursive `List<T>`, `Map<K,V>` with scalar K (Int/Bool/String keys), user-defined records with field mutation, all statically verified with exact-type call arguments and return-path analysis (`analyzer/verifier.py:441-1189`).
- **Control flow.** `if/elif/else` (desugared to nested ifs — a *decent* IR-level design), `for each`, inclusive `for from/to`, `while` — all three codegens (`codegen/*.py`).
- **9 list verbs** with parity across targets: sort (in-place & copy-into), clamp, filter (in-place), append, insert, set-index, length, indexing.
- **Records & maps** work end-to-end in all 3 targets, shown by the locked `examples/advanced/501-509` batch, including record→Map function plumbing.
- **Recursion** is supported and verified (funcs registered before body check, `verifier.py:1086`; demonstrated by corpus `cs103/251_bst_inorder_traversal`).
- **Ambiguity machinery.** Deterministic, user-resolvable, lockable (`--resolve stmt=option`), with re-canonicalized candidate snippets. This is a real language feature, not a demo.
- **Data-plumbing realism.** 491 corpus scripts across cs101–cs106, integer division normalized to C-semantics everywhere with generated helpers (`_meme_int_div/_meme_int_mod`), record/map/list float formatting mirrored per-codegen, cross-target byte parity asserted by `tests/test_codegen_targets.py:864-892` over all 9 advanced examples.

### 2.2 The expressiveness ceiling (the IR node inventory)

The IR is the language's hard ceiling — the canonical decompiler refuses anything else:

**19 expression nodes:** `literal`, `list_literal`, `var_ref`, `random_int`, `random_list`, `binary_op` (13 operators: `+ - * / % == != < <= > >= and or`), `unary_op` (`-`, `not`), `list_length`, `list_index`, `call`, `read_input`, `str_ends_with`, `read_json_list`, `string_length`, `string_slice`, `record_literal`, `record_field`, `map_literal`, `map_get` (+`default`), `map_has_key`.

**19 statement nodes:** `var_decl`, `assign`, `sort_collection`, `clamp_collection`, `filter_collection`, `list_append`, `list_insert`, `list_set_index`, `fail_stmt`, `print_stmt`, `if_stmt`, `for_each`, `for_range`, `while_loop`, `func_def`, `return_stmt`, `record_def`, `record_set_field`, `map_set`.

Notably missing node kinds: file-write/append, argv/env access, string library, `break/continue`, `switch`, try/catch, module/import, functions-as-values, map iteration.

### 2.3 What a "complete language" checklist demands that's missing

Derived by diffing the inventory above (§2.2) against the feature floor of modern imperative languages (Python/Rust/Go/C++/JS) plus shell-driver realism:

<details>
<summary>Detailed gap-by-gap table (click to expand)</summary>

| Capability | Status today | Where it breaks |
|---|---|---|
| Write/append/delete/rename files, file existence, read text file | Absent (only `read_json_list`, hardcoded `List<Float>`) | `ir/schema.py:152-154`, roadmap item "runtime output saving" |
| Command-line arguments (`argv`) | Absent | No IR node can reach argv; programs are stdin-only |
| Environment variables | Absent | Same |
| Clock/date/`sleep` | Absent | — |
| Meaningful exit code on `fail` | `fail` = print + **exit 0** everywhere | `codegen/python_gen.py:312-316`, `rust_gen.py:389-393`, `cpp_gen.py:395-399` |
| `break`/`continue`/early loop exit | Absent at all layers | schema.py:392-413 (no node); only escape is outer-function `return`/`fail` |
| `switch`/`match` | Absent | Desugars only to nested `if` |
| `try`/`catch`, Result/Either types, exceptions | Absent | Only `fail_stmt` print-and-stop; verifier bans mixed-return-type branches |
| `Optional<T>` / nullable / `None` | Absent | Only `map_get default` workaround |
| String `contains` / `startsWith` / `replace` / `upper` / `lower` / `trim-as-value` / `split` / `join` / `indexOf` / `charAt` | **Almost nothing** — only `str_ends_with`, `string_length`, `string_slice` (charAt improvised as slice in corpus) | schema.py:140-159 |
| Compound assignment (`+=`, `*=`), bitwise/shift ops | Absent | `BinaryOperator` enum (schema.py:10-24) has no space for them; updates must fully re-compute the expression |
| First-class functions, closures, lambdas, higher-order verbs | Absent | `verifier.py:1065-1066` bans nested `func_def`; a `var_ref` to a function name is an undeclared-variable error |
| Modules / imports / namespaces | Absent | Single flat top-level namespace; functions can't be imported |
| Iterating a `Map` (`for each … in map`) | Absent | `ForEachStmt` is List-only (`verifier.py:1029-1033`) |
| `for i, item in …` (loop-with-index) | Absent | Corpus works around by manual counter |
| Negative indexing (`list[-1]`, `s[-1]`) | Banned | verifier.py:616-624, 692-705 |
| List slicing (strings only), list skip/take | Absent | only `string_slice` exists |
| Deep record mutation (`set a.b.c to …`) | Absent | heuristic `:1087-1091` targets one-field depth only |
| Variadic / optional / keyword function arguments | Absent | exact-arity, exact-type enforcement |
| Generics beyond built-in `List/Map` | Absent | Type universe is a closed prose set (`MemeType = str` enforced by verifier) |
| Deterministic/reseedable RNG | Absent | 3 different RNG algorithms cross-target (Python random vs xorshift vs mt19937_64) — semantics legitimately differ |
| Recursive file/directory access | Absent | Beyond roadmap |

</details>

---

## 3. Tier 0 — The gaps that make it a "toy driver"

The largest single-category finding. Memelang programs cannot today:

1. **Persist data.** There is no way to write to a file. A todo list, a config file, a CSV export, an event log, a save-file, a state flag — all impossible. (Reading is limited to one narrow fixture-style builtin that always coerces to `List<Float>`).
2. **Accept arguments.** No `argv` access of any kind. Because of #1 and #2, a terminal CLI todo utility is structurally unbuildable — it must be either interactive-loop-only, test-only (stdin-driven), or paired with a host-language shim that feeds it stdin.
3. **Read general text.** Only `read_json_list`. No line-dataset reading, no arbitrary file string read, no file-existence check.
4. **Tell the shell anything.** `fail` exits 0 — "failure" and "success" are indistinguishable to any script driving `meme`. The corpus even relies on this behavior (test `find-largest`, `:351-543`). Exit codes should be a first-class language concept: exit success/failure on `fail`, plus an explicit "exit with code N" verb.
5. **Talk to the OS clock.** No date/time, no sleep, no timing.
6. **Use standard string shaping** (`uppercase`, `replace`, `contains`) for any real CLI polish.

> **However — the biggest *test-vehicle* blocker** (to @-user's todo-app design) is the **prompt-pollution finding**: `read_input` writes its prompt text to stdout with no way to suppress it, forcing the corpus runner (`scripts/run_corpus.py:163-289`) to post-strip every prompt line from captured output. For an interactive todo (where prompts *are* part of the UX) this is fine for humans but bad for testing and for script composition.

---

## 4. Tier 1 — Construct-level gaps (the "complete language" core)

These are the standard tools of modern imperative languages and should be priority 1 after Tier 0:

1. **`break` / `continue`.** The absence of any early loop exit is the most surprising gap. Loops run to completion, always — unless a `fail` kills the whole program. Consequences: any nearest-hit / binary-search / sentinel scan in the corpus (`cs102`, `cs103`) must be implemented as a loop-long condition instead of a break. This is a real expressiveness loss, not a stylistic one, and deserves an IR node (`loop_break`, `loop_continue`) with verifier loop-scope rules.
2. **An error channel.** Only two failure modes exist: `fail_stmt` (print, exit 0) or a return-path error. There is no `try`/`catch`, no `Result<T, E>`, no typed union return. `else return "Wrong File Type"` is routinely faked in the corpus as a `fail_stmt`. This is a design trade-off worth hashing explicitly: introduce either (a) a formal `Result`-like optional channel in the return type, or (b) an `Optional` type. Both have significant verifier + codegen + canonical design work attached.
3. **`switch` / `match`.** Only nested-if exists today. For a language whose pitch is *contractity*, a proper `match` would be a top-3 UX gain.
4. **A real string toolbox.** `contains`, `startsWith`, `replace`, `upper`/`lower`, `trim`, `split`, `join`, `indexOf`, `charAt` as verbs are what make a web/CLI utility worth writing. Today the language has three verbs without them (§2.2), forcing documented workarounds like slicing-to-collections character comparison in `cs105/403`.
5. **Map iteration + key/value pairs.** `for each … in map` is absent (`verifier.py:1029-1033`), which matters because map lookups + manual key lists has to imitate what other languages take for granted.
6. **Compound assignment & more binary ops** (`+=`, `*=`; bitwise `& | ^ << >>`). Every corner of the corpus becomes more natural in expressions rather than `define`-rebinding.
7. **First-class function values / closures.** This is the *hard* one. It forces both a type extension (`Function<Ts…, R>`), a verifier type rule, and a real codegen story (closures vs raw pointers; `Fn trait` in Rust, `function_ref`/lambda in C++, `Callable` in Python). It is the prerequisite for `filter/map/countWhere` *as verbs* to stop needing prototype-style boilerplate. Given the language's "strict types, no guessing" ethos, the recommended scoping is **start with node-level function *references*** (`Function[T1,T2,…,R]` type, call-by-reference semantics only, no closures initially) and expand to full closures later.
8. **Loop-with-index (`for each index item in …`)** and **negative indexing.**
9. **Optional/ Savage Not-Found object.** The trickiest gap conceptually. Today's `map_get default` is a *fine* ergonomics win but doesn't represent "this returned a distinct Not-Found to signal," which Tier 0 file-missing errors, Tier 1 string-method not-founds, and Tier 2 map iteration all want.

These also *compound* with Tier 0: without argv + break + a mature string toolbox, Memelang can't host a conventional CLI at all.

---

## 5. Tier 2 — Honesty and parity debt

### 5.1 The guide promises a language the offline parser can't deliver

This is the sharpest single finding. `docs/WRITING_GUIDE.md`'s **Quick Rules Card** (`:552-576`) documents all of these as ordinary constructs:

| Documented as first-class | What the offline heuristic parser does |
|---|---|
| `define x from user "Question? "` | Hard parses fail outside LLM providers (heuristic has no pattern) |
| `list item 1` / `list item last` | Expression → "Unexpected trailing token" |
| `set list item i to v` | Statement → "Heuristic frontend could not parse line N" |
| `sort A into B ascending` | Statement → same hard failure at `:1235` |
| `s char k` | Expression → unsupported |
| `empty` bareword (declare-empty idiom) | Verifier: `Reference to undeclared variable 'empty'` |
| `set x as y` (corpus `cs103/227` uses it) | Parser only accepts `set … to` |
| Inline trailing comments (`# …`) | Hard tokenize failure (`_tokenize_expr`, `:145-193` handles no comment) |
| `length of string s` | Works only if a very specific adjacent-token guess passes (`:404-418`); `length of s` on a String is a verifier error |
| `for each` (one word) | Only `for\s+each` accepted (`:776`) — a CS101 *core fixture* `059_loop_sort_mutation_ambiguity.meme` cannot be parsed offline at all |
| `this runs in the shell` | A conversational-only *narrative header* — fails hard offline |
| LLM-voice conventions (typo healing, `to lowercase`, `stop when…`) | Implemented as prompt rules (`base.py:82-96`), invisible offline |

**Consequence:** the "two voices" architecture currently means *the contained voice diverges from the documented voice*. Either (a) the WRITING_GUIDE should be retitled/annotated — clearly stating which idioms are LLM-voice-only — or (b) the heuristic should grow a real parser for them and the corpus lockfiles should be regenerated as offline-verifiable. Today the truth is that the **heuristic voice is a real language, the conversational voice is a prompt convention** — a distinction that's load-bearing and currently invisible to users.

### 5.2 Silent type defaults with no warning

Verified at `llm/heuristic.py`:

- Unrecognized expressions: `Int` (:683 catch-all)
- Untyped lists, if inference fails: `List<Int>` (:1060-1061)
- Map literals: `Map<String, String>` (:378-379)
- Function params: `Int` (:961) — but the LLM voice promises *`Float`* (`base.py` rules) — voice-contradicting conventions.
- `for each` over unknown lists: `List<Int>` (:834-835)

One or two of these is fine; a whole family of silent defaults means type errors can be silently absorbed at parse time and only *sometimes* surface later at the verifier. This should be aligned — either always `Float` (as the voice promises) or always annotated-and-warned.

### 5.3 Cross-target divergences that parity tests currently avoid

Known-good today, but these are landmines for any future real-world adoption:

1. **`_meme_fmt` integral-float cutoff:** Python prints *any* whole-valued float as an integer (including `1e20`); Rust/C++ only within ±2^53. (`rust_gen.py:532`, `cpp_gen.py:562`)
2. **NaN spelling** differs per target (`nan`/`NaN`/`nan`). (`rust_gen.py:529-536`)
3. **Stability of `sort`** differs (Python and Rust are stable; `std::sort` is not). Visible only on partial_cmp NaN fallback (`rust_gen.py:344`).
4. **`foreach` + body append** — Python iterates a copy (`:341`), Rust clones (`:419`), C++ iterates the original container. C++ (and only C++), will see appended items. This is an *inconsistency about an already-reported class* (loop-collision ambiguity detector only catches `sort`/`clamp`/`filter`/`append` on the run-list).
5. **Clamp with variable-inverted bounds** (`lo > hi` via variables) — Python yields `hi`, Rust yields `lo`, C++ skips the clamp entirely (`cpp_gen.py:360`). Verified unguarded when the bounds are expressions instead of literals.
6. **JSON list reading** is hand-rolled and non-JSON-conformant in Rust/C++ (a bracket check + comma split, `rust_gen.py:615-668`, `cpp_gen.py:718-769`). Bools are silently *skipped* in Python (`py:468`) but would be hard errors in Rust/C++. String lists beyond Float are impossible at the type level.
7. **Prompt text on stdout with no suppression** — a *protocol* problem, not a formatting one, since every downstream test has to strip prompts manually.

### 5.4 Verifier-level quirks worth reviewing before building anything new on them

- The verifier silently *normalizes* `sort A into B` rather than flagging it as ambiguous — semantics-history-sensitive and heuristics-only (`verifier.py:1351-1406`). In an ambiguity-first language, this is the one feature that breaks the contract.
- `filter` is **in-place only**; the guide's "define evens as each n in list where" is an LLM-voice re-expression, not a construct.
- Loop-collision ambiguity candidates contain **hard-coded** "[1, 10]" bounds in their *descriptions* (`verifier.py:341-342`) even when the clamp's actual bounds are different expressions.
- `empty_random_list` ambiguity recovery depends on the *exact* shape of a sibling declaration and silently degrades.

---

## 6. Tier 3 — Ecosystem / DX gaps (matters for the todo-app test vehicle)

| Need | Today |
|---|---|
| Interactive stdin loop with clean output | Works, but prompt string also lands on stdout and can't be suppressed |
| Exit code distinct from success | `fail` = 0; nothing else distinguishes |
| State across invocations | Impossible (no file write) |
| Command flags (`todo list`, `todo add "…"` | Impossible (no argv, no arg-parsing constructs) |
| Deterministic (?) output for tests | Possible, except random |
| A REPL or persistent session | Not in scope for the language, but "runtime output saving" (roadmap) touches it |

---

## 7. What must be built, in order

### Phase 0 — Trivial quality wins (do these while planning anything bigger)

1. **Align the WRITING_GUIDE** with what the heuristic actually parses; mark each idiom LLM-voice-only vs offline.
2. **Kill silent type defaults**; error or warn on every catch-all (`Int`/`List<Int>`/`Map<String,String>`).
3. Fix **inline comments** tokenizer support.
4. Make **`fail` exit non-zero** or add an explicit `exit with code N` statement — this alone makes the language usable from bash.
5. Fix the **prompt-on-stdout** floor (a suppress-prompt flag, even if not the default).
6. Fix misleading hard-coded ambiguity prose (`[1,10]`) and decide whether sort-into normalization is a contract feature or a bug.

### Phase 1 — Tier 0: the driver surface

The only path to "anything real" and the direct enabler of the terminal todo utility.

7. **`write file` / `append to file` / `read string from file` / `file exists`** — 4 new IR nodes, verified for type/arg validity, emitted in all 3 targets, decompiled canonically. Lockfiles must be previewed for all 4.
8. **`argv` / environment access** — either a built-in `argv` list-of-strings expression or a dedicated `command word n` node.
9. **`exit with code N` / sets the "meaningful exit code" contract.**
10. Fix `read_json_list`, generalizing to `read JSON list of <T>` or a proper stdlib mini-JSON wrapper.

### Phase 2 — Tier 1: language-critical constructs

11. `break`/`continue` (schema + verifier loop rules + 3 codegens + canonical).
12. String verbs: `contains`, `startsWith`, `replace`, `upper`, `lower`, `trim`, `split`, `join`, `indexOf`, `charAt`.
13. Map iteration; loop-with-index; negative index rules.
14. `switch`/`match`.
15. **Error channel decision**: choose `Result<T,E>` or `Optional` and mirror it through verifier + all codegens + canonical.
16. Compound assignment & a fuller op enum.

### Phase 3 — Tier 2: stretch goals

17. `Function[...]` values (no closures first), then closures if demanded.
18. Modules/imports (urgent for anything over ~300 lines).
19. A documented/generics story, current exact-arity call plus lists/maps.
20. Sort stability, clamp bounds, foreach-with-append, NaN formatting — *the parity contract* should grow property tests that forbid silent divergence from day one, instead of absorbing them into an already-reported-diff bucket.

---

## 8. The Design Principle This Report Should Impose Going Forward

Every Tier 0/1 feature is actually **3-7 coordinated artifacts**, not one:

1. IR schema node(s) (`src/memelang/ir/schema.py`)
2. Verifier type/scope/ambiguity rules (`src/memelang/analyzer/verifier.py`)
3. Canonical decompiler update (`src/memelang/ir/canonical.py` — it currently raises `TypeError` on unknown nodes, so it's a hard gate, not a soft one)
4. Codegen ×3 (`codegen/python_gen.py`, `rust_gen.py`, `cpp_gen.py`) with matched runtime helpers
5. Cross-target output-parity test (`tests/test_codegen_targets.py`)
6. LLM system-prompt / heuristic parser update (the *frontend* is still part of the language's "real surface")
7. Locked corpus examples + docs update

> **Consequence:** add feature-by-feature *checklists*, not tickets. A feature isn't "done" until all 7 artifacts land *and* a locked example demonstrates it across all three targets. This is exactly what `examples/advanced/501-509` already does for records — the model was proven by that batch; it should be institutionalized for every new feature.

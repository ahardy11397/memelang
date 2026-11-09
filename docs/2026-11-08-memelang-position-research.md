# Memelang: What It Is and What It Could Become

**Date:** 2026-11-08
**Question:** Memelang started as a joke. Is there something real here? Do we
need the LLM? Can it be self-hosted AND transpile to other languages? What
about Go or TypeScript targets?

---

## 1. What was actually built (strip the joke away)

After three days of development, Memelang is a **deterministic, multi-backend
compiler for a strictly-typed imperative language with an English surface
syntax**. The load-bearing pieces:

1. A JSON-schema-constrained synthesis step that turns English into a
   Pydantic-strict IR (500+ corpus scripts prove the pipeline).
2. A static verifier with exact-type checking, return-path analysis, and —
   the distinctive part — **deterministic, user-resolvable ambiguity reports**
   instead of silent guesses.
3. SHA-256 lockfiles giving **zero-LLM reproducible rebuilds**.
4. Three codegen backends (Python, Rust, C++) with **cross-target byte-parity
   tests** — not "similar output", identical output.

Each of these is a known-good compiler-architecture idea. What is not
standard is the combination: ambiguity made first-class, and
write-once/verify-everywhere as an enforced contract rather than a hope.

## 2. Prior art — the English-like graveyard, and the survivors

**COBOL (1959)** was explicitly designed so business code read like English,
drafted by a government-industry committee [7]. It succeeded enormously as a
language but failed at its *ambition*: the English surface became rigid,
verbose boilerplate — you wrote English-shaped tokens with none of English's
flexibility. Lesson: unconstrained English syntax is a dead end; the syntax
must be canonical and the *flexibility* must live somewhere else (the
frontend, not the grammar).

**Inform 7 (2006)** is the most successful genuinely natural-language
programming language — its "chief originality is that it is based entirely on
natural language" [8]. But it thrives only in one niche (interactive
fiction), and practitioners note it is not really "programming in English" —
it is a precise grammar wearing English clothing. Which is exactly what
Memelang's canonical form is.

**The 2026 difference:** every prior English-like language failed or
niche-shrank because the *human* had to memorize what was legal. An LLM
frontend inverts this: the human speaks loosely, the LLM writes canonical
Memelang, and the deterministic core guarantees the semantics. The
English-like dream fails without a translator; LLMs are the translator that
did not exist in 1959 or 2006.

## 3. The LLM research landscape — and why Memelang is aimed at the exact gap

Three findings from current research frame this precisely:

- **LLM code generation is non-deterministic even with identical prompts** —
  "a high degree of variability in LLM-generated code, even when prompted
  with identical inputs" [4]. Teams cannot build reproducible software on
  that.
- **Ambiguity is the failure mode**: LLM-based code generation "fails" under
  ambiguous requirements rather than asking — the model picks one reading
  silently [3].
- **The research answer is intent-discovery + proof of conformance**: generate
  code, spec, and tests from the same description, then repair them to
  consistency so the discovered intent becomes unambiguous [1].

Memelang already implements the third finding's *shape*: ambiguity is
surfaced and resolved by the user (`--resolve stmt=option`), the resolved
intent is frozen in a lockfile, and the verifier enforces conformance on
every rebuild. In research terms, Memelang is an **assured-programming
frontend**: it moves LLM non-determinism to write-time only, where a human
is watching, and keeps build-time fully deterministic.

**Do we need the LLM? No — and that's the point.** The completeness report
already proved the deterministic heuristic parser is the real language. The
correct positioning:

- The **LLM is optional sugar** — a dictation/transcription layer for people
  who won't learn canonical syntax (or use voice input).
- The **language is the canonical form** — what the heuristic parser accepts.
- As the canonical surface grows, the LLM's share of the pipeline shrinks.
  Zero-LLM rebuilds already work; the goal is zero-LLM *writes* becoming
  practical for simple programs.

This is the inverse of every "AI coding assistant": assistants generate
unverifiable code that drifts; Memelang generates verified code that
freezes.

## 4. Self-hosting and transpilation — the architecture already says yes

Memelang's design is the standard multi-backend compiler shape, and that
shape is proven: **Haxe** transpiles one source language to many targets
including JavaScript [5]; **Nim** compiles one language to C, C++, and
JavaScript backends [6]; **CrossTL (2025)** demonstrates a unified IR
serving many languages with "new languages requiring only frontend and
backend components" [2]. Memelang's difference is that its IR is small
(19+19 node kinds), strictly typed, and *already* parity-tested across
backends — most multi-target projects don't enforce byte-parity at all.

So: **can it be its own compiled/interpreted language AND spit out other
languages? Yes — that is what it already is.** The IR is the language; the
targets are interchangeable. Three concrete milestones, in order of value:

1. **A native runtime story**: a `meme run` interpreter or a Memelang→C
   backend would free programs from depending on Python toolchains at all.
2. **Self-hosting** (the compiler written in Memelang): the classic
   credibility milestone — but a late one, gated on modules/imports, an
   error channel, and first-class functions (Phase 2B/3 in the completeness
   report).
3. **The compiler decompiled to canonical form** is already half-built: the
   canonical decompiler means every program has a deterministic
   representation, which is what makes long-term maintenance of the
   toolchain tractable.

## 5. Go and TypeScript targets — cheap wins, in this order

Per the completeness report's 7-artifact rule, a new target is one codegen
file + runtime helpers + parity tests — not a rewrite. Concretely:

- **Go — recommend first.** Static types map 1:1 to the IR (slices, `map[K]V`,
  structs for records), single-binary output matches the Tier 0 "driver
  surface" positioning (CLI tools), and Go's `sort` is deterministic for
  basic types. Estimated: one agy run, comparable to the Phase 1 batch.
- **TypeScript — recommend second.** Maps/records are natural, but `number`
  is a float: the Int/Float formatting parity work (`_meme_fmt`) needs care,
  and `console.log` formatting differs. Still very tractable; unlocks web
  use.
- C — also cheap (existing C++ backend is 80% of the work) and completes the
  "no runtime anywhere" story.

The parity-test harness from `tests/test_codegen_targets.py` extends to any
new target unchanged — that harness is the asset that makes targets cheap.

## 6. What it could become — three honest futures

1. **The LLM-era specification language** (the ambitious one): "write the
   program once in constrained English, compile it to verified Python, Rust,
   C++, Go…" — the fix for teams maintaining the same logic in three
   languages. Differentiator vs. CrossTL/Haxe: ambiguity-halt + lockfile
   provenance. Nobody in the prior art resolves ambiguity *with the user*
   and freezes the resolution.
2. **The teaching language** (the practical one): strictly-typed, English-ish,
   fails loudly instead of guessing, compiles to languages students actually
   use. The completeness report's cs101–cs106 corpus is already a curriculum
   skeleton.
3. **A personal polyglot tool language** (the modest one): exactly what the
   roadmap targets today — write a CLI tool once, get it in whatever
   language the host project needs. The todo app is the test vehicle.

The failure mode to avoid is drift between the documented language and the
implemented one (report §5.1) — the two-voices problem. Every future in this
list depends on the deterministic parser remaining the single source of
truth.

## 7. Recommended order

1. Phase 2B (switch/match, error channel, compound assignment) — already queued.
2. Go target.
3. Modules/imports (the report calls it urgent past ~300 lines).
4. TypeScript and/or C targets.
5. Native runtime (interpreter or C backend).
6. Self-hosting — last, as a proof, not a prerequisite.

## Sources

[1] https://arxiv.org/html/2410.18494 — Assured Automatic Programming via Large Language Models
[2] https://arxiv.org/html/2508.21256v1 — CrossTL: A Universal Programming Language Translator with Unified IR
[3] https://arxiv.org/html/2604.21505v3 — Understanding LLM-Based Code Generation under Ambiguous Requirements
[4] https://orbilu.uni.lu/bitstream/10993/66851/1/First_paper.pdf — Revisiting the Non-Determinism of Code Generation by LLMs
[5] https://haxe.org/manual/target-javascript.html — Haxe Manual - JavaScript target
[6] https://nim-lang.github.io/Nim/backends.html — Nim Backend Integration
[7] https://www.i-programmer.info/history/57-computer-languages/472-part-2-the-1960s.html?start=2 — Computer Languages by Committee - the 1960s (COBOL)
[8] https://ganelson.github.io/inform-website/talks/2018/06/09/london.html — Assessing Inform (London 2018 talk)

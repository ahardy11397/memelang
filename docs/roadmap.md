# Memelang Roadmap

## Vision

Memelang started as a joke and is becoming a real language. The test every
decision must pass:

1. **Jumping in must be as easy as possible.** Minimal dependencies, minimal
   setup — nothing between "heard of Memelang" and "writing code".
2. **Writing code must be as easy as possible.** English surface, no ceremony,
   ultimate control for those who want it.

Ultimate control is NOT a rewrite-for-its-own-sake. "Rewrite the core in C"
is a means to the single-binary, zero-dependency end state, not a goal.

## The bootstrap ladder (how the vision gets built)

Instead of a big-bang rewrite, the compiler grows out of Python one component
at a time. Each rung is a working, shipped thing:

1. **DONE — Language closes its known limits** (2026-11-24, e45833b):
   recursive records via Optional, JSON record I/O with collections and
   nested records. Nothing in the language needs a workaround.
2. **NEXT — Self-hosting step 1: Memelang tokenizer.** A full .meme source
   tokenizer written in Memelang, compiled to a dependency-free native
   binary via `meme build` (C backend). Proves compiler-grade work runs on
   the ladder; tokenizes its own source.
3. Subsequent components: canonical-form checker, then further compiler
   pieces as the language allows. Each grows the language, shrinks the
   Python core.
4. End state: compiler shippable as a single native file; Python core
   reduced to the LLM-dictation frontend (optional, swappable) or replaced.

## Deliverables on the roadmap

- [x] Six target backends with byte-parity guarantees (beta)
- [x] Ambiguity-halt + zero-LLM lockfile rebuilds (beta)
- [x] Native binaries via `meme build` (beta)
- [x] Known language limits closed (2026-11-24)
- [x] Memelang tokenizer (self-hosting step 1) — projects/meme-tokenizer, 23×6 green, self-tokenizes
- [x] Canonical checker (self-hosting step 2) — projects/meme-canonical-checker, 22×6 green, reads real lockfiles
- [x] Canonical fixer (self-hosting step 3) — projects/meme-canonical-fixer, 20×6 green, fix/preview with round-trip invariant
- [x] sha256 builtin (`sha256 of <text>`) — a7f862a, byte-identical hex digests on all six targets
- [x] Exact-freshness checker (self-hosting step 4) — projects/meme-lock-check, 20×6 green, all 39 real locks LOCKED-FRESH
- [x] Parser subset (self-hosting step 5) — projects/meme-parser, 28×6 green, parses its own source; expression grammar via precedence climbing
- [x] Canonical emitter (self-hosting step 6) — meme-parser `emit`, 47×6 green; parse(emit(parse(x)))==parse(x) invariant + idempotence, byte-identical output on all six
- [x] Unified pipeline CLI (self-hosting step 7) — projects/meme-tools, 24×6 green
- [x] Lock backfill — all offline-parseable examples locked (78dce29); remainder are LLM-voice by design, documented
- [x] Static type-checker, batch A (self-hosting step 8) — projects/meme-verify, 14×6 green, oracle-agrees with the real verifier
- [x] Verifier batch B (cross-module analysis, return paths, flow refinements) — 5bad059 + bump 25defaa, 34×6 green, 18-rule empirical evidence table
- [x] Harness subprocess timeout 15s → 60s — d16886d (big generated components need real -O2 compile time)
- [x] Copy-on-write list codegen for rust/cpp — 604d66f; value semantics kept (make_mut/clone-on-write), self-hosting benchmark 17.5s -> 0.134s (130x)
- [ ] Further self-hosting components (codegen subset from IR, ...)

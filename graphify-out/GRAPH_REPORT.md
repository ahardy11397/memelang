# Graph Report - meme  (2026-11-03)

## Corpus Check
- 58 files · ~51,249 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 609 file(s) not represented in the graph (top: .meme 606, (none) 2, .lock 1)

## Summary
- 444 nodes · 2074 edges · 20 communities (16 shown, 4 thin omitted)
- Extraction: 66% EXTRACTED · 34% INFERRED · 0% AMBIGUOUS · INFERRED: 709 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Verifier & Ambiguity Detection
- LLM Provider Layer
- CLI & Verification Entry
- Static Verification Models
- Expression Parser
- Codegen Backends
- Corpus Runner
- Compiler Plan & Spec Docs
- Corpus Plan & Design Docs
- Corpus Integrity Tests
- IR Schema & Type System
- Rust Codegen
- Cpp Codegen
- Python Codegen
- Extensibility Axes
- Corpus Manifest
- LLM Frontend Concept
- Schema Validation Helpers
- Package Root

## God Nodes (most connected - your core abstractions)
1. `LiteralExpr` - 50 edges
2. `VarDeclStmt` - 48 edges
3. `ProgramIR` - 47 edges
4. `SynthesisResult` - 45 edges
5. `HeuristicProvider` - 42 edges
6. `VarRefExpr` - 40 edges
7. `FuncDefStmt` - 39 edges
8. `verify_synthesis()` - 38 edges
9. `BinaryOpExpr` - 37 edges
10. `_RustGen` - 36 edges

## Surprising Connections (you probably didn't know these)
- `scripts/run_corpus.py 2-Axis Gap Runner` --semantically_similar_to--> `scripts/run_corpus.py Corpus Runner`  [INFERRED] [semantically similar]
  README.md → docs/superpowers/plans/2026-11-03-cs101-103-corpus.md
- `build.lock Deterministic Lockfile` --semantically_similar_to--> `build.lock Specification`  [INFERRED] [semantically similar]
  README.md → docs/superpowers/specs/2026-11-03-memelang-design.md
- `examples/ Axis (Syntax & Library Extensibility)` --semantically_similar_to--> `examples/ Axis (Syntax & Library Extensibility)`  [INFERRED] [semantically similar]
  README.md → docs/superpowers/specs/2026-11-03-cs101-103-corpus-design.md
- `src/ Language Axis (IR & Output Target Extensibility)` --semantically_similar_to--> `src/ Language Axis (IR & Output Target Extensibility)`  [INFERRED] [semantically similar]
  README.md → docs/superpowers/specs/2026-11-03-cs101-103-corpus-design.md
- `300-Script CS 101-103 Stress Corpus` --semantically_similar_to--> `CS 101-103 Stress Corpus & 2-Axis Gap Harness Design Spec`  [INFERRED] [semantically similar]
  README.md → docs/superpowers/specs/2026-11-03-cs101-103-corpus-design.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Memelang Two-Phase Compiler Pipeline** — readme_pluggable_llm_frontend, readme_deterministic_static_verifier, readme_build_lock, readme_target_codegen [INFERRED 0.90]
- **CS Corpus Evaluation & Gap Attribution Flow** — docs_superpowers_plans_2026_11_03_cs101_103_corpus_run_corpus, tests_corpus_manifest, docs_superpowers_plans_2026_11_03_cs101_103_corpus_corpus_fixtures, docs_superpowers_plans_2026_11_03_cs101_103_corpus_outcome_buckets, tests_test_corpus_manifest [INFERRED 0.90]
- **Two-Axis Extensibility Model (examples/ vs src/)** — readme_examples_axis, readme_src_axis, docs_superpowers_specs_2026_11_03_cs101_103_corpus_design_examples_axis, docs_superpowers_specs_2026_11_03_cs101_103_corpus_design_language_axis, docs_superpowers_specs_2026_11_03_few_shot_ir_expansion_gap_analysis_design_bm25_retriever [INFERRED 0.85]

## Communities (20 total, 4 thin omitted)

### Community 0 - "Verifier & Ambiguity Detection"
Cohesion: 0.17
Nodes (59): _collect_expr_prompts(), _collect_stmt_prompts(), _branch_adds_to(), _build_loop_collision_ambiguity(), _build_lossy_partial_sort_ambiguity(), _collect_empty_list_decls(), _contains_loop_with_asymmetric_insert(), _expr_references_var() (+51 more)

### Community 1 - "LLM Provider Layer"
Cohesion: 0.08
Nodes (30): SynthesisResult, build_compiler_messages(), CompilationUnit, has_executable_content(), LLMProvider, LLMProviderError, split_compilation_units(), GeminiProvider (+22 more)

### Community 2 - "CLI & Verification Entry"
Cohesion: 0.09
Nodes (26): VerificationOutcome, _add_shared_args(), _build_parser(), _compute_source_key(), _format_ambiguity(), _load_or_synthesize_program(), main(), _parse_resolve_args() (+18 more)

### Community 3 - "Static Verification Models"
Cohesion: 0.13
Nodes (17): _check_literal_bounds(), _element_type_of(), _Scope, StaticVerificationError, verify_program(), verify_synthesis(), LiteralExpr, test_division_by_zero_and_mismatched_binop_raise() (+9 more)

### Community 4 - "Expression Parser"
Cohesion: 0.19
Nodes (8): _ExprParser, _guess_expr_type(), _parse_expr(), _refine_list_literal_types(), _SourceLine, _split_top_level_commas(), _Tok, _tokenize_expr()

### Community 5 - "Codegen Backends"
Cohesion: 0.17
Nodes (17): generate_cpp(), generate_code(), generate_python(), generate_rust(), ProgramIR, execute_ir(), ExecutionResult, program_uses_input() (+9 more)

### Community 6 - "Corpus Runner"
Cohesion: 0.16
Nodes (11): _collect_prompts(), CorpusManifest, CorpusRunSummary, CorpusScriptSpec, evaluate_script(), ExtensibilityGaps, main(), parse_id_filter() (+3 more)

### Community 7 - "Compiler Plan & Spec Docs"
Cohesion: 0.18
Nodes (15): Memelang Compiler Implementation Plan, AmbiguityDiagnostic & AmbiguityCandidate, to_canonical_meme Canonical Meme Decompiler, meme CLI (compile/run/check/explain), Deterministic Codegen Backends (python/rust/cpp), HeuristicProvider, LockfileManager (build.lock), verify_synthesis Deterministic Static Verifier (+7 more)

### Community 8 - "Corpus Plan & Design Docs"
Cohesion: 0.20
Nodes (13): CS 101-103 300-Script Stress Corpus Implementation Plan, tests/corpus/fixtures Shared Fixtures, CorpusScriptSpec Manifest Model, 8 Outcome Buckets, scripts/run_corpus.py Corpus Runner, 2-Axis Gap Attribution (examples vs language), CS 101-103 Stress Corpus & 2-Axis Gap Harness Design Spec, Authorial Memelang Voice & Style Distribution (+5 more)

### Community 9 - "Corpus Integrity Tests"
Cohesion: 0.23
Nodes (7): _load_runner_module(), test_cs101_slice_integrity(), test_cs102_slice_integrity(), test_cs103_slice_integrity(), test_evaluate_script_buckets_prompt_stripping_source_dir_and_lockfile_isolation(), test_full_300_uniqueness_examples_purity_and_cli_smoke(), test_parse_id_filter_valid_and_invalid()

### Community 10 - "IR Schema & Type System"
Cohesion: 0.24
Nodes (10): memelang.ir.schema Pydantic IR Models, MemeType Static Type System, Dynamic Few-Shot Retrieval & IR Expansion Gap Analysis Spec, Dynamic BM25 Few-Shot Retriever (memelang.llm.retriever), gap_report.json 2-Axis Report, Golden Seed Initializer (Locked Golden Examples), ListSetIndexStmt In-Place Element Assignment, 2D Matrix / Nested List Indexing (+2 more)

### Community 11 - "Rust Codegen"
Cohesion: 0.40
Nodes (3): _escape_rust_str(), _rust_ident(), _rust_type()

### Community 12 - "Cpp Codegen"
Cohesion: 0.38
Nodes (3): _cpp_ident(), _cpp_type(), _escape_cpp_str()

### Community 14 - "Extensibility Axes"
Cohesion: 0.47
Nodes (4): build.lock Deterministic Lockfile, Memelang (meme), scripts/run_corpus.py 2-Axis Gap Runner, 300-Script CS 101-103 Stress Corpus

### Community 15 - "Corpus Manifest"
Cohesion: 0.40
Nodes (4): Manifest Schema (tests/corpus/manifest.json), corpus_version, scripts, total_scripts

### Community 16 - "LLM Frontend Concept"
Cohesion: 0.67
Nodes (3): Pluggable LLM Providers (get_provider), Pluggable LLM Frontend Providers, Pluggable LLM Frontend

## Knowledge Gaps
- **6 isolated node(s):** `memelang`, `to_canonical_meme Canonical Meme Decompiler`, `HeuristicProvider`, `CorpusScriptSpec Manifest Model`, `Authorial Memelang Voice & Style Distribution` (+1 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 90 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CS 101-103 Stress Corpus & 2-Axis Gap Harness Design Spec` connect `Corpus Plan & Design Docs` to `Corpus Integrity Tests`, `IR Schema & Type System`, `Extensibility Axes`, `Corpus Manifest`?**
  _High betweenness centrality (0.130) - this node is a cross-community bridge._
- **Are the 34 inferred relationships involving `LiteralExpr` (e.g. with `_check_literal_bounds()` and `_StaticChecker`) actually correct?**
  _`LiteralExpr` has 34 INFERRED edges - model-reasoned connections that need verification._
- **What connects `memelang`, `to_canonical_meme Canonical Meme Decompiler`, `HeuristicProvider` to the rest of the system?**
  _6 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `LLM Provider Layer` be split into smaller, more focused modules?**
  _Cohesion score 0.0777928539122569 - nodes in this community are weakly interconnected._
- **Why does `scripts/run_corpus.py Corpus Runner` connect `Corpus Plan & Design Docs` to `Corpus Integrity Tests`, `Extensibility Axes`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 34 inferred relationships involving `VarDeclStmt` (e.g. with `_collect_stmt_prompts()` and `_collect_empty_list_decls()`) actually correct?**
  _`VarDeclStmt` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Should `CLI & Verification Entry` be split into smaller, more focused modules?**
  _Cohesion score 0.08778424114225278 - nodes in this community are weakly interconnected._
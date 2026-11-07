#!/usr/bin/env python3
"""CS 101-103 stress corpus batch runner & 2-axis gap attribution reporter for Memelang."""

import argparse
from pathlib import Path
import sys
import tempfile
from typing import Literal, cast

from pydantic import BaseModel, Field

from memelang.analyzer.verifier import (
    StaticVerificationError,
    VerificationOutcome,
    verify_synthesis,
)
from memelang.codegen import TargetLang
from memelang.ir.schema import (
    AssignStmt,
    BinaryOpExpr,
    CallExpr,
    ClampCollectionStmt,
    FailStmt,
    FilterCollectionStmt,
    ForEachStmt,
    ForRangeStmt,
    FuncDefStmt,
    IRExpr,
    IRStatement,
    IfStmt,
    ListAppendStmt,
    ListIndexExpr,
    ListInsertStmt,
    ListLengthExpr,
    ListLiteralExpr,
    ListSetIndexStmt,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    ReturnStmt,
    StrEndsWithExpr,
    StringLengthExpr,
    StringSliceExpr,
    UnaryOpExpr,
    VarDeclStmt,
    WhileStmt,
)
from memelang.llm import LLMProvider, LLMProviderError, get_provider
from memelang.llm.retriever import ExampleRetriever
from memelang.lockfile.manager import LockfileManager
from memelang.runner.executor import execute_ir

REPO_ROOT = Path(__file__).resolve().parents[1]

OutcomeBucket = Literal[
    "PASS",
    "AMBIGUOUS_EXPECTED",
    "AMBIGUOUS_UNEXPECTED",
    "MISSED_AMBIGUITY",
    "SYNTHESIS_ERROR",
    "STATIC_VERIFY_GAP",
    "CODEGEN_OR_RUNTIME_ERROR",
    "OUTPUT_MISMATCH",
]


class ExtensibilityGaps(BaseModel):
    examples: list[str] = Field(default_factory=list)
    language: list[str] = Field(default_factory=list)


class CorpusScriptSpec(BaseModel):
    id: int
    slug: str
    path: str
    course: Literal["cs101", "cs102", "cs103"]
    topic: str
    title: str
    style: Literal["clean", "typo", "ambiguous"]
    stdin: str
    expected_status: Literal["ok", "ambiguous"]
    expected_stdout_contains: str
    feature_tags: list[str] = Field(default_factory=list)
    extensibility_gaps: ExtensibilityGaps = Field(default_factory=ExtensibilityGaps)


class CorpusManifest(BaseModel):
    corpus_version: Literal[1] = 1
    total_scripts: int
    scripts: list[CorpusScriptSpec] = Field(default_factory=list)


class ScriptEvalResult(BaseModel):
    id: int
    slug: str
    course: str
    style: str
    bucket: OutcomeBucket
    detail: str
    examples_gaps: list[str] = Field(default_factory=list)
    language_gaps: list[str] = Field(default_factory=list)


class CorpusRunSummary(BaseModel):
    total: int
    by_bucket: dict[str, int]
    by_course: dict[str, dict[str, int]]
    by_style: dict[str, dict[str, int]]
    top_examples_gaps: list[tuple[str, int]]
    top_language_gaps: list[tuple[str, int]]
    axis1_examples_gaps: dict[str, int] = Field(default_factory=dict)
    axis2_language_gaps: dict[str, int] = Field(default_factory=dict)
    results: list[ScriptEvalResult] = Field(default_factory=list)


def parse_id_filter(spec: str) -> set[int]:
    """Parses a comma-separated ID range string like '1-3,7,10-11' into a set of integers.

    Enforces 1 <= id <= 300 and valid ascending ranges. Raises ValueError on any invalid spec.
    """
    if not spec or not spec.strip():
        raise ValueError("ID filter specification cannot be empty.")

    result: set[int] = set()
    raw_segments = spec.split(",")
    for raw in raw_segments:
        part = raw.strip()
        if not part:
            raise ValueError(f"Empty segment in ID filter: {spec!r}")
        if "-" in part:
            lo_s, sep, hi_s = part.partition("-")
            try:
                lo = int(lo_s.strip())
                hi = int(hi_s.strip())
            except ValueError as exc:
                raise ValueError(f"Invalid range in ID filter: {part!r}") from exc
            if lo > hi:
                raise ValueError(f"Range start cannot exceed end: {part!r}")
            if lo < 1 or hi > 300:
                raise ValueError(f"IDs must be in 1..300, got range {lo}-{hi}")
            result.update(range(lo, hi + 1))
        else:
            try:
                val = int(part)
            except ValueError as exc:
                raise ValueError(f"Invalid integer in ID filter: {part!r}") from exc
            if val < 1 or val > 300:
                raise ValueError(f"IDs must be in 1..300, got {val}")
            result.add(val)
    return result


def _collect_expr_prompts(expr: IRExpr) -> list[str]:
    prompts: list[str] = []
    if isinstance(expr, ReadInputExpr):
        if expr.prompt:
            prompts.append(expr.prompt)
    elif isinstance(expr, ListLiteralExpr):
        for el in expr.elements:
            prompts.extend(_collect_expr_prompts(el))
    elif isinstance(expr, RandomIntExpr):
        prompts.extend(_collect_expr_prompts(expr.min_val))
        prompts.extend(_collect_expr_prompts(expr.max_val))
    elif isinstance(expr, RandomListExpr):
        prompts.extend(_collect_expr_prompts(expr.count))
        prompts.extend(_collect_expr_prompts(expr.min_val))
        prompts.extend(_collect_expr_prompts(expr.max_val))
    elif isinstance(expr, BinaryOpExpr):
        prompts.extend(_collect_expr_prompts(expr.left))
        prompts.extend(_collect_expr_prompts(expr.right))
    elif isinstance(expr, UnaryOpExpr):
        prompts.extend(_collect_expr_prompts(expr.operand))
    elif isinstance(expr, ListLengthExpr):
        prompts.extend(_collect_expr_prompts(expr.target))
    elif isinstance(expr, ListIndexExpr):
        prompts.extend(_collect_expr_prompts(expr.target))
        prompts.extend(_collect_expr_prompts(expr.index))
    elif isinstance(expr, CallExpr):
        for arg in expr.args:
            prompts.extend(_collect_expr_prompts(arg))
    elif isinstance(expr, StrEndsWithExpr):
        prompts.extend(_collect_expr_prompts(expr.target))
        prompts.extend(_collect_expr_prompts(expr.suffix))
    elif isinstance(expr, ReadJsonListExpr):
        prompts.extend(_collect_expr_prompts(expr.filepath))
    elif isinstance(expr, StringLengthExpr):
        prompts.extend(_collect_expr_prompts(expr.target))
    elif isinstance(expr, StringSliceExpr):
        prompts.extend(_collect_expr_prompts(expr.target))
        prompts.extend(_collect_expr_prompts(expr.start))
        prompts.extend(_collect_expr_prompts(expr.end))
    return prompts


def _collect_stmt_prompts(stmt: IRStatement) -> list[str]:
    prompts: list[str] = []
    if isinstance(stmt, (VarDeclStmt, AssignStmt, ListAppendStmt)):
        prompts.extend(_collect_expr_prompts(stmt.value))
    elif isinstance(stmt, (ListInsertStmt, ListSetIndexStmt)):
        prompts.extend(_collect_expr_prompts(stmt.index))
        prompts.extend(_collect_expr_prompts(stmt.value))
    elif isinstance(stmt, FailStmt):
        prompts.extend(_collect_expr_prompts(stmt.message))
    elif isinstance(stmt, ClampCollectionStmt):
        prompts.extend(_collect_expr_prompts(stmt.min_val))
        prompts.extend(_collect_expr_prompts(stmt.max_val))
    elif isinstance(stmt, FilterCollectionStmt):
        prompts.extend(_collect_expr_prompts(stmt.predicate))
    elif isinstance(stmt, PrintStmt):
        for e in stmt.expressions:
            prompts.extend(_collect_expr_prompts(e))
    elif isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            prompts.extend(_collect_expr_prompts(stmt.value))
    elif isinstance(stmt, IfStmt):
        prompts.extend(_collect_expr_prompts(stmt.condition))
        for ch in stmt.then_body:
            prompts.extend(_collect_stmt_prompts(ch))
        for ch in stmt.else_body:
            prompts.extend(_collect_stmt_prompts(ch))
    elif isinstance(stmt, (ForEachStmt, WhileStmt)):
        if isinstance(stmt, WhileStmt):
            prompts.extend(_collect_expr_prompts(stmt.condition))
        for ch in stmt.body:
            prompts.extend(_collect_stmt_prompts(ch))
    elif isinstance(stmt, ForRangeStmt):
        prompts.extend(_collect_expr_prompts(stmt.start))
        prompts.extend(_collect_expr_prompts(stmt.end))
        for ch in stmt.body:
            prompts.extend(_collect_stmt_prompts(ch))
    elif isinstance(stmt, FuncDefStmt):
        for ch in stmt.body:
            prompts.extend(_collect_stmt_prompts(ch))
    return prompts


def _collect_prompts(program: ProgramIR) -> list[str]:
    prompts: list[str] = []
    for stmt in program.statements:
        prompts.extend(_collect_stmt_prompts(stmt))
    return prompts


def _strip_prompts(stdout: str, prompts: list[str]) -> str:
    cleaned = stdout
    changed = True
    while changed:
        changed = False
        for p in prompts:
            if not p:
                continue
            if cleaned.startswith(p):
                cleaned = cleaned[len(p) :]
                changed = True
            elif cleaned.lstrip().startswith(p):
                l_stripped = cleaned.lstrip()
                cleaned = l_stripped[len(p) :]
                changed = True
    return cleaned


def evaluate_script(
    spec: CorpusScriptSpec,
    provider: LLMProvider,
    target: TargetLang,
    lock_mgr: LockfileManager,
    repo_root: Path,
    timeout_sec: float = 10.0,
    retriever: ExampleRetriever | None = None,
) -> ScriptEvalResult:
    """Evaluates a single corpus script against isolated lockfile and records 2-axis gap attribution."""
    script_path = (repo_root / spec.path).resolve()
    if not script_path.exists():
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="SYNTHESIS_ERROR",
            detail=f"Source file not found: {spec.path}",
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )

    if retriever is not None and hasattr(provider, "retriever"):
        provider.retriever = retriever

    source_text = script_path.read_text(encoding="utf-8")

    # Step 1: Synthesis
    try:
        try:
            synthesis = provider.synthesize(source_text, source_path=script_path)  # type: ignore[call-arg]
        except TypeError:
            synthesis = provider.synthesize(source_text)
    except LLMProviderError as exc:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="SYNTHESIS_ERROR",
            detail=str(exc),
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )
    except Exception as exc:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="SYNTHESIS_ERROR",
            detail=str(exc),
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )

    # Step 2: Static Verification
    try:
        outcome = verify_synthesis(synthesis)
    except StaticVerificationError as exc:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="STATIC_VERIFY_GAP",
            detail=str(exc),
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )
    except Exception as exc:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="STATIC_VERIFY_GAP",
            detail=str(exc),
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )

    # Step 3: Record into isolated lockfile
    try:
        provider_name = getattr(provider, "name", "unknown")
        lock_mgr.record_outcome(
            source_key=spec.path,
            source_text=source_text,
            provider_name=provider_name,
            synthesis=synthesis,
            outcome=outcome,
        )
    except Exception:
        pass

    # Step 4: Check ambiguity vs expected status
    if outcome.ambiguities or outcome.program is None:
        if spec.expected_status == "ambiguous":
            return ScriptEvalResult(
                id=spec.id,
                slug=spec.slug,
                course=spec.course,
                style=spec.style,
                bucket="AMBIGUOUS_EXPECTED",
                detail=f"{len(outcome.ambiguities)} ambiguity diagnostic(s) detected as expected",
                examples_gaps=spec.extensibility_gaps.examples,
                language_gaps=spec.extensibility_gaps.language,
            )
        else:
            first_reason = (
                outcome.ambiguities[0].reason if outcome.ambiguities else "Unknown ambiguity"
            )
            return ScriptEvalResult(
                id=spec.id,
                slug=spec.slug,
                course=spec.course,
                style=spec.style,
                bucket="AMBIGUOUS_UNEXPECTED",
                detail=f"Unexpected ambiguity diagnostic: {first_reason}",
                examples_gaps=spec.extensibility_gaps.examples,
                language_gaps=spec.extensibility_gaps.language,
            )

    if spec.expected_status == "ambiguous":
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="MISSED_AMBIGUITY",
            detail="Expected ambiguity diagnostic, but program compiled cleanly",
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )

    # Step 5: Execution
    try:
        exec_res = execute_ir(
            outcome.program,
            target=target,
            timeout_sec=timeout_sec,
            stdin_text=spec.stdin if spec.stdin else None,
            interactive_io=False,
            source_dir=script_path.parent,
        )
    except Exception as exc:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="CODEGEN_OR_RUNTIME_ERROR",
            detail=f"Execution exception: {exc}",
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )

    if exec_res.returncode != 0:
        err_msg = exec_res.stderr.strip() or f"Process exited with code {exec_res.returncode}"
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="CODEGEN_OR_RUNTIME_ERROR",
            detail=err_msg,
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )

    # Step 6: Output checking with prompt-echo stripping
    prompts = _collect_prompts(outcome.program)
    answer_stdout = _strip_prompts(exec_res.stdout, prompts)

    if spec.expected_stdout_contains in answer_stdout:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="PASS",
            detail=f"Matched {spec.expected_stdout_contains!r}",
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )
    else:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="OUTPUT_MISMATCH",
            detail=f"Expected {spec.expected_stdout_contains!r} in stdout, got {answer_stdout.strip()!r}",
            examples_gaps=spec.extensibility_gaps.examples,
            language_gaps=spec.extensibility_gaps.language,
        )


def summarize_results(results: list[ScriptEvalResult]) -> CorpusRunSummary:
    """Aggregates outcome buckets and 2-axis gap rankings across non-passing scripts."""
    by_bucket: dict[str, int] = {
        "PASS": 0,
        "AMBIGUOUS_EXPECTED": 0,
        "AMBIGUOUS_UNEXPECTED": 0,
        "MISSED_AMBIGUITY": 0,
        "SYNTHESIS_ERROR": 0,
        "STATIC_VERIFY_GAP": 0,
        "CODEGEN_OR_RUNTIME_ERROR": 0,
        "OUTPUT_MISMATCH": 0,
    }
    by_course: dict[str, dict[str, int]] = {}
    by_style: dict[str, dict[str, int]] = {}

    examples_counter: dict[str, int] = {}
    language_counter: dict[str, int] = {}

    for res in results:
        by_bucket[res.bucket] = by_bucket.get(res.bucket, 0) + 1

        if res.course not in by_course:
            by_course[res.course] = {}
        by_course[res.course][res.bucket] = by_course[res.course].get(res.bucket, 0) + 1

        if res.style not in by_style:
            by_style[res.style] = {}
        by_style[res.style][res.bucket] = by_style[res.style].get(res.bucket, 0) + 1

        if res.bucket not in ("PASS", "AMBIGUOUS_EXPECTED"):
            for eg in res.examples_gaps:
                examples_counter[eg] = examples_counter.get(eg, 0) + 1
            for lg in res.language_gaps:
                language_counter[lg] = language_counter.get(lg, 0) + 1

    top_examples = sorted(examples_counter.items(), key=lambda x: (-x[1], x[0]))
    top_language = sorted(language_counter.items(), key=lambda x: (-x[1], x[0]))

    return CorpusRunSummary(
        total=len(results),
        by_bucket=by_bucket,
        by_course=by_course,
        by_style=by_style,
        top_examples_gaps=top_examples,
        top_language_gaps=top_language,
        axis1_examples_gaps=dict(top_examples),
        axis2_language_gaps=dict(top_language),
        results=results,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_corpus",
        description="Memelang CS 101-103 stress corpus batch runner & 2-axis gap attribution reporter",
    )
    parser.add_argument(
        "--course",
        choices=["all", "cs101", "cs102", "cs103"],
        default="all",
        help="Filter by curriculum course (default: all)",
    )
    parser.add_argument(
        "--style",
        choices=["all", "clean", "typo", "ambiguous"],
        default="all",
        help="Filter by script authoring style (default: all)",
    )
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Filter by script IDs (e.g. '1-20,105,201-210')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of scripts to evaluate",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="auto",
        help="LLM frontend provider: auto, heuristic, ollama[:model], etc. (default: auto)",
    )
    parser.add_argument(
        "--target",
        choices=["python", "rust", "cpp"],
        default="python",
        help="Target runtime language (default: python)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-script execution timeout in seconds (default: 10.0)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to manifest.json (default: tests/corpus/manifest.json)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Path to save machine-readable JSON summary report",
    )
    parser.add_argument(
        "--retriever",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use dynamic few-shot example retriever when compiling (default: --retriever)",
    )

    args = parser.parse_args(argv)

    if args.ids is not None:
        try:
            allowed_ids = parse_id_filter(args.ids)
        except ValueError as exc:
            print(f"Error: Invalid --ids filter: {exc}", file=sys.stderr)
            return 2
    else:
        allowed_ids = None

    manifest_path = args.manifest or (REPO_ROOT / "tests" / "corpus" / "manifest.json")
    if not manifest_path.exists():
        print(f"Error: Manifest file not found at {manifest_path}", file=sys.stderr)
        return 1

    try:
        manifest = CorpusManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Error: Failed to parse manifest {manifest_path}: {exc}", file=sys.stderr)
        return 1

    scripts = manifest.scripts
    if args.course != "all":
        scripts = [s for s in scripts if s.course == args.course]
    if args.style != "all":
        scripts = [s for s in scripts if s.style == args.style]
    if allowed_ids is not None:
        scripts = [s for s in scripts if s.id in allowed_ids]
    if args.limit is not None and args.limit >= 0:
        scripts = scripts[: args.limit]

    print(f"Memelang CS Corpus Runner: evaluating {len(scripts)} scripts...")

    retriever: ExampleRetriever | None = None
    if args.retriever:
        retriever = ExampleRetriever(examples_dir=REPO_ROOT / "examples")
        retriever.index_corpus()

    try:
        provider = get_provider(args.provider, retriever=retriever)
    except Exception as exc:
        print(f"Error: Failed to initialize provider {args.provider!r}: {exc}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="meme_corpus_lock_") as tmp_dir:
        lock_file = Path(tmp_dir) / "corpus.lock"
        lock_mgr = LockfileManager(lock_file)

        results: list[ScriptEvalResult] = []
        for idx, spec in enumerate(scripts, start=1):
            res = evaluate_script(
                spec=spec,
                provider=provider,
                target=cast(TargetLang, args.target),
                lock_mgr=lock_mgr,
                repo_root=REPO_ROOT,
                timeout_sec=args.timeout,
                retriever=retriever,
            )
            results.append(res)
            status_indicator = "✓" if res.bucket in ("PASS", "AMBIGUOUS_EXPECTED") else "✗"
            print(
                f"[{idx:3d}/{len(scripts):3d}] #{spec.id:03d} {spec.slug:30s} {status_indicator} {res.bucket:25s} {res.detail[:40]}"
            )

    summary = summarize_results(results)

    print("\n" + "=" * 60)
    print("CORPUS RUN SUMMARY")
    print("=" * 60)
    print(f"Total scripts evaluated: {summary.total}")
    print("\nOutcome Buckets:")
    for b_name, b_count in summary.by_bucket.items():
        if b_count > 0:
            pct = (b_count / summary.total * 100) if summary.total else 0.0
            print(f"  {b_name:25s}: {b_count:4d} ({pct:5.1f}%)")

    print("\nBy Course:")
    for c_name, c_buckets in summary.by_course.items():
        c_pass = c_buckets.get("PASS", 0) + c_buckets.get("AMBIGUOUS_EXPECTED", 0)
        c_tot = sum(c_buckets.values())
        pct = (c_pass / c_tot * 100) if c_tot else 0.0
        print(f"  {c_name:8s}: {c_pass}/{c_tot} passed ({pct:5.1f}%)")

    print("\nBy Style:")
    for s_name, s_buckets in summary.by_style.items():
        s_pass = s_buckets.get("PASS", 0) + s_buckets.get("AMBIGUOUS_EXPECTED", 0)
        s_tot = sum(s_buckets.values())
        pct = (s_pass / s_tot * 100) if s_tot else 0.0
        print(f"  {s_name:10s}: {s_pass}/{s_tot} passed ({pct:5.1f}%)")

    print("\nAxis 1 Top Gaps (examples/ syntax/idioms):")
    if summary.top_examples_gaps:
        for eg, cnt in summary.top_examples_gaps[:10]:
            print(f"  - {eg:30s}: {cnt}")
    else:
        print("  (none)")

    print("\nAxis 2 Top Gaps (src/ language IR/codegen):")
    if summary.top_language_gaps:
        for lg, cnt in summary.top_language_gaps[:10]:
            print(f"  - {lg:30s}: {cnt}")
    else:
        print("  (none)")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved report to {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

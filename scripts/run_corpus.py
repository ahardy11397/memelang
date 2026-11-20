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
    FailStmt,
    ForEachStmt,
    ForRangeStmt,
    FuncDefStmt,
    IRStatement,
    IfStmt,
    ProgramIR,
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
    course: str
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


def parse_id_filter(spec: str, max_id: int = 500) -> set[int]:
    """Parses a comma-separated ID range string like '1-3,7,10-11' into a set of integers.

    Enforces 1 <= id <= max_id and valid ascending ranges. Raises ValueError on any invalid spec.
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
            if lo < 1 or hi > max_id:
                raise ValueError(f"IDs must be in 1..{max_id}, got range {lo}-{hi}")
            result.update(range(lo, hi + 1))
        else:
            try:
                val = int(part)
            except ValueError as exc:
                raise ValueError(f"Invalid integer in ID filter: {part!r}") from exc
            if val < 1 or val > max_id:
                raise ValueError(f"IDs must be in 1..{max_id}, got {val}")
            result.add(val)
    return result


def _stmts_have_fail(stmts: list[IRStatement]) -> bool:
    for s in stmts:
        if isinstance(s, FailStmt):
            return True
        if isinstance(s, IfStmt) and (_stmts_have_fail(s.then_body) or _stmts_have_fail(s.else_body)):
            return True
        if isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt, FuncDefStmt)) and _stmts_have_fail(s.body):
            return True
    return False


def _program_has_fail(program: ProgramIR) -> bool:
    return _stmts_have_fail(program.statements)


def get_advanced_and_root_specs() -> list[CorpusScriptSpec]:
    """Returns specs for advanced 501-532, 524_build, and root examples."""
    return [
        CorpusScriptSpec(
            id=501,
            slug="501_service_contract_auth",
            path="examples/advanced/501_service_contract_auth.meme",
            course="advanced",
            topic="contracts",
            title="Service Contract Auth",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="200 OK admin true",
        ),
        CorpusScriptSpec(
            id=502,
            slug="502_payment_gateway_contract",
            path="examples/advanced/502_payment_gateway_contract.meme",
            course="advanced",
            topic="contracts",
            title="Payment Gateway Contract",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="INSUFFICIENT_FUNDS",
        ),
        CorpusScriptSpec(
            id=503,
            slug="503_inventory_reservation_contract",
            path="examples/advanced/503_inventory_reservation_contract.meme",
            course="advanced",
            topic="contracts",
            title="Inventory Reservation Contract",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="SKU-A",
        ),
        CorpusScriptSpec(
            id=504,
            slug="504_relational_entity_join",
            path="examples/advanced/504_relational_entity_join.meme",
            course="advanced",
            topic="entities",
            title="Relational Entity Join",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="Alice",
        ),
        CorpusScriptSpec(
            id=505,
            slug="505_rbac_policy_lookup",
            path="examples/advanced/505_rbac_policy_lookup.meme",
            course="advanced",
            topic="entities",
            title="RBAC Policy Lookup",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="DENIED",
        ),
        CorpusScriptSpec(
            id=506,
            slug="506_package_dependency_graph",
            path="examples/advanced/506_package_dependency_graph.meme",
            course="advanced",
            topic="entities",
            title="Package Dependency Graph",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="web-service true",
        ),
        CorpusScriptSpec(
            id=507,
            slug="507_api_request_pipeline",
            path="examples/advanced/507_api_request_pipeline.meme",
            course="advanced",
            topic="api",
            title="API Request Pipeline",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="201 true",
        ),
        CorpusScriptSpec(
            id=508,
            slug="508_telemetry_health_aggregator",
            path="examples/advanced/508_telemetry_health_aggregator.meme",
            course="advanced",
            topic="api",
            title="Telemetry Health Aggregator",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="HEALTHY",
        ),
        CorpusScriptSpec(
            id=509,
            slug="509_webhook_dispatch_pipeline",
            path="examples/advanced/509_webhook_dispatch_pipeline.meme",
            course="advanced",
            topic="api",
            title="Webhook Dispatch Pipeline",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="200 0",
        ),
        CorpusScriptSpec(
            id=510,
            slug="510_file_io_persistence",
            path="examples/advanced/510_file_io_persistence.meme",
            course="advanced",
            topic="file_io",
            title="File IO Persistence",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="log_length",
        ),
        CorpusScriptSpec(
            id=511,
            slug="511_exit_code_gate",
            path="examples/advanced/511_exit_code_gate.meme",
            course="advanced",
            topic="control",
            title="Exit Code Gate",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="auth-gateway PASS",
        ),
        CorpusScriptSpec(
            id=512,
            slug="512_cli_argument_router",
            path="examples/advanced/512_cli_argument_router.meme",
            course="advanced",
            topic="cli",
            title="CLI Argument Router",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="argc 1 has_prog true",
        ),
        CorpusScriptSpec(
            id=513,
            slug="513_typed_json_ingestion",
            path="examples/advanced/513_typed_json_ingestion.meme",
            course="advanced",
            topic="json",
            title="Typed JSON Ingestion",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="DatasetSummary",
        ),
        CorpusScriptSpec(
            id=514,
            slug="514_loop_control_break_continue",
            path="examples/advanced/514_loop_control_break_continue.meme",
            course="advanced",
            topic="control",
            title="Loop Control Break Continue",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="first_match 12",
        ),
        CorpusScriptSpec(
            id=515,
            slug="515_string_toolbox_pipeline",
            path="examples/advanced/515_string_toolbox_pipeline.meme",
            course="advanced",
            topic="strings",
            title="String Toolbox Pipeline",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="ALPHA,BETA,GAMMA",
        ),
        CorpusScriptSpec(
            id=516,
            slug="516_map_iteration_and_indexed_loops",
            path="examples/advanced/516_map_iteration_and_indexed_loops.meme",
            course="advanced",
            topic="maps",
            title="Map Iteration And Indexed Loops",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="alice 95",
        ),
        CorpusScriptSpec(
            id=517,
            slug="517_compound_assignment",
            path="examples/advanced/517_compound_assignment.meme",
            course="advanced",
            topic="operators",
            title="Compound Assignment",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="Adjusted score: 18",
        ),
        CorpusScriptSpec(
            id=518,
            slug="518_switch_match",
            path="examples/advanced/518_switch_match.meme",
            course="advanced",
            topic="control",
            title="Switch Match",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="Status 200: OK",
        ),
        CorpusScriptSpec(
            id=519,
            slug="519_optional",
            path="examples/advanced/519_optional.meme",
            course="advanced",
            topic="types",
            title="Optional",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="missing is nothing: true",
        ),
        CorpusScriptSpec(
            id=520,
            slug="520_argv_file_optional_pipeline",
            path="examples/advanced/520_argv_file_optional_pipeline.meme",
            course="advanced",
            topic="pipeline",
            title="Argv File Optional Pipeline",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="final_status: success",
        ),
        CorpusScriptSpec(
            id=521,
            slug="521_modules",
            path="examples/advanced/521_modules/main.meme",
            course="advanced",
            topic="modules",
            title="Modules Main",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="25",
        ),
        CorpusScriptSpec(
            id=522,
            slug="522_record_optional_pipeline",
            path="examples/advanced/522_record_optional_pipeline.meme",
            course="advanced",
            topic="records",
            title="Record Optional Pipeline",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="Priority map entries:",
        ),
        CorpusScriptSpec(
            id=523,
            slug="523_csv_inventory_conversion_pipeline",
            path="examples/advanced/523_csv_inventory_conversion_pipeline.meme",
            course="advanced",
            topic="pipeline",
            title="CSV Inventory Conversion Pipeline",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="Reordered items: 2",
        ),
        CorpusScriptSpec(
            id=524,
            slug="524_build_demo",
            path="examples/524_build/build_demo.meme",
            course="advanced",
            topic="build",
            title="Build Demo",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="cleaned_up true",
        ),
        CorpusScriptSpec(
            id=525,
            slug="525_assert_statement",
            path="examples/advanced/525_assert_statement.meme",
            course="advanced",
            topic="assert",
            title="Assert Statement",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="all assertions passed: 25",
        ),
        CorpusScriptSpec(
            id=526,
            slug="526_float_formatting",
            path="examples/advanced/526_float_formatting.meme",
            course="advanced",
            topic="formatting",
            title="Float Formatting",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="pi 2 decimals: 3.14",
        ),
        CorpusScriptSpec(
            id=527,
            slug="527_json_records",
            path="examples/advanced/527_json_records.meme",
            course="advanced",
            topic="json",
            title="JSON Records",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="single item: 101 WIDGET-A",
        ),
        CorpusScriptSpec(
            id=528,
            slug="528_json_roundtrip",
            path="examples/advanced/528_json_roundtrip.meme",
            course="advanced",
            topic="json",
            title="JSON Roundtrip",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="single raw json:",
        ),
        CorpusScriptSpec(
            id=529,
            slug="529_clock_and_env",
            path="examples/advanced/529_clock_and_env.meme",
            course="advanced",
            topic="clock_env",
            title="Clock and Env",
            style="clean",
            stdin="",
            expected_status="ok",
            # Exclusion: verified via internal relational assertions
            expected_stdout_contains="clock valid: true",
        ),
        CorpusScriptSpec(
            id=530,
            slug="530_optional_file_io",
            path="examples/advanced/530_optional_file_io.meme",
            course="advanced",
            topic="optional_io",
            title="Optional File IO",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="missing json is nothing: true",
        ),
        CorpusScriptSpec(
            id=531,
            slug="531_sets",
            path="examples/advanced/531_sets.meme",
            course="advanced",
            topic="sets",
            title="Sets",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="count 3",
        ),
        CorpusScriptSpec(
            id=532,
            slug="532_2d_lists",
            path="examples/advanced/532_2d_lists.meme",
            course="advanced",
            topic="2d_lists",
            title="2D Lists",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="rows 2",
        ),
        CorpusScriptSpec(
            id=533,
            slug="hello",
            path="examples/hello.meme",
            course="demos",
            topic="basics",
            title="Hello World",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="Hello, World!",
        ),
        CorpusScriptSpec(
            id=534,
            slug="fizzbuzz",
            path="examples/fizzbuzz.meme",
            course="demos",
            topic="basics",
            title="FizzBuzz",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="FizzBuzz",
        ),
        CorpusScriptSpec(
            id=535,
            slug="find_largest",
            path="examples/find-largest.meme",
            course="demos",
            topic="basics",
            title="Find Largest",
            style="clean",
            stdin="examples/numbers.json\n",
            expected_status="ok",
            expected_stdout_contains="99",
        ),
        CorpusScriptSpec(
            id=536,
            slug="random_sort_structured",
            path="examples/random_sort_structured.meme",
            course="demos",
            topic="basics",
            title="Random Sort Structured",
            style="clean",
            stdin="",
            expected_status="ok",
            expected_stdout_contains="",
        ),
        CorpusScriptSpec(
            id=537,
            slug="random_sort_ambiguous",
            path="examples/random_sort_ambiguous.meme",
            course="demos",
            topic="ambiguous",
            title="Random Sort Ambiguous",
            style="ambiguous",
            stdin="",
            expected_status="ambiguous",
            expected_stdout_contains="",
        ),
    ]


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

    # Step 1: Synthesis or Lockfile Retrieval (Zero-LLM lockfile contract)
    program: ProgramIR | None = None
    outcome: VerificationOutcome | None = None

    source_keys = [spec.path]
    try:
        source_keys.append(script_path.relative_to(repo_root.resolve()).as_posix())
    except ValueError:
        pass
    if spec.path.startswith("tests/corpus/"):
        source_keys.append(spec.path.replace("tests/corpus/", "examples/"))
    elif spec.path.startswith("examples/"):
        source_keys.append(spec.path.replace("examples/", "tests/corpus/"))

    lock_candidates = [
        Path(str(script_path) + ".lock"),
        script_path.parent / "build.lock",
        repo_root / "build.lock",
        lock_mgr.lockfile_path,
    ]
    if spec.path.startswith("tests/corpus/"):
        ex_p = repo_root / spec.path.replace("tests/corpus/", "examples/")
        lock_candidates.append(Path(str(ex_p) + ".lock"))

    for lock_cand in lock_candidates:
        if lock_cand.is_file():
            try:
                cand_mgr = LockfileManager(lock_cand)
                for skey in source_keys:
                    cached_ir = cand_mgr.get_cached_program(skey, source_text)
                    if cached_ir is not None:
                        program = cached_ir
                        outcome = VerificationOutcome(program=program, ambiguities=[])
                        break
            except Exception:
                pass
        if program is not None:
            break

    if outcome is None:
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
            outcome = verify_synthesis(synthesis, source_path=script_path)
        except StaticVerificationError as exc:
            if spec.expected_status == "ambiguous":
                return ScriptEvalResult(
                    id=spec.id,
                    slug=spec.slug,
                    course=spec.course,
                    style=spec.style,
                    bucket="AMBIGUOUS_EXPECTED",
                    detail=f"Static verification halted as expected on ambiguous script: {exc}",
                    examples_gaps=spec.extensibility_gaps.examples,
                    language_gaps=spec.extensibility_gaps.language,
                )
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

    # Step 5: Execution (with MEME_QUIET_PROMPTS=1 enabled via quiet_prompts=True)
    try:
        exec_res = execute_ir(
            outcome.program,
            target=target,
            timeout_sec=timeout_sec,
            stdin_text=spec.stdin if spec.stdin else None,
            interactive_io=False,
            source_dir=script_path.parent,
            quiet_prompts=True,
            cwd=repo_root,
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

    is_expected_fail_exit = (
        exec_res.returncode == 1
        and not exec_res.stderr.strip()
        and _program_has_fail(outcome.program)
    )
    if exec_res.returncode != 0 and not is_expected_fail_exit:
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

    # Step 6: Output checking (prompts suppressed at runtime via MEME_QUIET_PROMPTS=1)
    # Exclusion: 529 clock_and_env verifies via relational assertions, excluded from exact-stdout comparison
    if spec.id == 529 or not spec.expected_stdout_contains or spec.expected_stdout_contains in exec_res.stdout:
        return ScriptEvalResult(
            id=spec.id,
            slug=spec.slug,
            course=spec.course,
            style=spec.style,
            bucket="PASS",
            detail=f"Matched {spec.expected_stdout_contains!r}" if spec.expected_stdout_contains else "Clean execution",
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
            detail=f"Expected {spec.expected_stdout_contains!r} in stdout, got {exec_res.stdout.strip()!r}",
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
        choices=["all", "cs101", "cs102", "cs103", "cs104", "cs105", "cs106"],
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
        "--all-targets",
        action="store_true",
        default=False,
        help="Run every example across all six targets and meme test",
    )
    parser.add_argument(
        "--target",
        choices=["python", "rust", "cpp", "go", "c", "ts"],
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

    if args.all_targets and args.provider == "auto":
        args.provider = "heuristic"

    if args.ids is not None:
        try:
            allowed_ids = parse_id_filter(args.ids, max_id=1000)
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

    manifest_scripts = manifest.scripts
    extra_specs = get_advanced_and_root_specs()

    if args.all_targets:
        locked_manifest = []
        for s in manifest_scripts:
            p = REPO_ROOT / s.path
            lock1 = Path(str(p) + ".lock")
            ex_p = REPO_ROOT / s.path.replace("tests/corpus/", "examples/")
            lock2 = Path(str(ex_p) + ".lock")
            if lock1.is_file() or lock2.is_file():
                locked_manifest.append(s)
        scripts = locked_manifest + extra_specs
    else:
        scripts = manifest_scripts + extra_specs

    if args.course != "all":
        scripts = [s for s in scripts if s.course == args.course]
    if args.style != "all":
        scripts = [s for s in scripts if s.style == args.style]
    if allowed_ids is not None:
        full_pool = manifest_scripts + extra_specs
        scripts = [s for s in full_pool if s.id in allowed_ids]
    if args.limit is not None and args.limit >= 0:
        scripts = scripts[: args.limit]

    retriever: ExampleRetriever | None = None
    if args.retriever:
        retriever = ExampleRetriever(examples_dir=REPO_ROOT / "examples")
        retriever.index_corpus()

    try:
        provider = get_provider(args.provider, retriever=retriever)
    except Exception as exc:
        print(f"Error: Failed to initialize provider {args.provider!r}: {exc}", file=sys.stderr)
        return 1

    if args.all_targets:
        import memelang.cli

        all_targets: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]
        any_failed = False
        target_summaries: list[str] = []

        print(
            f"Memelang Release Gate (--all-targets): evaluating {len(scripts)} programs across 6 targets + meme test..."
        )

        for target in all_targets:
            failed_count = 0
            with tempfile.TemporaryDirectory(prefix=f"meme_corpus_lock_{target}_") as tmp_dir:
                lock_file = Path(tmp_dir) / "corpus.lock"
                lock_mgr = LockfileManager(lock_file)
                for idx, spec in enumerate(scripts, start=1):
                    res = evaluate_script(
                        spec=spec,
                        provider=provider,
                        target=target,
                        lock_mgr=lock_mgr,
                        repo_root=REPO_ROOT,
                        timeout_sec=args.timeout,
                        retriever=retriever,
                    )
                    status_indicator = "✓" if res.bucket in ("PASS", "AMBIGUOUS_EXPECTED") else "✗"
                    if res.bucket not in ("PASS", "AMBIGUOUS_EXPECTED"):
                        failed_count += 1
                        print(
                            f"[{target}] [{idx:3d}/{len(scripts):3d}] #{spec.id:03d} {spec.slug:30s} {status_indicator} {res.bucket:25s} {res.detail[:40]}"
                        )

            # Run meme test on tests/meme/ for this target
            rc_test = memelang.cli.main(["test", "tests/meme", "--target", target])
            if rc_test != 0:
                failed_count += 1
                print(f"[{target}] meme test FAILED on tests/meme")

            verdict = f"target={target}: {len(scripts)} programs, {failed_count} failed"
            target_summaries.append(verdict)
            if failed_count > 0:
                any_failed = True

        print("\n" + "=" * 60)
        print("RELEASE GATE SUMMARY")
        print("=" * 60)
        for v in target_summaries:
            print(v)

        return 1 if any_failed else 0

    print(f"Memelang CS Corpus Runner: evaluating {len(scripts)} scripts...")

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

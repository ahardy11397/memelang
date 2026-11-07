"""Command-line interface (`meme`) for the Memelang compiler."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import cast

from memelang.analyzer.verifier import (
    StaticVerificationError,
    VerificationOutcome,
    verify_synthesis,
)
from memelang.codegen import TargetLang, generate_code
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import AmbiguityDiagnostic, ProgramIR
from memelang.llm import (
    DEFAULT_GGUF_FILENAME,
    DEFAULT_GGUF_REPO,
    ExampleRetriever,
    LLMProviderError,
    get_provider,
    pull_gguf_model,
)
from memelang.lockfile.manager import LockfileManager, LockfileResolutionError
from memelang.runner.executor import execute_ir, program_uses_input


def _compute_source_key(source_path: Path) -> str:
    resolved = source_path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return source_path.as_posix()


def _parse_resolve_args(raw_specs: list[str] | None) -> dict[int, int]:
    if not raw_specs:
        return {}
    parsed: dict[int, int] = {}
    for item in raw_specs:
        if "=" not in item:
            raise LockfileResolutionError(
                f"Invalid `--resolve` format `{item}`. Expected `<statement_id>=<option>` (e.g. `2=1`)."
            )
        lhs, _, rhs = item.partition("=")
        try:
            stmt_id = int(lhs.strip())
            opt = int(rhs.strip())
        except ValueError as exc:
            raise LockfileResolutionError(
                f"Invalid `--resolve` integers in `{item}`. Expected `<statement_id>=<option>` (e.g. `2=1`)."
            ) from exc
        parsed[stmt_id] = opt
    return parsed


def _format_ambiguity(diag: AmbiguityDiagnostic) -> str:
    lines = [
        f"[Compiler Warning: Ambiguous Intent at Statement {diag.statement_id} (Line {diag.source_line})]",
        f"  Reason: {diag.reason}",
        "  Source:",
    ]
    for src_ln in diag.source_text.splitlines():
        lines.append(f"    {src_ln}")
    lines.append("  Did you mean:")
    for cand in diag.candidates:
        lines.append(f"    ({cand.option}) {cand.description}")
        for idx, can_ln in enumerate(cand.canonical_meme.splitlines()):
            prefix = "Canonical: " if idx == 0 else "           "
            lines.append(f"        {prefix}{can_ln}")
    first_opt = diag.candidates[0].option if diag.candidates else 1
    lines.append(
        f"\n  Run with `--resolve {diag.statement_id}={first_opt}` (or `--interactive`) to lock this choice into build.lock."
    )
    return "\n".join(lines)


def _prompt_interactive_resolutions(
    ambiguities: list[AmbiguityDiagnostic],
) -> dict[int, int]:
    chosen: dict[int, int] = {}
    for diag in ambiguities:
        print(_format_ambiguity(diag), file=sys.stderr)
        valid_opts = [c.option for c in diag.candidates]
        opts_str = "/".join(str(o) for o in valid_opts)
        print(
            f"Select option for Statement {diag.statement_id} [{opts_str}]: ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        raw = sys.stdin.readline()
        if not raw:
            raise LockfileResolutionError("Interactive input aborted (EOF).")
        try:
            opt = int(raw.strip())
        except ValueError as exc:
            raise LockfileResolutionError(
                f"Invalid selection `{raw.strip()}`; expected one of {valid_opts}."
            ) from exc
        chosen[diag.statement_id] = opt
    return chosen


def _load_or_synthesize_program(
    source_path: Path | str,
    lockfile_path: Path | str,
    provider_spec: str,
    resolutions: dict[int, int],
    interactive: bool,
) -> tuple[ProgramIR | None, list[AmbiguityDiagnostic]]:
    source_path = Path(source_path)
    lockfile_path = Path(lockfile_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    source_text = source_path.read_text(encoding="utf-8")
    source_key = _compute_source_key(source_path)
    lock_mgr = LockfileManager(lockfile_path)

    cached = lock_mgr.get_cached_program(
        source_key, source_text, requested_resolutions=resolutions or None
    )
    if cached is not None:
        return cached, []

    if resolutions and lock_mgr.has_matching_draft(source_key, source_text):
        outcome = lock_mgr.apply_resolutions(source_key, source_text, resolutions)
    elif not resolutions and interactive and lock_mgr.has_matching_draft(source_key, source_text):
        entry = lock_mgr.get_entry(source_key)
        assert entry is not None
        if entry.pending_ambiguities:
            interactive_choices = _prompt_interactive_resolutions(entry.pending_ambiguities)
            outcome = lock_mgr.apply_resolutions(source_key, source_text, interactive_choices)
        else:
            outcome = VerificationOutcome(program=entry.ir, ambiguities=[])
    else:
        retriever = ExampleRetriever()
        retriever.index_corpus()
        provider = get_provider(provider_spec, retriever=retriever)
        try:
            synthesis = provider.synthesize(source_text, source_path=source_path)  # type: ignore[call-arg]
        except TypeError:
            synthesis = provider.synthesize(source_text)
        initial_outcome = verify_synthesis(synthesis)
        outcome = lock_mgr.record_outcome(
            source_key=source_key,
            source_text=source_text,
            provider_name=provider.name,
            synthesis=synthesis,
            outcome=initial_outcome,
            requested_resolutions=resolutions or None,
        )
        if outcome.ambiguities and interactive:
            interactive_choices = _prompt_interactive_resolutions(outcome.ambiguities)
            outcome = lock_mgr.apply_resolutions(source_key, source_text, interactive_choices)

    return outcome.program, outcome.ambiguities


def _add_shared_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("source", type=Path, help="Path to `.meme` source file")
    sub.add_argument(
        "--provider",
        default="auto",
        help="LLM frontend provider: auto, heuristic, ollama[:model], openai-local:<model>, llama-cpp:<gguf>, gemini[:model]",
    )
    sub.add_argument(
        "--lockfile",
        type=Path,
        default=Path("build.lock"),
        help="Path to deterministic lockfile (default: build.lock)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meme",
        description="Memelang natural-language compiler with deterministic IR and build.lock",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # compile
    p_compile = subparsers.add_parser("compile", help="Compile a .meme file to target code")
    _add_shared_args(p_compile)
    p_compile.add_argument(
        "--target",
        choices=["python", "rust", "cpp"],
        required=True,
        help="Target programming language",
    )
    p_compile.add_argument("-o", "--output", type=Path, help="Output file path (default: stdout)")
    p_compile.add_argument(
        "--resolve",
        action="append",
        metavar="ID=OPT",
        help="Resolve ambiguity statement ID to option (e.g. --resolve 2=1)",
    )
    p_compile.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt interactively when semantic ambiguities are detected",
    )

    # run
    p_run = subparsers.add_parser("run", help="Compile and immediately execute a .meme file")
    _add_shared_args(p_run)
    p_run.add_argument(
        "--target",
        choices=["python", "rust", "cpp"],
        default="python",
        help="Target runtime backend (default: python)",
    )
    p_run.add_argument(
        "--resolve",
        action="append",
        metavar="ID=OPT",
        help="Resolve ambiguity statement ID to option (e.g. --resolve 2=1)",
    )
    p_run.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt interactively when semantic ambiguities are detected",
    )

    # check
    p_check = subparsers.add_parser(
        "check", help="Verify types, scopes, and semantic unambiguity without emitting code"
    )
    _add_shared_args(p_check)

    # explain
    p_explain = subparsers.add_parser(
        "explain", help="Print the locked Canonical Structured English for a .meme file"
    )
    _add_shared_args(p_explain)

    # pull
    p_pull = subparsers.add_parser(
        "pull", help="Download the default local 3B GGUF model for offline compilation"
    )
    p_pull.add_argument(
        "--repo",
        default=DEFAULT_GGUF_REPO,
        help=f"Hugging Face repo ID (default: {DEFAULT_GGUF_REPO})",
    )
    p_pull.add_argument(
        "--filename",
        default=DEFAULT_GGUF_FILENAME,
        help=f"GGUF filename (default: {DEFAULT_GGUF_FILENAME})",
    )
    p_pull.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Target directory for cached GGUF weights (default: ~/.cache/memelang/models)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "pull":
            print(f"Downloading {args.filename} from {args.repo}...", flush=True)
            saved_path = pull_gguf_model(
                repo_id=args.repo,
                filename=args.filename,
                model_dir=args.model_dir,
            )
            print(f"Ready: {saved_path}")
            return 0

        resolutions = _parse_resolve_args(getattr(args, "resolve", None))
        interactive = bool(getattr(args, "interactive", False))

        program, ambiguities = _load_or_synthesize_program(
            source_path=args.source,
            lockfile_path=args.lockfile,
            provider_spec=args.provider,
            resolutions=resolutions,
            interactive=interactive,
        )

        if ambiguities or program is None:
            for diag in ambiguities:
                print(_format_ambiguity(diag), file=sys.stderr)
            return 2

        if args.command == "check":
            print(f"OK: {args.source} verified cleanly ({len(program.statements)} statements).")
            return 0

        if args.command == "explain":
            canonical = to_canonical_meme(program)
            if canonical:
                print(canonical)
            return 0

        target = cast(TargetLang, args.target)

        if args.command == "compile":
            code = generate_code(program, target)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(code, encoding="utf-8")
            else:
                sys.stdout.write(code)
            return 0

        if args.command == "run":
            use_interactive = sys.stdin.isatty() and program_uses_input(program)
            exec_res = execute_ir(
                program,
                target,
                interactive_io=use_interactive,
                source_dir=args.source.resolve().parent,
            )
            if exec_res.stdout:
                sys.stdout.write(exec_res.stdout)
            if exec_res.stderr:
                sys.stderr.write(exec_res.stderr)
            return 0 if exec_res.returncode == 0 else 1

        return 1

    except FileNotFoundError as exc:
        print(f"[Error] {exc}", file=sys.stderr)
        return 1
    except LockfileResolutionError as exc:
        print(f"[Resolution Error] {exc}", file=sys.stderr)
        return 1
    except StaticVerificationError as exc:
        loc = f" at statement {exc.statement_index}" if exc.statement_index else ""
        print(f"[Static Verification Error{loc}] {exc.message}", file=sys.stderr)
        return 1
    except LLMProviderError as exc:
        print(f"[LLM Provider Error] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

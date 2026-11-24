"""Command-line interface (`meme`) for the Memelang compiler."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import cast

from memelang.analyzer.verifier import (
    StaticVerificationError,
    VerificationOutcome,
    verify_synthesis,
)
from memelang.codegen import TARGET_LANGS, TargetLang, generate_code
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import AmbiguityDiagnostic, ProgramIR, TestBlockStmt
from memelang.llm import (
    DEFAULT_GGUF_FILENAME,
    DEFAULT_GGUF_REPO,
    ExampleRetriever,
    LLMProviderError,
    ParseError,
    get_provider,
    pull_gguf_model,
)
from memelang.llm.base import synthesize_compat
from memelang.lockfile.manager import LockfileManager, LockfileResolutionError
from memelang.runner.executor import execute_ir, execute_test_blocks, program_uses_input

ALL_TARGETS = list(TARGET_LANGS)


def _env_quiet_prompts() -> bool:
    """Whether `MEME_QUIET_PROMPTS` opts out of progress chatter."""
    return os.environ.get("MEME_QUIET_PROMPTS", "").strip().lower() in ("1", "true", "yes")


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
        synthesis = synthesize_compat(provider, source_text, source_path)
        initial_outcome = verify_synthesis(synthesis, source_path=source_path)
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


def _add_shared_args(sub: argparse.ArgumentParser, default_provider: str = "auto") -> None:
    sub.add_argument("source", type=Path, help="Path to `.meme` source file")
    sub.add_argument(
        "--provider",
        default=default_provider,
        help=f"LLM frontend provider: auto, heuristic, ollama[:model], openai-local:<model>, llama-cpp:<gguf>, gemini[:model] (default: {default_provider})",
    )
    sub.add_argument(
        "--lockfile",
        type=Path,
        default=Path("build.lock"),
        help="Path to deterministic lockfile (default: build.lock)",
    )


def _add_resolve_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--resolve",
        action="append",
        metavar="ID=OPT",
        help="Resolve ambiguity statement ID to option (e.g. --resolve 2=1)",
    )
    sub.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt interactively when semantic ambiguities are detected",
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
        choices=ALL_TARGETS,
        required=True,
        help="Target programming language",
    )
    p_compile.add_argument("-o", "--output", type=Path, help="Output file path (default: stdout)")
    _add_resolve_args(p_compile)

    # run
    p_run = subparsers.add_parser("run", help="Compile and immediately execute a .meme file")
    _add_shared_args(p_run)
    p_run.add_argument(
        "--target",
        choices=ALL_TARGETS,
        default="python",
        help="Target runtime backend (default: python)",
    )
    _add_resolve_args(p_run)

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

    # build
    p_build = subparsers.add_parser(
        "build", help="Compile a .meme file to a native executable via the C backend"
    )
    _add_shared_args(p_build, default_provider="heuristic")
    p_build.add_argument("-o", "--output", type=Path, required=True, help="Output binary path")
    _add_resolve_args(p_build)
    p_build.add_argument(
        "--cc",
        type=str,
        default=None,
        help="C compiler executable (default: cc, fallback: gcc)",
    )
    p_build.add_argument(
        "--cflags",
        type=str,
        default=None,
        help='C compiler flags (default: "-std=c11 -O2")',
    )

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

    # test
    p_test = subparsers.add_parser("test", help="Run test blocks in .meme files")
    p_test.add_argument(
        "dir",
        nargs="?",
        default="tests/meme",
        help="Directory or .meme file to test (default: tests/meme)",
    )
    p_test.add_argument(
        "--target",
        choices=ALL_TARGETS,
        default="python",
        help="Target runtime backend (default: python)",
    )
    p_test.add_argument(
        "--provider",
        default="heuristic",
        help="LLM frontend provider: heuristic, auto, etc. (default: heuristic)",
    )
    p_test.add_argument(
        "--lockfile",
        type=Path,
        default=None,
        help="Path to deterministic lockfile (optional)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    forwarded_argv: list[str] = []
    if "--" in raw_argv:
        dash_idx = raw_argv.index("--")
        forwarded_argv = raw_argv[dash_idx + 1 :]
        cli_argv = raw_argv[:dash_idx]
    else:
        cli_argv = raw_argv

    args = parser.parse_args(cli_argv)

    if forwarded_argv and args.command != "run":
        parser.error(f"unrecognized arguments: -- {' '.join(forwarded_argv)}")

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

        if args.command == "test":
            target_path = Path(args.dir)
            if not target_path.exists():
                print(f"[Error] Test path not found: {target_path}", file=sys.stderr)
                return 1

            if target_path.is_file():
                meme_files = [target_path]
            else:
                meme_files = sorted(target_path.glob("*.meme"))

            target = cast(TargetLang, args.target)
            total_cases = 0
            failed_cases = 0

            for meme_file in meme_files:
                lockfile_path = args.lockfile or (
                    LockfileManager.find_lock(meme_file) or Path(str(meme_file) + ".lock")
                )

                source_text = meme_file.read_text(encoding="utf-8")
                cached_program = None
                is_stale = False

                if lockfile_path.is_file():
                    try:
                        lock_mgr = LockfileManager(lockfile_path)
                        source_key = _compute_source_key(meme_file)
                        cached_program = lock_mgr.get_cached_program(source_key, source_text)
                        is_stale = lock_mgr.is_stale(source_key, source_text)
                    except Exception:
                        is_stale = True

                quiet = _env_quiet_prompts()

                if is_stale:
                    if not quiet:
                        print(f"note: lock stale for {meme_file}, recompiled", file=sys.stderr)
                    retriever = ExampleRetriever()
                    retriever.index_corpus()
                    provider = get_provider(getattr(args, "provider", "heuristic"), retriever=retriever)
                    synthesis = synthesize_compat(provider, source_text, meme_file)
                    outcome = verify_synthesis(synthesis, source_path=meme_file)
                    program, ambiguities = outcome.program, outcome.ambiguities
                elif cached_program is not None:
                    program, ambiguities = cached_program, []
                else:
                    program, ambiguities = _load_or_synthesize_program(
                        source_path=meme_file,
                        lockfile_path=lockfile_path,
                        provider_spec=getattr(args, "provider", "heuristic"),
                        resolutions={},
                        interactive=False,
                    )
                if program is None:
                    for diag in ambiguities:
                        print(_format_ambiguity(diag), file=sys.stderr)
                    return 2

                test_blocks = [s for s in program.statements if isinstance(s, TestBlockStmt)]
                if not test_blocks:
                    continue

                test_names = [s.name for s in test_blocks]
                block_results = execute_test_blocks(
                    program,
                    target=target,
                    test_names=test_names,
                    source_dir=meme_file.resolve().parent,
                )

                file_display = meme_file.as_posix()
                for name, res in block_results:
                    total_cases += 1
                    if res.returncode == 0:
                        print(f"PASS {file_display}::{name}")
                    else:
                        failed_cases += 1
                        m = re.search(r"ASSERT FAILED line (\d+):", res.stderr)
                        line_str = f" (line {m.group(1)})" if m else ""
                        print(f"FAIL {file_display}::{name}{line_str}")

            print(f"Ran {total_cases} cases, {failed_cases} failed")
            return 1 if failed_cases > 0 else 0

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

        if args.command == "build":
            cc_arg = getattr(args, "cc", None)
            compiler: str | None = None
            if cc_arg is not None:
                cand = shutil.which(cc_arg)
                if cand is not None:
                    compiler = cand
                else:
                    p = Path(cc_arg)
                    if p.is_file() and os.access(p, os.X_OK):
                        compiler = str(p.resolve())
            else:
                for default_cc in ("cc", "gcc"):
                    cand = shutil.which(default_cc)
                    if cand is not None:
                        compiler = cand
                        break

            if compiler is None:
                if cc_arg:
                    print(f"[Error] C compiler not found: {cc_arg}", file=sys.stderr)
                else:
                    print("[Error] No C compiler found ('cc' or 'gcc').", file=sys.stderr)
                return 1

            code = generate_code(program, "c")
            args.output.parent.mkdir(parents=True, exist_ok=True)

            cflags_arg = getattr(args, "cflags", None)
            cflags = shlex.split(cflags_arg) if cflags_arg is not None else ["-std=c11", "-O2"]

            with tempfile.TemporaryDirectory(prefix="meme_build_") as tmp_dir:
                tmp_c = Path(tmp_dir) / f"{args.source.stem}.c"
                tmp_c.write_text(code, encoding="utf-8")

                cmd = [compiler, *cflags, str(tmp_c), "-o", str(args.output), "-lm"]
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                except OSError as exc:
                    print(f"[Error] Failed to execute C compiler: {exc}", file=sys.stderr)
                    return 1

                if proc.returncode != 0:
                    if proc.stderr:
                        sys.stderr.write(proc.stderr)
                    elif proc.stdout:
                        sys.stderr.write(proc.stdout)
                    return proc.returncode if proc.returncode != 0 else 1

            quiet = _env_quiet_prompts()
            if not quiet:
                print(str(args.output), file=sys.stderr)
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
            run_kwargs: dict[str, object] = {}
            if forwarded_argv:
                run_kwargs["argv"] = forwarded_argv
            exec_res = execute_ir(
                program,
                target,
                interactive_io=use_interactive,
                source_dir=args.source.resolve().parent,
                **run_kwargs,
            )
            if exec_res.stdout:
                sys.stdout.write(exec_res.stdout)
            if exec_res.stderr:
                sys.stderr.write(exec_res.stderr)
            return exec_res.returncode

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
    except ParseError as exc:
        print(f"[Parse Error] {exc}", file=sys.stderr)
        return 1
    except LLMProviderError as exc:
        print(f"[LLM Provider Error] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

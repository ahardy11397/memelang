"""Multi-target compiler & subprocess executor for Python, Rust, and C++20."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from memelang.codegen import TargetLang, generate_code
from memelang.ir.schema import (
    IRExpr,
    IRStatement,
    ProgramIR,
    ReadInputExpr,
    TestBlockStmt,
)
from memelang.ir.walk import iter_child_exprs, iter_stmt_bodies


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int
    generated_code: str


def _expr_uses_input(expr: IRExpr) -> bool:
    """Whether evaluating `expr` can consume stdin (`read input`)."""
    if isinstance(expr, ReadInputExpr):
        return True
    return any(_expr_uses_input(child) for child in iter_child_exprs(expr))


def _stmts_use_input(stmts: list[IRStatement]) -> bool:
    for s in stmts:
        if any(_expr_uses_input(child) for child in iter_child_exprs(s)):
            return True
        if any(_stmts_use_input(body) for body in iter_stmt_bodies(s)):
            return True
    return False


def program_uses_input(ir: ProgramIR) -> bool:
    return _stmts_use_input(ir.statements)


def _run_target_cmd(
    cmd: list[str],
    code: str,
    timeout_sec: float,
    stdin_text: str | None,
    interactive_io: bool,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> ExecutionResult:
    if interactive_io:
        proc = subprocess.run(cmd, env=env, cwd=cwd)
        return ExecutionResult(
            stdout="",
            stderr="",
            returncode=proc.returncode,
            generated_code=code,
        )
    proc = subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=env,
        cwd=cwd,
    )
    return ExecutionResult(
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        generated_code=code,
    )


@dataclass(frozen=True)
class _TargetRecipe:
    """Per-target build recipe shared by `execute_ir` and `execute_test_blocks`.

    ``compile_cmd`` / ``run_cmd`` are templates with ``{src}``, ``{bin}``,
    ``{run}`` (the artifact that gets executed), ``{tmp}`` and ``{tsc}``
    placeholders. ``compile_cmd`` is None for targets that need no
    compilation step (python).
    """

    source_name: str
    run_name: str
    run_cmd: tuple[str, ...]
    compile_cmd: tuple[str, ...] | None = None
    bin_name: str | None = None


_TARGET_RECIPES: dict[str, _TargetRecipe] = {
    "python": _TargetRecipe(
        source_name="main.py",
        run_name="main.py",
        run_cmd=(sys.executable, "{run}"),
    ),
    "rust": _TargetRecipe(
        source_name="main.rs",
        bin_name="app",
        run_name="app",
        run_cmd=("{bin}",),
        compile_cmd=("rustc", "--edition=2021", "-O", "{src}", "-o", "{bin}"),
    ),
    "cpp": _TargetRecipe(
        source_name="main.cpp",
        bin_name="app",
        run_name="app",
        run_cmd=("{bin}",),
        compile_cmd=("g++", "-std=c++20", "-O2", "{src}", "-o", "{bin}"),
    ),
    "go": _TargetRecipe(
        source_name="main.go",
        bin_name="app",
        run_name="app",
        run_cmd=("{bin}",),
        compile_cmd=("go", "build", "-o", "{bin}", "{src}"),
    ),
    "c": _TargetRecipe(
        source_name="main.c",
        bin_name="app",
        run_name="app",
        run_cmd=("{bin}",),
        compile_cmd=("gcc", "-std=c11", "-O2", "{src}", "-o", "{bin}", "-lm"),
    ),
    "ts": _TargetRecipe(
        source_name="main.ts",
        run_name="main.js",
        run_cmd=("node", "{run}"),
        compile_cmd=(
            "{tsc}",
            "{src}",
            "--outDir",
            "{tmp}",
            "--target",
            "es2022",
            "--module",
            "node16",
        ),
    ),
}


def _tsc_bin() -> str:
    return shutil.which("tsc") or str(Path.home() / ".local" / "bin" / "tsc")


def _format_cmd(cmd: tuple[str, ...], subs: dict[str, Path | str]) -> list[str]:
    return [part.format(**subs) for part in cmd]


def execute_ir(
    ir: ProgramIR,
    target: TargetLang,
    timeout_sec: float = 15.0,
    stdin_text: str | None = None,
    interactive_io: bool = False,
    source_dir: Path | None = None,
    quiet_prompts: bool = False,
    argv: list[str] | None = None,
    cwd: Path | None = None,
) -> ExecutionResult:
    code = generate_code(ir, target)
    run_env: dict[str, str] | None = None
    if source_dir is not None or quiet_prompts:
        run_env = dict(os.environ)
        if source_dir is not None:
            run_env["MEME_SOURCE_DIR"] = str(source_dir.resolve())
        if quiet_prompts:
            run_env["MEME_QUIET_PROMPTS"] = "1"
    extra_args = list(argv) if argv else []

    recipe = _TARGET_RECIPES.get(target)
    if recipe is None:
        raise ValueError(f"Unsupported target language: {target!r}")

    try:
        with tempfile.TemporaryDirectory(prefix=f"meme_{target}_") as tmp_dir:
            tmp = Path(tmp_dir)
            exec_cwd = cwd if cwd is not None else tmp

            src_path = tmp / recipe.source_name
            src_path.write_text(code, encoding="utf-8")
            subs = {
                "src": src_path,
                "bin": tmp / (recipe.bin_name or recipe.run_name),
                "run": tmp / recipe.run_name,
                "tmp": tmp,
                "tsc": _tsc_bin(),
            }
            if recipe.compile_cmd is not None:
                comp = subprocess.run(
                    _format_cmd(recipe.compile_cmd, subs),
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                if comp.returncode != 0:
                    return ExecutionResult(
                        stdout=comp.stdout,
                        stderr=comp.stderr,
                        returncode=comp.returncode,
                        generated_code=code,
                    )
            return _run_target_cmd(
                [*_format_cmd(recipe.run_cmd, subs), *extra_args],
                code=code,
                timeout_sec=timeout_sec,
                stdin_text=stdin_text,
                interactive_io=interactive_io,
                env=run_env,
                cwd=exec_cwd,
            )
    except subprocess.TimeoutExpired as exc:
        out_str = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
        )
        return ExecutionResult(
            stdout=out_str,
            stderr=f"Execution timed out after {timeout_sec}s\n",
            returncode=124,
            generated_code=code,
        )


def execute_test_blocks(
    ir: ProgramIR,
    target: TargetLang,
    test_names: list[str] | None = None,
    timeout_sec: float = 15.0,
    source_dir: Path | None = None,
    cwd: Path | None = None,
) -> list[tuple[str, ExecutionResult]]:
    """Compile once, then execute each specified test block in a separate process."""
    if test_names is None:
        test_names = [s.name for s in ir.statements if isinstance(s, TestBlockStmt)]
    if not test_names:
        return []

    code = generate_code(ir, target)
    run_env: dict[str, str] | None = None
    if source_dir is not None:
        run_env = dict(os.environ)
        run_env["MEME_SOURCE_DIR"] = str(source_dir.resolve())

    recipe = _TARGET_RECIPES.get(target)
    if recipe is None:
        raise ValueError(f"Unsupported target language: {target!r}")

    results: list[tuple[str, ExecutionResult]] = []

    with tempfile.TemporaryDirectory(prefix=f"meme_test_{target}_") as tmp_dir:
        tmp = Path(tmp_dir)
        exec_cwd = cwd if cwd is not None else tmp

        src_path = tmp / recipe.source_name
        src_path.write_text(code, encoding="utf-8")
        subs = {
            "src": src_path,
            "bin": tmp / (recipe.bin_name or recipe.run_name),
            "run": tmp / recipe.run_name,
            "tmp": tmp,
            "tsc": _tsc_bin(),
        }
        if recipe.compile_cmd is not None:
            comp = subprocess.run(
                _format_cmd(recipe.compile_cmd, subs),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if comp.returncode != 0:
                err_res = ExecutionResult(
                    stdout=comp.stdout,
                    stderr=comp.stderr,
                    returncode=comp.returncode,
                    generated_code=code,
                )
                return [(name, err_res) for name in test_names]
        for name in test_names:
            res = _run_target_cmd(
                [*_format_cmd(recipe.run_cmd, subs), "--meme-test", name],
                code=code,
                timeout_sec=timeout_sec,
                stdin_text=None,
                interactive_io=False,
                env=run_env,
                cwd=exec_cwd,
            )
            results.append((name, res))
        return results

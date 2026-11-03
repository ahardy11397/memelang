"""Multi-target compiler & subprocess executor for Python, Rust, and C++20."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile

from memelang.codegen import TargetLang, generate_code
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
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    ReturnStmt,
    StrEndsWithExpr,
    UnaryOpExpr,
    VarDeclStmt,
    WhileStmt,
)


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int
    generated_code: str


def _expr_uses_input(expr: IRExpr) -> bool:
    if isinstance(expr, ReadInputExpr):
        return True
    if isinstance(expr, ListLiteralExpr):
        return any(_expr_uses_input(e) for e in expr.elements)
    if isinstance(expr, RandomIntExpr):
        return _expr_uses_input(expr.min_val) or _expr_uses_input(expr.max_val)
    if isinstance(expr, RandomListExpr):
        return (
            _expr_uses_input(expr.count)
            or _expr_uses_input(expr.min_val)
            or _expr_uses_input(expr.max_val)
        )
    if isinstance(expr, BinaryOpExpr):
        return _expr_uses_input(expr.left) or _expr_uses_input(expr.right)
    if isinstance(expr, UnaryOpExpr):
        return _expr_uses_input(expr.operand)
    if isinstance(expr, ListLengthExpr):
        return _expr_uses_input(expr.target)
    if isinstance(expr, ListIndexExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.index)
    if isinstance(expr, CallExpr):
        return any(_expr_uses_input(a) for a in expr.args)
    if isinstance(expr, StrEndsWithExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.suffix)
    if isinstance(expr, ReadJsonListExpr):
        return _expr_uses_input(expr.filepath)
    return False


def _stmts_use_input(stmts: list[IRStatement]) -> bool:
    for s in stmts:
        if isinstance(s, (VarDeclStmt, AssignStmt, ListAppendStmt)) and _expr_uses_input(s.value):
            return True
        if isinstance(s, ListInsertStmt) and (
            _expr_uses_input(s.index) or _expr_uses_input(s.value)
        ):
            return True
        if isinstance(s, FailStmt) and _expr_uses_input(s.message):
            return True
        if isinstance(s, ClampCollectionStmt) and (
            _expr_uses_input(s.min_val) or _expr_uses_input(s.max_val)
        ):
            return True
        if isinstance(s, FilterCollectionStmt) and _expr_uses_input(s.predicate):
            return True
        if isinstance(s, PrintStmt) and any(_expr_uses_input(e) for e in s.expressions):
            return True
        if isinstance(s, ReturnStmt) and s.value is not None and _expr_uses_input(s.value):
            return True
        if isinstance(s, IfStmt) and (
            _expr_uses_input(s.condition)
            or _stmts_use_input(s.then_body)
            or _stmts_use_input(s.else_body)
        ):
            return True
        if isinstance(s, ForEachStmt) and _stmts_use_input(s.body):
            return True
        if isinstance(s, ForRangeStmt) and (
            _expr_uses_input(s.start)
            or _expr_uses_input(s.end)
            or _stmts_use_input(s.body)
        ):
            return True
        if isinstance(s, WhileStmt) and (
            _expr_uses_input(s.condition) or _stmts_use_input(s.body)
        ):
            return True
        if isinstance(s, FuncDefStmt) and _stmts_use_input(s.body):
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
) -> ExecutionResult:
    if interactive_io:
        proc = subprocess.run(cmd)
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
    )
    return ExecutionResult(
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        generated_code=code,
    )


def execute_ir(
    ir: ProgramIR,
    target: TargetLang,
    timeout_sec: float = 15.0,
    stdin_text: str | None = None,
    interactive_io: bool = False,
) -> ExecutionResult:
    code = generate_code(ir, target)

    try:
        with tempfile.TemporaryDirectory(prefix=f"meme_{target}_") as tmp_dir:
            tmp = Path(tmp_dir)

            if target == "python":
                src_path = tmp / "main.py"
                src_path.write_text(code, encoding="utf-8")
                return _run_target_cmd(
                    [sys.executable, str(src_path)],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
                )

            if target == "rust":
                src_path = tmp / "main.rs"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["rustc", "--edition=2021", "-O", str(src_path), "-o", str(bin_path)],
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
                    [str(bin_path)],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
                )

            if target == "cpp":
                src_path = tmp / "main.cpp"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["g++", "-std=c++20", "-O2", str(src_path), "-o", str(bin_path)],
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
                    [str(bin_path)],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
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

    raise ValueError(f"Unsupported target language: {target!r}")

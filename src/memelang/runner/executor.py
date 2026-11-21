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
    AppendFileStmt,
    ArgAtExpr,
    ArgCountExpr,
    AssignStmt,
    BinaryOpExpr,
    CallExpr,
    ClampCollectionStmt,
    CompoundAssignStmt,
    CopyFileStmt,
    CreateDirectoryStmt,
    CurrentEpochExpr,
    DeleteFileStmt,
    EnvVarExpr,
    ExitStmt,
    FailStmt,
    FileExistsExpr,
    FilterCollectionStmt,
    ForEachStmt,
    FormatIntExpr,
    FormatFloatExpr,
    ForRangeStmt,
    FuncDefStmt,
    IRExpr,
    IRStatement,
    IfStmt,
    IsDigitExpr,
    IsLetterExpr,
    IsUpperExpr,
    IsLowerExpr,
    ListAppendStmt,
    ListFilesExpr,
    ListIndexExpr,
    ListInsertStmt,
    ListLengthExpr,
    ListLiteralExpr,
    ListRemoveStmt,
    ListSetIndexStmt,
    MapGetExpr,
    MapHasKeyExpr,
    MapLiteralExpr,
    MapSetStmt,
    MoveFileStmt,
    OptionalIsNothingExpr,
    OptionalNoneExpr,
    OptionalUnwrapExpr,
    OptionalUnwrapOrDefaultExpr,
    OptionalWrapExpr,
    ParseIntExpr,
    ParseIntOrDefaultExpr,
    PrintErrorStmt,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadFileStringExpr,
    ReadFileLinesExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    ReadJsonRecordExpr,
    ReadJsonRecordsExpr,
    RenameFileStmt,
    RecordFieldExpr,
    RecordLiteralExpr,
    RecordSetFieldStmt,
    ReturnStmt,
    StrContainsExpr,
    StrEndsWithExpr,
    StrStartsWithExpr,
    StringCharAtExpr,
    StringIndexOfExpr,
    StringJoinExpr,
    StringLengthExpr,
    StringLowerExpr,
    StringReplaceExpr,
    StringSliceExpr,
    StringSplitExpr,
    StringTrimExpr,
    StringUpperExpr,
    SwitchStmt,
    TestBlockStmt,
    UnaryOpExpr,
    VarDeclStmt,
    WhileStmt,
    WriteFileStmt,
    WriteJsonStmt,
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
    if isinstance(expr, StrStartsWithExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.prefix)
    if isinstance(expr, (StrContainsExpr, StringIndexOfExpr)):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.substring)
    if isinstance(expr, StringReplaceExpr):
        return (
            _expr_uses_input(expr.target)
            or _expr_uses_input(expr.old)
            or _expr_uses_input(expr.new)
        )
    if isinstance(
        expr,
        (
            StringUpperExpr,
            StringLowerExpr,
            StringTrimExpr,
            ParseIntExpr,
            FormatIntExpr,
            IsDigitExpr,
            IsLetterExpr,
            IsUpperExpr,
            IsLowerExpr,
        ),
    ):
        return _expr_uses_input(expr.target)
    if isinstance(expr, FormatFloatExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.decimals)
    if isinstance(expr, CurrentEpochExpr):
        return False
    if isinstance(expr, EnvVarExpr):
        ref = _expr_uses_input(expr.var_name)
        if expr.default_val is not None:
            ref = ref or _expr_uses_input(expr.default_val)
        return ref
    if isinstance(expr, ParseIntOrDefaultExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.default_val)
    if isinstance(expr, StringSplitExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.separator)
    if isinstance(expr, StringJoinExpr):
        return _expr_uses_input(expr.items) or _expr_uses_input(expr.separator)
    if isinstance(expr, StringCharAtExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.index)
    if isinstance(expr, (FileExistsExpr, ReadFileStringExpr, ReadFileLinesExpr)):
        ref = _expr_uses_input(expr.filepath)
        if getattr(expr, "default_val", None) is not None:
            ref = ref or _expr_uses_input(expr.default_val)
        return ref
    if isinstance(expr, ListFilesExpr):
        return _expr_uses_input(expr.path)
    if isinstance(expr, ArgAtExpr):
        return _expr_uses_input(expr.index)
    if isinstance(expr, (ReadJsonRecordExpr, ReadJsonRecordsExpr)):
        ref = _expr_uses_input(expr.filepath)
        if expr.default_val is not None:
            ref = ref or _expr_uses_input(expr.default_val)
        return ref
    if isinstance(expr, ReadJsonListExpr):
        ref = _expr_uses_input(expr.filepath)
        if expr.default_val is not None:
            ref = ref or _expr_uses_input(expr.default_val)
        return ref
    if isinstance(expr, StringLengthExpr):
        return _expr_uses_input(expr.target)
    if isinstance(expr, StringSliceExpr):
        return (
            _expr_uses_input(expr.target)
            or _expr_uses_input(expr.start)
            or _expr_uses_input(expr.end)
        )
    if isinstance(expr, RecordLiteralExpr):
        return any(_expr_uses_input(f.value) for f in expr.fields)
    if isinstance(expr, RecordFieldExpr):
        return _expr_uses_input(expr.target)
    if isinstance(expr, MapLiteralExpr):
        return any(
            _expr_uses_input(e.key) or _expr_uses_input(e.value) for e in expr.entries
        )
    if isinstance(expr, MapGetExpr):
        return (
            _expr_uses_input(expr.target)
            or _expr_uses_input(expr.key)
            or (_expr_uses_input(expr.default_val) if expr.default_val is not None else False)
        )
    if isinstance(expr, MapHasKeyExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.key)
    if isinstance(expr, OptionalWrapExpr):
        return _expr_uses_input(expr.value)
    if isinstance(expr, (OptionalIsNothingExpr, OptionalUnwrapExpr)):
        return _expr_uses_input(expr.target)
    if isinstance(expr, OptionalUnwrapOrDefaultExpr):
        return _expr_uses_input(expr.target) or _expr_uses_input(expr.default_val)
    return False


def _stmts_use_input(stmts: list[IRStatement]) -> bool:
    for s in stmts:
        if isinstance(s, (VarDeclStmt, AssignStmt, CompoundAssignStmt, ListAppendStmt, RecordSetFieldStmt)) and _expr_uses_input(s.value):
            return True
        if isinstance(s, (ListInsertStmt, ListSetIndexStmt)) and (
            _expr_uses_input(s.index) or _expr_uses_input(s.value)
        ):
            return True
        if isinstance(s, ListRemoveStmt) and s.index is not None and _expr_uses_input(s.index):
            return True
        if isinstance(s, MapSetStmt) and (
            _expr_uses_input(s.key) or _expr_uses_input(s.value)
        ):
            return True
        if isinstance(s, (WriteFileStmt, AppendFileStmt)) and (
            _expr_uses_input(s.filepath) or _expr_uses_input(s.content)
        ):
            return True
        if isinstance(s, WriteJsonStmt) and (
            _expr_uses_input(s.target) or _expr_uses_input(s.filepath)
        ):
            return True
        if isinstance(s, (CopyFileStmt, MoveFileStmt)) and (
            _expr_uses_input(s.src) or _expr_uses_input(s.dst)
        ):
            return True
        if isinstance(s, RenameFileStmt) and (
            _expr_uses_input(s.path) or _expr_uses_input(s.new_name)
        ):
            return True
        if isinstance(s, (DeleteFileStmt, CreateDirectoryStmt)) and (
            _expr_uses_input(s.path)
        ):
            return True
        if isinstance(s, FailStmt) and _expr_uses_input(s.message):
            return True
        if isinstance(s, ExitStmt) and _expr_uses_input(s.code):
            return True
        if isinstance(s, ClampCollectionStmt) and (
            _expr_uses_input(s.min_val) or _expr_uses_input(s.max_val)
        ):
            return True
        if isinstance(s, FilterCollectionStmt) and _expr_uses_input(s.predicate):
            return True
        if isinstance(s, (PrintStmt, PrintErrorStmt)) and any(_expr_uses_input(e) for e in s.expressions):
            return True
        if isinstance(s, ReturnStmt) and s.value is not None and _expr_uses_input(s.value):
            return True
        if isinstance(s, IfStmt) and (
            _expr_uses_input(s.condition)
            or _stmts_use_input(s.then_body)
            or _stmts_use_input(s.else_body)
        ):
            return True
        if isinstance(s, SwitchStmt) and (
            _expr_uses_input(s.target)
            or any(
                _expr_uses_input(c.value) or _stmts_use_input(c.body)
                for c in s.cases
            )
            or _stmts_use_input(s.default_body)
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

    try:
        with tempfile.TemporaryDirectory(prefix=f"meme_{target}_") as tmp_dir:
            tmp = Path(tmp_dir)
            exec_cwd = cwd if cwd is not None else tmp

            if target == "python":
                src_path = tmp / "main.py"
                src_path.write_text(code, encoding="utf-8")
                return _run_target_cmd(
                    [sys.executable, str(src_path), *extra_args],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
                    env=run_env,
                    cwd=exec_cwd,
                )

            if target == "rust":
                src_path = tmp / "main.rs"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["rustc", "--edition=2021", str(src_path), "-o", str(bin_path)],
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
                    [str(bin_path), *extra_args],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
                    env=run_env,
                    cwd=exec_cwd,
                )

            if target == "cpp":
                src_path = tmp / "main.cpp"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["g++", "-std=c++20", str(src_path), "-o", str(bin_path)],
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
                    [str(bin_path), *extra_args],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
                    env=run_env,
                    cwd=exec_cwd,
                )

            if target == "go":
                src_path = tmp / "main.go"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["go", "build", "-o", str(bin_path), str(src_path)],
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
                    [str(bin_path), *extra_args],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
                    env=run_env,
                    cwd=exec_cwd,
                )

            if target == "c":
                src_path = tmp / "main.c"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["gcc", "-std=c11", "-O2", str(src_path), "-o", str(bin_path), "-lm"],
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
                    [str(bin_path), *extra_args],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=stdin_text,
                    interactive_io=interactive_io,
                    env=run_env,
                    cwd=exec_cwd,
                )

            if target == "ts":
                src_path = tmp / "main.ts"
                js_path = tmp / "main.js"
                src_path.write_text(code, encoding="utf-8")
                tsc_bin = shutil.which("tsc") or str(Path.home() / ".local" / "bin" / "tsc")
                comp = subprocess.run(
                    [tsc_bin, str(src_path), "--outDir", str(tmp), "--target", "es2022", "--module", "node16"],
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
                    ["node", str(js_path), *extra_args],
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

    raise ValueError(f"Unsupported target language: {target!r}")


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

    results: list[tuple[str, ExecutionResult]] = []

    with tempfile.TemporaryDirectory(prefix=f"meme_test_{target}_") as tmp_dir:
        tmp = Path(tmp_dir)
        exec_cwd = cwd if cwd is not None else tmp

        if target == "python":
            src_path = tmp / "main.py"
            src_path.write_text(code, encoding="utf-8")
            for name in test_names:
                res = _run_target_cmd(
                    [sys.executable, str(src_path), "--meme-test", name],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=None,
                    interactive_io=False,
                    env=run_env,
                    cwd=exec_cwd,
                )
                results.append((name, res))
            return results

        if target == "rust":
            src_path = tmp / "main.rs"
            bin_path = tmp / "app"
            src_path.write_text(code, encoding="utf-8")
            comp = subprocess.run(
                ["rustc", "--edition=2021", str(src_path), "-o", str(bin_path)],
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
                    [str(bin_path), "--meme-test", name],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=None,
                    interactive_io=False,
                    env=run_env,
                    cwd=exec_cwd,
                )
                results.append((name, res))
            return results

        if target == "cpp":
            src_path = tmp / "main.cpp"
            bin_path = tmp / "app"
            src_path.write_text(code, encoding="utf-8")
            comp = subprocess.run(
                ["g++", "-std=c++20", str(src_path), "-o", str(bin_path)],
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
                    [str(bin_path), "--meme-test", name],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=None,
                    interactive_io=False,
                    env=run_env,
                    cwd=exec_cwd,
                )
                results.append((name, res))
            return results

        if target == "go":
            src_path = tmp / "main.go"
            bin_path = tmp / "app"
            src_path.write_text(code, encoding="utf-8")
            comp = subprocess.run(
                ["go", "build", "-o", str(bin_path), str(src_path)],
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
                    [str(bin_path), "--meme-test", name],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=None,
                    interactive_io=False,
                    env=run_env,
                    cwd=exec_cwd,
                )
                results.append((name, res))
            return results

        if target == "c":
            src_path = tmp / "main.c"
            bin_path = tmp / "app"
            src_path.write_text(code, encoding="utf-8")
            comp = subprocess.run(
                ["gcc", "-std=c11", "-O2", str(src_path), "-o", str(bin_path), "-lm"],
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
                    [str(bin_path), "--meme-test", name],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=None,
                    interactive_io=False,
                    env=run_env,
                    cwd=exec_cwd,
                )
                results.append((name, res))
            return results

        if target == "ts":
            src_path = tmp / "main.ts"
            js_path = tmp / "main.js"
            src_path.write_text(code, encoding="utf-8")
            tsc_bin = shutil.which("tsc") or str(Path.home() / ".local" / "bin" / "tsc")
            comp = subprocess.run(
                [tsc_bin, str(src_path), "--outDir", str(tmp), "--target", "es2022", "--module", "node16"],
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
                    ["node", str(js_path), "--meme-test", name],
                    code=code,
                    timeout_sec=timeout_sec,
                    stdin_text=None,
                    interactive_io=False,
                    env=run_env,
                    cwd=exec_cwd,
                )
                results.append((name, res))
            return results

    raise ValueError(f"Unsupported target language: {target!r}")


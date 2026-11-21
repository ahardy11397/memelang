from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    CallExpr,
    CallStmt,
    FuncDefStmt,
    FuncParam,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    ReturnStmt,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]

MUTUAL_RECURSION_PROGRAM = (
    "function is_even(n: Int) -> Bool:\n"
    "    if n == 0:\n"
    "        return true\n"
    "    return is_odd(n - 1)\n"
    "\n"
    "function is_odd(n: Int) -> Bool:\n"
    "    if n == 0:\n"
    "        return false\n"
    "    return is_even(n - 1)\n"
    "\n"
    'print "4 is even:", is_even(4)\n'
    'print "4 is odd:", is_odd(4)\n'
    'print "7 is even:", is_even(7)\n'
    'print "7 is odd:", is_odd(7)\n'
)


@pytest.mark.parametrize("target", TARGETS)
def test_mutual_recursion_cross_target_parity(target: TargetLang):
    outcome = verify_synthesis(HeuristicProvider().synthesize(MUTUAL_RECURSION_PROGRAM))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    expected_stdout = (
        "4 is even: true\n"
        "4 is odd: false\n"
        "7 is even: false\n"
        "7 is odd: true\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected_stdout
    assert res.stderr == ""


def test_mutual_recursion_canonical_decompilation():
    outcome = verify_synthesis(HeuristicProvider().synthesize(MUTUAL_RECURSION_PROGRAM))
    assert outcome.program is not None
    out = to_canonical_meme(outcome.program)
    assert "function is_even(n: Int) -> Bool:" in out
    assert "function is_odd(n: Int) -> Bool:" in out


@pytest.mark.parametrize("target", TARGETS)
def test_locked_536_mutual_recursion_parity(target: TargetLang):
    from pathlib import Path
    from memelang.lockfile.manager import LockfileManager

    meme_path = Path("examples/advanced/536_mutual_recursion.meme")
    lock_path = Path("examples/advanced/536_mutual_recursion.meme.lock")
    src = meme_path.read_text(encoding="utf-8")
    mgr = LockfileManager(lock_path)
    prog = mgr.get_cached_program(str(meme_path), src)
    assert prog is not None
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "0 is even: true\n"
        "0 is odd: false\n"
        "4 is even: true\n"
        "4 is odd: false\n"
        "7 is even: false\n"
        "7 is odd: true\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


def test_mutual_recursion_verifier_rejects_duplicates():
    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="f",
                params=[],
                return_type="Void",
                body=[],
                source_line=1,
            ),
            FuncDefStmt(
                name="f",
                params=[],
                return_type="Void",
                body=[],
                source_line=3,
            ),
        ]
    )
    with pytest.raises(StaticVerificationError, match="Duplicate function definition `f`"):
        verify_program(prog)


def test_mutual_recursion_verifier_rejects_main_function():
    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="main",
                params=[],
                return_type="Void",
                body=[],
                source_line=1,
            ),
            PrintStmt(
                expressions=[LiteralExpr(value="hello", data_type="String")],
                source_line=2,
            ),
        ]
    )
    with pytest.raises(StaticVerificationError, match="do not define main()"):
        verify_program(prog)


def test_mutual_recursion_verifier_rejects_nested_function():
    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="outer",
                params=[],
                return_type="Void",
                body=[
                    FuncDefStmt(
                        name="inner",
                        params=[],
                        return_type="Void",
                        body=[],
                        source_line=2,
                    )
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="Nested function definitions are not supported"):
        verify_program(prog)


def test_mutual_recursion_verifier_rejects_undeclared_call():
    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="foo",
                params=[],
                return_type="Void",
                body=[
                    CallStmt(func_name="missing_fn", args=[])
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="Call to undeclared function `missing_fn`"):
        verify_program(prog)

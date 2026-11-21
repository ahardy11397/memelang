from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    FloatOfExpr,
    FormatFloatExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    VarRefExpr,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_float_of_format_cross_target_parity(target: TargetLang):
    src = "print format float of 12345 with 2 decimals\n"
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.replace("\r\n", "\n") == "12345.00\n"
    assert res.stderr == ""


@pytest.mark.parametrize("target", TARGETS)
def test_float_of_money_math_cross_target_parity(target: TargetLang):
    src = (
        "define cents: Int as 1999\n"
        "define dollars: Float as float of cents / 100.0\n"
        'print "$" + (format dollars with 2 decimals)\n'
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.replace("\r\n", "\n") == "$19.99\n"
    assert res.stderr == ""


def test_float_of_verifier_rejects_non_int():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    FloatOfExpr(target=LiteralExpr(value="abc", data_type="String"))
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="`float of` requires Int target"):
        verify_program(prog)


def test_float_of_canonical_decompilation():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    FloatOfExpr(target=VarRefExpr(name="x"))
                ],
                source_line=1,
            )
        ]
    )
    out = to_canonical_meme(prog)
    assert "float of x" in out

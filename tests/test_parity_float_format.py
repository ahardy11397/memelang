from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    FormatFloatExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    VarDeclStmt,
    VarRefExpr,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_float_format_cross_target_parity(target: TargetLang):
    src = (
        "print format 2.345 with 2 decimals\n"
        "print format 2.5 with 0 decimals\n"
        "print format -2.5 with 0 decimals\n"
        "print format 0.005 with 2 decimals\n"
        "print format 10.0 with 2 decimals\n"
        "print format 1000000000.0 with 0 decimals\n"
        "print format -0.001 with 2 decimals\n"
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    expected = "2.35\n3\n-3\n0.01\n10.00\n1000000000\n0.00\n"
    assert res.stdout.replace("\r\n", "\n") == expected


def test_float_format_verifier_rejects_non_float_target():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    FormatFloatExpr(
                        target=LiteralExpr(value=42, data_type="Int"),
                        decimals=LiteralExpr(value=2, data_type="Int"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="requires Float target"):
        verify_program(prog)


def test_float_format_verifier_rejects_non_literal_decimals():
    prog = ProgramIR(
        statements=[
            VarDeclStmt(name="d", var_type="Int", value=LiteralExpr(value=2, data_type="Int")),
            PrintStmt(
                expressions=[
                    FormatFloatExpr(
                        target=LiteralExpr(value=3.14, data_type="Float"),
                        decimals=VarRefExpr(name="d"),
                    )
                ]
            ),
        ]
    )
    with pytest.raises(StaticVerificationError, match="must be a literal Int"):
        verify_program(prog)


def test_float_format_verifier_rejects_out_of_bounds_decimals():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    FormatFloatExpr(
                        target=LiteralExpr(value=3.14, data_type="Float"),
                        decimals=LiteralExpr(value=11, data_type="Int"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="between 0 and 10"):
        verify_program(prog)


def test_float_format_canonical_roundtrip():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    FormatFloatExpr(
                        target=LiteralExpr(value=2.345, data_type="Float"),
                        decimals=LiteralExpr(value=2, data_type="Int"),
                    )
                ]
            )
        ]
    )
    canonical = to_canonical_meme(prog)
    assert canonical.strip() == "print format 2.345 with 2 decimals"

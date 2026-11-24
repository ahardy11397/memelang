from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    FloatOfExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    VarRefExpr,
)


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

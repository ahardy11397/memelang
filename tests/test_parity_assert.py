from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    AssertStmt,
    BinaryOpExpr,
    LiteralExpr,
    ProgramIR,
)


def test_assert_verifier_rejects_non_bool():
    prog = ProgramIR(
        statements=[
            AssertStmt(
                condition=LiteralExpr(value=42, data_type="Int"),
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="must evaluate to Bool"):
        verify_program(prog)


def test_assert_canonical_roundtrip():
    prog = ProgramIR(
        statements=[
            AssertStmt(
                condition=BinaryOpExpr(
                    op=">",
                    left=LiteralExpr(value=2, data_type="Int"),
                    right=LiteralExpr(value=3, data_type="Int"),
                ),
                source_line=2,
            )
        ]
    )
    canonical = to_canonical_meme(prog)
    assert canonical.strip() == "assert 2 > 3"

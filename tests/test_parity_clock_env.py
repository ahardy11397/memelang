from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    CurrentEpochExpr,
    EnvVarExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
)


def test_env_var_verifier_rejects_non_string_var_name():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    EnvVarExpr(
                        var_name=LiteralExpr(value=123, data_type="Int"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="var_name must be String"):
        verify_program(prog)


def test_env_var_verifier_rejects_non_string_fallback():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    EnvVarExpr(
                        var_name=LiteralExpr(value="MY_VAR", data_type="String"),
                        default_val=LiteralExpr(value=123, data_type="Int"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="fallback must have type String"):
        verify_program(prog)


def test_clock_and_env_canonical_roundtrip():
    prog = ProgramIR(
        statements=[
            PrintStmt(expressions=[CurrentEpochExpr()]),
            PrintStmt(
                expressions=[
                    EnvVarExpr(
                        var_name=LiteralExpr(value="MY_VAR", data_type="String"),
                        default_val=LiteralExpr(value="fallback", data_type="String"),
                    )
                ]
            ),
            PrintStmt(
                expressions=[
                    EnvVarExpr(
                        var_name=LiteralExpr(value="MY_VAR", data_type="String"),
                    )
                ]
            ),
        ]
    )
    canonical = to_canonical_meme(prog)
    assert "print current epoch seconds" in canonical
    assert 'print environment variable "MY_VAR" or else "fallback"' in canonical
    assert 'print environment variable "MY_VAR"' in canonical

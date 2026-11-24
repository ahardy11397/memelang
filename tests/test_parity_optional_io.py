from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    LiteralExpr,
    OptionalNoneExpr,
    PrintStmt,
    ProgramIR,
    ReadFileLinesExpr,
    ReadFileStringExpr,
    ReadJsonListExpr,
)


def test_optional_io_verifier_rejects_wrong_fallback_string():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    ReadFileStringExpr(
                        filepath=LiteralExpr(value="foo.txt", data_type="String"),
                        default_val=LiteralExpr(value=123, data_type="Int"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="fallback must have type String"):
        verify_program(prog)


def test_optional_io_verifier_rejects_wrong_fallback_lines():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    ReadFileLinesExpr(
                        filepath=LiteralExpr(value="foo.txt", data_type="String"),
                        default_val=LiteralExpr(value="not a list", data_type="String"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="fallback must have type List<String>"):
        verify_program(prog)


def test_optional_io_verifier_rejects_wrong_fallback_json_list():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    ReadJsonListExpr(
                        filepath=LiteralExpr(value="foo.json", data_type="String"),
                        element_type="Int",
                        default_val=LiteralExpr(value="not a list", data_type="String"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match=r"fallback must have type List<Int>"):
        verify_program(prog)


def test_optional_io_canonical_roundtrip():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    ReadFileStringExpr(
                        filepath=LiteralExpr(value="foo.txt", data_type="String"),
                        default_val=OptionalNoneExpr(),
                    ),
                    ReadFileLinesExpr(
                        filepath=LiteralExpr(value="foo.txt", data_type="String"),
                        default_val=OptionalNoneExpr(),
                    ),
                    ReadJsonListExpr(
                        filepath=LiteralExpr(value="foo.json", data_type="String"),
                        element_type="Int",
                        default_val=OptionalNoneExpr(),
                    ),
                ]
            )
        ]
    )
    canonical = to_canonical_meme(prog)
    assert 'read string from file "foo.txt" or else nothing' in canonical
    assert 'read lines from file "foo.txt" or else nothing' in canonical
    assert 'read json file "foo.json" as List<Int> or else nothing' in canonical

from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program
from memelang.codegen import TARGET_LANGS, TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    CharacterOfExpr,
    LiteralExpr,
    NumberOfExpr,
    PrintStmt,
    ProgramIR,
    VarRefExpr,
)

from conftest import run_parity


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_locked_534_conversions_example_cross_target_parity(target: TargetLang):
    from pathlib import Path
    example_path = Path("examples/advanced/534_conversions.meme")
    assert example_path.is_file()
    assert example_path.with_suffix(".meme.lock").is_file()

    src = example_path.read_text(encoding="utf-8")
    res = run_parity(src, target)
    assert res.returncode == 0, res.stderr
    expected_stdout = (
        "cents: 1999\n"
        "dollars: $19.99\n"
        "format int as float: 12345.00\n"
        "code_a: 65\n"
        "char_a: A\n"
        "roundtrip 90: 90\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected_stdout
    assert res.stderr == ""


def test_char_codes_verifier_rejects_empty_string_literal():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    NumberOfExpr(target=LiteralExpr(value="", data_type="String"))
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="single-character string"):
        verify_program(prog)


def test_char_codes_verifier_rejects_multi_char_string_literal():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    NumberOfExpr(target=LiteralExpr(value="ab", data_type="String"))
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="single-character string"):
        verify_program(prog)


def test_char_codes_verifier_rejects_non_string():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    NumberOfExpr(target=LiteralExpr(value=42, data_type="Int"))
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="requires String target"):
        verify_program(prog)


def test_char_codes_verifier_rejects_non_int():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    CharacterOfExpr(target=LiteralExpr(value="a", data_type="String"))
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="requires Int target"):
        verify_program(prog)


def test_char_codes_canonical_decompilation():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    NumberOfExpr(target=VarRefExpr(name="s")),
                    CharacterOfExpr(target=VarRefExpr(name="x")),
                ],
                source_line=1,
            )
        ]
    )
    out = to_canonical_meme(prog)
    assert "number of s" in out
    assert "character of x" in out

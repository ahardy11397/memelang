from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    CharacterOfExpr,
    LiteralExpr,
    NumberOfExpr,
    PrintStmt,
    ProgramIR,
    VarRefExpr,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_char_codes_round_trip_ascii_cross_target_parity(target: TargetLang):
    src = (
        "define ok: Bool as true\n"
        "for n from 32 to 126:\n"
        "    define ch: String as character of n\n"
        "    define roundtrip: Int as number of ch\n"
        "    if roundtrip != n:\n"
        "        set ok to false\n"
        'if ok:\n'
        '    print "ASCII 32..126 roundtrip ok"\n'
        'else:\n'
        '    print "roundtrip failed"\n'
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.replace("\r\n", "\n") == "ASCII 32..126 roundtrip ok\n"
    assert res.stderr == ""


@pytest.mark.parametrize("target", TARGETS)
def test_char_codes_basic_cross_target_parity(target: TargetLang):
    src = (
        'define n: Int as number of "a"\n'
        "define c: String as character of 97\n"
        'print n, c\n'
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.replace("\r\n", "\n") == "97 a\n"
    assert res.stderr == ""


@pytest.mark.parametrize("target", TARGETS)
def test_locked_534_conversions_example_cross_target_parity(target: TargetLang):
    from pathlib import Path
    example_path = Path("examples/advanced/534_conversions.meme")
    assert example_path.is_file()
    assert example_path.with_suffix(".meme.lock").is_file()

    src = example_path.read_text(encoding="utf-8")
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
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

from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program
from memelang.codegen import TARGET_LANGS, TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    LiteralExpr,
    PrintErrorStmt,
    ProgramIR,
    VarRefExpr,
)

from conftest import run_parity


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_locked_533_print_error_example_cross_target_parity(target: TargetLang):
    from pathlib import Path
    example_path = Path("examples/advanced/533_print_error.meme")
    assert example_path.is_file()
    assert example_path.with_suffix(".meme.lock").is_file()

    src = example_path.read_text(encoding="utf-8")
    res = run_parity(src, target)
    assert res.returncode == 0, res.stderr
    expected_stdout = "starting diagnostic run\nfinished diagnostic run\n"
    expected_stderr = "warning: diagnostic check triggered\nerror 404 resource not found\n"
    assert res.stdout.replace("\r\n", "\n") == expected_stdout
    assert res.stderr.replace("\r\n", "\n") == expected_stderr


def test_print_error_verifier_rejects_empty_expressions():
    prog = ProgramIR(
        statements=[
            PrintErrorStmt(
                expressions=[],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="`print error` requires at least one expression"):
        verify_program(prog)


def test_print_error_verifier_rejects_undeclared_variable():
    prog = ProgramIR(
        statements=[
            PrintErrorStmt(
                expressions=[VarRefExpr(name="undeclared_var")],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="undeclared variable"):
        verify_program(prog)


def test_print_error_canonical_roundtrip():
    prog = ProgramIR(
        statements=[
            PrintErrorStmt(
                expressions=[
                    LiteralExpr(value="error code", data_type="String"),
                    LiteralExpr(value=404, data_type="Int"),
                ],
                source_line=1,
            )
        ]
    )
    canonical = to_canonical_meme(prog)
    assert canonical.strip() == 'print error "error code", 404'

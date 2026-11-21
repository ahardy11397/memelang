from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    LiteralExpr,
    PrintErrorStmt,
    PrintStmt,
    ProgramIR,
    VarRefExpr,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_print_error_single_expr_cross_target_parity(target: TargetLang):
    src = 'print error "hello from stderr"\n'
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""
    assert res.stderr.replace("\r\n", "\n") == "hello from stderr\n"


@pytest.mark.parametrize("target", TARGETS)
def test_print_error_multi_expr_cross_target_parity(target: TargetLang):
    src = (
        'define code: Int as 500\n'
        'define active: Bool as true\n'
        'print error "fatal:", code, active, "system failure"\n'
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""
    assert res.stderr.replace("\r\n", "\n") == "fatal: 500 true system failure\n"


@pytest.mark.parametrize("target", TARGETS)
def test_print_error_stream_separation_cross_target_parity(target: TargetLang):
    src = (
        'print "standard out 1"\n'
        'print error "standard err 1"\n'
        'print "standard out 2"\n'
        'print error "standard err 2"\n'
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.replace("\r\n", "\n") == "standard out 1\nstandard out 2\n"
    assert res.stderr.replace("\r\n", "\n") == "standard err 1\nstandard err 2\n"


@pytest.mark.parametrize("target", TARGETS)
def test_locked_533_print_error_example_cross_target_parity(target: TargetLang):
    from pathlib import Path
    example_path = Path("examples/advanced/533_print_error.meme")
    assert example_path.is_file()
    assert example_path.with_suffix(".meme.lock").is_file()

    src = example_path.read_text(encoding="utf-8")
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
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

from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    AssertStmt,
    BinaryOpExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_assert_failure_cross_target_parity(target: TargetLang):
    src = "assert 1 is 1\nassert 2 > 3\n"
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 1
    assert res.stderr.replace("\r\n", "\n") == "ASSERT FAILED line 2: 2 > 3\n"


@pytest.mark.parametrize("target", TARGETS)
def test_assert_success_cross_target_parity(target: TargetLang):
    src = "assert 1 is 1\nassert 10 > 2\nprint \"ok\"\n"
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "ok"
    assert res.stderr == ""


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

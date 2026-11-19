from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    CurrentEpochExpr,
    EnvVarExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


SRC = """
define t1 as current epoch seconds
define t2 as current epoch seconds
assert t1 > 0
assert t2 >= t1

define unset_val as environment variable "MEME_TEST_NONEXISTENT_VAR_xyz"
if unset_val is nothing:
    print "unset is nothing: true"
else:
    print "unset is nothing: false"

define fallback_val as environment variable "MEME_TEST_NONEXISTENT_VAR_xyz" or else "default_value"
print "fallback:", fallback_val

define set_fallback as environment variable "PATH" or else "no_path"
assert set_fallback != "no_path"
print "path exists: true"

define path_opt as environment variable "PATH"
if path_opt is nothing:
    print "path is nothing: true"
else:
    print "path is nothing: false"
"""


@pytest.mark.parametrize("target", TARGETS)
def test_clock_and_env_cross_target_parity(target: TargetLang):
    outcome = verify_synthesis(HeuristicProvider().synthesize(SRC))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"Target {target} failed: {res.stderr}"
    expected = (
        "unset is nothing: true\n"
        "fallback: default_value\n"
        "path exists: true\n"
        "path is nothing: false\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


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

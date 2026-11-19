from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
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
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]

SRC = """
# String reader
define s_missing as read string from file "tmp_opt_missing_530.txt" or else nothing
if s_missing is nothing:
    print "s_missing is nothing: true"
else:
    print "s_missing is nothing: false"

define s_fallback as read string from file "tmp_opt_missing_530.txt" or else "default string"
print "s_fallback:", s_fallback

write file "tmp_opt_existing_530.txt" with "hello memelang"
define s_existing as read string from file "tmp_opt_existing_530.txt" or else nothing
if s_existing is nothing:
    print "s_existing is nothing: true"
else:
    print "s_existing:", value of s_existing

# Lines reader
define l_missing as read lines from file "tmp_opt_missing_530.txt" or else nothing
if l_missing is nothing:
    print "l_missing is nothing: true"
else:
    print "l_missing is nothing: false"

define l_fallback as read lines from file "tmp_opt_missing_530.txt" or else ["fallback_line"]
print "l_fallback length:", length of l_fallback

define l_existing as read lines from file "tmp_opt_existing_530.txt" or else nothing
if l_existing is nothing:
    print "l_existing is nothing: true"
else:
    define lines as value of l_existing
    for each line in lines:
        print "l_existing line:", line

# JSON list reader
define j_missing as read json file "tmp_opt_missing_530.json" as List<Int> or else nothing
if j_missing is nothing:
    print "j_missing is nothing: true"
else:
    print "j_missing is nothing: false"

define j_fallback as read json file "tmp_opt_missing_530.json" as List<Int> or else [42, 43]
print "j_fallback length:", length of j_fallback

write file "tmp_opt_malformed_530.json" with "{ bad json: "
define j_bad as read json file "tmp_opt_malformed_530.json" as List<Int> or else nothing
if j_bad is nothing:
    print "j_bad is nothing: true"
else:
    print "j_bad is nothing: false"

write file "tmp_opt_valid_530.json" with "[10, 20, 30]"
define j_valid as read json file "tmp_opt_valid_530.json" as List<Int> or else nothing
if j_valid is nothing:
    print "j_valid is nothing: true"
else:
    define nums as value of j_valid
    for each num in nums:
        print "j_valid num:", num

delete file "tmp_opt_existing_530.txt"
delete file "tmp_opt_malformed_530.json"
delete file "tmp_opt_valid_530.json"
"""


@pytest.mark.parametrize("target", TARGETS)
def test_optional_io_cross_target_parity(target: TargetLang):
    outcome = verify_synthesis(HeuristicProvider().synthesize(SRC))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"Target {target} failed: {res.stderr}"
    expected = (
        "s_missing is nothing: true\n"
        "s_fallback: default string\n"
        "s_existing: hello memelang\n"
        "l_missing is nothing: true\n"
        "l_fallback length: 1\n"
        "l_existing line: hello memelang\n"
        "j_missing is nothing: true\n"
        "j_fallback length: 2\n"
        "j_bad is nothing: true\n"
        "j_valid num: 10\n"
        "j_valid num: 20\n"
        "j_valid num: 30\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


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

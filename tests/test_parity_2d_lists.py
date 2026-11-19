"""Cross-target parity test for generic 2D lists (List<List<T>>)."""

import pytest
from memelang.analyzer.verifier import StaticVerificationError, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]

TWO_D_PARITY_SRC = """
define grid as [[1, 2], [3, 4]]
print "rows", length of grid
print "cell01", grid[0][1]
set grid[1][0] to 9
print "cell10", grid[1][0]
for each row in grid:
    print "rowlen", length of row
define jag as [[1], [2, 3]]
print "jag11", jag[1][1]
print "jag00", jag[0][0]
"""


@pytest.mark.parametrize("target", TARGETS)
def test_2d_lists_cross_target_parity(target: TargetLang):
    outcome = verify_synthesis(HeuristicProvider().synthesize(TWO_D_PARITY_SRC))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"Target {target} failed: {res.stderr}"
    assert res.stdout.splitlines() == [
        "rows 2",
        "cell01 2",
        "cell10 9",
        "rowlen 2",
        "rowlen 2",
        "jag11 3",
        "jag00 1",
    ]


def test_2d_lists_nested_index_type_mismatch_rejected():
    src = """
define g as [[1, 2], [3, 4]]
set g[0][0] to "x"
"""
    with pytest.raises(StaticVerificationError):
        verify_synthesis(HeuristicProvider().synthesize(src))


def test_2d_lists_nested_index_must_be_int():
    src = """
define g as [[1, 2], [3, 4]]
set g[0]["x"] to 5
"""
    with pytest.raises(StaticVerificationError):
        verify_synthesis(HeuristicProvider().synthesize(src))


def test_2d_lists_canonical_roundtrip():
    outcome = verify_synthesis(HeuristicProvider().synthesize(TWO_D_PARITY_SRC))
    assert outcome.program is not None
    canon = to_canonical_meme(outcome.program)
    outcome2 = verify_synthesis(HeuristicProvider().synthesize(canon))
    assert outcome2.program is not None
    canon2 = to_canonical_meme(outcome2.program)
    assert canon == canon2

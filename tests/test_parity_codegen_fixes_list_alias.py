from __future__ import annotations

import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import TargetLang
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_list_copy_semantics_define_and_set(target: TargetLang):
    src = """
define src as [3, 1, 2]
define out as src
sort out ascending
append 99 to out
print "src:", src[0], src[1], src[2], length of src
print "out:", out[0], out[1], out[2], out[3], length of out

define src2 as [10, 20]
define out2 as [999]
set out2 to src2
append 30 to out2
print "src2:", src2[0], src2[1], length of src2
print "out2:", out2[0], out2[1], out2[2], length of out2
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "src: 3 1 2 3\n"
        "out: 1 2 3 99 4\n"
        "src2: 10 20 2\n"
        "out2: 10 20 30 3\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected

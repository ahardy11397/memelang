from __future__ import annotations

import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import TargetLang
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_map_iteration_inside_test_block(target: TargetLang):
    src = """
test map_iter:
    define m as {"banana": 2, "apple": 1, "cherry": 3}
    for each k in m:
        print k
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target, argv=["--meme-test", "map_iter"])
    assert res.returncode == 0, res.stderr
    expected = "apple\nbanana\ncherry\n"
    assert res.stdout.replace("\r\n", "\n") == expected

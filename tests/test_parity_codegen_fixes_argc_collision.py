from __future__ import annotations

import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import TargetLang
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_argc_argv_user_variables_parity(target: TargetLang):
    src = """
define argc as argument count
define argv as ["first", "second"]
print "argc is:", argc >= 0
print "argv:", argv[0], argv[1]

test dummy:
    assert 1 == 1
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None

    # Normal execution
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    expected = "argc is: true\nargv: first second\n"
    assert res.stdout.replace("\r\n", "\n") == expected

    # Test block execution
    res_test = execute_ir(outcome.program, target, argv=["--meme-test", "dummy"])
    assert res_test.returncode == 0, res_test.stderr

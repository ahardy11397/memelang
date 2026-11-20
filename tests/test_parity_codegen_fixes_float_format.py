from __future__ import annotations

import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import TargetLang
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_json_write_float_format_helper_parity(target: TargetLang):
    src = """
record Product:
    name: String
    price: Float

define p as Product(name="Widget", price=19.95)
define ps as [p]
write ps as json to file "products.json"
define content as read string from file "products.json" or else ""
print content
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    expected = '[{"name":"Widget","price":19.95}]\n'
    assert res.stdout.replace("\r\n", "\n") == expected

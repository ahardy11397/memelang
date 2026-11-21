from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    CallExpr,
    ForEachStmt,
    PrintStmt,
    ProgramIR,
    VarRefExpr,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]

ITER_PROGRAM = (
    "record Task:\n"
    "    name: String\n"
    "    deps: List<String>\n"
    "\n"
    "function get_items() -> List<Int>:\n"
    "    return [10, 20, 30]\n"
    "\n"
    'define t: Task as Task(name="release", deps=["build", "test", "deploy"])\n'
    "for each d in t.deps:\n"
    '    print "dep:", d\n'
    "\n"
    "for each item in get_items():\n"
    '    print "item:", item\n'
    "\n"
    "define grid: List<List<Int>> as [[1, 2, 3], [4, 5, 6]]\n"
    "for each cell in grid[0]:\n"
    '    print "cell:", cell\n'
    "\n"
    "for each index i item d in t.deps:\n"
    '    print "idx:", i, d\n'
)

WORKAROUND_PROGRAM = (
    "record Task:\n"
    "    name: String\n"
    "    deps: List<String>\n"
    "\n"
    "function get_items() -> List<Int>:\n"
    "    return [10, 20, 30]\n"
    "\n"
    'define t: Task as Task(name="release", deps=["build", "test", "deploy"])\n'
    "define temp_deps: List<String> as t.deps\n"
    "for each d in temp_deps:\n"
    '    print "dep:", d\n'
    "\n"
    "define temp_items: List<Int> as get_items()\n"
    "for each item in temp_items:\n"
    '    print "item:", item\n'
    "\n"
    "define grid: List<List<Int>> as [[1, 2, 3], [4, 5, 6]]\n"
    "define temp_row: List<Int> as grid[0]\n"
    "for each cell in temp_row:\n"
    '    print "cell:", cell\n'
    "\n"
    "for each index i item d in temp_deps:\n"
    '    print "idx:", i, d\n'
)


@pytest.mark.parametrize("target", TARGETS)
def test_for_each_expressions_cross_target_parity(target: TargetLang):
    outcome_direct = verify_synthesis(HeuristicProvider().synthesize(ITER_PROGRAM))
    assert outcome_direct.program is not None
    res_direct = execute_ir(outcome_direct.program, target)
    assert res_direct.returncode == 0, res_direct.stderr

    outcome_workaround = verify_synthesis(HeuristicProvider().synthesize(WORKAROUND_PROGRAM))
    assert outcome_workaround.program is not None
    res_workaround = execute_ir(outcome_workaround.program, target)
    assert res_workaround.returncode == 0, res_workaround.stderr

    expected_stdout = (
        "dep: build\n"
        "dep: test\n"
        "dep: deploy\n"
        "item: 10\n"
        "item: 20\n"
        "item: 30\n"
        "cell: 1\n"
        "cell: 2\n"
        "cell: 3\n"
        "idx: 0 build\n"
        "idx: 1 test\n"
        "idx: 2 deploy\n"
    )
    assert res_direct.stdout.replace("\r\n", "\n") == expected_stdout
    assert res_workaround.stdout.replace("\r\n", "\n") == expected_stdout
    assert res_direct.stderr == ""


def test_for_each_canonical_decompilation():
    src = (
        "record Task:\n"
        "    deps: List<String>\n"
        'define t: Task as Task(deps=["a", "b"])\n'
        "for each d in t.deps:\n"
        '    print d\n'
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    out = to_canonical_meme(outcome.program)
    assert "for each d in t.deps:" in out


@pytest.mark.parametrize("target", TARGETS)
def test_locked_535_iteration_exprs_parity(target: TargetLang):
    from pathlib import Path
    from memelang.lockfile.manager import LockfileManager

    meme_path = Path("examples/advanced/535_iteration_exprs.meme")
    lock_path = Path("examples/advanced/535_iteration_exprs.meme.lock")
    src = meme_path.read_text(encoding="utf-8")
    mgr = LockfileManager(lock_path)
    prog = mgr.get_cached_program(str(meme_path), src)
    assert prog is not None
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "dep: build\n"
        "dep: test\n"
        "dep: deploy\n"
        "item: 10\n"
        "item: 20\n"
        "item: 30\n"
        "cell: 1\n"
        "cell: 2\n"
        "cell: 3\n"
        "idx: 0 build\n"
        "idx: 1 test\n"
        "idx: 2 deploy\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


def test_for_each_non_collection_rejected():
    from memelang.llm.base import LLMProviderError

    with pytest.raises((StaticVerificationError, LLMProviderError)):
        HeuristicProvider().synthesize("for each x in 42:\n    print x\n")

    with pytest.raises((StaticVerificationError, LLMProviderError)):
        HeuristicProvider().synthesize('for each x in "hello":\n    print x\n')


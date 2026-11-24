from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_synthesis
from memelang.codegen import TARGET_LANGS, TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir


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


@pytest.mark.parametrize("target", list(TARGET_LANGS))
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


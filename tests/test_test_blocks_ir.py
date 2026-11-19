from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    AssertStmt,
    BinaryOpExpr,
    ExitStmt,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    TestBlockStmt,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.lockfile.manager import LockfileManager
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


def test_test_blocks_decompiler_roundtrip():
    src = (
        "define x as 10\n"
        "\n"
        "test first_case:\n"
        "    assert x == 10\n"
        "\n"
        "test second_case:\n"
        "    assert x > 0\n"
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    canonical = to_canonical_meme(outcome.program)
    assert "test first_case:" in canonical
    assert "test second_case:" in canonical
    # Round-trip through heuristic parser
    outcome2 = verify_synthesis(HeuristicProvider().synthesize(canonical))
    assert outcome2.program is not None
    assert to_canonical_meme(outcome2.program) == canonical


def test_test_blocks_lock_hash_rename_vs_reorder():
    src_original = (
        "define x as 10\n"
        "\n"
        "test alpha:\n"
        "    assert x == 10\n"
        "\n"
        "test beta:\n"
        "    assert x > 0\n"
    )
    src_reordered = (
        "define x as 10\n"
        "\n"
        "test beta:\n"
        "    assert x > 0\n"
        "\n"
        "test alpha:\n"
        "    assert x == 10\n"
    )
    src_renamed = (
        "define x as 10\n"
        "\n"
        "test alpha:\n"
        "    assert x == 10\n"
        "\n"
        "test gamma:\n"
        "    assert x > 0\n"
    )
    hash_orig = LockfileManager.compute_source_hash(src_original)
    hash_reordered = LockfileManager.compute_source_hash(src_reordered)
    hash_renamed = LockfileManager.compute_source_hash(src_renamed)

    assert hash_orig == hash_reordered, "Reordering test blocks must not change lock hash"
    assert hash_orig != hash_renamed, "Renaming a test block must change lock hash"


@pytest.mark.parametrize("target", TARGETS)
def test_test_blocks_plain_compiled_run_skips_blocks(target: TargetLang):
    src = (
        "print \"main executed\"\n"
        "\n"
        "test block1:\n"
        "    print \"block1 executed\"\n"
        "\n"
        "test block2:\n"
        "    print \"block2 executed\"\n"
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "main executed"
    assert "block1 executed" not in res.stdout
    assert "block2 executed" not in res.stdout


@pytest.mark.parametrize("target", TARGETS)
def test_test_blocks_dispatch_arg_runs_one_block(target: TargetLang):
    src = (
        "print \"main executed\"\n"
        "\n"
        "test block1:\n"
        "    print \"block1 executed\"\n"
        "\n"
        "test block2:\n"
        "    print \"block2 executed\"\n"
    )
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None

    res1 = execute_ir(outcome.program, target, argv=["--meme-test", "block1"])
    assert res1.returncode == 0, res1.stderr
    assert "block1 executed" in res1.stdout
    assert "main executed" not in res1.stdout
    assert "block2 executed" not in res1.stdout

    res2 = execute_ir(outcome.program, target, argv=["--meme-test", "block2"])
    assert res2.returncode == 0, res2.stderr
    assert "block2 executed" in res2.stdout
    assert "main executed" not in res2.stdout
    assert "block1 executed" not in res2.stdout


def test_test_blocks_exit_stmt_verifier_error():
    src = (
        "test bad_block:\n"
        "    exit with code 1\n"
    )
    outcome = HeuristicProvider().synthesize(src)
    with pytest.raises(StaticVerificationError, match="(?i)exit.*test"):
        verify_synthesis(outcome)

    prog = ProgramIR(
        statements=[
            TestBlockStmt(
                name="bad_block",
                body=[ExitStmt(code=LiteralExpr(value=1, data_type="Int"), source_line=2)],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="(?i)exit.*test"):
        verify_program(prog)

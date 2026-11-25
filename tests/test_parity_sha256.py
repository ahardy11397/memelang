from __future__ import annotations

from pathlib import Path
import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program
from memelang.codegen import TARGET_LANGS, TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    Sha256Expr,
    VarRefExpr,
)

from conftest import run_parity


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_locked_541_sha256_example_cross_target_parity(target: TargetLang):
    example_path = Path("examples/advanced/541_sha256.meme")
    assert example_path.is_file()
    assert example_path.with_suffix(".meme.lock").is_file()

    src = example_path.read_text(encoding="utf-8")
    res = run_parity(src, target)
    assert res.returncode == 0, res.stderr
    expected_stdout = (
        "empty: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n"
        "abc: ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n"
        "msg: 36430da7a6401b36351b0e71dd7519f92642bc797405778d6545544f0e7c4391\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected_stdout
    assert res.stderr == ""


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_sha256_standard_vectors_cross_target_parity(target: TargetLang):
    src = (
        'define v1: String as sha256 of ""\n'
        'define v2: String as sha256 of "abc"\n'
        'define v3: String as sha256 of "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"\n'
        'define v4: String as sha256 of "abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu"\n'
        'print v1\n'
        'print v2\n'
        'print v3\n'
        'print v4\n'
    )
    res = run_parity(src, target)
    assert res.returncode == 0, res.stderr
    expected_stdout = (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n"
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad\n"
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1\n"
        "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected_stdout
    assert res.stderr == ""


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_sha256_multiblock_and_non_ascii_cross_target_parity(target: TargetLang):
    src = (
        'define long_text: String as "The quick brown fox jumps over the lazy dog and runs across the wide open fields in the morning sun."\n'
        'define h_long: String as sha256 of long_text\n'
        'print "long:", h_long\n'
        'define utf8_text: String as "café 🚀"\n'
        'define h_utf8: String as sha256 of utf8_text\n'
        'print "utf8:", h_utf8\n'
    )
    res = run_parity(src, target)
    assert res.returncode == 0, res.stderr
    expected_stdout = (
        "long: ac861fbb367bb0c9e324686b701b69a5f87c95d236bb2eaaef11c1b095c09237\n"
        "utf8: 22b8c9581c75829df9ef018ebff80267c35f980ae1501f77d8a93ee193bede78\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected_stdout
    assert res.stderr == ""


def test_sha256_verifier_rejects_non_string():
    prog_int = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    Sha256Expr(target=LiteralExpr(value=123, data_type="Int"))
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="`sha256` requires a String target"):
        verify_program(prog_int)

    prog_bool = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    Sha256Expr(target=LiteralExpr(value=True, data_type="Bool"))
                ],
                source_line=1,
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="`sha256` requires a String target"):
        verify_program(prog_bool)


def test_sha256_canonical_decompilation():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    Sha256Expr(target=VarRefExpr(name="msg"))
                ],
                source_line=1,
            )
        ]
    )
    out = to_canonical_meme(prog)
    assert "sha256 of msg" in out

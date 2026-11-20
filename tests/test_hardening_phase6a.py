import re
from pathlib import Path
import pytest

from memelang.cli import main


def test_item1_build_defaults_to_heuristic_on_unlocked_unparseable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    # Ensure llama-cpp / LLM is NOT called
    def _poison_llm(spec="auto", retriever=None):
        if spec != "heuristic":
            raise AssertionError(f"LLM provider should not be called! spec={spec}")
        from memelang.llm import HeuristicProvider
        return HeuristicProvider(retriever=retriever)

    monkeypatch.setattr("memelang.cli.get_provider", _poison_llm)

    bad_src = tmp_path / "unparseable.meme"
    bad_src.write_text("this is completely invalid memelang syntax ::::\n", encoding="utf-8")
    out_bin = tmp_path / "out_bin"

    # Build with no --provider flag and no lockfile
    rc = main(["build", str(bad_src), "-o", str(out_bin), "--lockfile", str(tmp_path / "nonexistent.lock")])
    cap = capsys.readouterr()

    assert rc != 0
    assert "[LLM Provider Error]" not in cap.err
    assert "line 1" in cap.err.lower() or "line: 1" in cap.err.lower()


def test_item1_test_defaults_to_heuristic_on_unlocked_unparseable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    def _poison_llm(spec="auto", retriever=None):
        if spec != "heuristic":
            raise AssertionError(f"LLM provider should not be called! spec={spec}")
        from memelang.llm import HeuristicProvider
        return HeuristicProvider(retriever=retriever)

    monkeypatch.setattr("memelang.cli.get_provider", _poison_llm)

    bad_src = tmp_path / "unparseable.meme"
    bad_src.write_text("this is completely invalid memelang syntax ::::\n", encoding="utf-8")

    # Test with no --provider flag and no lockfile
    rc = main(["test", str(bad_src)])
    cap = capsys.readouterr()

    assert rc != 0
    assert "[LLM Provider Error]" not in cap.err
    assert "line 1" in cap.err.lower() or "line: 1" in cap.err.lower()


def test_item1_provider_flag_overrides_and_compile_keeps_auto(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    recorded_specs = []

    def _spy_provider(spec="auto", retriever=None):
        recorded_specs.append(spec)
        from memelang.llm import HeuristicProvider
        return HeuristicProvider(retriever=retriever)

    monkeypatch.setattr("memelang.cli.get_provider", _spy_provider)

    src = tmp_path / "prog.meme"
    src.write_text("define x as 10\nassert x == 10\n", encoding="utf-8")
    out_bin = tmp_path / "out_bin"

    # 1. compile without --provider defaults to auto
    recorded_specs.clear()
    rc = main(["compile", str(src), "--target", "python", "--lockfile", str(tmp_path / "no1.lock")])
    assert rc == 0
    assert recorded_specs == ["auto"]

    # 2. build with explicit --provider overrides
    recorded_specs.clear()
    rc = main(["build", str(src), "-o", str(out_bin), "--provider", "ollama:foo", "--lockfile", str(tmp_path / "no2.lock")])
    assert recorded_specs == ["ollama:foo"]

    # 3. test with explicit --provider overrides
    recorded_specs.clear()
    rc = main(["test", str(src), "--provider", "ollama:bar", "--lockfile", str(tmp_path / "no3.lock")])
    assert recorded_specs == ["ollama:bar"]


def test_item2_meme_test_treats_lockfiles_as_advisory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    test_src = tmp_path / "test_advisory.meme"
    test_src.write_text(
        "test my_case:\n"
        "    define a as 10\n"
        "    assert a == 10\n",
        encoding="utf-8",
    )
    lock_file = test_src.with_suffix(".meme.lock")

    # Step 1: compile to generate matching lockfile
    rc_lock = main(["compile", str(test_src), "--target", "python", "--provider", "heuristic", "--lockfile", str(lock_file)])
    assert rc_lock == 0
    assert lock_file.is_file()
    capsys.readouterr()

    # Step 2: run meme test on fresh file with matching lock: passes, no stale-lock note
    rc_test_fresh = main(["test", str(test_src)])
    cap_fresh = capsys.readouterr()
    assert rc_test_fresh == 0
    assert "note: lock stale for" not in cap_fresh.err

    # Step 3: edit source to change asserted value to 999 (which fails)
    test_src.write_text(
        "test my_case:\n"
        "    define a as 10\n"
        "    assert a == 999\n",
        encoding="utf-8",
    )

    # Step 4: run meme test: new behavior wins, exit code reflects NEW source (fails with 1),
    # and stale-lock note is printed exactly once
    rc_test_stale = main(["test", str(test_src)])
    cap_stale = capsys.readouterr()
    assert rc_test_stale == 1, f"Expected exit code 1 from new source failure, got {rc_test_stale}. Output: {cap_stale.out}"
    assert "FAIL" in cap_stale.out
    assert cap_stale.err.count(f"note: lock stale for {test_src}, recompiled") == 1

    # Step 5: verify MEME_QUIET_PROMPTS suppresses the note
    monkeypatch.setenv("MEME_QUIET_PROMPTS", "1")
    rc_test_quiet = main(["test", str(test_src)])
    cap_quiet = capsys.readouterr()
    assert rc_test_quiet == 1
    assert "note: lock stale for" not in cap_quiet.err


def test_item3_function_main_verifier_error_parse_level():
    from memelang.analyzer.verifier import StaticVerificationError, verify_program
    from memelang.llm.heuristic import HeuristicProvider

    src = (
        "function main() -> Int:\n"
        "    return 0\n"
    )
    syn = HeuristicProvider().synthesize(src)
    from memelang.ir.schema import ProgramIR
    prog = ProgramIR(statements=syn.items)

    with pytest.raises(StaticVerificationError) as exc_info:
        verify_program(prog)

    expected_msg = (
        "Error: do not define main() — Memelang programs are top-level statements; "
        "use 'call <fn>(...)' or top-level code"
    )
    assert exc_info.value.message == expected_msg


@pytest.mark.parametrize("target", ["python", "rust", "cpp", "go", "c", "ts"])
def test_item3_function_main_verifier_error_all_six_targets(
    tmp_path: Path, target: str, capsys: pytest.CaptureFixture[str]
):
    prog = tmp_path / "main_prog.meme"
    prog.write_text(
        "function main() -> Int:\n"
        "    return 42\n",
        encoding="utf-8",
    )
    lock_path = tmp_path / f"{target}.lock"

    rc = main(
        [
            "compile",
            str(prog),
            "--target",
            target,
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_path),
        ]
    )
    cap = capsys.readouterr()

    assert rc == 1
    expected_msg = (
        "Error: do not define main() — Memelang programs are top-level statements; "
        "use 'call <fn>(...)' or top-level code"
    )
    assert expected_msg in cap.err




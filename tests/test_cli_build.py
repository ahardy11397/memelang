import os
from pathlib import Path
import subprocess
import pytest

from memelang.cli import main
from memelang.runner.executor import execute_ir
from memelang.lockfile.manager import LockfileManager


def test_cli_build_happy_path_and_execution(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    src_file = tmp_path / "hello.meme"
    src_file.write_text('print "hello native build"\n', encoding="utf-8")
    lock_file = tmp_path / "hello.meme.lock"
    out_bin = tmp_path / "hello_bin"

    rc = main(
        [
            "build",
            str(src_file),
            "-o",
            str(out_bin),
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_file),
        ]
    )
    cap = capsys.readouterr()
    assert rc == 0, cap.err
    assert out_bin.is_file()
    # Stdout must be completely clean
    assert cap.out == ""
    # Single summary line to stderr: the binary path
    assert cap.err.strip() == str(out_bin)

    # Executing the binary produces expected output
    run_res = subprocess.run([str(out_bin)], capture_output=True, text=True)
    assert run_res.returncode == 0
    assert run_res.stdout == "hello native build\n"


def test_cli_build_missing_compiler(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    src_file = tmp_path / "hello.meme"
    src_file.write_text('print "should not compile"\n', encoding="utf-8")
    out_bin = tmp_path / "out_bin"

    rc = main(
        [
            "build",
            str(src_file),
            "-o",
            str(out_bin),
            "--provider",
            "heuristic",
            "--lockfile",
            str(tmp_path / "b.lock"),
            "--cc",
            "nonexistent_compiler_executable_xyz",
        ]
    )
    cap = capsys.readouterr()
    assert rc == 1
    assert "Traceback" not in cap.err
    assert "C compiler not found" in cap.err or "nonexistent_compiler_executable_xyz" in cap.err
    assert not out_bin.exists()


def test_cli_build_ambiguity_halt_propagates(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    lock_path = tmp_path / "build.lock"
    out_bin = tmp_path / "amb_bin"
    example = Path("examples/random_sort_ambiguous.meme")

    rc = main(
        [
            "build",
            str(example),
            "-o",
            str(out_bin),
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_path),
        ]
    )
    cap = capsys.readouterr()
    assert rc == 2
    assert "[Compiler Warning: Ambiguous Intent" in cap.err
    assert not out_bin.exists()


def test_cli_build_refuses_and_exits_1_on_lockfile_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    # 1. Invalid --resolve argument (mismatched statement ID) exits 1
    lock_path = tmp_path / "build.lock"
    out_bin = tmp_path / "out_bin"
    rc_bad_res = main(
        [
            "build",
            "examples/random_sort_ambiguous.meme",
            "-o",
            str(out_bin),
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_path),
            "--resolve",
            "99=1",
        ]
    )
    cap1 = capsys.readouterr()
    assert rc_bad_res == 1
    assert "[Resolution Error]" in cap1.err
    assert not out_bin.exists()

    # 2. Corrupt lockfile exits 1
    bad_lock = tmp_path / "corrupt.lock"
    bad_lock.write_text("{invalid json", encoding="utf-8")
    src_file = tmp_path / "test.meme"
    src_file.write_text('print "test"\n', encoding="utf-8")
    rc_corrupt = main(
        [
            "build",
            str(src_file),
            "-o",
            str(out_bin),
            "--provider",
            "heuristic",
            "--lockfile",
            str(bad_lock),
        ]
    )
    cap2 = capsys.readouterr()
    assert rc_corrupt == 1
    assert "[Resolution Error]" in cap2.err
    assert not out_bin.exists()


def test_cli_build_exit_code_propagation_and_stdout_parity(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    src_file = tmp_path / "exit_test.meme"
    src_file.write_text(
        'print "about to exit"\nexit with code 42\nprint "unreachable"\n',
        encoding="utf-8",
    )
    lock_file = tmp_path / "exit_test.meme.lock"
    out_bin = tmp_path / "exit_test_bin"

    rc = main(
        [
            "build",
            str(src_file),
            "-o",
            str(out_bin),
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_file),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert out_bin.is_file()

    # Run native binary: assert exit code 42
    bin_run = subprocess.run([str(out_bin)], capture_output=True, text=True)
    assert bin_run.returncode == 42
    assert bin_run.stdout == "about to exit\n"

    # Compare with meme run --target python
    rc_py = main(
        [
            "run",
            str(src_file),
            "--target",
            "python",
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_file),
        ]
    )
    cap_py = capsys.readouterr()
    assert rc_py == 42
    # Stdout byte parity
    assert bin_run.stdout == cap_py.out


def test_cli_build_module_support_and_stdout_parity(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    main_meme = Path("examples/advanced/521_modules/main.meme")
    lock_path = Path("examples/advanced/521_modules/main.meme.lock")
    out_bin = tmp_path / "modules_bin"

    rc = main(
        [
            "build",
            str(main_meme),
            "-o",
            str(out_bin),
            "--lockfile",
            str(lock_path),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert out_bin.is_file()

    # Execute native binary
    bin_run = subprocess.run([str(out_bin)], capture_output=True, text=True)
    assert bin_run.returncode == 0
    assert bin_run.stdout == "25\n7\n169\n17\n"

    # Run via python backend and check byte parity
    rc_py = main(
        [
            "run",
            str(main_meme),
            "--target",
            "python",
            "--lockfile",
            str(lock_path),
        ]
    )
    cap_py = capsys.readouterr()
    assert rc_py == 0
    assert bin_run.stdout == cap_py.out


def test_cli_build_respects_quiet_prompts(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    src_file = tmp_path / "quiet.meme"
    src_file.write_text('print "quiet test"\n', encoding="utf-8")
    out_bin = tmp_path / "quiet_bin"

    monkeypatch.setenv("MEME_QUIET_PROMPTS", "1")
    rc = main(
        [
            "build",
            str(src_file),
            "-o",
            str(out_bin),
            "--provider",
            "heuristic",
            "--lockfile",
            str(tmp_path / "quiet.lock"),
        ]
    )
    cap = capsys.readouterr()
    assert rc == 0
    assert out_bin.is_file()
    assert cap.out == ""
    assert cap.err == ""


def test_cli_build_example_524_probe(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    src_path = Path("examples/524_build/build_demo.meme")
    lock_path = Path("examples/524_build/build_demo.meme.lock")
    assert src_path.is_file()
    assert lock_path.is_file()
    out_bin = tmp_path / "meme_build_probe"

    # Enforce zero-LLM contract on locked example
    def _poison(spec="auto", retriever=None):
        raise AssertionError("Zero-LLM contract violated: LLM called during locked example build!")
    monkeypatch.setattr("memelang.cli.get_provider", _poison)

    rc = main(
        [
            "build",
            str(src_path),
            "-o",
            str(out_bin),
            "--lockfile",
            str(lock_path),
        ]
    )
    cap = capsys.readouterr()
    assert rc == 0, cap.err
    assert out_bin.is_file()
    assert cap.err.strip() == str(out_bin)

    run = subprocess.run([str(out_bin)], capture_output=True, text=True)
    assert run.returncode == 0
    assert "before_exists false" in run.stdout
    assert "has_args true" in run.stdout
    assert "status=ok" in run.stdout
    assert "phase=3a" in run.stdout
    assert "after_exists true" in run.stdout
    assert "cleaned_up true" in run.stdout


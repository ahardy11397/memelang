from __future__ import annotations

from pathlib import Path
import subprocess
import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.cli import main
from memelang.codegen import TargetLang
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]

ARGV_PROGRAM = (
    "define count: Int as argument count\n"
    'print "count:", count\n'
    "if count > 1:\n"
    '    print "arg1:", argument 1\n'
    "if count > 2:\n"
    '    print "arg2:", argument 2\n'
)


@pytest.mark.parametrize("target", TARGETS)
def test_runner_argv_forwarding_cross_target_parity(target: TargetLang):
    outcome = verify_synthesis(HeuristicProvider().synthesize(ARGV_PROGRAM))
    assert outcome.program is not None

    res = execute_ir(outcome.program, target, argv=["hello", "world"])
    assert res.returncode == 0, res.stderr
    expected_stdout = "count: 3\narg1: hello\narg2: world\n"
    assert res.stdout.replace("\r\n", "\n") == expected_stdout
    assert res.stderr == ""


def test_cli_argv_forwarding_parity_with_compiled_binary(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    src_file = tmp_path / "argv_app.meme"
    src_file.write_text(ARGV_PROGRAM, encoding="utf-8")
    bin_file = tmp_path / "argv_bin"
    lock_file = tmp_path / "argv_app.meme.lock"

    # 1. Build native binary via meme build
    rc_build = main(["build", str(src_file), "-o", str(bin_file), "--lockfile", str(lock_file)])
    assert rc_build == 0
    assert bin_file.is_file()
    capsys.readouterr()

    # 2. Execute compiled binary directly with args: hello world
    proc = subprocess.run([str(bin_file), "hello", "world"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    binary_stdout = proc.stdout.replace("\r\n", "\n")
    assert binary_stdout == "count: 3\narg1: hello\narg2: world\n"

    # 3. Execute via `meme run` across targets with `-- hello world` and compare stdout
    for target in TARGETS:
        rc_run = main(
            [
                "run",
                str(src_file),
                "--target",
                target,
                "--lockfile",
                str(lock_file),
                "--",
                "hello",
                "world",
            ]
        )
        cap = capsys.readouterr()
        assert rc_run == 0, f"Target {target} failed: {cap.err}"
        assert cap.out.replace("\r\n", "\n") == binary_stdout, f"Target {target} stdout mismatch"
        assert cap.err == ""


def test_cli_argv_forwarding_empty_flags_after_double_dash(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    src_file = tmp_path / "argv_app.meme"
    src_file.write_text(ARGV_PROGRAM, encoding="utf-8")
    lock_file = tmp_path / "argv_app.meme.lock"

    # meme run without any args after --
    rc_run = main(
        [
            "run",
            str(src_file),
            "--target",
            "python",
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_file),
            "--",
        ]
    )
    cap = capsys.readouterr()
    assert rc_run == 0
    assert cap.out.replace("\r\n", "\n") == "count: 1\n"


def test_cli_argv_forwarding_rejects_non_run_command(tmp_path: Path):
    src_file = tmp_path / "argv_app.meme"
    src_file.write_text(ARGV_PROGRAM, encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["compile", str(src_file), "--target", "python", "--", "hello"])

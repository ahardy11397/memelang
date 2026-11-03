import ast
import io
from pathlib import Path
import pytest

from memelang.cli import main


def test_cli_structured_compile_and_run_all_targets(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    lock_path = tmp_path / "build.lock"
    example = Path("examples/random_sort_structured.meme")

    for target in ("python", "rust", "cpp"):
        rc = main(
            [
                "run",
                str(example),
                "--target",
                target,
                "--provider",
                "heuristic",
                "--lockfile",
                str(lock_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == 0, captured.err
        assert lock_path.exists()
        nums = ast.literal_eval(captured.out.strip())
        assert len(nums) == 10
        assert nums == sorted(nums)
        assert all(1 <= n <= 100 for n in nums)


def test_cli_ambiguous_workflow_and_lock_resolution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    lock_path = tmp_path / "build.lock"
    out_rs = tmp_path / "out.rs"
    example = Path("examples/random_sort_ambiguous.meme")

    # 1. Initial compile fails with exit code 2 and prints diagnostic
    rc1 = main(
        [
            "compile",
            str(example),
            "--target",
            "rust",
            "-o",
            str(out_rs),
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_path),
        ]
    )
    cap1 = capsys.readouterr()
    assert rc1 == 2
    assert "[Compiler Warning: Ambiguous Intent" in cap1.err
    assert "--resolve 2=1" in cap1.err
    assert not out_rs.exists()

    # 2. Resolve with `--resolve 2=1` WITHOUT calling LLM (verify by poisoning get_provider!)
    def _must_not_call_llm(spec: str = "auto"):
        raise AssertionError("LLM provider should not be called when resolving from build.lock!")

    monkeypatch.setattr("memelang.cli.get_provider", _must_not_call_llm)

    rc2 = main(
        [
            "compile",
            str(example),
            "--target",
            "rust",
            "-o",
            str(out_rs),
            "--lockfile",
            str(lock_path),
            "--resolve",
            "2=1",
        ]
    )
    cap2 = capsys.readouterr()
    assert rc2 == 0, cap2.err
    assert out_rs.exists()
    assert "fn main()" in out_rs.read_text(encoding="utf-8")

    # 3. `meme explain` outputs the locked Canonical Structured English without LLM
    rc3 = main(["explain", str(example), "--lockfile", str(lock_path)])
    cap3 = capsys.readouterr()
    assert rc3 == 0
    assert "sort array ascending" in cap3.out


def test_cli_interactive_ambiguity_resolution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    lock_path = tmp_path / "build.lock"
    example = Path("examples/random_sort_ambiguous.meme")
    monkeypatch.setattr("sys.stdin", io.StringIO("3\n"))

    rc = main(
        [
            "compile",
            str(example),
            "--target",
            "python",
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_path),
            "--interactive",
        ]
    )
    cap = capsys.readouterr()
    assert rc == 0, cap.err
    assert "_meme_rand_int(1, 10)" in cap.out


def test_cli_exit_codes_for_static_and_provider_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    bad_src = tmp_path / "bad.meme"
    bad_src.write_text("sort undeclared_list ascending\n", encoding="utf-8")
    lock_path = tmp_path / "build.lock"

    # Undeclared variable -> StaticVerificationError -> exit code 1
    rc_static = main(
        ["check", str(bad_src), "--provider", "heuristic", "--lockfile", str(lock_path)]
    )
    assert rc_static == 1
    capsys.readouterr()

    # Bad `--resolve 99=1` -> LockfileResolutionError -> exit code 1
    rc_res = main(
        [
            "compile",
            "examples/random_sort_ambiguous.meme",
            "--target",
            "python",
            "--provider",
            "heuristic",
            "--lockfile",
            str(lock_path),
            "--resolve",
            "99=1",
        ]
    )
    assert rc_res == 1
    capsys.readouterr()

    # Explicit `--provider gemini` with no API key -> LLMProviderError -> exit code 3
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    fresh_src = tmp_path / "hello.meme"
    fresh_src.write_text('print "hello"\n', encoding="utf-8")
    rc_prov = main(
        ["check", str(fresh_src), "--provider", "gemini", "--lockfile", str(lock_path)]
    )
    assert rc_prov == 3
    capsys.readouterr()


def test_cli_pull_and_interactive_io_dispatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    from memelang.ir.schema import PrintStmt, ProgramIR, ReadInputExpr, VarDeclStmt, VarRefExpr
    from memelang.runner.executor import ExecutionResult

    pulled: dict[str, str] = {}

    def _fake_pull(repo_id: str, filename: str, model_dir: Path | None = None) -> Path:
        pulled["repo_id"] = repo_id
        pulled["filename"] = filename
        dest = (model_dir or tmp_path) / filename
        dest.write_bytes(b"GGUF")
        return dest

    monkeypatch.setattr("memelang.cli.pull_gguf_model", _fake_pull, raising=False)
    rc_pull = main(["pull", "--model-dir", str(tmp_path)])
    cap_pull = capsys.readouterr()
    assert rc_pull == 0, cap_pull.err
    assert "qwen2.5-coder-3b-instruct-q4_k_m.gguf" in cap_pull.out

    # Verify `meme run` sets interactive_io=True when stdin.isatty() and program reads input
    calc_file = tmp_path / "ask.meme"
    calc_file.write_text('define name: String as read String with prompt "Name? "\nprint name\n', encoding="utf-8")
    seen_interactive: list[bool] = []

    def _spy_execute_ir(
        ir: ProgramIR,
        target: str,
        timeout_sec: float = 15.0,
        stdin_text=None,
        interactive_io: bool = False,
        source_dir: Path | None = None,
    ):
        assert source_dir == calc_file.resolve().parent
        seen_interactive.append(interactive_io)
        return ExecutionResult(stdout="Alice\n", stderr="", returncode=0, generated_code="")

    monkeypatch.setattr("memelang.cli.execute_ir", _spy_execute_ir)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    rc_run = main(["run", str(calc_file), "--provider", "heuristic", "--lockfile", str(tmp_path / "b.lock")])
    capsys.readouterr()
    assert rc_run == 0
    assert seen_interactive == [True]

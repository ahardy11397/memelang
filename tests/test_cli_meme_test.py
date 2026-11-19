from pathlib import Path
import pytest

from memelang.cli import main


def test_meme_test_runner_two_files_four_cases_one_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    # File 1: Two passing tests
    file1 = tmp_path / "01_first_test.meme"
    file1.write_text(
        "test addition:\n"
        "    define a as 10\n"
        "    define b as 20\n"
        "    assert a + b == 30\n"
        "\n"
        "test subtraction:\n"
        "    define a as 10\n"
        "    define b as 20\n"
        "    assert b - a == 10\n",
        encoding="utf-8",
    )

    # File 2: One passing test, one failing assert at line 7
    file2 = tmp_path / "02_second_test.meme"
    file2.write_text(
        "test check_starts_with:\n"
        "    define msg as \"hello\"\n"
        "    assert msg starts with \"he\"\n"
        "\n"
        "test check_bad_length:\n"
        "    define items as [1, 2, 3]\n"
        "    assert length of items == 99\n",
        encoding="utf-8",
    )

    # File 3: Zero test blocks (should count as 0 cases, pass silently)
    file3 = tmp_path / "03_helper.meme"
    file3.write_text(
        "function square(x: Int) -> Int:\n"
        "    return x * x\n",
        encoding="utf-8",
    )

    rc = main(["test", str(tmp_path)])
    cap = capsys.readouterr()

    assert rc == 1, f"Expected exit code 1 on failure, got {rc}. Output:\n{cap.out}"

    lines = [ln.strip() for ln in cap.out.strip().splitlines() if ln.strip()]
    expected_lines = [
        f"PASS {file1.as_posix()}::addition",
        f"PASS {file1.as_posix()}::subtraction",
        f"PASS {file2.as_posix()}::check_starts_with",
        f"FAIL {file2.as_posix()}::check_bad_length (line 7)",
        "Ran 4 cases, 1 failed",
    ]
    assert lines == expected_lines, f"Output lines did not match expected:\nActual:\n{cap.out}\nExpected:\n" + "\n".join(expected_lines)


def test_meme_test_runner_zero_blocks_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    file_empty = tmp_path / "helper.meme"
    file_empty.write_text(
        "function helper(x: Int) -> Int:\n"
        "    return x + 1\n",
        encoding="utf-8",
    )

    rc = main(["test", str(tmp_path)])
    cap = capsys.readouterr()

    assert rc == 0
    lines = [ln.strip() for ln in cap.out.strip().splitlines() if ln.strip()]
    assert lines == ["Ran 0 cases, 0 failed"]


def test_meme_test_runner_all_passing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    f = tmp_path / "test_success.meme"
    f.write_text(
        "test pass_one:\n"
        "    assert 1 == 1\n"
        "test pass_two:\n"
        "    assert 2 == 2\n",
        encoding="utf-8",
    )

    rc = main(["test", str(tmp_path)])
    cap = capsys.readouterr()

    assert rc == 0
    lines = [ln.strip() for ln in cap.out.strip().splitlines() if ln.strip()]
    assert lines == [
        f"PASS {f.as_posix()}::pass_one",
        f"PASS {f.as_posix()}::pass_two",
        "Ran 2 cases, 0 failed",
    ]


@pytest.mark.parametrize("target", ["c", "rust", "cpp"])
def test_meme_test_runner_target_flag(
    tmp_path: Path, target: str, capsys: pytest.CaptureFixture[str]
):
    f = tmp_path / "test_target.meme"
    f.write_text(
        "test check_val:\n"
        "    define val as 42\n"
        "    assert val == 42\n",
        encoding="utf-8",
    )

    rc = main(["test", str(tmp_path), "--target", target])
    cap = capsys.readouterr()

    assert rc == 0, f"Target {target} failed: {cap.err}\n{cap.out}"
    lines = [ln.strip() for ln in cap.out.strip().splitlines() if ln.strip()]
    assert lines == [
        f"PASS {f.as_posix()}::check_val",
        "Ran 1 cases, 0 failed",
    ]


def test_meme_test_runner_default_dir(capsys: pytest.CaptureFixture[str]):
    rc = main(["test"])
    cap = capsys.readouterr()

    assert rc == 0, f"Running default tests/meme failed: {cap.err}\n{cap.out}"
    lines = [ln.strip() for ln in cap.out.strip().splitlines() if ln.strip()]
    assert "PASS tests/meme/01_math_test.meme::addition_test" in lines
    assert "PASS tests/meme/01_math_test.meme::multiplication_test" in lines
    assert "PASS tests/meme/02_logic_test.meme::boolean_logic" in lines
    assert "PASS tests/meme/02_logic_test.meme::list_operations" in lines
    assert lines[-1] == "Ran 4 cases, 0 failed"

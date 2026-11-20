from pathlib import Path
import pytest
import subprocess
import sys

from memelang.codegen import TargetLang

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_release_gate_all_targets_fixture_subset(capsys: pytest.CaptureFixture[str]):
    # Import run_corpus module
    import importlib.util
    runner_path = REPO_ROOT / "scripts" / "run_corpus.py"
    spec = importlib.util.spec_from_file_location("run_corpus", runner_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Run release gate over small fixture subset (524_build, 531_sets, 532_2d_lists)
    rc = mod.main(["--all-targets", "--ids", "524,531,532"])
    cap = capsys.readouterr()

    assert rc == 0, f"Expected exit code 0, got {rc}. Output:\n{cap.out}\nStderr:\n{cap.err}"

    expected_targets = ["python", "rust", "cpp", "go", "c", "ts"]
    lines = cap.out.splitlines()

    verdict_lines = [ln.strip() for ln in lines if ln.strip().startswith("target=")]
    assert len(verdict_lines) == 6, f"Expected 6 verdict lines, got {len(verdict_lines)}:\n{cap.out}"

    for target in expected_targets:
        match = [ln for ln in verdict_lines if ln.startswith(f"target={target}:")]
        assert len(match) == 1, f"Missing or duplicate verdict line for target {target}: {verdict_lines}"
        line = match[0]
        assert "3 programs, 0 failed" in line, f"Verdict line for {target} not clean: {line}"


def test_release_gate_failure_propagates_exit_1(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    import importlib.util
    runner_path = REPO_ROOT / "scripts" / "run_corpus.py"
    spec = importlib.util.spec_from_file_location("run_corpus", runner_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    orig_eval = mod.evaluate_script

    def fake_eval(*args, **kwargs):
        res = orig_eval(*args, **kwargs)
        if kwargs.get("target") == "python":
            return mod.ScriptEvalResult(
                id=res.id,
                slug=res.slug,
                course=res.course,
                style=res.style,
                bucket="OUTPUT_MISMATCH",
                detail="Synthetic failure for exit code test",
                examples_gaps=[],
                language_gaps=[],
            )
        return res

    monkeypatch.setattr(mod, "evaluate_script", fake_eval)
    rc = mod.main(["--all-targets", "--ids", "524"])
    cap = capsys.readouterr()
    assert rc == 1, f"Expected exit code 1 on failure, got {rc}"
    assert "target=python: 1 programs, 1 failed" in cap.out


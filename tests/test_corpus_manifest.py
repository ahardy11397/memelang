import importlib.util
from pathlib import Path
import pytest

from memelang.ir.schema import (
    AmbiguityCandidate,
    AmbiguityDiagnostic,
    FuncDefStmt,
    FuncParam,
    LiteralExpr,
    PrintStmt,
    ReadInputExpr,
    ReadJsonListExpr,
    ReturnStmt,
    SortCollectionStmt,
    SynthesisResult,
    VarDeclStmt,
    VarRefExpr,
)
from memelang.llm.base import LLMProviderError
from memelang.lockfile.manager import LockfileManager

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_runner_module():
    runner_path = REPO_ROOT / "scripts" / "run_corpus.py"
    spec = importlib.util.spec_from_file_location("run_corpus", runner_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_shared_fixtures_exist_and_valid():
    fix_dir = REPO_ROOT / "tests" / "corpus" / "fixtures"
    expected = {
        "numbers.json",
        "scores.json",
        "sorted_nums.json",
        "negatives.json",
        "weights.json",
        "values.json",
        "matrix_flat.json",
        "graph_adj.json",
        "words.json",
        "notes.txt",
    }
    assert expected.issubset({p.name for p in fix_dir.iterdir()})


def test_parse_id_filter_valid_and_invalid():
    rc = _load_runner_module()
    assert rc.parse_id_filter("1-3,7,10-11") == {1, 2, 3, 7, 10, 11}
    for bad in ("10-5", "0", "301", "abc", ""):
        with pytest.raises(ValueError):
            rc.parse_id_filter(bad)


def test_evaluate_script_buckets_prompt_stripping_source_dir_and_lockfile_isolation(tmp_path):
    rc = _load_runner_module()
    sub = tmp_path / "tests" / "corpus" / "cs102"
    fix = tmp_path / "tests" / "corpus" / "fixtures"
    sub.mkdir(parents=True)
    fix.mkdir(parents=True)
    (fix / "numbers.json").write_text("[10, 50, 3]\n", encoding="utf-8")

    s_path = sub / "sample.meme"
    s_path.write_text('print "x"\n', encoding="utf-8")

    def _make_spec(expected_status="ok", expected_out="1", stdin="0\n", ex_gaps=None, lang_gaps=None):
        return rc.CorpusScriptSpec(
            id=1,
            slug="001_sample",
            path=str(s_path.relative_to(tmp_path).as_posix()),
            course="cs102",
            topic="test",
            title="Sample",
            style="clean" if expected_status == "ok" else "ambiguous",
            stdin=stdin,
            expected_status=expected_status,
            expected_stdout_contains=expected_out,
            feature_tags=["print"],
            extensibility_gaps=rc.ExtensibilityGaps(
                examples=ex_gaps or [], language=lang_gaps or []
            ),
        )

    class StubProvider:
        name = "stub"
        def __init__(self, fn):
            self._fn = fn
        def synthesize(self, text: str) -> SynthesisResult:
            return self._fn(text)

    lock_mgr = LockfileManager(tmp_path / "isolated.lock")

    # 1. Prompt echo ("Item 1? ") must NOT falsely satisfy expected_stdout_contains="1" when answer is 0
    prompt_prog = SynthesisResult(
        items=[
            VarDeclStmt(
                name="v",
                var_type="Int",
                value=ReadInputExpr(prompt="Item 1? ", target_type="Int"),
            ),
            PrintStmt(expressions=[VarRefExpr(name="v")]),
        ]
    )
    res_mismatch = rc.evaluate_script(
        _make_spec(expected_out="1", stdin="0\n", ex_gaps=["idiom_a"]),
        StubProvider(lambda _: prompt_prog),
        "python",
        lock_mgr,
        repo_root=tmp_path,
    )
    assert res_mismatch.bucket == "OUTPUT_MISMATCH"

    # 2. Relative fixture `../fixtures/numbers.json` resolves via script parent `source_dir`
    json_prog = SynthesisResult(
        items=[
            VarDeclStmt(
                name="fp",
                var_type="String",
                value=ReadInputExpr(prompt="Path? ", target_type="String"),
            ),
            VarDeclStmt(
                name="nums",
                var_type="List<Float>",
                value=ReadJsonListExpr(filepath=VarRefExpr(name="fp")),
            ),
            SortCollectionStmt(target="nums", direction="ascending"),
            PrintStmt(expressions=[VarRefExpr(name="nums")]),
        ]
    )
    res_pass = rc.evaluate_script(
        _make_spec(expected_out="[3, 10, 50]", stdin="../fixtures/numbers.json\n"),
        StubProvider(lambda _: json_prog),
        "python",
        LockfileManager(tmp_path / "isolated2.lock"),
        repo_root=tmp_path,
    )
    assert res_pass.bucket == "PASS"

    # 3. Synthesis error, static verify gap, expected/unexpected/missed ambiguity, & 2-axis summary
    res_syn = rc.evaluate_script(
        _make_spec(ex_gaps=["swap_phrase"], lang_gaps=["list_set_index"]),
        StubProvider(lambda _: (_ for _ in ()).throw(LLMProviderError("bad json"))),
        "python",
        LockfileManager(tmp_path / "isolated3.lock"),
        repo_root=tmp_path,
    )
    assert res_syn.bucket == "SYNTHESIS_ERROR"

    res_static = rc.evaluate_script(
        _make_spec(lang_gaps=["list_set_index"]),
        StubProvider(lambda _: SynthesisResult(items=[PrintStmt(expressions=[VarRefExpr(name="undecl")])])),
        "python",
        LockfileManager(tmp_path / "isolated4.lock"),
        repo_root=tmp_path,
    )
    assert res_static.bucket == "STATIC_VERIFY_GAP"

    amb_diag = AmbiguityDiagnostic(
        statement_id=1,
        source_line=1,
        source_text="amb",
        reason="amb",
        candidates=[
            AmbiguityCandidate(
                option=1,
                description="d",
                canonical_meme='print "x"',
                replacement_ir=[PrintStmt(expressions=[LiteralExpr(value="x", data_type="String")])],
            )
        ],
    )
    res_amb_ok = rc.evaluate_script(
        _make_spec(expected_status="ambiguous", expected_out=""),
        StubProvider(lambda _: SynthesisResult(items=[amb_diag])),
        "python",
        LockfileManager(tmp_path / "isolated5.lock"),
        repo_root=tmp_path,
    )
    assert res_amb_ok.bucket == "AMBIGUOUS_EXPECTED"

    res_missed = rc.evaluate_script(
        _make_spec(expected_status="ambiguous", expected_out=""),
        StubProvider(lambda _: SynthesisResult(items=[PrintStmt(expressions=[LiteralExpr(value="x", data_type="String")])])),
        "python",
        LockfileManager(tmp_path / "isolated6.lock"),
        repo_root=tmp_path,
    )
    assert res_missed.bucket == "MISSED_AMBIGUITY"

    summary = rc.summarize_results([res_mismatch, res_pass, res_syn, res_static, res_amb_ok, res_missed])
    assert summary.by_bucket["PASS"] == 1
    assert summary.by_bucket["AMBIGUOUS_EXPECTED"] == 1
    assert dict(summary.top_language_gaps)["list_set_index"] == 2
    assert dict(summary.top_examples_gaps)["swap_phrase"] == 1
    assert not (tmp_path / "build.lock").exists()


def test_cs101_slice_integrity():
    import re
    rc = _load_runner_module()
    manifest_path = REPO_ROOT / "tests" / "corpus" / "manifest.json"
    manifest = rc.CorpusManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    cs101 = [s for s in manifest.scripts if s.course == "cs101"]
    assert [s.id for s in cs101] == list(range(1, 101))
    assert sum(1 for s in cs101 if s.style == "clean") == 80
    assert sum(1 for s in cs101 if s.style == "typo") == 10
    assert sum(1 for s in cs101 if s.style == "ambiguous") == 10

    assert len({s.slug for s in cs101}) == 100
    assert len({s.title.lower() for s in cs101}) == 100

    skeletons = set()
    for s in cs101:
        p = REPO_ROOT / s.path
        assert p.is_file() and p.parent.name == "cs101"
        raw = p.read_text(encoding="utf-8").strip()
        assert raw != ""
        if s.style == "ambiguous":
            assert s.expected_status == "ambiguous" and s.expected_stdout_contains == ""
        else:
            assert s.expected_status == "ok" and s.expected_stdout_contains != ""
        skel = re.sub(r"\d+", "#", re.sub(r"\s+", " ", raw.lower()))
        skeletons.add(skel)
    assert len(skeletons) == 100


def test_cs102_slice_integrity():
    import re
    rc = _load_runner_module()
    manifest_path = REPO_ROOT / "tests" / "corpus" / "manifest.json"
    manifest = rc.CorpusManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    cs102 = [s for s in manifest.scripts if s.course == "cs102"]
    assert [s.id for s in cs102] == list(range(101, 201))
    assert sum(1 for s in cs102 if s.style == "clean") == 80
    assert sum(1 for s in cs102 if s.style == "typo") == 10
    assert sum(1 for s in cs102 if s.style == "ambiguous") == 10

    assert len({s.slug for s in cs102}) == 100
    assert len({s.title.lower() for s in cs102}) == 100

    skeletons = set()
    for s in cs102:
        p = REPO_ROOT / s.path
        assert p.is_file() and p.parent.name == "cs102"
        raw = p.read_text(encoding="utf-8").strip()
        assert raw != ""
        if s.style == "ambiguous":
            assert s.expected_status == "ambiguous" and s.expected_stdout_contains == ""
        else:
            assert s.expected_status == "ok" and s.expected_stdout_contains != ""
        skel = re.sub(r"\d+", "#", re.sub(r"\s+", " ", raw.lower()))
        skeletons.add(skel)
    assert len(skeletons) == 100


def test_cs103_slice_integrity():
    import re
    rc = _load_runner_module()
    manifest_path = REPO_ROOT / "tests" / "corpus" / "manifest.json"
    manifest = rc.CorpusManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    cs103 = [s for s in manifest.scripts if s.course == "cs103"]
    assert [s.id for s in cs103] == list(range(201, 301))
    assert sum(1 for s in cs103 if s.style == "clean") == 80
    assert sum(1 for s in cs103 if s.style == "typo") == 10
    assert sum(1 for s in cs103 if s.style == "ambiguous") == 10

    assert len({s.slug for s in cs103}) == 100
    assert len({s.title.lower() for s in cs103}) == 100

    skeletons = set()
    for s in cs103:
        p = REPO_ROOT / s.path
        assert p.is_file() and p.parent.name == "cs103"
        raw = p.read_text(encoding="utf-8").strip()
        assert raw != ""
        if s.style == "ambiguous":
            assert s.expected_status == "ambiguous" and s.expected_stdout_contains == ""
        else:
            assert s.expected_status == "ok" and s.expected_stdout_contains != ""
        skel = re.sub(r"\d+", "#", re.sub(r"\s+", " ", raw.lower()))
        skeletons.add(skel)
    assert len(skeletons) == 100




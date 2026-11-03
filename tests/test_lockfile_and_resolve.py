from pathlib import Path
import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.ir.schema import (
    ForEachStmt,
    LiteralExpr,
    PrintStmt,
    RandomListExpr,
    SortCollectionStmt,
    SynthesisResult,
    VarDeclStmt,
    VarRefExpr,
)
from memelang.lockfile.manager import (
    LockEntry,
    LockfileManager,
    LockfileResolutionError,
)


def _sample_unambiguous_synthesis() -> SynthesisResult:
    return SynthesisResult(
        items=[
            VarDeclStmt(
                name="numbers",
                var_type="List<Int>",
                value=RandomListExpr(
                    count=LiteralExpr(value=10, data_type="Int"),
                    min_val=LiteralExpr(value=1, data_type="Int"),
                    max_val=LiteralExpr(value=100, data_type="Int"),
                    implicit_bounds=False,
                ),
            ),
            SortCollectionStmt(target="numbers", direction="ascending"),
            PrintStmt(expressions=[VarRefExpr(name="numbers")]),
        ]
    )


def _sample_ambiguous_synthesis() -> SynthesisResult:
    return SynthesisResult(
        items=[
            VarDeclStmt(
                name="array",
                var_type="List<Int>",
                value=RandomListExpr(
                    count=LiteralExpr(value=10, data_type="Int"),
                    min_val=LiteralExpr(value=1, data_type="Int"),
                    max_val=LiteralExpr(value=100, data_type="Int"),
                    implicit_bounds=True,
                ),
            ),
            ForEachStmt(
                item_var="number",
                collection="array",
                body=[SortCollectionStmt(target="array", direction="ascending")],
            ),
        ]
    )


def test_cache_hit_returns_locked_program_until_source_changes(tmp_path: Path):
    lock_path = tmp_path / "build.lock"
    mgr = LockfileManager(lock_path)
    src = "define list numbers as 10 random integers between 1 and 100\nsort numbers ascending\nprint numbers\n"

    assert mgr.get_cached_program("main.meme", src) is None

    syn = _sample_unambiguous_synthesis()
    outcome = verify_synthesis(syn)
    recorded = mgr.record_outcome("main.meme", src, "heuristic", syn, outcome)
    assert recorded.is_unambiguous is True
    assert lock_path.exists()

    # Exact cache hit (including CRLF normalization)
    cached = mgr.get_cached_program("main.meme", src.replace("\n", "\r\n"))
    assert cached == outcome.program

    # Modified source invalidates cache
    assert mgr.get_cached_program("main.meme", src + "print numbers\n") is None


def test_pending_ambiguity_resolved_without_llm(tmp_path: Path):
    lock_path = tmp_path / "build.lock"
    mgr = LockfileManager(lock_path)
    src = "array = 10.random numbers\nfor each number in array\n    sort from 1 to 10\n"

    syn = _sample_ambiguous_synthesis()
    outcome = verify_synthesis(syn)
    assert outcome.is_unambiguous is False

    mgr.record_outcome("main.meme", src, "heuristic", syn, outcome)
    assert mgr.get_cached_program("main.meme", src) is None

    # Resolve statement 2 -> option 1 without calling any LLM
    resolved_1 = mgr.apply_resolutions("main.meme", src, {2: 1})
    assert resolved_1.is_unambiguous is True
    assert resolved_1.program is not None

    entry: LockEntry | None = mgr.get_entry("main.meme")
    assert entry is not None
    assert entry.resolutions == {"2": 1}
    assert entry.pending_ambiguities == []
    assert entry.canonical_meme is not None
    assert "sort array ascending" in entry.canonical_meme

    # Subsequent compile with no flags hits the locked resolution!
    assert mgr.get_cached_program("main.meme", src) == resolved_1.program

    # Switching to option 3 (replaces_whole_program=True) re-resolves from draft_items
    resolved_3 = mgr.apply_resolutions("main.meme", src, {2: 3})
    assert resolved_3.is_unambiguous is True
    entry3 = mgr.get_entry("main.meme")
    assert entry3 is not None
    assert entry3.resolutions == {"2": 3}
    assert "between 1 and 10" in (entry3.canonical_meme or "")


def test_invalid_resolution_id_or_option_raises(tmp_path: Path):
    lock_path = tmp_path / "build.lock"
    mgr = LockfileManager(lock_path)
    src = "array = 10.random numbers\nfor each number in array\n    sort from 1 to 10\n"

    syn = _sample_ambiguous_synthesis()
    outcome = verify_synthesis(syn)
    mgr.record_outcome("main.meme", src, "heuristic", syn, outcome)

    with pytest.raises(LockfileResolutionError) as exc_bad_id:
        mgr.apply_resolutions("main.meme", src, {99: 1})
    assert "2" in str(exc_bad_id.value)

    with pytest.raises(LockfileResolutionError) as exc_bad_opt:
        mgr.apply_resolutions("main.meme", src, {2: 9})
    assert "1, 2, 3" in str(exc_bad_opt.value)

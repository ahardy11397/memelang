from pathlib import Path

from memelang.llm.retriever import ExampleRetriever, bm25_tokenize


def test_bm25_tokenize_extracts_clean_tokens():
    tokens = bm25_tokenize("define list as [1, 2] # comment\nsort list ascending")
    assert "define" in tokens
    assert "sort" in tokens
    assert "ascending" in tokens
    assert "comment" not in tokens


def test_retriever_discovers_locked_examples(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    meme_file = ex_dir / "demo.meme"
    meme_file.write_text("print 42\n")
    lock_file = ex_dir / "demo.meme.lock"
    lock_file.write_text(
        '{"ir": {"items": [{"op": "print_stmt", "expressions": [{"expr_type": "literal", "value": 42, "data_type": "Int"}]}]}}'
    )

    retriever = ExampleRetriever(examples_dir=ex_dir)
    count = retriever.index_corpus()
    assert count == 1

    results = retriever.retrieve("print something", top_k=2)
    assert len(results) == 1
    assert results[0].slug == "demo"
    assert "print_stmt" in str(results[0].locked_ir)


def test_retriever_excludes_self(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    meme_file = ex_dir / "demo.meme"
    meme_file.write_text("print 42\n")
    lock_file = ex_dir / "demo.meme.lock"
    lock_file.write_text('{"ir": {"items": []}}')

    retriever = ExampleRetriever(examples_dir=ex_dir)
    retriever.index_corpus()
    results = retriever.retrieve("print 42", top_k=2, exclude_path=meme_file)
    assert len(results) == 0


def test_retriever_ignores_unlocked_examples(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    # Unlocked example (.meme only)
    (ex_dir / "unlocked.meme").write_text("print 99\n")
    # Locked example (.meme + .meme.lock)
    (ex_dir / "locked.meme").write_text("print 100\n")
    (ex_dir / "locked.meme.lock").write_text('{"ir": {"items": []}}')

    retriever = ExampleRetriever(examples_dir=ex_dir)
    count = retriever.index_corpus()
    assert count == 1
    results = retriever.retrieve("print", top_k=5)
    assert len(results) == 1
    assert results[0].slug == "locked"


def test_retriever_ranks_by_relevance(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    # Example 1: sorting list
    (ex_dir / "sort_demo.meme").write_text("sort list ascending\n")
    (ex_dir / "sort_demo.meme.lock").write_text('{"ir": {"items": [{"op": "sort"}]}}')

    # Example 2: matrix transpose
    (ex_dir / "matrix_demo.meme").write_text("matrix transpose 2d array\n")
    (ex_dir / "matrix_demo.meme.lock").write_text('{"ir": {"items": [{"op": "transpose"}]}}')

    retriever = ExampleRetriever(examples_dir=ex_dir)
    assert retriever.index_corpus() == 2

    results = retriever.retrieve("sort numbers ascending", top_k=2)
    assert len(results) >= 1
    assert results[0].slug == "sort_demo"
    assert results[0].score > 0.0


def test_retriever_recursive_discovery(tmp_path: Path):
    sub_dir = tmp_path / "examples" / "cs101"
    sub_dir.mkdir(parents=True)
    (sub_dir / "001_hello.meme").write_text("print 'hello world'\n")
    (sub_dir / "001_hello.meme.lock").write_text('{"ir": {"items": []}}')

    retriever = ExampleRetriever(examples_dir=tmp_path / "examples")
    count = retriever.index_corpus()
    assert count == 1
    results = retriever.retrieve("hello world", top_k=1)
    assert len(results) == 1
    assert results[0].slug == "001_hello"

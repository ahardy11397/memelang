from pathlib import Path

from memelang.llm.base import build_compiler_messages
from memelang.llm.retriever import ExampleRetriever


def test_build_compiler_messages_with_retriever(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    (ex_dir / "binary_search.meme").write_text("define function binarySearch with list and target\n")
    (ex_dir / "binary_search.meme.lock").write_text(
        '{"ir": {"items": [{"op": "func_def", "name": "binarySearch", "params": [], "return_type": "Int", "body": []}]}}'
    )

    retriever = ExampleRetriever(examples_dir=ex_dir)
    retriever.index_corpus()

    messages = build_compiler_messages("binarySearch in array for key", retriever=retriever, top_k=1)
    prompt_content = messages[0]["content"]
    assert "binarySearch" in prompt_content
    assert "Relevant Syntactic Example: binary_search" in prompt_content
    assert "Example 1 (Structured):" not in prompt_content


def test_build_compiler_messages_fallback_when_no_match(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    retriever = ExampleRetriever(examples_dir=ex_dir)
    retriever.index_corpus()

    messages = build_compiler_messages("some completely novel query", retriever=retriever)
    prompt_content = messages[0]["content"]
    assert "Example 1 (Structured):" in prompt_content


def test_build_compiler_messages_without_retriever():
    messages = build_compiler_messages("define list numbers as 10 random integers")
    prompt_content = messages[0]["content"]
    assert "Example 1 (Structured):" in prompt_content


def test_build_compiler_messages_excludes_source_path(tmp_path: Path):
    ex_dir = tmp_path / "examples"
    ex_dir.mkdir()
    meme_file = ex_dir / "binary_search.meme"
    meme_file.write_text("define function binarySearch with list and target\n")
    (ex_dir / "binary_search.meme.lock").write_text(
        '{"ir": {"items": [{"op": "func_def", "name": "binarySearch", "params": [], "return_type": "Int", "body": []}]}}'
    )

    retriever = ExampleRetriever(examples_dir=ex_dir)
    retriever.index_corpus()

    messages = build_compiler_messages(
        "binarySearch in array for key",
        source_path=meme_file,
        retriever=retriever,
        top_k=1,
    )
    prompt_content = messages[0]["content"]
    assert "Relevant Syntactic Example: binary_search" not in prompt_content
    assert "Example 1 (Structured):" in prompt_content

import re
from pathlib import Path
import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.llm.heuristic import HeuristicProvider

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_writing_guide_beta_feature_snippets_heuristic_parse():
    guide_path = REPO_ROOT / "docs" / "WRITING_GUIDE.md"
    content = guide_path.read_text(encoding="utf-8")

    # Extract sections 11e through 11l
    # Each section contains a ```meme ... ``` code block
    pattern = r"## (11[e-l]\.[^\n]+)\n+.*?```meme\n(.*?)\n```"
    matches = re.findall(pattern, content, flags=re.DOTALL)
    assert len(matches) == 8, f"Expected 8 beta feature sections (11e-11l), found {len(matches)}: {[m[0] for m in matches]}"

    provider = HeuristicProvider()
    for section_title, snippet in matches:
        res = provider.synthesize(snippet)
        outcome = verify_synthesis(res)
        assert outcome.program is not None, f"Snippet in {section_title} failed verification"


def test_tutorial_snippets_heuristic_parse(tmp_path: Path):
    tutorial_path = REPO_ROOT / "docs" / "TUTORIAL.md"
    content = tutorial_path.read_text(encoding="utf-8")

    # Check simple_math module snippet
    m_math = re.search(r"```meme\n(# simple_math\.meme.*?)\n```", content, flags=re.DOTALL)
    assert m_math is not None
    math_src = m_math.group(1)
    math_file = tmp_path / "simple_math.meme"
    math_file.write_text(math_src, encoding="utf-8")

    provider = HeuristicProvider()
    res_math = provider.synthesize(math_src, source_path=str(math_file))
    outcome_math = verify_synthesis(res_math, source_path=math_file)
    assert outcome_math.program is not None

    # Check tutorial.meme main app snippet
    m_app = re.search(r"```meme\n(# tutorial\.meme.*?)\n```", content, flags=re.DOTALL)
    assert m_app is not None
    app_src = m_app.group(1)
    app_file = tmp_path / "tutorial.meme"
    app_file.write_text(app_src, encoding="utf-8")
    res_app = provider.synthesize(app_src, source_path=str(app_file))
    outcome_app = verify_synthesis(res_app, source_path=app_file)
    assert outcome_app.program is not None

    # Check simple_math_test.meme test snippet
    m_test = re.search(r"```meme\n(# simple_math_test\.meme.*?)\n```", content, flags=re.DOTALL)
    assert m_test is not None
    test_src = m_test.group(1)
    test_file = tmp_path / "simple_math_test.meme"
    test_file.write_text(test_src, encoding="utf-8")
    res_test = provider.synthesize(test_src, source_path=str(test_file))
    outcome_test = verify_synthesis(res_test, source_path=test_file)
    assert outcome_test.program is not None

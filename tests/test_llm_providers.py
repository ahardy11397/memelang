import json
import httpx
import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.ir.schema import AmbiguityDiagnostic, PrintStmt, LiteralExpr, SynthesisResult
from memelang.llm import (
    HeuristicProvider,
    LLMProviderError,
    OllamaProvider,
    OpenAILocalProvider,
    get_provider,
)


def test_empty_and_comment_only_source():
    prov = HeuristicProvider()
    assert prov.synthesize("") == SynthesisResult(items=[])
    assert prov.synthesize("# just a comment\n   \n# second comment\n") == SynthesisResult(items=[])


def test_heuristic_structured_and_control_flow():
    prov = HeuristicProvider()
    structured = (
        "define list numbers as 10 random integers between 1 and 100\n"
        "sort numbers ascending\n"
        "print numbers\n"
    )
    res1 = prov.synthesize(structured)
    out1 = verify_synthesis(res1)
    assert out1.is_unambiguous is True
    assert out1.program is not None
    assert len(out1.program.statements) == 3

    fizzbuzz = (
        "function is_divisible(n: Int, d: Int) -> Bool:\n"
        "    return n % d == 0\n"
        "\n"
        "for i from 1 to 15:\n"
        "    if is_divisible(i, 15):\n"
        '        print "FizzBuzz"\n'
        "    else:\n"
        "        if is_divisible(i, 3):\n"
        '            print "Fizz"\n'
        "        else:\n"
        "            print i\n"
    )
    res2 = prov.synthesize(fizzbuzz)
    out2 = verify_synthesis(res2)
    assert out2.is_unambiguous is True


def test_heuristic_ambiguous_prompt_example():
    prov = HeuristicProvider()
    ambiguous_src = (
        "array = 10.random numbers\n"
        "\n"
        "for each number in array\n"
        "    sort from 1 to 10\n"
    )
    res = prov.synthesize(ambiguous_src)
    out = verify_synthesis(res)
    assert out.is_unambiguous is False
    assert len(out.ambiguities) == 1
    diag: AmbiguityDiagnostic = out.ambiguities[0]
    assert diag.statement_id == 2
    assert len(diag.candidates) == 3
    assert diag.candidates[2].replaces_whole_program is True


def test_ollama_provider_sends_schema_and_parses_response():
    expected_result = SynthesisResult(
        items=[PrintStmt(expressions=[LiteralExpr(value="hello", data_type="String")])]
    )
    captured_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": expected_result.model_dump_json()}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    prov = OllamaProvider(model="qwen2.5-coder:3b", host="http://127.0.0.1:11434", client=client)
    parsed = prov.synthesize('print "hello"')
    assert parsed == expected_result
    assert captured_payload["options"]["temperature"] == 0.0
    assert captured_payload["options"]["seed"] == 42
    assert "properties" in captured_payload["format"]

    # Unreachable server raises LLMProviderError
    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    bad_prov = OllamaProvider(client=httpx.Client(transport=httpx.MockTransport(fail_handler)))
    with pytest.raises(LLMProviderError):
        bad_prov.synthesize('print "hello"')

    # OpenAILocalProvider contract check
    def oai_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content.decode("utf-8"))
        assert body["temperature"] == 0.0
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": expected_result.model_dump_json()}}]},
        )

    oai_prov = OpenAILocalProvider(
        model="local-3b",
        base_url="http://127.0.0.1:8080/v1",
        client=httpx.Client(transport=httpx.MockTransport(oai_handler)),
    )
    assert oai_prov.synthesize('print "hello"') == expected_result


def test_heuristic_option3_preserves_trailing_statements(tmp_path):
    from memelang.lockfile.manager import LockfileManager

    src = (
        "array = 10.random numbers\n"
        "for each number in array\n"
        "    sort from 1 to 10\n"
        "print array\n"
    )
    prov = HeuristicProvider()
    syn = prov.synthesize(src)
    out = verify_synthesis(syn)
    assert not out.is_unambiguous

    mgr = LockfileManager(tmp_path / "build.lock")
    resolved = mgr.record_outcome("main.meme", src, prov.name, syn, out, requested_resolutions={2: 3})
    assert resolved.is_unambiguous is True
    assert resolved.program is not None
    assert isinstance(resolved.program.statements[-1], PrintStmt)


def test_heuristic_single_quotes_elif_and_expr_type_inference():
    src = (
        "function is_even(n: Int) -> Bool:\n"
        "    return n % 2 == 0\n"
        "\n"
        'words = ["alpha", "beta"]\n'
        "first = words[0]\n"
        "flag = is_even(4)\n"
        "nums = [1, 2, 3, 4]\n"
        "filter nums where is_even(x)\n"
        "if flag:\n"
        "    print 'say \"hi\"', first\n"
        "else if not flag:\n"
        '    print "nope"\n'
        "else:\n"
        '    print "fallback"\n'
    )
    prov = HeuristicProvider()
    syn = prov.synthesize(src)
    out = verify_synthesis(syn)
    assert out.is_unambiguous is True
    assert out.program is not None


def test_missing_gemini_key_or_gguf_raises_provider_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(LLMProviderError):
        prov = get_provider("gemini")
        prov.synthesize('print "hello"')

    with pytest.raises(LLMProviderError):
        gguf_prov = get_provider("llama-cpp:/nonexistent/model.gguf")
        gguf_prov.synthesize('print "hello"')

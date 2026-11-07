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


def test_heuristic_records_and_maps():
    prov = HeuristicProvider()
    src = (
        "record User:\n"
        "    id: Int\n"
        "    name: String\n"
        "\n"
        'define u as User(id=1, name="Alice")\n'
        'set u.name to "Bob"\n'
        'define scores as {"Alice": 100, "Bob": 90}\n'
        'set scores["Bob"] to 95\n'
        'print u.name, scores["Bob"], scores has key "Alice"\n'
    )
    res = prov.synthesize(src)
    out = verify_synthesis(res)
    assert out.is_unambiguous is True
    assert out.program is not None
    assert len(out.program.statements) == 6


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


def test_auto_and_bare_llama_cpp_discover_cached_gguf(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from memelang.llm.llama_cpp import LlamaCppProvider

    monkeypatch.delenv("MEME_PROVIDER", raising=False)
    monkeypatch.setenv("MEME_MODEL_DIR", str(tmp_path))

    # When empty and no Ollama running, bare `llama-cpp` errors clearly
    with pytest.raises(LLMProviderError) as exc_empty:
        get_provider("llama-cpp")
    assert "meme pull" in str(exc_empty.value)

    # Create a fake cached GGUF file and verify both `auto` and `llama-cpp` pick it up
    fake_gguf = tmp_path / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
    fake_gguf.write_bytes(b"GGUF")

    p_auto = get_provider("auto")
    assert isinstance(p_auto, LlamaCppProvider)
    assert p_auto.model_path == fake_gguf

    p_bare = get_provider("llama-cpp")
    assert isinstance(p_bare, LlamaCppProvider)
    assert p_bare.model_path == fake_gguf


def test_memelang_gbnf_grammar_allows_multiline_and_passes_to_llama_cpp(tmp_path):
    from memelang.llm.llama_cpp import LlamaCppProvider, MEMELANG_GBNF, build_llama_grammar

    assert "[ \\t\\n\\r]*" in MEMELANG_GBNF
    grammar = build_llama_grammar()
    assert grammar is not None

    fake_gguf = tmp_path / "model.gguf"
    fake_gguf.write_bytes(b"GGUF")
    prov = LlamaCppProvider(fake_gguf)

    captured_kwargs: dict = {}

    class FakeLlama:
        def create_chat_completion(self, **kwargs):
            captured_kwargs.update(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{\n  "items": [\n    {\n      "op": "print_stmt",\n      "expressions": [\n        {"expr_type": "literal", "value": "ok", "data_type": "String"}\n      ]\n    }\n  ]\n}'
                        }
                    }
                ]
            }

    prov._llm = FakeLlama()
    res = prov.synthesize('print "ok"')
    assert len(res.items) == 1
    assert "grammar" in captured_kwargs
    assert captured_kwargs["grammar"] is not None
    assert "response_format" not in captured_kwargs


def test_gbnf_and_system_prompt_include_file_json_insert_and_fail():
    from memelang.llm.base import SYSTEM_PROMPT
    from memelang.llm.llama_cpp import MEMELANG_FUNC_GBNF, MEMELANG_GBNF, build_llama_grammar

    for token in (
        "str_ends_with",
        "read_json_list",
        "list_insert",
        "list_set_index",
        "string_length",
        "string_slice",
        "fail_stmt",
        "List<List<Int>>",
        "List<List<Float>>",
        "List<List<Bool>>",
        "List<List<String>>",
    ):
        assert token in MEMELANG_GBNF, f"Missing {token} in MEMELANG_GBNF"
        assert token in SYSTEM_PROMPT, f"Missing {token} in SYSTEM_PROMPT"
    assert "\nint-expr ::=" in MEMELANG_GBNF
    assert "\nbool-expr ::=" in MEMELANG_GBNF
    assert "typed-func-body" not in MEMELANG_FUNC_GBNF
    assert '"op": "list_insert"' in SYSTEM_PROMPT
    assert '"op": "for_range"' in SYSTEM_PROMPT
    assert build_llama_grammar(func_only=False) is not None
    assert build_llama_grammar(func_only=True) is not None


def test_split_compilation_units_and_per_function_llama_cpp_synthesis(tmp_path):
    from pathlib import Path
    from memelang.llm.base import split_compilation_units
    from memelang.llm.llama_cpp import LlamaCppProvider

    fl_text = Path("examples/find-largest.meme").read_text(encoding="utf-8")
    units = split_compilation_units(fl_text)
    assert len(units) == 3
    assert units[0].is_func is True and "loadFile" in units[0].text
    assert units[1].is_func is True and "findLargest" in units[1].text
    assert units[2].is_func is False and "Filepath?" in units[2].text

    stop_when_src = (
        "class demo\n"
        "  define function fn with arr\n"
        "    define out as arr\n"
        "    stop when out item 1 is smaller than every other item\n"
        "    return out item last\n"
    )
    sw_units = split_compilation_units(stop_when_src)
    assert len(sw_units) == 1
    assert "stop when " not in sw_units[0].text
    assert sw_units[0].line_numbers[-1] == 5

    fake_gguf = tmp_path / "model.gguf"
    fake_gguf.write_bytes(b"GGUF")
    prov = LlamaCppProvider(fake_gguf)

    prompts_seen: list[str] = []
    canned = [
        '{"items": [{"op": "func_def", "name": "loadFile", "params": [{"name": "filepath", "param_type": "String"}], "return_type": "List<Float>", "body": [{"op": "fail_stmt", "message": {"expr_type": "literal", "value": "Wrong File Type", "data_type": "String"}}]}]}',
        '{"items": [{"op": "func_def", "name": "findLargest", "params": [{"name": "list", "param_type": "List<Float>"}], "return_type": "Float", "body": [{"op": "return_stmt", "value": {"expr_type": "literal", "value": 0.0, "data_type": "Float"}}]}]}',
        '{"items": [{"op": "print_stmt", "expressions": [{"expr_type": "literal", "value": 1.0, "data_type": "Float"}]}]}',
    ]

    class MultiUnitFakeLlama:
        def create_chat_completion(self, **kwargs):
            idx = len(prompts_seen)
            prompts_seen.append(kwargs["messages"][-1]["content"])
            return {"choices": [{"message": {"content": canned[idx]}}]}

    prov._llm = MultiUnitFakeLlama()
    merged = prov.synthesize(fl_text)
    assert len(prompts_seen) == 3
    assert "loadFile(filepath: String) -> List<Float>" in prompts_seen[2]
    assert "findLargest(list: List<Float>) -> Float" in prompts_seen[2]
    assert len(merged.items) == 3




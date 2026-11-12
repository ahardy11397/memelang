from memelang.ir.schema import (
    AmbiguityCandidate,
    AmbiguityDiagnostic,
    AssignStmt,
    BinaryOpExpr,
    CallExpr,
    ClampCollectionStmt,
    FilterCollectionStmt,
    ForEachStmt,
    ForRangeStmt,
    FuncDefStmt,
    FuncParam,
    IfStmt,
    ListAppendStmt,
    ListIndexExpr,
    ListLengthExpr,
    ListLiteralExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadInputExpr,
    ReturnStmt,
    SortCollectionStmt,
    SynthesisResult,
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
)
from memelang.ir.canonical import to_canonical_meme


def test_program_ir_roundtrip_and_canonical():
    prog = ProgramIR(
        statements=[
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
    dumped = prog.model_dump_json()
    restored = ProgramIR.model_validate_json(dumped)
    assert restored == prog
    assert to_canonical_meme(restored) == (
        "define list numbers as 10 random integers between 1 and 100\n"
        "sort numbers ascending\n"
        "print numbers"
    )


def test_synthesis_result_discriminates_ambiguity_and_exports_json_schema():
    res = SynthesisResult(
        items=[
            AmbiguityDiagnostic(
                statement_id=2,
                source_line=2,
                source_text="for each number in array sort from 1 to 10",
                reason="Contradictory loop and sort",
                candidates=[
                    AmbiguityCandidate(
                        option=1,
                        description="Sort array ascending",
                        canonical_meme="sort array ascending",
                        replacement_ir=[SortCollectionStmt(target="array", direction="ascending")],
                    )
                ],
            )
        ]
    )
    schema = SynthesisResult.model_json_schema()
    assert "items" in schema["properties"]
    assert SynthesisResult.model_validate_json(res.model_dump_json()) == res


def test_json_schema_requires_discriminator_tags():
    from memelang.llm.base import SYSTEM_PROMPT

    schema = SynthesisResult.model_json_schema()
    defs = schema.get("$defs", {})
    assert defs, "Expected $defs in SynthesisResult JSON schema"
    for def_name, def_schema in defs.items():
        props = def_schema.get("properties", {})
        req = def_schema.get("required") or []
        if "op" in props:
            assert "op" in req, f"{def_name} missing 'op' in required"
        if "expr_type" in props:
            assert "expr_type" in req, f"{def_name} missing 'expr_type' in required"

    assert '"var_decl"' in SYSTEM_PROMPT
    assert '"ambiguity"' in SYSTEM_PROMPT


def test_canonical_formatting_for_all_statements_and_expressions():
    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="double_val",
                params=[FuncParam(name="x", param_type="Int")],
                return_type="Int",
                body=[
                    ReturnStmt(
                        value=BinaryOpExpr(
                            op="*",
                            left=VarRefExpr(name="x"),
                            right=LiteralExpr(value=2, data_type="Int"),
                        )
                    )
                ],
            ),
            VarDeclStmt(
                name="vals",
                var_type="List<Int>",
                value=ListLiteralExpr(
                    elements=[
                        LiteralExpr(value=1, data_type="Int"),
                        RandomIntExpr(
                            min_val=LiteralExpr(value=2, data_type="Int"),
                            max_val=LiteralExpr(value=5, data_type="Int"),
                        ),
                    ],
                    element_type="Int",
                ),
            ),
            ListAppendStmt(
                target="vals",
                value=CallExpr(func_name="double_val", args=[LiteralExpr(value=3, data_type="Int")]),
            ),
            ClampCollectionStmt(
                target="vals",
                min_val=LiteralExpr(value=1, data_type="Int"),
                max_val=LiteralExpr(value=10, data_type="Int"),
            ),
            FilterCollectionStmt(
                target="vals",
                item_var="item",
                predicate=BinaryOpExpr(
                    op=">",
                    left=VarRefExpr(name="item"),
                    right=LiteralExpr(value=0, data_type="Int"),
                ),
            ),
            VarDeclStmt(
                name="n",
                var_type="Int",
                value=ListLengthExpr(target=VarRefExpr(name="vals")),
            ),
            IfStmt(
                condition=UnaryOpExpr(
                    op="not",
                    operand=BinaryOpExpr(
                        op="==",
                        left=VarRefExpr(name="n"),
                        right=LiteralExpr(value=0, data_type="Int"),
                    ),
                ),
                then_body=[
                    AssignStmt(
                        name="n",
                        value=ListIndexExpr(
                            target=VarRefExpr(name="vals"),
                            index=LiteralExpr(value=0, data_type="Int"),
                        ),
                    )
                ],
                else_body=[
                    AssignStmt(
                        name="n",
                        value=ReadInputExpr(prompt="Enter n: ", target_type="Int"),
                    )
                ],
            ),
            ForEachStmt(
                item_var="v",
                collection="vals",
                body=[PrintStmt(expressions=[VarRefExpr(name="v")])],
            ),
            ForRangeStmt(
                loop_var="i",
                start=LiteralExpr(value=1, data_type="Int"),
                end=LiteralExpr(value=3, data_type="Int"),
                body=[PrintStmt(expressions=[VarRefExpr(name="i")])],
            ),
            WhileStmt(
                condition=BinaryOpExpr(
                    op=">",
                    left=VarRefExpr(name="n"),
                    right=LiteralExpr(value=10, data_type="Int"),
                ),
                body=[
                    AssignStmt(
                        name="n",
                        value=BinaryOpExpr(
                            op="-",
                            left=VarRefExpr(name="n"),
                            right=LiteralExpr(value=1, data_type="Int"),
                        ),
                    )
                ],
            ),
        ]
    )
    canonical = to_canonical_meme(prog)
    assert "function double_val(x: Int) -> Int:" in canonical
    assert "clamp vals between 1 and 10" in canonical
    assert "filter vals where item > 0" in canonical
    assert "for each v in vals:" in canonical
    assert "for i from 1 to 3:" in canonical
    assert "while n > 10:" in canonical


def test_file_json_list_insert_and_fail_canonical():
    from memelang.ir.schema import FailStmt, ListInsertStmt, ReadJsonListExpr, StrEndsWithExpr

    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="loadFile",
                params=[FuncParam(name="filepath", param_type="String")],
                return_type="List<Float>",
                body=[
                    IfStmt(
                        condition=StrEndsWithExpr(
                            target=VarRefExpr(name="filepath"),
                            suffix=LiteralExpr(value=".json", data_type="String"),
                        ),
                        then_body=[
                            VarDeclStmt(
                                name="nums",
                                var_type="List<Float>",
                                value=ReadJsonListExpr(filepath=VarRefExpr(name="filepath")),
                            ),
                            ListInsertStmt(
                                target="nums",
                                index=LiteralExpr(value=0, data_type="Int"),
                                value=LiteralExpr(value=1.5, data_type="Float"),
                            ),
                            ReturnStmt(value=VarRefExpr(name="nums")),
                        ],
                        else_body=[
                            FailStmt(message=LiteralExpr(value="Wrong File Type", data_type="String"))
                        ],
                    )
                ],
            )
        ]
    )
    restored = ProgramIR.model_validate_json(prog.model_dump_json())
    assert restored == prog
    canonical = to_canonical_meme(restored)
    assert 'filepath ends with ".json"' in canonical
    assert "read JSON number list from filepath" in canonical
    assert "insert 1.5 into nums at 0" in canonical
    assert 'fail with "Wrong File Type"' in canonical


def test_exhaustive_ir_synchronization_across_canonical_heuristic_verifier_gbnf_and_codegen():
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.codegen import generate_code
    from memelang.ir.schema import (
        FailStmt,
        ListInsertStmt,
        ListSetIndexStmt,
        ReadJsonListExpr,
        StrEndsWithExpr,
        StringLengthExpr,
        StringSliceExpr,
    )
    from memelang.llm.heuristic import HeuristicProvider
    from memelang.llm.llama_cpp import MEMELANG_GBNF
    from memelang.runner.executor import program_uses_input

    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="load_or_fail",
                params=[FuncParam(name="filepath", param_type="String")],
                return_type="List<Float>",
                body=[
                    IfStmt(
                        condition=StrEndsWithExpr(
                            target=VarRefExpr(name="filepath"),
                            suffix=LiteralExpr(value=".json", data_type="String"),
                        ),
                        then_body=[
                            VarDeclStmt(
                                name="nums",
                                var_type="List<Float>",
                                value=ReadJsonListExpr(filepath=VarRefExpr(name="filepath")),
                            ),
                            ListInsertStmt(
                                target="nums",
                                index=LiteralExpr(value=0, data_type="Int"),
                                value=LiteralExpr(value=1.5, data_type="Float"),
                            ),
                            ReturnStmt(value=VarRefExpr(name="nums")),
                        ],
                        else_body=[
                            FailStmt(message=LiteralExpr(value="Wrong File Type", data_type="String"))
                        ],
                    )
                ],
            ),
            VarDeclStmt(
                name="matrix",
                var_type="List<List<Int>>",
                value=ListLiteralExpr(
                    elements=[
                        ListLiteralExpr(
                            elements=[
                                LiteralExpr(value=1, data_type="Int"),
                                LiteralExpr(value=2, data_type="Int"),
                            ],
                            element_type="Int",
                        ),
                        ListLiteralExpr(
                            elements=[
                                LiteralExpr(value=3, data_type="Int"),
                                LiteralExpr(value=4, data_type="Int"),
                            ],
                            element_type="Int",
                        ),
                    ],
                    element_type="List<Int>",
                ),
            ),
            VarDeclStmt(
                name="arr",
                var_type="List<Int>",
                value=ListLiteralExpr(
                    elements=[
                        LiteralExpr(value=10, data_type="Int"),
                        LiteralExpr(value=20, data_type="Int"),
                    ],
                    element_type="Int",
                ),
            ),
            ListSetIndexStmt(
                target="arr",
                index=LiteralExpr(value=0, data_type="Int"),
                value=ReadInputExpr(prompt="Enter int: ", target_type="Int"),
            ),
            VarDeclStmt(
                name="word",
                var_type="String",
                value=LiteralExpr(value="hello", data_type="String"),
            ),
            VarDeclStmt(
                name="slen",
                var_type="Int",
                value=StringLengthExpr(target=VarRefExpr(name="word")),
            ),
            VarDeclStmt(
                name="sub",
                var_type="String",
                value=StringSliceExpr(
                    target=VarRefExpr(name="word"),
                    start=LiteralExpr(value=1, data_type="Int"),
                    end=VarRefExpr(name="slen"),
                ),
            ),
            PrintStmt(
                expressions=[
                    ListIndexExpr(
                        target=ListIndexExpr(
                            target=VarRefExpr(name="matrix"),
                            index=LiteralExpr(value=0, data_type="Int"),
                        ),
                        index=LiteralExpr(value=1, data_type="Int"),
                    ),
                    VarRefExpr(name="sub"),
                ]
            ),
        ]
    )

    # 1. Verify synthesis succeeds
    outcome = verify_synthesis(SynthesisResult(items=list(prog.statements)))
    assert outcome.is_unambiguous and outcome.program is not None

    # 2. Canonical formatting + HeuristicProvider round-trip
    canonical = to_canonical_meme(outcome.program)
    roundtrip_syn = HeuristicProvider().synthesize(canonical)
    roundtrip_out = verify_synthesis(roundtrip_syn)
    assert roundtrip_out.is_unambiguous and roundtrip_out.program is not None
    assert to_canonical_meme(roundtrip_out.program) == canonical

    # 3. program_uses_input detects ReadInputExpr inside ListSetIndexStmt
    assert program_uses_input(outcome.program) is True

    # 4. GBNF contains all discriminators and types used
    for token in (
        "var_decl",
        "list_set_index",
        "list_insert",
        "fail_stmt",
        "string_length",
        "string_slice",
        "parse_int",
        "format_int",
        "str_ends_with",
        "read_json_list",
        "record_def",
        "record_set_field",
        "record_literal",
        "record_field",
        "map_literal",
        "map_get",
        "map_has_key",
        "map_set",
        "List<List<Int>>",
    ):
        assert token in MEMELANG_GBNF

    # 5. Codegen succeeds across all 4 targets
    for target in ("python", "rust", "cpp", "go"):
        code = generate_code(outcome.program, target)
        assert code.strip() != ""


def test_records_and_maps_canonical_and_roundtrip():
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.schema import (
        MapEntry,
        MapGetExpr,
        MapHasKeyExpr,
        MapLiteralExpr,
        MapSetStmt,
        RecordDefStmt,
        RecordFieldDef,
        RecordFieldExpr,
        RecordFieldInit,
        RecordLiteralExpr,
        RecordSetFieldStmt,
    )
    from memelang.llm.heuristic import HeuristicProvider

    prog = ProgramIR(
        statements=[
            RecordDefStmt(
                name="User",
                fields=[
                    RecordFieldDef(name="id", field_type="Int"),
                    RecordFieldDef(name="name", field_type="String"),
                ],
            ),
            VarDeclStmt(
                name="u",
                var_type="User",
                value=RecordLiteralExpr(
                    record_name="User",
                    fields=[
                        RecordFieldInit(name="id", value=LiteralExpr(value=1, data_type="Int")),
                        RecordFieldInit(name="name", value=LiteralExpr(value="Alice", data_type="String")),
                    ],
                ),
            ),
            RecordSetFieldStmt(
                target="u",
                field_name="name",
                value=LiteralExpr(value="Bob", data_type="String"),
            ),
            VarDeclStmt(
                name="scores",
                var_type="Map<String, Int>",
                value=MapLiteralExpr(
                    key_type="String",
                    value_type="Int",
                    entries=[
                        MapEntry(
                            key=LiteralExpr(value="Alice", data_type="String"),
                            value=LiteralExpr(value=100, data_type="Int"),
                        ),
                        MapEntry(
                            key=LiteralExpr(value="Bob", data_type="String"),
                            value=LiteralExpr(value=90, data_type="Int"),
                        ),
                    ],
                ),
            ),
            MapSetStmt(
                target="scores",
                key=LiteralExpr(value="Bob", data_type="String"),
                value=LiteralExpr(value=95, data_type="Int"),
            ),
            PrintStmt(
                expressions=[
                    RecordFieldExpr(target=VarRefExpr(name="u"), field_name="name"),
                    MapGetExpr(
                        target=VarRefExpr(name="scores"),
                        key=LiteralExpr(value="Bob", data_type="String"),
                    ),
                    MapHasKeyExpr(
                        target=VarRefExpr(name="scores"),
                        key=LiteralExpr(value="Alice", data_type="String"),
                    ),
                ]
            ),
        ]
    )

    canonical = to_canonical_meme(prog)
    assert "record User:" in canonical
    assert "    id: Int" in canonical
    assert "    name: String" in canonical
    assert 'define u: User as User(id=1, name="Alice")' in canonical
    assert 'set u.name to "Bob"' in canonical
    assert 'define scores: Map<String, Int> as {"Alice": 100, "Bob": 90}' in canonical
    assert 'set scores["Bob"] to 95' in canonical
    assert 'print u.name, scores["Bob"], scores has key "Alice"' in canonical

    roundtrip_syn = HeuristicProvider().synthesize(canonical)
    roundtrip_out = verify_synthesis(roundtrip_syn)
    assert roundtrip_out.is_unambiguous and roundtrip_out.program is not None
    assert to_canonical_meme(roundtrip_out.program) == canonical
    assert isinstance(roundtrip_out.program.statements[-1], PrintStmt)
    assert isinstance(roundtrip_out.program.statements[-1].expressions[1], MapGetExpr)


def test_map_default_and_has_key_precedence_roundtrip():
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    src = """define scores: Map<String, Int> as {"Alice": 10}
define x: Int as (scores["Bob"] default 0) + 5
if scores has key "Alice" and x > 0:
    print x
"""
    syn = HeuristicProvider().synthesize(src)
    out = verify_synthesis(syn)
    assert out.is_unambiguous and out.program is not None
    canonical = to_canonical_meme(out.program)
    roundtrip = verify_synthesis(HeuristicProvider().synthesize(canonical))
    assert roundtrip.is_unambiguous and roundtrip.program == out.program


def test_conversion_builtins_canonical_and_roundtrip():
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.schema import FormatIntExpr, ParseIntExpr
    from memelang.llm.heuristic import HeuristicProvider

    src = """define s: String as "123"
define n: Int as integer value of s
define back: String as text of n
define n2: Int as integer value of "  -42  "
define s2: String as text of (n + 10)
print n, back, n2, s2
"""
    syn = HeuristicProvider().synthesize(src)
    out = verify_synthesis(syn)
    assert out.is_unambiguous and out.program is not None
    canonical = to_canonical_meme(out.program)
    assert "integer value of s" in canonical
    assert "text of n" in canonical
    roundtrip = verify_synthesis(HeuristicProvider().synthesize(canonical))
    assert roundtrip.is_unambiguous and roundtrip.program is not None
    assert to_canonical_meme(roundtrip.program) == canonical

    # Also test alternative heuristic syntax synonyms: "string of", "text from", "integer of"
    syn_alt = HeuristicProvider().synthesize("""define a: Int as integer of "77"
define b: String as string of a
define c: String as text from 99
define d: String as string from 100
print a, b, c, d
""")
    out_alt = verify_synthesis(syn_alt)
    assert out_alt.is_unambiguous and out_alt.program is not None
    can_alt = to_canonical_meme(out_alt.program)
    assert "integer value of \"77\"" in can_alt
    assert "text of a" in can_alt
    assert "text of 99" in can_alt
    assert "text of 100" in can_alt






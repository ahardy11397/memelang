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

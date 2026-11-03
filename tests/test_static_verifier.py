import pytest

from memelang.analyzer.verifier import (
    StaticVerificationError,
    VerificationOutcome,
    verify_program,
    verify_synthesis,
)
from memelang.ir.schema import (
    AssignStmt,
    BinaryOpExpr,
    CallExpr,
    ForEachStmt,
    FuncDefStmt,
    FuncParam,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    RandomListExpr,
    ReturnStmt,
    SortCollectionStmt,
    SynthesisResult,
    VarDeclStmt,
    VarRefExpr,
)


def test_valid_program_verifies():
    res = SynthesisResult(
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
    outcome: VerificationOutcome = verify_synthesis(res)
    assert outcome.is_unambiguous is True
    assert outcome.program is not None
    assert len(outcome.program.statements) == 3
    assert verify_program(outcome.program) == outcome.program


def test_undeclared_variable_raises():
    res = SynthesisResult(
        items=[SortCollectionStmt(target="missing", direction="ascending")]
    )
    with pytest.raises(StaticVerificationError) as exc_info:
        verify_synthesis(res)
    assert "missing" in str(exc_info.value)


def test_incompatible_reassignment_raises():
    res = SynthesisResult(
        items=[
            VarDeclStmt(
                name="x",
                var_type="Int",
                value=LiteralExpr(value=5, data_type="Int"),
            ),
            AssignStmt(
                name="x",
                value=LiteralExpr(value="oops", data_type="String"),
            ),
        ]
    )
    with pytest.raises(StaticVerificationError) as exc_info:
        verify_synthesis(res)
    assert "Int" in str(exc_info.value) and "String" in str(exc_info.value)


def test_division_by_zero_and_mismatched_binop_raise():
    div_zero = SynthesisResult(
        items=[
            VarDeclStmt(
                name="x",
                var_type="Int",
                value=BinaryOpExpr(
                    op="/",
                    left=LiteralExpr(value=10, data_type="Int"),
                    right=LiteralExpr(value=0, data_type="Int"),
                ),
            )
        ]
    )
    with pytest.raises(StaticVerificationError) as exc_div:
        verify_synthesis(div_zero)
    assert "zero" in str(exc_div.value).lower()

    mod_zero = SynthesisResult(
        items=[
            VarDeclStmt(
                name="x",
                var_type="Int",
                value=BinaryOpExpr(
                    op="%",
                    left=LiteralExpr(value=10, data_type="Int"),
                    right=LiteralExpr(value=0, data_type="Int"),
                ),
            )
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(mod_zero)

    mismatched = SynthesisResult(
        items=[
            VarDeclStmt(
                name="s",
                var_type="String",
                value=BinaryOpExpr(
                    op="+",
                    left=LiteralExpr(value="hi", data_type="String"),
                    right=LiteralExpr(value=5, data_type="Int"),
                ),
            )
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(mismatched)


def test_naive_loop_sort_collision_upgraded_to_ambiguity():
    res = SynthesisResult(
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
    outcome = verify_synthesis(res)
    assert outcome.is_unambiguous is False
    assert outcome.program is None
    assert len(outcome.ambiguities) == 1
    diag = outcome.ambiguities[0]
    assert diag.statement_id == 2
    assert len(diag.candidates) == 3
    assert diag.candidates[0].replaces_whole_program is False
    assert diag.candidates[2].replaces_whole_program is True
    # Every candidate's replacement_ir must pass static verification when spliced
    assert verify_program(ProgramIR(statements=[res.items[0], *diag.candidates[0].replacement_ir]))
    assert verify_program(ProgramIR(statements=[res.items[0], *diag.candidates[1].replacement_ir]))
    assert verify_program(ProgramIR(statements=diag.candidates[2].replacement_ir))


def test_function_signature_and_return_type_checking():
    valid_fn = SynthesisResult(
        items=[
            FuncDefStmt(
                name="inc",
                params=[FuncParam(name="n", param_type="Int")],
                return_type="Int",
                body=[
                    ReturnStmt(
                        value=BinaryOpExpr(
                            op="+",
                            left=VarRefExpr(name="n"),
                            right=LiteralExpr(value=1, data_type="Int"),
                        )
                    )
                ],
            ),
            VarDeclStmt(
                name="y",
                var_type="Int",
                value=CallExpr(func_name="inc", args=[LiteralExpr(value=4, data_type="Int")]),
            ),
        ]
    )
    assert verify_synthesis(valid_fn).is_unambiguous is True

    bad_call = SynthesisResult(
        items=[
            valid_fn.items[0],
            VarDeclStmt(
                name="y",
                var_type="Int",
                value=CallExpr(func_name="inc", args=[LiteralExpr(value="wrong", data_type="String")]),
            ),
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(bad_call)


def test_function_scope_isolation_and_complete_return_paths():
    from memelang.ir.schema import IfStmt, WhileStmt

    # 1. Function referencing outer main variable must fail
    leak_outer = SynthesisResult(
        items=[
            VarDeclStmt(name="outer_x", var_type="Int", value=LiteralExpr(value=10, data_type="Int")),
            FuncDefStmt(
                name="bad_read",
                params=[],
                return_type="Int",
                body=[ReturnStmt(value=VarRefExpr(name="outer_x"))],
            ),
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(leak_outer)

    # 2. Duplicate parameter names must fail
    dup_params = SynthesisResult(
        items=[
            FuncDefStmt(
                name="dup",
                params=[FuncParam(name="a", param_type="Int"), FuncParam(name="a", param_type="Int")],
                return_type="Int",
                body=[ReturnStmt(value=VarRefExpr(name="a"))],
            )
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(dup_params)

    # 3. Partial return path (`if` without `else`) must fail
    partial_if = SynthesisResult(
        items=[
            FuncDefStmt(
                name="maybe_ret",
                params=[FuncParam(name="x", param_type="Int")],
                return_type="Int",
                body=[
                    IfStmt(
                        condition=BinaryOpExpr(
                            op=">",
                            left=VarRefExpr(name="x"),
                            right=LiteralExpr(value=0, data_type="Int"),
                        ),
                        then_body=[ReturnStmt(value=LiteralExpr(value=1, data_type="Int"))],
                        else_body=[],
                    )
                ],
            )
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(partial_if)

    # 4. Return only inside `while` loop must fail
    loop_only_ret = SynthesisResult(
        items=[
            FuncDefStmt(
                name="loop_ret",
                params=[FuncParam(name="x", param_type="Int")],
                return_type="Int",
                body=[
                    WhileStmt(
                        condition=LiteralExpr(value=True, data_type="Bool"),
                        body=[ReturnStmt(value=LiteralExpr(value=1, data_type="Int"))],
                    )
                ],
            )
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(loop_only_ret)

    # 5. Complete `if`/`else` returning in both branches succeeds
    complete_if = SynthesisResult(
        items=[
            FuncDefStmt(
                name="abs_val",
                params=[FuncParam(name="x", param_type="Int")],
                return_type="Int",
                body=[
                    IfStmt(
                        condition=BinaryOpExpr(
                            op=">=",
                            left=VarRefExpr(name="x"),
                            right=LiteralExpr(value=0, data_type="Int"),
                        ),
                        then_body=[ReturnStmt(value=VarRefExpr(name="x"))],
                        else_body=[
                            ReturnStmt(
                                value=BinaryOpExpr(
                                    op="-",
                                    left=LiteralExpr(value=0, data_type="Int"),
                                    right=VarRefExpr(name="x"),
                                )
                            )
                        ],
                    )
                ],
            )
        ]
    )
    assert verify_synthesis(complete_if).is_unambiguous is True


def test_same_scope_redeclaration_raises():
    redecl = SynthesisResult(
        items=[
            VarDeclStmt(name="x", var_type="Int", value=LiteralExpr(value=1, data_type="Int")),
            VarDeclStmt(name="x", var_type="String", value=LiteralExpr(value="two", data_type="String")),
        ]
    )
    with pytest.raises(StaticVerificationError) as exc_info:
        verify_synthesis(redecl)
    assert "already declared" in str(exc_info.value)


def test_inverted_literal_bounds_and_negative_index_raise():
    from memelang.ir.schema import ClampCollectionStmt, ListIndexExpr, ListLiteralExpr

    inverted_rand = SynthesisResult(
        items=[
            VarDeclStmt(
                name="nums",
                var_type="List<Int>",
                value=RandomListExpr(
                    count=LiteralExpr(value=5, data_type="Int"),
                    min_val=LiteralExpr(value=100, data_type="Int"),
                    max_val=LiteralExpr(value=1, data_type="Int"),
                ),
            )
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(inverted_rand)

    inverted_clamp = SynthesisResult(
        items=[
            VarDeclStmt(
                name="nums",
                var_type="List<Int>",
                value=ListLiteralExpr(elements=[LiteralExpr(value=5, data_type="Int")], element_type="Int"),
            ),
            ClampCollectionStmt(
                target="nums",
                min_val=LiteralExpr(value=50, data_type="Int"),
                max_val=LiteralExpr(value=10, data_type="Int"),
            ),
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(inverted_clamp)

    neg_idx = SynthesisResult(
        items=[
            VarDeclStmt(
                name="nums",
                var_type="List<Int>",
                value=ListLiteralExpr(elements=[LiteralExpr(value=5, data_type="Int")], element_type="Int"),
            ),
            VarDeclStmt(
                name="last",
                var_type="Int",
                value=ListIndexExpr(
                    target=VarRefExpr(name="nums"),
                    index=LiteralExpr(value=-1, data_type="Int"),
                ),
            ),
        ]
    )
    with pytest.raises(StaticVerificationError):
        verify_synthesis(neg_idx)


def test_fail_stmt_diverges_and_lossy_partial_sort_detected(tmp_path):
    from memelang.ir.schema import (
        FailStmt,
        ForRangeStmt,
        IfStmt,
        ListAppendStmt,
        ListIndexExpr,
        ListInsertStmt,
        ListLengthExpr,
        ListLiteralExpr,
        ReadJsonListExpr,
        StrEndsWithExpr,
    )
    from memelang.lockfile.manager import LockfileManager

    load_fn = FuncDefStmt(
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
                        name="fromFile",
                        var_type="List<Float>",
                        value=ReadJsonListExpr(filepath=VarRefExpr(name="filepath")),
                    ),
                    ReturnStmt(value=VarRefExpr(name="fromFile")),
                ],
                else_body=[
                    FailStmt(message=LiteralExpr(value="Wrong File Type", data_type="String"))
                ],
            )
        ],
    )

    find_fn = FuncDefStmt(
        name="findLargest",
        params=[FuncParam(name="items", param_type="List<Float>")],
        return_type="Float",
        body=[
            VarDeclStmt(name="unsorted", var_type="List<Float>", value=VarRefExpr(name="items")),
            VarDeclStmt(
                name="sorted",
                var_type="List<Float>",
                value=ListLiteralExpr(elements=[], element_type="Float"),
            ),
            IfStmt(
                condition=BinaryOpExpr(
                    op="<=",
                    left=ListIndexExpr(
                        target=VarRefExpr(name="unsorted"),
                        index=LiteralExpr(value=0, data_type="Int"),
                    ),
                    right=ListIndexExpr(
                        target=VarRefExpr(name="unsorted"),
                        index=LiteralExpr(value=1, data_type="Int"),
                    ),
                ),
                then_body=[
                    ListAppendStmt(
                        target="sorted",
                        value=ListIndexExpr(
                            target=VarRefExpr(name="unsorted"),
                            index=LiteralExpr(value=0, data_type="Int"),
                        ),
                    )
                ],
                else_body=[
                    ListAppendStmt(
                        target="sorted",
                        value=ListIndexExpr(
                            target=VarRefExpr(name="unsorted"),
                            index=LiteralExpr(value=1, data_type="Int"),
                        ),
                    )
                ],
            ),
            ForRangeStmt(
                loop_var="idx",
                start=LiteralExpr(value=1, data_type="Int"),
                end=BinaryOpExpr(
                    op="-",
                    left=ListLengthExpr(target=VarRefExpr(name="unsorted")),
                    right=LiteralExpr(value=1, data_type="Int"),
                ),
                body=[
                    VarDeclStmt(
                        name="x",
                        var_type="Float",
                        value=ListIndexExpr(
                            target=VarRefExpr(name="unsorted"),
                            index=VarRefExpr(name="idx"),
                        ),
                    ),
                    IfStmt(
                        condition=BinaryOpExpr(
                            op="<",
                            left=VarRefExpr(name="x"),
                            right=ListIndexExpr(
                                target=VarRefExpr(name="sorted"),
                                index=LiteralExpr(value=0, data_type="Int"),
                            ),
                        ),
                        then_body=[
                            ListInsertStmt(
                                target="sorted",
                                index=LiteralExpr(value=0, data_type="Int"),
                                value=VarRefExpr(name="x"),
                            )
                        ],
                        else_body=[],
                    ),
                ],
            ),
            ReturnStmt(
                value=ListIndexExpr(
                    target=VarRefExpr(name="sorted"),
                    index=BinaryOpExpr(
                        op="-",
                        left=ListLengthExpr(target=VarRefExpr(name="sorted")),
                        right=LiteralExpr(value=1, data_type="Int"),
                    ),
                )
            ),
        ],
    )

    syn = SynthesisResult(items=[load_fn, find_fn])
    out = verify_synthesis(syn)
    assert out.is_unambiguous is False
    assert len(out.ambiguities) == 1
    diag = out.ambiguities[0]
    assert diag.statement_id == 2
    assert len(diag.candidates) == 2

    mgr = LockfileManager(tmp_path / "build.lock")
    mgr.record_outcome("find-largest.meme", "src", "test", syn, out)

    res1 = mgr.apply_resolutions("find-largest.meme", "src", {2: 1})
    assert res1.is_unambiguous is True
    assert res1.program is not None

    res2 = mgr.apply_resolutions("find-largest.meme", "src", {2: 2})
    assert res2.is_unambiguous is True
    assert res2.program is not None

    # Also verify `FuncDefStmt(name="main")` wrapper unwraps into top-level executable statements
    wrapped_main = SynthesisResult(
        items=[
            load_fn,
            FuncDefStmt(
                name="main",
                params=[],
                return_type="Void",
                body=[PrintStmt(expressions=[LiteralExpr(value="ran", data_type="String")])],
            ),
        ]
    )
    unwrapped_out = verify_synthesis(wrapped_main)
    assert unwrapped_out.is_unambiguous is True
    assert unwrapped_out.program is not None
    assert isinstance(unwrapped_out.program.statements[-1], PrintStmt)

    # Also detect lossy partial sort when the loop is nested inside an outer `IfStmt`
    nested_loop_fn = FuncDefStmt(
        name="findLargest",
        params=[FuncParam(name="items", param_type="List<Float>")],
        return_type="Float",
        body=[
            VarDeclStmt(
                name="sorted",
                var_type="List<Float>",
                value=ListLiteralExpr(elements=[], element_type="Float"),
            ),
            IfStmt(
                condition=BinaryOpExpr(
                    op="<",
                    left=ListIndexExpr(
                        target=VarRefExpr(name="items"),
                        index=LiteralExpr(value=0, data_type="Int"),
                    ),
                    right=ListIndexExpr(
                        target=VarRefExpr(name="items"),
                        index=LiteralExpr(value=1, data_type="Int"),
                    ),
                ),
                then_body=[
                    ListAppendStmt(
                        target="sorted",
                        value=ListIndexExpr(
                            target=VarRefExpr(name="items"),
                            index=LiteralExpr(value=0, data_type="Int"),
                        ),
                    ),
                    ForEachStmt(
                        item_var="x",
                        collection="items",
                        body=[
                            IfStmt(
                                condition=BinaryOpExpr(
                                    op="<",
                                    left=VarRefExpr(name="x"),
                                    right=ListIndexExpr(
                                        target=VarRefExpr(name="sorted"),
                                        index=LiteralExpr(value=0, data_type="Int"),
                                    ),
                                ),
                                then_body=[
                                    ListInsertStmt(
                                        target="sorted",
                                        index=LiteralExpr(value=0, data_type="Int"),
                                        value=VarRefExpr(name="x"),
                                    )
                                ],
                                else_body=[],
                            )
                        ],
                    ),
                ],
                else_body=[
                    ListAppendStmt(
                        target="sorted",
                        value=ListIndexExpr(
                            target=VarRefExpr(name="items"),
                            index=LiteralExpr(value=1, data_type="Int"),
                        ),
                    )
                ],
            ),
            ReturnStmt(
                value=ListIndexExpr(
                    target=VarRefExpr(name="sorted"),
                    index=BinaryOpExpr(
                        op="-",
                        left=ListLengthExpr(target=VarRefExpr(name="sorted")),
                        right=LiteralExpr(value=1, data_type="Int"),
                    ),
                )
            ),
        ],
    )
    nested_out = verify_synthesis(SynthesisResult(items=[nested_loop_fn]))
    assert nested_out.is_unambiguous is False
    assert len(nested_out.ambiguities) == 1



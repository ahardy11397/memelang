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
    ListIndexExpr,
    ListLiteralExpr,
    ListSetIndexStmt,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    RandomListExpr,
    ReturnStmt,
    SortCollectionStmt,
    StringLengthExpr,
    StringSliceExpr,
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


def test_indexing_never_populated_empty_list_raises_and_invalidates_stale_lock(tmp_path):
    from memelang.ir.schema import AssignStmt, ListIndexExpr, ListLengthExpr, ListLiteralExpr
    from memelang.lockfile.manager import LockEntry, LockFileDocument, LockfileManager

    # 1. Truly unpopulated empty list (`sorted = []; return sorted[0]`) raises StaticVerificationError
    truly_empty_fn = FuncDefStmt(
        name="badEmpty",
        params=[],
        return_type="Float",
        body=[
            VarDeclStmt(
                name="sorted",
                var_type="List<Float>",
                value=ListLiteralExpr(elements=[], element_type="Float"),
            ),
            ReturnStmt(
                value=ListIndexExpr(
                    target=VarRefExpr(name="sorted"),
                    index=LiteralExpr(value=0, data_type="Int"),
                )
            ),
        ],
    )
    with pytest.raises(StaticVerificationError) as exc_info:
        verify_synthesis(SynthesisResult(items=[truly_empty_fn]))
    assert "empty" in str(exc_info.value).lower()

    # 2. `sort unsorted into sorted`: when LLM emits `sort_collection(unsorted)` followed by reading
    #    unpopulated `sorted`, `verify_synthesis` normalizes it to `assign sorted = unsorted` + `sort sorted`,
    #    whereas raw un-normalized `ProgramIR` in a stale `build.lock` fails `verify_program` and invalidates!
    raw_sort_into_fn = FuncDefStmt(
        name="findLargest",
        params=[FuncParam(name="list", param_type="List<Float>")],
        return_type="Float",
        body=[
            VarDeclStmt(name="unsorted", var_type="List<Float>", value=VarRefExpr(name="list")),
            VarDeclStmt(
                name="sorted",
                var_type="List<Float>",
                value=ListLiteralExpr(elements=[], element_type="Float"),
            ),
            SortCollectionStmt(target="unsorted", direction="ascending"),
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
    with pytest.raises(StaticVerificationError):
        verify_program(ProgramIR(statements=[raw_sort_into_fn]))

    # Stale `build.lock` containing un-normalized `raw_sort_into_fn` is invalidated by `get_cached_program`
    lock_path = tmp_path / "build.lock"
    mgr = LockfileManager(lock_path)
    doc = LockFileDocument(
        entries={
            "examples/find-largest.meme": LockEntry(
                source_sha256=mgr.compute_source_hash("dummy src"),
                provider="test",
                draft_items=[raw_sort_into_fn],
                ir=ProgramIR(statements=[raw_sort_into_fn]),
            )
        }
    )
    lock_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    assert mgr.get_cached_program("examples/find-largest.meme", "dummy src") is None

    # `verify_synthesis` normalizes `raw_sort_into_fn` cleanly!
    norm_out = verify_synthesis(SynthesisResult(items=[raw_sort_into_fn]))
    assert norm_out.is_unambiguous is True
    assert norm_out.program is not None
    norm_fn = norm_out.program.statements[0]
    assert isinstance(norm_fn, FuncDefStmt)
    assert any(isinstance(s, AssignStmt) and s.name == "sorted" for s in norm_fn.body)


def test_verify_list_set_index_success():
    program = ProgramIR(items=[
        VarDeclStmt(name="arr", var_type="List<Int>", value=ListLiteralExpr(elements=[LiteralExpr(value=10, data_type="Int")], element_type="Int"), source_line=1),
        ListSetIndexStmt(target="arr", index=LiteralExpr(value=0, data_type="Int"), value=LiteralExpr(value=20, data_type="Int"), source_line=2),
    ])
    outcome = verify_synthesis(program)
    assert outcome.passed


def test_verify_list_set_index_type_mismatch():
    program = ProgramIR(items=[
        VarDeclStmt(name="arr", var_type="List<Int>", value=ListLiteralExpr(elements=[LiteralExpr(value=10, data_type="Int")], element_type="Int"), source_line=1),
        ListSetIndexStmt(target="arr", index=LiteralExpr(value=0, data_type="Int"), value=LiteralExpr(value="bad", data_type="String"), source_line=2),
    ])
    with pytest.raises(StaticVerificationError, match="Cannot assign String to element of List<Int>"):
        verify_synthesis(program)


def test_verify_string_slice_and_length():
    program = ProgramIR(items=[
        VarDeclStmt(name="msg", var_type="String", value=LiteralExpr(value="hello world", data_type="String"), source_line=1),
        VarDeclStmt(name="n", var_type="Int", value=StringLengthExpr(target=VarRefExpr(name="msg")), source_line=2),
        VarDeclStmt(name="sub", var_type="String", value=StringSliceExpr(target=VarRefExpr(name="msg"), start=LiteralExpr(value=0, data_type="Int"), end=LiteralExpr(value=5, data_type="Int")), source_line=3),
    ])
    outcome = verify_synthesis(program)
    assert outcome.passed


def test_verify_2d_list_indexing():
    program = ProgramIR(statements=[
        VarDeclStmt(
            name="grid",
            var_type="List<List<Int>>",
            value=ListLiteralExpr(
                elements=[
                    ListLiteralExpr(elements=[LiteralExpr(value=1, data_type="Int")], element_type="Int"),
                    ListLiteralExpr(elements=[LiteralExpr(value=2, data_type="Int")], element_type="Int"),
                ],
                element_type="List<Int>",
            ),
            source_line=1,
        ),
        VarDeclStmt(
            name="row0",
            var_type="List<Int>",
            value=ListIndexExpr(target=VarRefExpr(name="grid"), index=LiteralExpr(value=0, data_type="Int")),
            source_line=2,
        ),
        VarDeclStmt(
            name="cell",
            var_type="Int",
            value=ListIndexExpr(
                target=ListIndexExpr(target=VarRefExpr(name="grid"), index=LiteralExpr(value=0, data_type="Int")),
                index=LiteralExpr(value=0, data_type="Int"),
            ),
            source_line=3,
        ),
        ListSetIndexStmt(
            target="grid",
            index=LiteralExpr(value=1, data_type="Int"),
            value=ListLiteralExpr(elements=[LiteralExpr(value=99, data_type="Int")], element_type="Int"),
            source_line=4,
        ),
    ])
    outcome = verify_synthesis(program)
    assert outcome.passed


def test_verify_records_and_maps_negative_cases():
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

    user_def = RecordDefStmt(
        name="User",
        fields=[
            RecordFieldDef(name="id", field_type="Int"),
            RecordFieldDef(name="name", field_type="String"),
        ],
    )

    # 1. Unknown record instantiation & unknown variable type
    with pytest.raises(StaticVerificationError, match="unknown record `Ghost`"):
        verify_synthesis(
            ProgramIR(
                items=[
                    PrintStmt(expressions=[RecordLiteralExpr(record_name="Ghost", fields=[])])
                ]
            )
        )

    with pytest.raises(StaticVerificationError, match="Unknown type `Ghost`"):
        verify_synthesis(
            ProgramIR(
                items=[
                    VarDeclStmt(
                        name="g",
                        var_type="Ghost",
                        value=RecordLiteralExpr(record_name="Ghost", fields=[]),
                    )
                ]
            )
        )

    # 2. Duplicate record definition
    with pytest.raises(StaticVerificationError, match="Duplicate record definition `User`"):
        verify_synthesis(ProgramIR(items=[user_def, user_def]))

    # 3. Unknown field in RecordLiteralExpr
    with pytest.raises(StaticVerificationError, match="Unknown field `age`"):
        verify_synthesis(
            ProgramIR(
                items=[
                    user_def,
                    VarDeclStmt(
                        name="u",
                        var_type="User",
                        value=RecordLiteralExpr(
                            record_name="User",
                            fields=[
                                RecordFieldInit(name="id", value=LiteralExpr(value=1, data_type="Int")),
                                RecordFieldInit(name="name", value=LiteralExpr(value="A", data_type="String")),
                                RecordFieldInit(name="age", value=LiteralExpr(value=9, data_type="Int")),
                            ],
                        ),
                    ),
                ]
            )
        )

    # 4. Missing required field in RecordLiteralExpr
    with pytest.raises(StaticVerificationError, match="Missing required fields"):
        verify_synthesis(
            ProgramIR(
                items=[
                    user_def,
                    VarDeclStmt(
                        name="u",
                        var_type="User",
                        value=RecordLiteralExpr(
                            record_name="User",
                            fields=[
                                RecordFieldInit(name="id", value=LiteralExpr(value=1, data_type="Int")),
                            ],
                        ),
                    ),
                ]
            )
        )

    # 5. Field type mismatch in RecordLiteralExpr
    with pytest.raises(StaticVerificationError, match="expects Int, got String"):
        verify_synthesis(
            ProgramIR(
                items=[
                    user_def,
                    VarDeclStmt(
                        name="u",
                        var_type="User",
                        value=RecordLiteralExpr(
                            record_name="User",
                            fields=[
                                RecordFieldInit(name="id", value=LiteralExpr(value="bad", data_type="String")),
                                RecordFieldInit(name="name", value=LiteralExpr(value="A", data_type="String")),
                            ],
                        ),
                    ),
                ]
            )
        )

    # 6. RecordFieldExpr & RecordSetFieldStmt on unknown field / non-record
    with pytest.raises(StaticVerificationError, match="has no field `missing`"):
        verify_synthesis(
            ProgramIR(
                items=[
                    user_def,
                    VarDeclStmt(
                        name="u",
                        var_type="User",
                        value=RecordLiteralExpr(
                            record_name="User",
                            fields=[
                                RecordFieldInit(name="id", value=LiteralExpr(value=1, data_type="Int")),
                                RecordFieldInit(name="name", value=LiteralExpr(value="A", data_type="String")),
                            ],
                        ),
                    ),
                    PrintStmt(expressions=[RecordFieldExpr(target=VarRefExpr(name="u"), field_name="missing")]),
                ]
            )
        )

    with pytest.raises(StaticVerificationError, match="is not a record"):
        verify_synthesis(
            ProgramIR(
                items=[
                    VarDeclStmt(name="x", var_type="Int", value=LiteralExpr(value=1, data_type="Int")),
                    RecordSetFieldStmt(target="x", field_name="id", value=LiteralExpr(value=2, data_type="Int")),
                ]
            )
        )

    # 7. Unhashable Map key type (Float)
    with pytest.raises(StaticVerificationError, match="Map key type must be Int, Bool, or String"):
        verify_synthesis(
            ProgramIR(
                items=[
                    VarDeclStmt(
                        name="m",
                        var_type="Map<Float, Int>",
                        value=MapLiteralExpr(key_type="Float", value_type="Int", entries=[]),
                    )
                ]
            )
        )

    # 8. Map key/value/default type mismatches
    valid_map_decl = VarDeclStmt(
        name="m",
        var_type="Map<String, Int>",
        value=MapLiteralExpr(
            key_type="String",
            value_type="Int",
            entries=[
                MapEntry(
                    key=LiteralExpr(value="a", data_type="String"),
                    value=LiteralExpr(value=1, data_type="Int"),
                )
            ],
        ),
    )
    with pytest.raises(StaticVerificationError, match="Map default value expected Int, got String"):
        verify_synthesis(
            ProgramIR(
                items=[
                    valid_map_decl,
                    PrintStmt(
                        expressions=[
                            MapGetExpr(
                                target=VarRefExpr(name="m"),
                                key=LiteralExpr(value="a", data_type="String"),
                                default_val=LiteralExpr(value="bad", data_type="String"),
                            )
                        ]
                    ),
                ]
            )
        )

    with pytest.raises(StaticVerificationError, match="Map key check expected String, got Int"):
        verify_synthesis(
            ProgramIR(
                items=[
                    valid_map_decl,
                    PrintStmt(
                        expressions=[
                            MapHasKeyExpr(
                                target=VarRefExpr(name="m"),
                                key=LiteralExpr(value=123, data_type="Int"),
                            )
                        ]
                    ),
                ]
            )
        )

    with pytest.raises(StaticVerificationError, match="Map set value expected Int, got String"):
        verify_synthesis(
            ProgramIR(
                items=[
                    valid_map_decl,
                    MapSetStmt(
                        target="m",
                        key=LiteralExpr(value="b", data_type="String"),
                        value=LiteralExpr(value="wrong", data_type="String"),
                    ),
                ]
            )
        )


def test_loop_collision_ambiguity_renders_actual_clamp_bounds_in_descriptions():
    from memelang.ir.schema import ClampCollectionStmt

    syn = SynthesisResult(
        items=[
            VarDeclStmt(
                name="nums",
                var_type="List<Int>",
                value=RandomListExpr(
                    count=LiteralExpr(value=5, data_type="Int"),
                    min_val=LiteralExpr(value=1, data_type="Int"),
                    max_val=LiteralExpr(value=100, data_type="Int"),
                    implicit_bounds=True,
                ),
            ),
            ForEachStmt(
                item_var="n",
                collection="nums",
                body=[
                    ClampCollectionStmt(
                        target="nums",
                        min_val=LiteralExpr(value=5, data_type="Int"),
                        max_val=LiteralExpr(value=50, data_type="Int"),
                    ),
                    SortCollectionStmt(target="nums", direction="ascending"),
                ],
            ),
        ]
    )
    out = verify_synthesis(syn)
    assert not out.is_unambiguous
    assert len(out.ambiguities) == 1
    cands = {c.option: c.description for c in out.ambiguities[0].candidates}
    assert "[5, 50]" in cands[2]
    assert "[1, 10]" not in cands[2]
    assert "[5, 50]" in cands[3]
    assert "[1, 10]" not in cands[3]


def test_file_io_verification_and_canonical_roundtrip():
    from memelang.ir.canonical import to_canonical_meme
    from memelang.ir.schema import (
        AppendFileStmt,
        FileExistsExpr,
        ReadFileStringExpr,
        WriteFileStmt,
    )
    from memelang.llm.heuristic import HeuristicProvider

    prog = ProgramIR(
        items=[
            VarDeclStmt(
                name="path",
                var_type="String",
                value=LiteralExpr(value="notes.txt", data_type="String"),
            ),
            WriteFileStmt(
                filepath=VarRefExpr(name="path"),
                content=LiteralExpr(value="hello", data_type="String"),
            ),
            AppendFileStmt(
                filepath=VarRefExpr(name="path"),
                content=LiteralExpr(value=" world", data_type="String"),
            ),
            VarDeclStmt(
                name="exists",
                var_type="Bool",
                value=FileExistsExpr(filepath=VarRefExpr(name="path")),
            ),
            VarDeclStmt(
                name="text",
                var_type="String",
                value=ReadFileStringExpr(filepath=VarRefExpr(name="path")),
            ),
            PrintStmt(expressions=[VarRefExpr(name="exists"), VarRefExpr(name="text")]),
        ]
    )
    out = verify_synthesis(prog)
    assert out.is_unambiguous and out.program is not None

    canonical = to_canonical_meme(out.program)
    assert 'write file path with "hello"' in canonical
    assert 'append " world" to file path' in canonical
    assert "file exists path" in canonical
    assert "read string from file path" in canonical

    re_syn = HeuristicProvider().synthesize(canonical)
    re_out = verify_synthesis(re_syn)
    assert re_out.is_unambiguous and re_out.program is not None
    assert to_canonical_meme(re_out.program) == canonical

    # Type check failures
    with pytest.raises(StaticVerificationError, match="`write_file` requires String filepath"):
        verify_synthesis(
            ProgramIR(
                items=[
                    WriteFileStmt(
                        filepath=LiteralExpr(value=123, data_type="Int"),
                        content=LiteralExpr(value="x", data_type="String"),
                    )
                ]
            )
        )
    with pytest.raises(StaticVerificationError, match="`write_file` requires String content"):
        verify_synthesis(
            ProgramIR(
                items=[
                    WriteFileStmt(
                        filepath=LiteralExpr(value="a.txt", data_type="String"),
                        content=LiteralExpr(value=123, data_type="Int"),
                    )
                ]
            )
        )
    with pytest.raises(StaticVerificationError, match="`append_file` requires String content"):
        verify_synthesis(
            ProgramIR(
                items=[
                    AppendFileStmt(
                        filepath=LiteralExpr(value="a.txt", data_type="String"),
                        content=LiteralExpr(value=True, data_type="Bool"),
                    )
                ]
            )
        )
    with pytest.raises(StaticVerificationError, match="`file_exists` requires String filepath"):
        verify_synthesis(
            ProgramIR(
                items=[
                    PrintStmt(
                        expressions=[FileExistsExpr(filepath=LiteralExpr(value=1, data_type="Int"))]
                    )
                ]
            )
        )
    with pytest.raises(StaticVerificationError, match="`read_file_string` requires String filepath"):
        verify_synthesis(
            ProgramIR(
                items=[
                    PrintStmt(
                        expressions=[
                            ReadFileStringExpr(filepath=LiteralExpr(value=1, data_type="Int"))
                        ]
                    )
                ]
            )
        )


def test_exit_stmt_verification_return_path_and_roundtrip():
    from memelang.ir.canonical import to_canonical_meme
    from memelang.ir.schema import ExitStmt, IfStmt
    from memelang.llm.heuristic import HeuristicProvider

    # ExitStmt counts as diverging return path inside non-Void function
    prog = ProgramIR(
        items=[
            FuncDefStmt(
                name="checked",
                params=[FuncParam(name="x", param_type="Int")],
                return_type="Int",
                body=[
                    IfStmt(
                        condition=BinaryOpExpr(
                            op="<",
                            left=VarRefExpr(name="x"),
                            right=LiteralExpr(value=0, data_type="Int"),
                        ),
                        then_body=[ExitStmt(code=LiteralExpr(value=2, data_type="Int"))],
                        else_body=[ReturnStmt(value=VarRefExpr(name="x"))],
                    )
                ],
            ),
            ExitStmt(code=LiteralExpr(value=0, data_type="Int")),
        ]
    )
    out = verify_synthesis(prog)
    assert out.is_unambiguous and out.program is not None
    can = to_canonical_meme(out.program)
    assert "exit with code 2" in can
    assert "exit with code 0" in can
    re_out = verify_synthesis(HeuristicProvider().synthesize(can))
    assert re_out.is_unambiguous and re_out.program is not None
    assert to_canonical_meme(re_out.program) == can

    with pytest.raises(StaticVerificationError, match="`exit_stmt` requires Int code"):
        verify_synthesis(
            ProgramIR(items=[ExitStmt(code=LiteralExpr(value="bad", data_type="String"))])
        )


def test_argv_verification_and_canonical_roundtrip():
    from memelang.ir.canonical import to_canonical_meme
    from memelang.ir.schema import ArgAtExpr, ArgCountExpr
    from memelang.llm.heuristic import HeuristicProvider

    prog = ProgramIR(
        items=[
            VarDeclStmt(name="n", var_type="Int", value=ArgCountExpr()),
            VarDeclStmt(
                name="first",
                var_type="String",
                value=ArgAtExpr(index=LiteralExpr(value=1, data_type="Int")),
            ),
            PrintStmt(expressions=[VarRefExpr(name="n"), VarRefExpr(name="first")]),
        ]
    )
    out = verify_synthesis(prog)
    assert out.is_unambiguous and out.program is not None
    can = to_canonical_meme(out.program)
    assert "argument count" in can
    assert "argument 1" in can
    re_out = verify_synthesis(HeuristicProvider().synthesize(can))
    assert re_out.is_unambiguous and re_out.program is not None
    assert to_canonical_meme(re_out.program) == can

    with pytest.raises(StaticVerificationError, match="`arg_at` index must be Int"):
        verify_synthesis(
            ProgramIR(
                items=[
                    PrintStmt(
                        expressions=[
                            ArgAtExpr(index=LiteralExpr(value="bad", data_type="String"))
                        ]
                    )
                ]
            )
        )

    with pytest.raises(StaticVerificationError, match="Negative argument index"):
        verify_synthesis(
            ProgramIR(
                items=[
                    PrintStmt(
                        expressions=[ArgAtExpr(index=LiteralExpr(value=-1, data_type="Int"))]
                    )
                ]
            )
        )


def test_typed_read_json_list_verification_and_canonical_roundtrip():
    from memelang.ir.canonical import to_canonical_meme
    from memelang.ir.schema import ReadJsonListExpr
    from memelang.llm.heuristic import HeuristicProvider

    prog = ProgramIR(
        items=[
            VarDeclStmt(
                name="legacy_nums",
                var_type="List<Float>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="a.json", data_type="String"),
                ),
            ),
            VarDeclStmt(
                name="explicit_floats",
                var_type="List<Float>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="b.json", data_type="String"),
                    element_type="Float",
                    explicit_type=True,
                ),
            ),
            VarDeclStmt(
                name="ints",
                var_type="List<Int>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="c.json", data_type="String"),
                    element_type="Int",
                    explicit_type=True,
                ),
            ),
            VarDeclStmt(
                name="tags",
                var_type="List<String>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="d.json", data_type="String"),
                    element_type="String",
                    explicit_type=True,
                ),
            ),
            VarDeclStmt(
                name="flags",
                var_type="List<Bool>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="e.json", data_type="String"),
                    element_type="Bool",
                    explicit_type=True,
                ),
            ),
        ]
    )
    out = verify_synthesis(prog)
    assert out.is_unambiguous and out.program is not None

    can = to_canonical_meme(out.program)
    assert 'read JSON number list from "a.json"' in can
    assert 'read json file "b.json" as List<Float>' in can
    assert 'read json file "c.json" as List<Int>' in can
    assert 'read json file "d.json" as List<String>' in can
    assert 'read json file "e.json" as List<Bool>' in can

    re_out = verify_synthesis(HeuristicProvider().synthesize(can))
    assert re_out.is_unambiguous and re_out.program is not None
    assert to_canonical_meme(re_out.program) == can

    # Type mismatch between declared variable type and ReadJsonListExpr element_type fails
    with pytest.raises(StaticVerificationError, match="declared as List<Int> but initialized with List<String>"):
        verify_synthesis(
            ProgramIR(
                items=[
                    VarDeclStmt(
                        name="bad",
                        var_type="List<Int>",
                        value=ReadJsonListExpr(
                            filepath=LiteralExpr(value="d.json", data_type="String"),
                            element_type="String",
                            explicit_type=True,
                        ),
                    )
                ]
            )
        )






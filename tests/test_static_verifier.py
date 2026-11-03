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

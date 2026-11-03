import ast
import pytest

from memelang.codegen import TargetLang, generate_code
from memelang.ir.schema import (
    AssignStmt,
    BinaryOpExpr,
    CallExpr,
    ClampCollectionStmt,
    FilterCollectionStmt,
    ForEachStmt,
    FuncDefStmt,
    FuncParam,
    ListAppendStmt,
    ListLiteralExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    RandomListExpr,
    ReturnStmt,
    SortCollectionStmt,
    VarDeclStmt,
    VarRefExpr,
)
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp"]


@pytest.mark.parametrize("target", TARGETS)
def test_empty_program_compiles_and_runs(target: TargetLang):
    prog = ProgramIR(statements=[])
    code = generate_code(prog, target)
    assert code.strip() != ""
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""


@pytest.mark.parametrize("target", TARGETS)
def test_escaped_strings_and_empty_typed_list(target: TargetLang):
    prog = ProgramIR(
        statements=[
            VarDeclStmt(
                name="empty",
                var_type="List<Int>",
                value=ListLiteralExpr(elements=[], element_type="Int"),
            ),
            ListAppendStmt(target="empty", value=LiteralExpr(value=42, data_type="Int")),
            PrintStmt(expressions=[VarRefExpr(name="empty")]),
            PrintStmt(
                expressions=[
                    LiteralExpr(value='say "hi"\nline2\t\\end', data_type="String")
                ]
            ),
        ]
    )
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout == '[42]\nsay "hi"\nline2\t\\end\n'


@pytest.mark.parametrize("target", TARGETS)
def test_random_clamp_sort_and_functions_across_targets(target: TargetLang):
    prog = ProgramIR(
        statements=[
            FuncDefStmt(
                name="add_one",
                params=[FuncParam(name="x", param_type="Int")],
                return_type="Int",
                body=[
                    ReturnStmt(
                        value=BinaryOpExpr(
                            op="+",
                            left=VarRefExpr(name="x"),
                            right=LiteralExpr(value=1, data_type="Int"),
                        )
                    )
                ],
            ),
            VarDeclStmt(
                name="nums",
                var_type="List<Int>",
                value=RandomListExpr(
                    count=LiteralExpr(value=10, data_type="Int"),
                    min_val=LiteralExpr(value=1, data_type="Int"),
                    max_val=LiteralExpr(value=100, data_type="Int"),
                ),
            ),
            ClampCollectionStmt(
                target="nums",
                min_val=LiteralExpr(value=10, data_type="Int"),
                max_val=LiteralExpr(value=50, data_type="Int"),
            ),
            SortCollectionStmt(target="nums", direction="ascending"),
            PrintStmt(expressions=[VarRefExpr(name="nums")]),
            PrintStmt(
                expressions=[
                    CallExpr(func_name="add_one", args=[LiteralExpr(value=41, data_type="Int")])
                ]
            ),
        ]
    )
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    lines = res.stdout.strip().splitlines()
    assert len(lines) == 2
    parsed_list = ast.literal_eval(lines[0])
    assert len(parsed_list) == 10
    assert parsed_list == sorted(parsed_list)
    assert all(10 <= x <= 50 for x in parsed_list)
    assert lines[1] == "42"


@pytest.mark.parametrize("target", TARGETS)
def test_filter_and_loops_parity(target: TargetLang):
    prog = ProgramIR(
        statements=[
            VarDeclStmt(
                name="items",
                var_type="List<Int>",
                value=ListLiteralExpr(
                    elements=[
                        LiteralExpr(value=v, data_type="Int") for v in [1, 2, 3, 4, 5, 6]
                    ],
                    element_type="Int",
                ),
            ),
            FilterCollectionStmt(
                target="items",
                item_var="item",
                predicate=BinaryOpExpr(
                    op="==",
                    left=BinaryOpExpr(
                        op="%",
                        left=VarRefExpr(name="item"),
                        right=LiteralExpr(value=2, data_type="Int"),
                    ),
                    right=LiteralExpr(value=0, data_type="Int"),
                ),
            ),
            VarDeclStmt(
                name="total",
                var_type="Int",
                value=LiteralExpr(value=0, data_type="Int"),
            ),
            ForEachStmt(
                item_var="n",
                collection="items",
                body=[
                    AssignStmt(
                        name="total",
                        value=BinaryOpExpr(
                            op="+",
                            left=VarRefExpr(name="total"),
                            right=VarRefExpr(name="n"),
                        ),
                    )
                ],
            ),
            PrintStmt(expressions=[VarRefExpr(name="total")]),
        ]
    )
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "12"

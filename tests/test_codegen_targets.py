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


@pytest.mark.parametrize("target", TARGETS)
def test_list_bool_sort_and_index_print_parity(target: TargetLang):
    from memelang.ir.schema import ListIndexExpr

    prog = ProgramIR(
        statements=[
            VarDeclStmt(
                name="flags",
                var_type="List<Bool>",
                value=ListLiteralExpr(
                    elements=[
                        LiteralExpr(value=True, data_type="Bool"),
                        LiteralExpr(value=False, data_type="Bool"),
                        LiteralExpr(value=True, data_type="Bool"),
                    ],
                    element_type="Bool",
                ),
            ),
            SortCollectionStmt(target="flags", direction="ascending"),
            PrintStmt(expressions=[VarRefExpr(name="flags")]),
            PrintStmt(
                expressions=[
                    ListIndexExpr(
                        target=VarRefExpr(name="flags"),
                        index=LiteralExpr(value=0, data_type="Int"),
                    )
                ]
            ),
        ]
    )
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "[false, true, true]\nfalse\n"


@pytest.mark.parametrize("target", TARGETS)
def test_python_builtin_shadowing_variables(target: TargetLang):
    from memelang.ir.schema import ListLengthExpr

    prog = ProgramIR(
        statements=[
            VarDeclStmt(name="min", var_type="Int", value=LiteralExpr(value=2, data_type="Int")),
            VarDeclStmt(name="max", var_type="Int", value=LiteralExpr(value=5, data_type="Int")),
            VarDeclStmt(
                name="list",
                var_type="List<Int>",
                value=ListLiteralExpr(
                    elements=[
                        LiteralExpr(value=1, data_type="Int"),
                        LiteralExpr(value=4, data_type="Int"),
                        LiteralExpr(value=9, data_type="Int"),
                    ],
                    element_type="Int",
                ),
            ),
            ClampCollectionStmt(
                target="list",
                min_val=VarRefExpr(name="min"),
                max_val=VarRefExpr(name="max"),
            ),
            ForEachStmt(
                item_var="item",
                collection="list",
                body=[PrintStmt(expressions=[VarRefExpr(name="item")])],
            ),
            PrintStmt(expressions=[ListLengthExpr(target=VarRefExpr(name="list"))]),
        ]
    )
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout == "2\n4\n5\n3\n"


@pytest.mark.parametrize("target", TARGETS)
def test_read_input_calculator_across_targets(target: TargetLang):
    from memelang.analyzer.verifier import verify_program
    from memelang.ir.schema import IfStmt, ReadInputExpr
    from memelang.runner.executor import program_uses_input

    calc_prog = ProgramIR(
        statements=[
            VarDeclStmt(
                name="num1",
                var_type="Float",
                value=ReadInputExpr(prompt="First Number? ", target_type="Float"),
            ),
            VarDeclStmt(
                name="num2",
                var_type="Float",
                value=ReadInputExpr(prompt="Second Number? ", target_type="Float"),
            ),
            VarDeclStmt(
                name="operator",
                var_type="String",
                value=ReadInputExpr(prompt="Operator? ", target_type="String"),
            ),
            IfStmt(
                condition=BinaryOpExpr(
                    op="==",
                    left=VarRefExpr(name="operator"),
                    right=LiteralExpr(value="*", data_type="String"),
                ),
                then_body=[
                    PrintStmt(
                        expressions=[
                            BinaryOpExpr(
                                op="*",
                                left=VarRefExpr(name="num1"),
                                right=VarRefExpr(name="num2"),
                            )
                        ]
                    )
                ],
                else_body=[
                    IfStmt(
                        condition=BinaryOpExpr(
                            op="==",
                            left=VarRefExpr(name="operator"),
                            right=LiteralExpr(value="%", data_type="String"),
                        ),
                        then_body=[
                            PrintStmt(
                                expressions=[
                                    BinaryOpExpr(
                                        op="%",
                                        left=VarRefExpr(name="num1"),
                                        right=VarRefExpr(name="num2"),
                                    )
                                ]
                            )
                        ],
                        else_body=[
                            PrintStmt(
                                expressions=[
                                    BinaryOpExpr(
                                        op="+",
                                        left=VarRefExpr(name="num1"),
                                        right=VarRefExpr(name="num2"),
                                    )
                                ]
                            )
                        ],
                    )
                ],
            ),
        ]
    )
    verify_program(calc_prog)
    assert program_uses_input(calc_prog) is True
    assert program_uses_input(ProgramIR(statements=[])) is False

    res_dec = execute_ir(calc_prog, target, stdin_text="6.25\n2\n*\n")
    assert res_dec.returncode == 0, res_dec.stderr
    assert res_dec.stdout.strip().endswith("12.5")

    res_mod = execute_ir(calc_prog, target, stdin_text="-7.5\n2\n%\n")
    assert res_mod.returncode == 0, res_mod.stderr
    assert res_mod.stdout.strip().endswith("-1.5")

    res_whole = execute_ir(calc_prog, target, stdin_text="5\n3\n+\n")
    assert res_whole.returncode == 0, res_whole.stderr
    assert res_whole.stdout.strip().endswith("8")

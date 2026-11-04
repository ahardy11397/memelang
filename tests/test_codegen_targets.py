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


@pytest.mark.parametrize("target", TARGETS)
def test_find_largest_json_file_and_partial_sort_resolutions(target: TargetLang, tmp_path):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.schema import (
        FailStmt,
        ForRangeStmt,
        IfStmt,
        ListAppendStmt,
        ListIndexExpr,
        ListInsertStmt,
        ListLengthExpr,
        ReadInputExpr,
        ReadJsonListExpr,
        StrEndsWithExpr,
        SynthesisResult,
    )
    from memelang.lockfile.manager import LockfileManager

    json_file = tmp_path / "nums.json"
    json_file.write_text("[10, 50, 3, 99, 1]\n", encoding="utf-8")

    syn = SynthesisResult(
        items=[
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
            ),
            FuncDefStmt(
                name="findLargest",
                params=[FuncParam(name="items", param_type="List<Float>")],
                return_type="Float",
                body=[
                    VarDeclStmt(
                        name="unsorted", var_type="List<Float>", value=VarRefExpr(name="items")
                    ),
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
            ),
            VarDeclStmt(
                name="filepath",
                var_type="String",
                value=ReadInputExpr(prompt="Filepath? ", target_type="String"),
            ),
            VarDeclStmt(
                name="largest",
                var_type="Float",
                value=CallExpr(
                    func_name="findLargest",
                    args=[CallExpr(func_name="loadFile", args=[VarRefExpr(name="filepath")])],
                ),
            ),
            PrintStmt(expressions=[VarRefExpr(name="largest")]),
        ]
    )

    out = verify_synthesis(syn)
    assert not out.is_unambiguous
    mgr = LockfileManager(tmp_path / "build.lock")
    mgr.record_outcome("find-largest.meme", "src", "test", syn, out)

    # Option 1: Full ascending sort -> returns 99
    prog_opt1 = mgr.apply_resolutions("find-largest.meme", "src", {2: 1}).program
    assert prog_opt1 is not None
    r1 = execute_ir(prog_opt1, target, stdin_text=f"{json_file}\n")
    assert r1.returncode == 0, r1.stderr
    assert r1.stdout.strip().endswith("99")

    # Wrong file type -> prints "Wrong File Type" cleanly and exits 0
    r_bad = execute_ir(prog_opt1, target, stdin_text="notes.txt\n")
    assert r_bad.returncode == 0, r_bad.stderr
    assert r_bad.stdout.strip().endswith("Wrong File Type")

    # Option 2: Literal partial front-insertion -> skips 50 and 99, sorted=[1, 3, 10] -> returns 10
    prog_opt2 = mgr.apply_resolutions("find-largest.meme", "src", {2: 2}).program
    assert prog_opt2 is not None
    r2 = execute_ir(prog_opt2, target, stdin_text=f"{json_file}\n")
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip().endswith("10")

    # Relative path lookup against `source_dir` (`numbers.json` and `./numbers.json`)
    sub_dir = tmp_path / "examples_sub"
    sub_dir.mkdir(exist_ok=True)
    (sub_dir / "numbers.json").write_text("[4, 42, 7]\n", encoding="utf-8")

    r_rel1 = execute_ir(prog_opt1, target, stdin_text="numbers.json\n", source_dir=sub_dir)
    assert r_rel1.returncode == 0, r_rel1.stderr
    assert r_rel1.stdout.strip().endswith("42")

    r_rel2 = execute_ir(prog_opt1, target, stdin_text="./numbers.json\n", source_dir=sub_dir)
    assert r_rel2.returncode == 0, r_rel2.stderr
    assert r_rel2.stdout.strip().endswith("42")


def _run_target(program: ProgramIR, target: TargetLang) -> str:
    res = execute_ir(program, target)
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
def test_codegen_list_set_index_and_strings_parity(target: TargetLang):
    program = ProgramIR(
        items=[
            VarDeclStmt(
                name="nums",
                var_type="List<Int>",
                value=ListLiteralExpr(
                    elements=[LiteralExpr(value=1, data_type="Int"), LiteralExpr(value=2, data_type="Int")],
                    element_type="Int",
                ),
            ),
            ListSetIndexStmt(
                target="nums",
                index=LiteralExpr(value=0, data_type="Int"),
                value=LiteralExpr(value=99, data_type="Int"),
            ),
            PrintStmt(
                expressions=[ListIndexExpr(target=VarRefExpr(name="nums"), index=LiteralExpr(value=0, data_type="Int"))]
            ),
            VarDeclStmt(name="word", var_type="String", value=LiteralExpr(value="abcdef", data_type="String")),
            PrintStmt(expressions=[StringLengthExpr(target=VarRefExpr(name="word"))]),
            PrintStmt(
                expressions=[
                    StringSliceExpr(
                        target=VarRefExpr(name="word"),
                        start=LiteralExpr(value=1, data_type="Int"),
                        end=LiteralExpr(value=4, data_type="Int"),
                    )
                ]
            ),
        ]
    )
    output = _run_target(program, target)
    assert output.strip().splitlines() == ["99", "6", "bcd"]


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
def test_codegen_2d_list_indexing_parity(target: TargetLang):
    program = ProgramIR(
        items=[
            VarDeclStmt(
                name="matrix",
                var_type="List<List<Int>>",
                value=ListLiteralExpr(
                    elements=[
                        ListLiteralExpr(
                            elements=[LiteralExpr(value=10, data_type="Int"), LiteralExpr(value=20, data_type="Int")],
                            element_type="Int",
                        ),
                        ListLiteralExpr(
                            elements=[LiteralExpr(value=30, data_type="Int"), LiteralExpr(value=40, data_type="Int")],
                            element_type="Int",
                        ),
                    ],
                    element_type="List<Int>",
                ),
            ),
            PrintStmt(
                expressions=[
                    ListIndexExpr(
                        target=ListIndexExpr(
                            target=VarRefExpr(name="matrix"),
                            index=LiteralExpr(value=1, data_type="Int"),
                        ),
                        index=LiteralExpr(value=0, data_type="Int"),
                    )
                ]
            ),
        ]
    )
    output = _run_target(program, target)
    assert output.strip().splitlines() == ["30"]


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
def test_codegen_string_slice_end_less_than_start_empty_parity(target: TargetLang):
    program = ProgramIR(
        items=[
            VarDeclStmt(name="word", var_type="String", value=LiteralExpr(value="abcdef", data_type="String")),
            VarDeclStmt(name="s", var_type="Int", value=LiteralExpr(value=3, data_type="Int")),
            VarDeclStmt(name="e", var_type="Int", value=LiteralExpr(value=1, data_type="Int")),
            PrintStmt(
                expressions=[
                    StringSliceExpr(
                        target=VarRefExpr(name="word"),
                        start=VarRefExpr(name="s"),
                        end=VarRefExpr(name="e"),
                    )
                ]
            ),
        ]
    )
    output = _run_target(program, target)
    assert output.strip() == ""




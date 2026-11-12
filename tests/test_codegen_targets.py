import ast
from pathlib import Path
import pytest

from memelang.codegen import TargetLang, generate_code
from memelang.lockfile.manager import LockfileManager
from memelang.ir.schema import (
    AppendFileStmt,
    ArgAtExpr,
    ArgCountExpr,
    AssignStmt,
    BinaryOpExpr,
    BreakStmt,
    CallExpr,
    ClampCollectionStmt,
    ContinueStmt,
    ExitStmt,
    FailStmt,
    FileExistsExpr,
    FilterCollectionStmt,
    ForEachStmt,
    ForRangeStmt,
    FuncDefStmt,
    FuncParam,
    ListAppendStmt,
    ListIndexExpr,
    ListLengthExpr,
    ListLiteralExpr,
    ListSetIndexStmt,
    LiteralExpr,
    MapEntry,
    MapGetExpr,
    MapHasKeyExpr,
    MapLiteralExpr,
    MapSetStmt,
    PrintStmt,
    ProgramIR,
    RandomListExpr,
    ReadFileStringExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    RecordDefStmt,
    RecordFieldDef,
    RecordFieldExpr,
    RecordFieldInit,
    RecordLiteralExpr,
    RecordSetFieldStmt,
    ReturnStmt,
    SortCollectionStmt,
    StrContainsExpr,
    StringCharAtExpr,
    StringIndexOfExpr,
    StringJoinExpr,
    StringLengthExpr,
    StringLowerExpr,
    StringReplaceExpr,
    StringSliceExpr,
    StringSplitExpr,
    StringTrimExpr,
    StringUpperExpr,
    StrStartsWithExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
    WriteFileStmt,
)
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


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

    # Wrong file type -> prints "Wrong File Type" cleanly and exits 1 (FailStmt contract)
    r_bad = execute_ir(prog_opt1, target, stdin_text="notes.txt\n")
    assert r_bad.returncode == 1, r_bad.stderr
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


@pytest.mark.parametrize("target", TARGETS)
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


@pytest.mark.parametrize("target", TARGETS)
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


@pytest.mark.parametrize("target", TARGETS)
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
                    ),
                    StringSliceExpr(
                        target=VarRefExpr(name="word"),
                        start=LiteralExpr(value=10, data_type="Int"),
                        end=LiteralExpr(value=15, data_type="Int"),
                    ),
                    BinaryOpExpr(
                        op="%",
                        left=LiteralExpr(value=-7, data_type="Int"),
                        right=LiteralExpr(value=2, data_type="Int"),
                    ),
                    BinaryOpExpr(
                        op="/",
                        left=LiteralExpr(value=-7, data_type="Int"),
                        right=LiteralExpr(value=2, data_type="Int"),
                    ),
                ]
            ),
        ]
    )
    output = _run_target(program, target)
    assert output.strip() == "-1 -3"


@pytest.mark.parametrize("target", TARGETS)
def test_codegen_record_definition_and_mutation(target: TargetLang):
    program = ProgramIR(
        items=[
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
            PrintStmt(
                expressions=[
                    VarRefExpr(name="u"),
                    RecordFieldExpr(target=VarRefExpr(name="u"), field_name="name"),
                ]
            ),
            RecordSetFieldStmt(
                target="u",
                field_name="name",
                value=LiteralExpr(value="Bob", data_type="String"),
            ),
            PrintStmt(
                expressions=[
                    VarRefExpr(name="u"),
                ]
            ),
        ]
    )
    output = _run_target(program, target)
    assert output.strip().splitlines() == [
        "User(id=1, name=Alice) Alice",
        "User(id=1, name=Bob)",
    ]


@pytest.mark.parametrize("target", TARGETS)
def test_codegen_map_operations_and_formatting(target: TargetLang):
    program = ProgramIR(
        items=[
            VarDeclStmt(
                name="scores",
                var_type="Map<String, Int>",
                value=MapLiteralExpr(
                    key_type="String",
                    value_type="Int",
                    entries=[
                        MapEntry(
                            key=LiteralExpr(value="Alice", data_type="String"),
                            value=LiteralExpr(value=95, data_type="Int"),
                        ),
                        MapEntry(
                            key=LiteralExpr(value="Bob", data_type="String"),
                            value=LiteralExpr(value=80, data_type="Int"),
                        ),
                    ],
                ),
            ),
            PrintStmt(
                expressions=[
                    MapGetExpr(
                        target=VarRefExpr(name="scores"),
                        key=LiteralExpr(value="Alice", data_type="String"),
                    ),
                    MapGetExpr(
                        target=VarRefExpr(name="scores"),
                        key=LiteralExpr(value="Charlie", data_type="String"),
                        default_val=LiteralExpr(value=0, data_type="Int"),
                    ),
                    MapHasKeyExpr(
                        target=VarRefExpr(name="scores"),
                        key=LiteralExpr(value="Bob", data_type="String"),
                    ),
                    MapHasKeyExpr(
                        target=VarRefExpr(name="scores"),
                        key=LiteralExpr(value="Dave", data_type="String"),
                    ),
                ]
            ),
            MapSetStmt(
                target="scores",
                key=LiteralExpr(value="Charlie", data_type="String"),
                value=LiteralExpr(value=88, data_type="Int"),
            ),
            PrintStmt(
                expressions=[
                    VarRefExpr(name="scores"),
                ]
            ),
        ]
    )
    output = _run_target(program, target)
    assert output.strip().splitlines() == [
        "95 0 true false",
        "{Alice: 95, Bob: 80, Charlie: 88}",
    ]


@pytest.mark.parametrize("target", TARGETS)
def test_codegen_function_with_records_and_maps(target: TargetLang):
    program = ProgramIR(
        items=[
            RecordDefStmt(
                name="Request",
                fields=[
                    RecordFieldDef(name="action", field_type="String"),
                    RecordFieldDef(name="user_id", field_type="Int"),
                ],
            ),
            RecordDefStmt(
                name="Response",
                fields=[
                    RecordFieldDef(name="status", field_type="Int"),
                    RecordFieldDef(name="message", field_type="String"),
                ],
            ),
            FuncDefStmt(
                name="handle_req",
                params=[
                    FuncParam(name="req", param_type="Request"),
                    FuncParam(name="roles", param_type="Map<Int, String>"),
                ],
                return_type="Response",
                body=[
                    ReturnStmt(
                        value=RecordLiteralExpr(
                            record_name="Response",
                            fields=[
                                RecordFieldInit(name="status", value=LiteralExpr(value=200, data_type="Int")),
                                RecordFieldInit(
                                    name="message",
                                    value=MapGetExpr(
                                        target=VarRefExpr(name="roles"),
                                        key=RecordFieldExpr(
                                            target=VarRefExpr(name="req"),
                                            field_name="user_id",
                                        ),
                                        default_val=LiteralExpr(value="guest", data_type="String"),
                                    ),
                                ),
                            ],
                        )
                    )
                ],
            ),
            VarDeclStmt(
                name="req",
                var_type="Request",
                value=RecordLiteralExpr(
                    record_name="Request",
                    fields=[
                        RecordFieldInit(name="action", value=LiteralExpr(value="login", data_type="String")),
                        RecordFieldInit(name="user_id", value=LiteralExpr(value=42, data_type="Int")),
                    ],
                ),
            ),
            VarDeclStmt(
                name="roles",
                var_type="Map<Int, String>",
                value=MapLiteralExpr(
                    key_type="Int",
                    value_type="String",
                    entries=[
                        MapEntry(
                            key=LiteralExpr(value=42, data_type="Int"),
                            value=LiteralExpr(value="admin", data_type="String"),
                        )
                    ],
                ),
            ),
            VarDeclStmt(
                name="resp",
                var_type="Response",
                value=CallExpr(
                    func_name="handle_req",
                    args=[VarRefExpr(name="req"), VarRefExpr(name="roles")],
                ),
            ),
            PrintStmt(
                expressions=[
                    RecordFieldExpr(target=VarRefExpr(name="resp"), field_name="status"),
                    RecordFieldExpr(target=VarRefExpr(name="resp"), field_name="message"),
                ]
            ),
        ]
    )
    output = _run_target(program, target)
    assert output.strip().splitlines() == ["200 admin"]


def test_advanced_examples_output_parity():
    adv_dir = Path("examples/advanced")
    scripts = sorted(adv_dir.glob("*.meme")) + sorted(adv_dir.glob("*/main.meme"))
    assert len(scripts) >= 9, f"Expected at least 9 advanced scripts, found {len(scripts)}"

    for script in scripts:
        lock_path = script.with_suffix(".meme.lock")
        assert lock_path.exists(), f"Missing lockfile: {lock_path}"

        mgr = LockfileManager(lock_path)
        src = script.read_text(encoding="utf-8")
        prog = mgr.get_cached_program(str(script), src)
        assert prog is not None, f"Failed to load cached ProgramIR from {lock_path}"

        py_res = execute_ir(prog, "python")
        assert py_res.returncode == 0, f"Python failed on {script.name}: {py_res.stderr}"

        rust_res = execute_ir(prog, "rust")
        assert rust_res.returncode == 0, f"Rust failed on {script.name}: {rust_res.stderr}"

        cpp_res = execute_ir(prog, "cpp")
        assert cpp_res.returncode == 0, f"C++ failed on {script.name}: {cpp_res.stderr}"

        go_res = execute_ir(prog, "go")
        assert go_res.returncode == 0, f"Go failed on {script.name}: {go_res.stderr}"

        c_res = execute_ir(prog, "c")
        assert c_res.returncode == 0, f"C failed on {script.name}: {c_res.stderr}"

        ts_res = execute_ir(prog, "ts")
        assert ts_res.returncode == 0, f"TypeScript failed on {script.name}: {ts_res.stderr}"

        assert py_res.stdout == rust_res.stdout == cpp_res.stdout == go_res.stdout == c_res.stdout == ts_res.stdout, (
            f"Output parity mismatch on {script.name}:\n"
            f"Python:\n{py_res.stdout}\n"
            f"Rust:\n{rust_res.stdout}\n"
            f"C++:\n{cpp_res.stdout}\n"
            f"Go:\n{go_res.stdout}\n"
            f"C:\n{c_res.stdout}\n"
            f"TypeScript:\n{ts_res.stdout}"
        )


@pytest.mark.parametrize("target", TARGETS)
def test_codegen_unsorted_map_keys_and_out_of_order_record_fields_parity(target: TargetLang):
    program = ProgramIR(
        items=[
            RecordDefStmt(
                name="Item",
                fields=[
                    RecordFieldDef(name="sku", field_type="String"),
                    RecordFieldDef(name="qty", field_type="Int"),
                    RecordFieldDef(name="active", field_type="Bool"),
                ],
            ),
            VarDeclStmt(
                name="it",
                var_type="Item",
                value=RecordLiteralExpr(
                    record_name="Item",
                    fields=[
                        RecordFieldInit(name="active", value=LiteralExpr(value=True, data_type="Bool")),
                        RecordFieldInit(name="qty", value=LiteralExpr(value=5, data_type="Int")),
                        RecordFieldInit(name="sku", value=LiteralExpr(value="SKU-9", data_type="String")),
                    ],
                ),
            ),
            VarDeclStmt(
                name="m",
                var_type="Map<String, Int>",
                value=MapLiteralExpr(
                    key_type="String",
                    value_type="Int",
                    entries=[
                        MapEntry(
                            key=LiteralExpr(value="zebra", data_type="String"),
                            value=LiteralExpr(value=1, data_type="Int"),
                        ),
                        MapEntry(
                            key=LiteralExpr(value="apple", data_type="String"),
                            value=LiteralExpr(value=2, data_type="Int"),
                        ),
                        MapEntry(
                            key=LiteralExpr(value="mango", data_type="String"),
                            value=LiteralExpr(value=3, data_type="Int"),
                        ),
                    ],
                ),
            ),
            PrintStmt(expressions=[VarRefExpr(name="it"), VarRefExpr(name="m")]),
        ]
    )
    output = _run_target(program, target)
    assert output.strip() == "Item(sku=SKU-9, qty=5, active=true) {apple: 2, mango: 3, zebra: 1}"


@pytest.mark.parametrize("target", TARGETS)
def test_fail_stmt_exits_with_code_1_across_targets(target: TargetLang):
    program = ProgramIR(
        items=[
            FailStmt(message=LiteralExpr(value="Guard failed", data_type="String")),
            PrintStmt(expressions=[LiteralExpr(value="Unreachable", data_type="String")]),
        ]
    )
    res = execute_ir(program, target)
    assert res.returncode == 1
    assert res.stdout.strip() == "Guard failed"


@pytest.mark.parametrize("target", TARGETS)
def test_meme_quiet_prompts_suppresses_prompt_echo_across_targets(target: TargetLang):
    program = ProgramIR(
        items=[
            VarDeclStmt(
                name="val",
                var_type="Int",
                value=ReadInputExpr(prompt="Enter number: ", target_type="Int"),
            ),
            PrintStmt(expressions=[VarRefExpr(name="val")]),
        ]
    )
    loud = execute_ir(program, target, stdin_text="42\n", quiet_prompts=False)
    assert loud.returncode == 0, loud.stderr
    assert "Enter number: " in loud.stdout
    assert loud.stdout.strip().endswith("42")

    quiet = execute_ir(program, target, stdin_text="42\n", quiet_prompts=True)
    assert quiet.returncode == 0, quiet.stderr
    assert "Enter number: " not in quiet.stdout
    assert quiet.stdout.strip() == "42"


@pytest.mark.parametrize("target", TARGETS)
def test_file_io_write_append_read_exists_and_missing_error_parity(target: TargetLang):
    program = ProgramIR(
        items=[
            VarDeclStmt(
                name="p",
                var_type="String",
                value=LiteralExpr(value="memo.txt", data_type="String"),
            ),
            PrintStmt(expressions=[FileExistsExpr(filepath=VarRefExpr(name="p"))]),
            WriteFileStmt(
                filepath=VarRefExpr(name="p"),
                content=LiteralExpr(value="line1\n", data_type="String"),
            ),
            PrintStmt(expressions=[FileExistsExpr(filepath=VarRefExpr(name="p"))]),
            AppendFileStmt(
                filepath=VarRefExpr(name="p"),
                content=LiteralExpr(value="line2", data_type="String"),
            ),
            VarDeclStmt(
                name="body",
                var_type="String",
                value=ReadFileStringExpr(filepath=VarRefExpr(name="p")),
            ),
            PrintStmt(expressions=[VarRefExpr(name="body")]),
            WriteFileStmt(
                filepath=VarRefExpr(name="p"),
                content=LiteralExpr(value="overwritten", data_type="String"),
            ),
            PrintStmt(expressions=[ReadFileStringExpr(filepath=VarRefExpr(name="p"))]),
        ]
    )
    res = execute_ir(program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["false", "true", "line1", "line2", "overwritten"]

    missing_prog = ProgramIR(
        items=[
            PrintStmt(
                expressions=[
                    ReadFileStringExpr(
                        filepath=LiteralExpr(value="does_not_exist.txt", data_type="String")
                    )
                ]
            )
        ]
    )
    missing_res = execute_ir(missing_prog, target)
    assert missing_res.returncode == 1
    assert missing_res.stdout.strip() == "Error reading file: does_not_exist.txt"


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize(
    ("code_val", "expected_rc"),
    [
        (0, 0),
        (42, 42),
        (255, 255),
        (256, 0),
        (258, 2),
        (-1, 255),
        (-250, 6),
    ],
)
def test_exit_stmt_truncation_and_immediate_termination_across_targets(
    target: TargetLang, code_val: int, expected_rc: int
):
    prog = ProgramIR(
        items=[
            PrintStmt(expressions=[LiteralExpr(value="before", data_type="String")]),
            ExitStmt(code=LiteralExpr(value=code_val, data_type="Int")),
            PrintStmt(expressions=[LiteralExpr(value="after", data_type="String")]),
        ]
    )
    res = execute_ir(prog, target)
    assert res.returncode == expected_rc
    assert res.stdout.strip() == "before"


@pytest.mark.parametrize("target", TARGETS)
def test_argv_count_positional_and_out_of_range_parity(target: TargetLang):
    prog = ProgramIR(
        items=[
            PrintStmt(
                expressions=[
                    ArgCountExpr(),
                    ArgAtExpr(index=LiteralExpr(value=1, data_type="Int")),
                    ArgAtExpr(index=LiteralExpr(value=2, data_type="Int")),
                ]
            )
        ]
    )
    res = execute_ir(prog, target, argv=["add", "buy milk"])
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "3 add buy milk"

    # Out-of-range index -> deterministic fail-style exit 1
    oor_prog = ProgramIR(
        items=[
            PrintStmt(expressions=[ArgAtExpr(index=LiteralExpr(value=5, data_type="Int"))])
        ]
    )
    oor_res = execute_ir(oor_prog, target, argv=["only_one"])
    assert oor_res.returncode == 1
    assert oor_res.stdout.strip() == "Error: argument index 5 out of range"


@pytest.mark.parametrize("target", TARGETS)
def test_read_json_list_typed_elements_escapes_and_error_parity(target: TargetLang, tmp_path):
    int_file = tmp_path / "ints.json"
    int_file.write_text(" [ -10 , 0 ,\n  42 , 99 ] \n", encoding="utf-8")

    float_file = tmp_path / "floats.json"
    float_file.write_text("[ 1.5, -2.25, 3, 4.0e1 ]", encoding="utf-8")

    str_file = tmp_path / "strings.json"
    str_file.write_text(
        r'["alpha, beta", "quote: \"hi\"", "slash: \\", "unicode: \u0041\nline2"]',
        encoding="utf-8",
    )

    bool_file = tmp_path / "bools.json"
    bool_file.write_text("[ true , false , true ]", encoding="utf-8")

    empty_file = tmp_path / "empty.json"
    empty_file.write_text(" [ \n\t ] ", encoding="utf-8")

    prog = ProgramIR(
        items=[
            VarDeclStmt(
                name="ints",
                var_type="List<Int>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="ints.json", data_type="String"),
                    element_type="Int",
                    explicit_type=True,
                ),
            ),
            VarDeclStmt(
                name="floats",
                var_type="List<Float>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="floats.json", data_type="String"),
                    element_type="Float",
                    explicit_type=True,
                ),
            ),
            VarDeclStmt(
                name="strs",
                var_type="List<String>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="strings.json", data_type="String"),
                    element_type="String",
                    explicit_type=True,
                ),
            ),
            VarDeclStmt(
                name="bools",
                var_type="List<Bool>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="bools.json", data_type="String"),
                    element_type="Bool",
                    explicit_type=True,
                ),
            ),
            VarDeclStmt(
                name="empty_ints",
                var_type="List<Int>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="empty.json", data_type="String"),
                    element_type="Int",
                    explicit_type=True,
                ),
            ),
            PrintStmt(expressions=[VarRefExpr(name="ints")]),
            PrintStmt(expressions=[VarRefExpr(name="floats")]),
            PrintStmt(
                expressions=[
                    ListLengthExpr(target=VarRefExpr(name="strs")),
                    ListIndexExpr(
                        target=VarRefExpr(name="strs"),
                        index=LiteralExpr(value=0, data_type="Int"),
                    ),
                    ListIndexExpr(
                        target=VarRefExpr(name="strs"),
                        index=LiteralExpr(value=1, data_type="Int"),
                    ),
                    ListIndexExpr(
                        target=VarRefExpr(name="strs"),
                        index=LiteralExpr(value=2, data_type="Int"),
                    ),
                    ListIndexExpr(
                        target=VarRefExpr(name="strs"),
                        index=LiteralExpr(value=3, data_type="Int"),
                    ),
                ]
            ),
            PrintStmt(expressions=[VarRefExpr(name="bools")]),
            PrintStmt(expressions=[ListLengthExpr(target=VarRefExpr(name="empty_ints"))]),
        ]
    )

    res = execute_ir(prog, target, source_dir=tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "[-10, 0, 42, 99]",
        "[1.5, -2.25, 3, 40]",
        '4 alpha, beta quote: "hi" slash: \\ unicode: A',
        "line2",
        "[true, false, true]",
        "0",
    ]

    # Null in JSON array is rejected with non-zero exit across all targets
    null_file = tmp_path / "bad_null.json"
    null_file.write_text("[1, null, 3]", encoding="utf-8")
    null_prog = ProgramIR(
        items=[
            VarDeclStmt(
                name="bad",
                var_type="List<Int>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="bad_null.json", data_type="String"),
                    element_type="Int",
                    explicit_type=True,
                ),
            )
        ]
    )
    null_res = execute_ir(null_prog, target, source_dir=tmp_path)
    assert null_res.returncode == 1

    # Boolean inside numeric JSON array is rejected (Python bool is a subclass of int, so must be guarded)
    bool_in_num_file = tmp_path / "bool_in_num.json"
    bool_in_num_file.write_text("[1, true, 3]", encoding="utf-8")
    bool_in_num_prog = ProgramIR(
        items=[
            VarDeclStmt(
                name="bad_num",
                var_type="List<Int>",
                value=ReadJsonListExpr(
                    filepath=LiteralExpr(value="bool_in_num.json", data_type="String"),
                    element_type="Int",
                    explicit_type=True,
                ),
            )
        ]
    )
    bool_in_num_res = execute_ir(bool_in_num_prog, target, source_dir=tmp_path)
    assert bool_in_num_res.returncode == 1


@pytest.mark.parametrize("target", TARGETS)
def test_break_and_continue_across_all_loop_kinds_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.canonical import to_canonical_meme
    from memelang.llm.heuristic import HeuristicProvider

    source = """
define list nums as [2, 5, 8, 11, 14, 17, 20]
define evens_sum: Int as 0
for each n in nums:
    if n % 2 != 0:
        continue
    if n > 15:
        break
    set evens_sum to evens_sum + n
print "evens_sum", evens_sum

define range_acc: Int as 0
for i from 1 to 10:
    if i == 3 or i == 5:
        continue
    if i == 7:
        break
    set range_acc to range_acc + i
print "range_acc", range_acc

define w: Int as 0
define w_hits: Int as 0
while w < 10:
    set w to w + 1
    if w % 2 == 0:
        continue
    set w_hits to w_hits + w
    if w >= 5:
        break
print "w", w, "w_hits", w_hits
""".strip()

    prov = HeuristicProvider()
    outcome = verify_synthesis(prov.synthesize(source))
    assert outcome.program is not None
    canon = to_canonical_meme(outcome.program)
    assert "continue" in canon and "break" in canon

    # Round-trip canonical decompiled source through heuristic
    rt_outcome = verify_synthesis(prov.synthesize(canon))
    assert rt_outcome.program is not None

    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "evens_sum 24",
        "range_acc 13",
        "w 5 w_hits 9",
    ]


def test_break_and_continue_verifier_loop_scope_rules():
    from memelang.analyzer.verifier import StaticVerificationError, verify_program

    # 1. break at top level
    with pytest.raises(StaticVerificationError, match="`break` statement outside of a loop"):
        verify_program(ProgramIR(statements=[BreakStmt()]))

    # 2. continue at top level
    with pytest.raises(StaticVerificationError, match="`continue` statement outside of a loop"):
        verify_program(ProgramIR(statements=[ContinueStmt()]))

    # 3. break inside a function body (not in a loop)
    with pytest.raises(StaticVerificationError, match="`break` statement outside of a loop"):
        verify_program(
            ProgramIR(
                statements=[
                    FuncDefStmt(
                        name="bad_fn",
                        params=[],
                        return_type="Void",
                        body=[BreakStmt()],
                    )
                ]
            )
        )

    # 4. break inside a function defined inside a loop body (func_def resets loop scope)
    with pytest.raises(StaticVerificationError, match="`break` statement outside of a loop"):
        verify_program(
            ProgramIR(
                statements=[
                    ForRangeStmt(
                        loop_var="i",
                        start=LiteralExpr(value=1, data_type="Int"),
                        end=LiteralExpr(value=3, data_type="Int"),
                        body=[
                            FuncDefStmt(
                                name="inner_fn",
                                params=[],
                                return_type="Void",
                                body=[BreakStmt()],
                            )
                        ],
                    )
                ]
            )
        )


@pytest.mark.parametrize("target", TARGETS)
def test_string_verbs_all_10_cross_target_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.canonical import to_canonical_meme
    from memelang.llm.heuristic import HeuristicProvider

    source = """
define raw: String as " \\t\\n  pre_Hello--World--Hello_suf  \\r\\n "
define trimmed: String as trim raw
print "trimmed:", trimmed

define has_world: Bool as trimmed contains "World"
define has_mars: Bool as trimmed contains "Mars"
define starts_ok: Bool as trimmed starts with "pre_"
define starts_bad: Bool as trimmed starts with "PRE_"
print has_world, has_mars, starts_ok, starts_bad

define replaced: String as replace "Hello" with "Hi" in trimmed
define up: String as upper replaced
define lo: String as lower up
print replaced
print up
print lo

define parts: List<String> as split lo by "--"
print "parts_len:", length of parts, parts
define rejoined: String as join parts with "::"
print "rejoined:", rejoined

define idx_found: Int as index of "::world::" in rejoined
define idx_missing: Int as index of "galaxy" in rejoined
define ch0: String as char at 0 of rejoined
define ch4: String as char at 4 of rejoined
print idx_found, idx_missing, ch0, ch4
""".strip()

    prov = HeuristicProvider()
    outcome = verify_synthesis(prov.synthesize(source))
    assert outcome.program is not None

    canon = to_canonical_meme(outcome.program)
    rt_outcome = verify_synthesis(prov.synthesize(canon))
    assert rt_outcome.program is not None

    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "trimmed: pre_Hello--World--Hello_suf",
        "true false true false",
        "pre_Hi--World--Hi_suf",
        "PRE_HI--WORLD--HI_SUF",
        "pre_hi--world--hi_suf",
        "parts_len: 3 [pre_hi, world, hi_suf]",
        "rejoined: pre_hi::world::hi_suf",
        "6 -1 p h",
    ]


@pytest.mark.parametrize("target", TARGETS)
def test_string_split_runtime_empty_sep_and_char_at_oob_errors(target: TargetLang):
    # Dynamic empty separator in split -> exit 1 with deterministic message
    prog_split = ProgramIR(
        statements=[
            VarDeclStmt(
                name="sep",
                var_type="String",
                value=StringTrimExpr(target=LiteralExpr(value="   ", data_type="String")),
            ),
            VarDeclStmt(
                name="parts",
                var_type="List<String>",
                value=StringSplitExpr(
                    target=LiteralExpr(value="a,b", data_type="String"),
                    separator=VarRefExpr(name="sep"),
                ),
            ),
            PrintStmt(expressions=[VarRefExpr(name="parts")]),
        ]
    )
    res_split = execute_ir(prog_split, target)
    assert res_split.returncode == 1
    assert res_split.stdout.strip() == "Error: empty separator in split"

    # Out-of-bounds char at -> exit 1 with deterministic message
    prog_char = ProgramIR(
        statements=[
            VarDeclStmt(
                name="c",
                var_type="String",
                value=StringCharAtExpr(
                    target=LiteralExpr(value="abc", data_type="String"),
                    index=LiteralExpr(value=5, data_type="Int"),
                ),
            ),
            PrintStmt(expressions=[VarRefExpr(name="c")]),
        ]
    )
    res_char = execute_ir(prog_char, target)
    assert res_char.returncode == 1
    assert res_char.stdout.strip() == "Error: string index 5 out of range"


def test_string_verbs_static_verifier_rules():
    from memelang.analyzer.verifier import StaticVerificationError, verify_program

    # Static empty literal separator in split
    with pytest.raises(StaticVerificationError, match="`string_split` separator cannot be empty"):
        verify_program(
            ProgramIR(
                statements=[
                    VarDeclStmt(
                        name="parts",
                        var_type="List<String>",
                        value=StringSplitExpr(
                            target=LiteralExpr(value="a,b", data_type="String"),
                            separator=LiteralExpr(value="", data_type="String"),
                        ),
                    )
                ]
            )
        )

    # join requires List<String>
    with pytest.raises(StaticVerificationError, match="`string_join` requires List<String>"):
        verify_program(
            ProgramIR(
                statements=[
                    VarDeclStmt(
                        name="s",
                        var_type="String",
                        value=StringJoinExpr(
                            items=ListLiteralExpr(
                                elements=[LiteralExpr(value=1, data_type="Int")],
                                element_type="Int",
                            ),
                            separator=LiteralExpr(value=",", data_type="String"),
                        ),
                    )
                ]
            )
        )


@pytest.mark.parametrize("target", TARGETS)
def test_map_iteration_and_loop_with_index_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.canonical import to_canonical_meme
    from memelang.llm.heuristic import HeuristicProvider

    source = """
define scores: Map<String, Int> as {"zara": 85, "alice": 95, "bob": 90, "charlie": 88}

for each k in scores:
    if k == "bob":
        continue
    print k, scores[k]

define nums: List<Int> as [10, 20, 30, 40]
for each index i item v in nums:
    if i == 1:
        continue
    print i, v
    if i == 2:
        break

for each idx, k in scores:
    print idx, k, scores[k]
    if idx == 1:
        break
""".strip()

    prov = HeuristicProvider()
    outcome = verify_synthesis(prov.synthesize(source))
    assert outcome.program is not None

    canon = to_canonical_meme(outcome.program)
    assert "for each index i item v in nums:" in canon
    assert "for each index idx item k in scores:" in canon
    rt_outcome = verify_synthesis(prov.synthesize(canon))
    assert rt_outcome.program is not None

    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "alice 95",
        "charlie 88",
        "zara 85",
        "0 10",
        "2 30",
        "0 alice 95",
        "1 bob 90",
    ]


def test_negative_indexing_policy_upgraded_diagnostics_and_loop_rules():
    from memelang.analyzer.verifier import StaticVerificationError, verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    prov = HeuristicProvider()

    # 1. Negative list index via heuristic (`nums[-1]` parses as UnaryOpExpr(-, 1))
    with pytest.raises(
        StaticVerificationError,
        match=r"Negative list index \(-1\) is not allowed; use positive index `nums\[length of nums - 1\]` instead",
    ):
        verify_synthesis(
            prov.synthesize(
                "define nums: List<Int> as [10, 20, 30]\ndefine last: Int as nums[-1]"
            )
        )

    # 2. Negative string char at index
    with pytest.raises(
        StaticVerificationError,
        match=r"Negative string index \(-1\) is not allowed; use positive index `char at \(length of string s - 1\) of s` instead",
    ):
        verify_synthesis(
            prov.synthesize(
                'define s: String as "hello"\ndefine last_ch: String as char at -1 of s'
            )
        )

    # 3. Duplicate index_var and item_var name in for_each
    with pytest.raises(
        StaticVerificationError,
        match=r"`for each` index variable `x` cannot have the same name as item variable `x`",
    ):
        verify_synthesis(
            prov.synthesize(
                "define nums: List<Int> as [1, 2]\nfor each index x item x in nums:\n    print x"
            )
        )


@pytest.mark.parametrize("target", TARGETS)
def test_compound_assignment_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.canonical import to_canonical_meme
    from memelang.llm.heuristic import HeuristicProvider

    source = """
define x: Int as 10
add 5 to x
subtract 3 from x
multiply x by 2
divide x by 5
print "x:", x

define neg: Int as -7
divide neg by 2
print "neg:", neg

define f: Float as 10.0
add 2.5 to f
subtract 0.5 from f
multiply f by 1.5
divide f by 4.0
print "f:", f

define nums: List<Int> as [1, 2]
add 3 to nums
print "nums:", nums
""".strip()

    prov = HeuristicProvider()
    outcome = verify_synthesis(prov.synthesize(source))
    assert outcome.program is not None

    canon = to_canonical_meme(outcome.program)
    assert "add 5 to x" in canon
    assert "subtract 3 from x" in canon
    assert "multiply x by 2" in canon
    assert "divide x by 5" in canon
    assert "append 3 to nums" in canon
    rt_outcome = verify_synthesis(prov.synthesize(canon))
    assert rt_outcome.program is not None

    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "x: 4",
        "neg: -3",
        "f: 4.5",
        "nums: [1, 2, 3]",
    ]


def test_compound_assignment_static_verifier_rules():
    from memelang.analyzer.verifier import StaticVerificationError, verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    prov = HeuristicProvider()

    # 1. Compound assignment on non-numeric variable (String)
    with pytest.raises(
        StaticVerificationError,
        match=r"Compound assignment \(`\+`\) requires Int or Float variable, but `s` has type String",
    ):
        verify_synthesis(
            prov.synthesize('define s: String as "hi"\nadd "!" to s')
        )

    # 2. Compound assignment with mismatched numeric type (Int vs Float)
    with pytest.raises(
        StaticVerificationError,
        match=r"Compound assignment \(`\+`\) on `x` \(Int\) requires Int operand, got Float",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as 10\nadd 1.5 to x")
        )

    # 3. Compound assignment division by literal zero
    with pytest.raises(
        StaticVerificationError,
        match=r"Division or modulo by literal zero",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as 10\ndivide x by 0")
        )


@pytest.mark.parametrize("target", TARGETS)
def test_switch_match_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.canonical import to_canonical_meme
    from memelang.llm.heuristic import HeuristicProvider

    source = """
function classify_code(code: Int) -> String:
    match code:
        when 1:
            return "one"
        when 2:
            return "two"
        otherwise:
            return "many"

define role: String as "admin"
define access: String as "none"
match role:
    when "admin":
        set access to "full"
    when "guest":
        set access to "limited"

define flag: Bool as true
define flag_desc: String as "off"
match flag:
    when true:
        set flag_desc to "on"

print "Code 1:", classify_code(1)
print "Code 99:", classify_code(99)
print "Access:", access
print "Flag:", flag_desc
""".strip()

    prov = HeuristicProvider()
    outcome = verify_synthesis(prov.synthesize(source))
    assert outcome.program is not None

    canon = to_canonical_meme(outcome.program)
    assert "match code:" in canon
    assert "when 1:" in canon
    assert "otherwise:" in canon
    assert "match role:" in canon
    assert 'when "admin":' in canon
    assert "match flag:" in canon

    rt_outcome = verify_synthesis(prov.synthesize(canon))
    assert rt_outcome.program is not None

    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "Code 1: one",
        "Code 99: many",
        "Access: full",
        "Flag: on",
    ]


def test_switch_match_static_verifier_rules():
    from memelang.analyzer.verifier import StaticVerificationError, verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    prov = HeuristicProvider()

    # 1. Non-scalar match target
    with pytest.raises(
        StaticVerificationError,
        match=r"`match` expression must evaluate to Int, String, or Bool, got List<Int>",
    ):
        verify_synthesis(
            prov.synthesize("define xs: List<Int> as [1, 2]\nmatch xs:\n    when 1:\n        print 1")
        )

    # 2. Non-literal case label
    with pytest.raises(
        StaticVerificationError,
        match=r"Match `when` case label must be a literal",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as 1\ndefine y: Int as 2\nmatch x:\n    when y:\n        print 1")
        )

    # 3. Label type mismatch with match expression
    with pytest.raises(
        StaticVerificationError,
        match=r"Match case label type `String` does not match expression type `Int`",
    ):
        verify_synthesis(
            prov.synthesize('define x: Int as 1\nmatch x:\n    when "one":\n        print 1')
        )

    # 4. Duplicate case label
    with pytest.raises(
        StaticVerificationError,
        match=r"Duplicate match case label `1`",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as 1\nmatch x:\n    when 1:\n        print 1\n    when 1:\n        print 2")
        )


@pytest.mark.parametrize("target", TARGETS)
def test_optional_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.ir.canonical import to_canonical_meme
    from memelang.llm.heuristic import HeuristicProvider

    source = """
function find_first_even(nums: List<Int>) -> Optional<Int>:
    for each n in nums:
        if n % 2 == 0:
            return optional n
    return nothing

define missing: Optional<Int> as find_first_even([1, 3, 5])
define found: Optional<Int> as find_first_even([1, 3, 4, 7])

if missing is nothing:
    print "missing: none"
else:
    print "missing: some"

if found is not nothing:
    print "found: some"
else:
    print "found: none"

define v1: Int as value of missing or else -1
print "v1:", v1

# Short-circuiting test: default evaluates ONLY when absent
# (100 / zero) would crash with zero division if evaluated
define zero: Int as 0
define v2: Int as value of found or else 100 / zero
print "v2:", v2

define v3: Int as value of found
print "v3:", v3
"""
    prov = HeuristicProvider()
    outcome = verify_synthesis(prov.synthesize(source))

    # Test roundtrip
    canon = to_canonical_meme(outcome.program)
    assert "return nothing" in canon
    assert "return optional n" in canon
    assert "is nothing" in canon
    assert "is not nothing" in canon
    assert "value of missing or else -1" in canon
    assert "value of found" in canon

    reparsed = verify_synthesis(prov.synthesize(canon))
    assert reparsed.program is not None

    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == [
        "missing: none",
        "found: some",
        "v1: -1",
        "v2: 4",
        "v3: 4",
    ]


@pytest.mark.parametrize("target", TARGETS)
def test_optional_strict_unwrap_fail_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    source = """
define opt: Optional<Int> as nothing
define val: Int as value of opt
print val
"""
    prov = HeuristicProvider()
    outcome = verify_synthesis(prov.synthesize(source))
    res = execute_ir(outcome.program, target)
    assert res.returncode != 0
    assert "Unwrap failed: Optional value is nothing" in res.stdout


def test_optional_static_verifier_rules():
    from memelang.analyzer.verifier import StaticVerificationError, verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    prov = HeuristicProvider()

    # 1. Non-optional assigned nothing
    with pytest.raises(
        StaticVerificationError,
        match=r"Variable `x` declared as Int but initialized with Optional<Void>",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as nothing")
        )

    # 2. Optional assigned non-wrapped value
    with pytest.raises(
        StaticVerificationError,
        match=r"Variable `x` declared as Optional<Int> but initialized with Int",
    ):
        verify_synthesis(
            prov.synthesize("define x: Optional<Int> as 42")
        )

    # 3. Nested Optional declaration rejected
    with pytest.raises(
        StaticVerificationError,
        match=r"Nested Optional types are not allowed: `Optional<Optional<Int>>`",
    ):
        verify_synthesis(
            prov.synthesize("define x: Optional<Optional<Int>> as nothing")
        )

    # 4. Nested Optional wrapping rejected
    with pytest.raises(
        StaticVerificationError,
        match=r"Cannot wrap an Optional type in another Optional: `Optional<Int>`",
    ):
        verify_synthesis(
            prov.synthesize("define x: Optional<Int> as optional (optional 42)")
        )

    # 5. return nothing in non-optional function
    with pytest.raises(
        StaticVerificationError,
        match=r"Return value has type Optional<Void>, expected Int",
    ):
        verify_synthesis(
            prov.synthesize("function f() -> Int:\n    return nothing")
        )

    # 6. Strict unwrap on non-optional
    with pytest.raises(
        StaticVerificationError,
        match=r"Strict unwrap \(`value of`\) requires an Optional operand, got `Int`",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as 10\ndefine y: Int as value of x")
        )

    # 7. Safe unwrap on non-optional
    with pytest.raises(
        StaticVerificationError,
        match=r"Safe unwrap \(`or else`\) requires an Optional operand, got `Int`",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as 10\ndefine y: Int as value of x or else 0")
        )

    # 8. Safe unwrap default type mismatch
    with pytest.raises(
        StaticVerificationError,
        match=r"`or else` default expression type `String` does not match Optional payload type `Int`",
    ):
        verify_synthesis(
            prov.synthesize('define x: Optional<Int> as optional 10\ndefine y: Int as value of x or else "dflt"')
        )

    # 9. is nothing check on non-optional
    with pytest.raises(
        StaticVerificationError,
        match=r"`is nothing` check requires an Optional operand, got `Int`",
    ):
        verify_synthesis(
            prov.synthesize("define x: Int as 10\nif x is nothing:\n    print 1")
        )


def test_go_emitted_code_is_gofmt_clean():
    import subprocess
    adv_dir = Path("examples/advanced")
    scripts = sorted(adv_dir.glob("*.meme")) + sorted(adv_dir.glob("*/main.meme"))
    assert len(scripts) >= 20, f"Expected at least 20 advanced scripts, found {len(scripts)}"

    for script in scripts:
        lock_path = script.with_suffix(".meme.lock")
        mgr = LockfileManager(lock_path)
        src = script.read_text(encoding="utf-8")
        prog = mgr.get_cached_program(str(script), src)
        assert prog is not None
        go_code = generate_code(prog, "go")
        res = subprocess.run(["gofmt", "-l"], input=go_code, capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        assert res.stdout.strip() == "", f"Emitted Go code for {script.name} is not gofmt-clean: {res.stdout.strip()}"


def test_c_emitted_code_is_gcc_wall_clean(tmp_path: Path):
    import subprocess
    adv_dir = Path("examples/advanced")
    scripts = sorted(adv_dir.glob("*.meme")) + sorted(adv_dir.glob("*/main.meme"))
    assert len(scripts) >= 21

    for script in scripts:
        lock_path = Path(str(script) + ".lock") if script.name != "main.meme" else script.parent / "main.meme.lock"
        mgr = LockfileManager(lock_path)
        src = script.read_text(encoding="utf-8")
        prog = mgr.get_cached_program(str(script), src)
        assert prog is not None, f"Failed to load cached program for {script}"
        c_code = generate_code(prog, "c")
        c_file = tmp_path / f"{script.stem}.c"
        c_file.write_text(c_code, encoding="utf-8")
        res = subprocess.run(
            ["gcc", "-std=c11", "-fsyntax-only", "-Wall", str(c_file)],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"gcc failed on {script.name}:\n{res.stderr}"
        assert res.stderr.strip() == "", f"gcc emitted warnings on {script.name}:\n{res.stderr}"


def test_ts_emitted_code_is_tsc_no_emit_clean(tmp_path: Path):
    import shutil
    import subprocess
    tsc_bin = shutil.which("tsc") or str(Path.home() / ".local" / "bin" / "tsc")
    adv_dir = Path("examples/advanced")
    scripts = sorted(adv_dir.glob("*.meme")) + sorted(adv_dir.glob("*/main.meme"))
    assert len(scripts) >= 21

    for script in scripts:
        lock_path = Path(str(script) + ".lock") if script.name != "main.meme" else script.parent / "main.meme.lock"
        mgr = LockfileManager(lock_path)
        src = script.read_text(encoding="utf-8")
        prog = mgr.get_cached_program(str(script), src)
        assert prog is not None, f"Failed to load cached program for {script}"
        ts_code = generate_code(prog, "ts")
        ts_file = tmp_path / f"{script.stem}.ts"
        ts_file.write_text(ts_code, encoding="utf-8")
        res = subprocess.run(
            [tsc_bin, "--noEmit", "--target", "es2022", "--module", "node16", str(ts_file)],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"tsc failed on {script.name}:\n{res.stdout}\n{res.stderr}"
        assert res.stdout.strip() == "", f"tsc emitted diagnostics on {script.name}:\n{res.stdout}"


ADVANCED_PARITY_SCRIPTS = [
    f.name for f in sorted(Path("examples/advanced").glob("[5][0-2][0-9]_*.meme"))
]


@pytest.mark.parametrize("script_name", ADVANCED_PARITY_SCRIPTS)
@pytest.mark.parametrize("target", TARGETS)
def test_advanced_examples_501_to_522_parity(script_name: str, target: TargetLang):
    script_path = Path("examples/advanced") / script_name
    lock_path = Path(str(script_path) + ".lock")
    assert script_path.is_file()
    assert lock_path.is_file()

    mgr = LockfileManager(lock_path)
    src = script_path.read_text(encoding="utf-8")
    prog = mgr.get_cached_program(str(script_path), src)
    assert prog is not None

    res = execute_ir(prog, target)
    assert res.returncode == 0, f"{target} failed on {script_name}:\n{res.stderr}"

    py_res = execute_ir(prog, "python")
    assert res.stdout == py_res.stdout, f"{target} parity mismatch on {script_name}"


@pytest.mark.parametrize("target", TARGETS)
def test_conversion_valid_parse_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    src = """
define s1: String as "42"
define n1: Int as integer value of s1
define s2: String as "0"
define n2: Int as integer value of s2
define s3: String as "1000000"
define n3: Int as integer value of s3
print n1, n2, n3, n1 + n2 + n3
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "42 0 1000000 1000042"


@pytest.mark.parametrize("target", TARGETS)
def test_conversion_negative_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    src = """
define s1: String as "-42"
define n1: Int as integer value of s1
define s2: String as "-1"
define n2: Int as integer value of s2
define s3: String as "-99999"
define n3: Int as integer value of s3
print n1, n2, n3, n1 + 10
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "-42 -1 -99999 -32"


@pytest.mark.parametrize("target", TARGETS)
def test_conversion_whitespace_padded_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    src = """
define s1: String as "   123   "
define n1: Int as integer value of s1
define s2: String as "   -456   "
define n2: Int as integer value of s2
print n1, n2, n1 + n2
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "123 -456 -333"


@pytest.mark.parametrize("bad_str", ["not_a_number", "12a", "12.34", ""])
@pytest.mark.parametrize("target", TARGETS)
def test_conversion_invalid_text_fail_parity(bad_str: str, target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    src = f"""
define bad: String as {repr(bad_str)}
define parsed: Int as integer value of bad
print parsed
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    res = execute_ir(outcome.program, target)
    assert res.returncode != 0
    assert f"Error parsing integer: {bad_str}" in res.stdout


@pytest.mark.parametrize("target", TARGETS)
def test_conversion_roundtrip_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    src = """
define orig_int: Int as -789
define str_val: String as text of orig_int
define back_int: Int as integer value of str_val

define orig_str: String as "12345"
define int_val: Int as integer value of orig_str
define back_str: String as text of int_val

print orig_int, str_val, back_int, orig_str, int_val, back_str
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "-789 -789 -789 12345 12345 12345"


@pytest.mark.parametrize("target", TARGETS)
def test_conversion_zero_padding_pipeline_parity(target: TargetLang):
    from memelang.analyzer.verifier import verify_synthesis
    from memelang.llm.heuristic import HeuristicProvider

    src = """
function pad_zero(num: Int, width: Int) -> String:
    define raw as text of num
    define padded as raw
    while length of string padded < width:
        set padded to "0" + padded
    return padded

define p1 as pad_zero(7, 4)
define p2 as pad_zero(42, 6)
define p3 as pad_zero(1234, 4)
define p4 as pad_zero(98765, 3)

define n1 as integer value of p1
define n2 as integer value of p2

print p1, p2, p3, p4, n1, n2
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "0007 000042 1234 98765 7 42"














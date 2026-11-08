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
    CallExpr,
    ClampCollectionStmt,
    ExitStmt,
    FailStmt,
    FileExistsExpr,
    FilterCollectionStmt,
    ForEachStmt,
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
    StringLengthExpr,
    StringSliceExpr,
    VarDeclStmt,
    VarRefExpr,
    WriteFileStmt,
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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
    scripts = sorted(adv_dir.glob("*.meme"))
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

        assert py_res.stdout == rust_res.stdout == cpp_res.stdout, (
            f"Output parity mismatch on {script.name}:\n"
            f"Python:\n{py_res.stdout}\n"
            f"Rust:\n{rust_res.stdout}\n"
            f"C++:\n{cpp_res.stdout}"
        )


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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


@pytest.mark.parametrize("target", ["python", "rust", "cpp"])
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





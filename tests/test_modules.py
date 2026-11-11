"""Tests for Memelang modules, imports (`use <mod>`), and transitive resolution."""

import hashlib
from pathlib import Path
import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    AssignStmt,
    FuncDefStmt,
    FuncParam,
    IfStmt,
    ImportStmt,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    RecordDefStmt,
    RecordFieldDef,
    RecordFieldExpr,
    RecordFieldInit,
    RecordLiteralExpr,
    ReturnStmt,
    SynthesisResult,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
)
from memelang.llm.base import LLMProviderError
from memelang.llm.heuristic import HeuristicProvider
from memelang.lockfile.manager import LockfileManager
from memelang.runner.executor import execute_ir


def test_import_schema_and_canonical_roundtrip():
    stmt = ImportStmt(module="math_utils")
    assert stmt.module == "math_utils"

    # Schema bare identifier validation
    with pytest.raises(ValueError):
        ImportStmt(module="invalid-name")
    with pytest.raises(ValueError):
        ImportStmt(module="path/to/mod")
    with pytest.raises(ValueError):
        ImportStmt(module="foo.bar")

    prog = ProgramIR(statements=[stmt])
    canonical = to_canonical_meme(prog)
    assert canonical.strip() == "use math_utils"

    # Heuristic parsing
    syn = HeuristicProvider().synthesize("use math_utils")
    assert len(syn.items) == 1
    assert isinstance(syn.items[0], ImportStmt)
    assert syn.items[0].module == "math_utils"

    # Invalid module names in heuristic
    with pytest.raises(LLMProviderError, match="Invalid module name"):
        HeuristicProvider().synthesize("use 'quoted_module'")
    with pytest.raises(LLMProviderError, match="Invalid module name"):
        HeuristicProvider().synthesize("use foo.bar")
    with pytest.raises(LLMProviderError, match="Invalid module name"):
        HeuristicProvider().synthesize("use path/to/mod")


def test_use_only_at_top_level():
    # Inside if statement
    bad_if = ProgramIR(
        statements=[
            IfStmt(
                condition=LiteralExpr(value=True, data_type="Bool"),
                then_body=[ImportStmt(module="math_utils")],
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="`use` statement is only allowed at the top level"):
        verify_program(bad_if)

    # Inside while loop
    bad_while = ProgramIR(
        statements=[
            WhileStmt(
                condition=LiteralExpr(value=True, data_type="Bool"),
                body=[ImportStmt(module="math_utils")],
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="`use` statement is only allowed at the top level"):
        verify_program(bad_while)

    # Inside function body
    bad_fn = ProgramIR(
        statements=[
            FuncDefStmt(
                name="my_func",
                params=[],
                return_type="Void",
                body=[ImportStmt(module="math_utils")],
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="`use` statement is only allowed at the top level"):
        verify_program(bad_fn)


def test_module_resolution_relative_to_importing_file(tmp_path: Path):
    math_path = tmp_path / "math_utils.meme"
    math_path.write_text(
        "function add(a: Int, b: Int) -> Int:\n    return a + b\n",
        encoding="utf-8",
    )
    main_path = tmp_path / "main.meme"
    main_path.write_text(
        "use math_utils\ndefine x as add(10, 20)\nprint x\n",
        encoding="utf-8",
    )

    syn = HeuristicProvider().synthesize(main_path.read_text(encoding="utf-8"), source_path=main_path)
    outcome = verify_synthesis(syn, source_path=main_path)
    assert outcome.is_unambiguous is True
    assert outcome.program is not None

    prog = outcome.program
    assert len(prog.imported_definitions) == 1
    assert isinstance(prog.imported_definitions[0], FuncDefStmt)
    assert prog.imported_definitions[0].name == "add"
    assert "math_utils.meme" in prog.module_files
    expected_hash = hashlib.sha256(math_path.read_text(encoding="utf-8").strip().encode("utf-8")).hexdigest()
    assert prog.module_files["math_utils.meme"] == expected_hash


def test_missing_module_error(tmp_path: Path):
    main_path = tmp_path / "main.meme"
    main_path.write_text("use nonexistent_mod\nprint 1\n", encoding="utf-8")

    syn = HeuristicProvider().synthesize(main_path.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match=r"Module file not found: .*nonexistent_mod\.meme"):
        verify_synthesis(syn, source_path=main_path)


def test_circular_import_detection(tmp_path: Path):
    # Direct self-cycle: A -> A
    a_path = tmp_path / "a_mod.meme"
    a_path.write_text("use a_mod\nfunction f() -> Void:\n    return\n", encoding="utf-8")
    main_path = tmp_path / "main.meme"
    main_path.write_text("use a_mod\nprint 1\n", encoding="utf-8")
    syn = HeuristicProvider().synthesize(main_path.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match=r"Circular import detected: .*a_mod -> a_mod"):
        verify_synthesis(syn, source_path=main_path)

    # 2-cycle: A -> B -> A
    mod_a = tmp_path / "mod_a.meme"
    mod_b = tmp_path / "mod_b.meme"
    mod_a.write_text("use mod_b\nfunction f_a() -> Void:\n    return\n", encoding="utf-8")
    mod_b.write_text("use mod_a\nfunction f_b() -> Void:\n    return\n", encoding="utf-8")
    main2 = tmp_path / "main2.meme"
    main2.write_text("use mod_a\nprint 1\n", encoding="utf-8")
    syn2 = HeuristicProvider().synthesize(main2.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match=r"Circular import detected: .*mod_a -> mod_b -> mod_a"):
        verify_synthesis(syn2, source_path=main2)

    # 3-cycle: A -> B -> C -> A
    c1 = tmp_path / "cycle1.meme"
    c2 = tmp_path / "cycle2.meme"
    c3 = tmp_path / "cycle3.meme"
    c1.write_text("use cycle2\nfunction c1_fn() -> Void:\n    return\n", encoding="utf-8")
    c2.write_text("use cycle3\nfunction c2_fn() -> Void:\n    return\n", encoding="utf-8")
    c3.write_text("use cycle1\nfunction c3_fn() -> Void:\n    return\n", encoding="utf-8")
    main3 = tmp_path / "main3.meme"
    main3.write_text("use cycle1\nprint 1\n", encoding="utf-8")
    syn3 = HeuristicProvider().synthesize(main3.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match=r"Circular import detected: .*cycle1 -> cycle2 -> cycle3 -> cycle1"):
        verify_synthesis(syn3, source_path=main3)


def test_diamond_transitive_imports_and_topological_order(tmp_path: Path):
    # A defines Point & make_point
    mod_a = tmp_path / "geom_base.meme"
    mod_a.write_text(
        "record Point:\n    x: Int\n    y: Int\n\nfunction make_point(x: Int, y: Int) -> Point:\n    return Point(x=x, y=y)\n",
        encoding="utf-8",
    )
    # B imports A, defines get_x
    mod_b = tmp_path / "geom_x.meme"
    mod_b.write_text(
        "use geom_base\nfunction get_x(p: Point) -> Int:\n    return p.x\n",
        encoding="utf-8",
    )
    # C imports A, defines get_y
    mod_c = tmp_path / "geom_y.meme"
    mod_c.write_text(
        "use geom_base\nfunction get_y(p: Point) -> Int:\n    return p.y\n",
        encoding="utf-8",
    )
    # main imports A, B, C (diamond)
    main = tmp_path / "main.meme"
    main.write_text(
        "use geom_base\nuse geom_x\nuse geom_y\ndefine pt as make_point(3, 4)\nprint get_x(pt), get_y(pt)\n",
        encoding="utf-8",
    )

    syn = HeuristicProvider().synthesize(main.read_text(encoding="utf-8"), source_path=main)
    outcome = verify_synthesis(syn, source_path=main)
    assert outcome.is_unambiguous is True
    assert outcome.program is not None

    prog = outcome.program
    # Definitions in topological order: geom_base first (Point, make_point), then geom_x (get_x), geom_y (get_y)
    def_names = [getattr(d, "name") for d in prog.imported_definitions]
    assert def_names == ["Point", "make_point", "get_x", "get_y"]
    assert "geom_base.meme" in prog.module_files
    assert "geom_x.meme" in prog.module_files
    assert "geom_y.meme" in prog.module_files


def test_no_re_export_rule(tmp_path: Path):
    mod_a = tmp_path / "mod_a.meme"
    mod_a.write_text("function secret() -> Int:\n    return 42\n", encoding="utf-8")

    mod_b = tmp_path / "mod_b.meme"
    mod_b.write_text("use mod_a\nfunction call_secret() -> Int:\n    return secret()\n", encoding="utf-8")

    # main imports B only, tries to call secret() directly -> should FAIL
    main = tmp_path / "main.meme"
    main.write_text("use mod_b\ndefine s: Int as secret()\nprint s\n", encoding="utf-8")

    syn = HeuristicProvider().synthesize(main.read_text(encoding="utf-8"), source_path=main)
    with pytest.raises(StaticVerificationError, match="Call to undeclared function `secret`"):
        verify_synthesis(syn, source_path=main)

    # When main also uses mod_a directly, it succeeds
    main_ok = tmp_path / "main_ok.meme"
    main_ok.write_text("use mod_a\nuse mod_b\ndefine s: Int as secret()\nprint s\n", encoding="utf-8")
    syn_ok = HeuristicProvider().synthesize(main_ok.read_text(encoding="utf-8"), source_path=main_ok)
    outcome = verify_synthesis(syn_ok, source_path=main_ok)
    assert outcome.is_unambiguous is True


def test_collision_errors(tmp_path: Path):
    # 1. Local function vs imported function
    mod = tmp_path / "util.meme"
    mod.write_text("function calc(n: Int) -> Int:\n    return n * 2\n", encoding="utf-8")

    main1 = tmp_path / "main1.meme"
    main1.write_text(
        "use util\nfunction calc(n: Int) -> Int:\n    return n + 1\nprint calc(5)\n",
        encoding="utf-8",
    )
    syn1 = HeuristicProvider().synthesize(main1.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match="Collision: imported `calc` from module `util` collides with local definition"):
        verify_synthesis(syn1, source_path=main1)

    # 2. Imported function vs imported function from different modules
    mod1 = tmp_path / "m1.meme"
    mod2 = tmp_path / "m2.meme"
    mod1.write_text("function duplicate_name() -> Int:\n    return 1\n", encoding="utf-8")
    mod2.write_text("function duplicate_name() -> Int:\n    return 2\n", encoding="utf-8")

    main2 = tmp_path / "main2.meme"
    main2.write_text("use m1\nuse m2\nprint 1\n", encoding="utf-8")
    syn2 = HeuristicProvider().synthesize(main2.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match="Collision: `duplicate_name` is defined in both module `m2` and module `m1`"):
        verify_synthesis(syn2, source_path=main2)

    # 3. Transitive module collision (two dependencies collide in global namespace)
    sub1 = tmp_path / "sub1.meme"
    sub2 = tmp_path / "sub2.meme"
    sub1.write_text("function global_helper() -> Int:\n    return 1\n", encoding="utf-8")
    sub2.write_text("function global_helper() -> Int:\n    return 2\n", encoding="utf-8")

    parent1 = tmp_path / "parent1.meme"
    parent2 = tmp_path / "parent2.meme"
    parent1.write_text("use sub1\nfunction p1() -> Int:\n    return global_helper()\n", encoding="utf-8")
    parent2.write_text("use sub2\nfunction p2() -> Int:\n    return global_helper()\n", encoding="utf-8")

    main3 = tmp_path / "main3.meme"
    main3.write_text("use parent1\nuse parent2\nprint p1() + p2()\n", encoding="utf-8")
    syn3 = HeuristicProvider().synthesize(main3.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match="Collision: `global_helper` is defined in both module `sub2` and module `sub1`"):
        verify_synthesis(syn3, source_path=main3)

    # 4. Local variable collides with imported definition
    main4 = tmp_path / "main4.meme"
    main4.write_text("use util\ndefine calc as 100\nprint calc\n", encoding="utf-8")
    syn4 = HeuristicProvider().synthesize(main4.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match="Collision: local variable `calc` collides with imported definition from module `util`"):
        verify_synthesis(syn4, source_path=main4)


def test_invalid_module_contents(tmp_path: Path):
    bad_mod = tmp_path / "bad_mod.meme"
    bad_mod.write_text("print 100\n", encoding="utf-8")

    main = tmp_path / "main.meme"
    main.write_text("use bad_mod\nprint 1\n", encoding="utf-8")

    syn = HeuristicProvider().synthesize(main.read_text(encoding="utf-8"))
    with pytest.raises(StaticVerificationError, match=r"Module `bad_mod` may only contain functions, records, and `use` statements, found `print_stmt`"):
        verify_synthesis(syn, source_path=main)


def test_module_transitive_lockfile_hashing_and_invalidation(tmp_path: Path):
    math_mod = tmp_path / "math_mod.meme"
    math_mod.write_text("function mult(a: Int, b: Int) -> Int:\n    return a * b\n", encoding="utf-8")

    geom_mod = tmp_path / "geom_mod.meme"
    geom_mod.write_text(
        "use math_mod\nfunction area(w: Int, h: Int) -> Int:\n    return mult(w, h)\n",
        encoding="utf-8",
    )

    main = tmp_path / "main.meme"
    main_text = "use geom_mod\ndefine a: Int as area(4, 5)\nprint a\n"
    main.write_text(main_text, encoding="utf-8")

    lock_file = tmp_path / "main.meme.lock"
    mgr = LockfileManager(lock_file)

    syn = HeuristicProvider().synthesize(main_text, source_path=main)
    outcome = verify_synthesis(syn, source_path=main)
    assert outcome.is_unambiguous is True
    assert outcome.program is not None

    mgr.record_outcome(
        source_key="main.meme",
        source_text=main_text,
        provider_name="heuristic",
        synthesis=syn,
        outcome=outcome,
    )

    # Cache hit when files unchanged
    cached = mgr.get_cached_program("main.meme", main_text)
    assert cached is not None
    assert mgr.has_matching_draft("main.meme", main_text) is True

    # Mutate deep transitive module `math_mod.meme` -> lock must be invalidated
    orig_math = math_mod.read_text(encoding="utf-8")
    math_mod.write_text("function mult(a: Int, b: Int) -> Int:\n    return a * b + 1\n", encoding="utf-8")
    assert mgr.get_cached_program("main.meme", main_text) is None
    assert mgr.has_matching_draft("main.meme", main_text) is False

    # Restore math_mod -> cache hit works again
    math_mod.write_text(orig_math, encoding="utf-8")
    assert mgr.get_cached_program("main.meme", main_text) is not None
    assert mgr.has_matching_draft("main.meme", main_text) is True

    # Mutate direct module `geom_mod.meme` -> lock must be invalidated
    orig_geom = geom_mod.read_text(encoding="utf-8")
    geom_mod.write_text("use math_mod\nfunction area(w: Int, h: Int) -> Int:\n    return mult(w, h) * 2\n", encoding="utf-8")
    assert mgr.get_cached_program("main.meme", main_text) is None
    assert mgr.has_matching_draft("main.meme", main_text) is False

    # Restore geom_mod -> cache hit works again
    geom_mod.write_text(orig_geom, encoding="utf-8")
    assert mgr.get_cached_program("main.meme", main_text) is not None

    # Delete math_mod.meme -> lock must be invalidated
    math_mod.unlink()
    assert mgr.get_cached_program("main.meme", main_text) is None
    assert mgr.has_matching_draft("main.meme", main_text) is False


def test_multi_file_parity_fixture_521():
    main_meme = Path("examples/advanced/521_modules/main.meme")
    lock_path = Path("examples/advanced/521_modules/main.meme.lock")
    assert main_meme.is_file()
    assert lock_path.is_file()

    mgr = LockfileManager(lock_path)
    src = main_meme.read_text(encoding="utf-8")
    prog = mgr.get_cached_program(str(main_meme), src)
    assert prog is not None, "Failed to load cached program from 521_modules lock"

    py_res = execute_ir(prog, "python")
    assert py_res.returncode == 0, f"Python failed: {py_res.stderr}"

    rust_res = execute_ir(prog, "rust")
    assert rust_res.returncode == 0, f"Rust failed: {rust_res.stderr}"

    cpp_res = execute_ir(prog, "cpp")
    assert cpp_res.returncode == 0, f"C++ failed: {cpp_res.stderr}"

    go_res = execute_ir(prog, "go")
    assert go_res.returncode == 0, f"Go failed: {go_res.stderr}"

    c_res = execute_ir(prog, "c")
    assert c_res.returncode == 0, f"C failed: {c_res.stderr}"

    ts_res = execute_ir(prog, "ts")
    assert ts_res.returncode == 0, f"TypeScript failed: {ts_res.stderr}"

    assert py_res.stdout == rust_res.stdout == cpp_res.stdout == go_res.stdout == c_res.stdout == ts_res.stdout == "25\n7\n169\n17\n"


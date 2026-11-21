from __future__ import annotations

from pathlib import Path
import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import TargetLang
from memelang.llm.heuristic import HeuristicProvider
from memelang.lockfile.manager import LockfileManager
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_recursive_record_through_list_parity(target: TargetLang) -> None:
    src = """
record Node:
    val: Int
    children: List<Node>

function count_nodes(n: Node) -> Int:
    define total: Int as 1
    for each child in n.children:
        set total to total + count_nodes(child)
    return total

define empty_nodes: List<Node> as empty List<Node>
define c1: Node as Node(val=2, children=empty_nodes)
define c2: Node as Node(val=3, children=empty_nodes)
define root: Node as Node(val=1, children=[c1, c2])

print "Total nodes:", count_nodes(root)
print "Root val:", root.val
print "Child 0 val:", root.children[0].val
print "Child 1 val:", root.children[1].val
print "Eq self:", root == root
print "Eq other:", root == c1
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"{target} failed: {res.stderr}"
    expected = (
        "Total nodes: 3\n"
        "Root val: 1\n"
        "Child 0 val: 2\n"
        "Child 1 val: 3\n"
        "Eq self: true\n"
        "Eq other: false\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


@pytest.mark.parametrize("target", TARGETS)
def test_optional_collections_parity(target: TargetLang) -> None:
    src = """
function get_scores(found: Bool) -> Optional<List<Int>>:
    if found:
        return optional [95, 87, 92]
    return nothing

function get_config(found: Bool) -> Optional<Map<String, Int>>:
    if found:
        define cfg: Map<String, Int> as {"a": 1, "b": 2}
        return optional cfg
    return nothing

define opt_scores_none: Optional<List<Int>> as get_scores(false)
define opt_scores_some: Optional<List<Int>> as get_scores(true)
define opt_cfg_none: Optional<Map<String, Int>> as get_config(false)
define opt_cfg_some: Optional<Map<String, Int>> as get_config(true)

print "Scores None:", opt_scores_none is nothing
print "Scores Some:", value of opt_scores_some
print "Scores Eq self:", opt_scores_some == opt_scores_some
print "Scores Eq none:", opt_scores_none == opt_scores_some
print "Config None:", opt_cfg_none is nothing
print "Config Some:", value of opt_cfg_some
print "Config Eq self:", opt_cfg_some == opt_cfg_some
print "Config Eq none:", opt_cfg_none == opt_cfg_some
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"{target} failed: {res.stderr}"
    expected = (
        "Scores None: true\n"
        "Scores Some: [95, 87, 92]\n"
        "Scores Eq self: true\n"
        "Scores Eq none: false\n"
        "Config None: true\n"
        "Config Some: {a: 1, b: 2}\n"
        "Config Eq self: true\n"
        "Config Eq none: false\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


@pytest.mark.parametrize("target", TARGETS)
def test_collection_value_semantics_parity(target: TargetLang) -> None:
    src = """
function modify_set(s: Set<Int>) -> Void:
    add 99 to s

function modify_list(l: List<Int>) -> Void:
    append 99 to l

function modify_map(m: Map<String, Int>) -> Void:
    set m["z"] to 99

define my_set: Set<Int> as empty set of Int
add 1 to my_set
add 2 to my_set
call modify_set(my_set)
assert not (my_set contains 99)
print "Set preserved:", length of my_set

define list my_list as [1, 2]
call modify_list(my_list)
assert length of my_list == 2
print "List preserved:", length of my_list

define my_map: Map<String, Int> as {"a": 1}
call modify_map(my_map)
assert not (my_map has key "z")
print "Map preserved:", my_map has key "a"
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"{target} failed: {res.stderr}"
    expected = (
        "Set preserved: 2\n"
        "List preserved: 2\n"
        "Map preserved: true\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


@pytest.mark.parametrize("target", TARGETS)
def test_parent_relative_import_parity(target: TargetLang, tmp_path: Path) -> None:
    lib_file = tmp_path / "lib.meme"
    lib_file.write_text("function helper_add(a: Int, b: Int) -> Int:\n    return a + b\n")

    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    prog_file = sub_dir / "test_prog.meme"
    prog_file.write_text("use ../lib\n\ndefine ans: Int as helper_add(40, 2)\nprint \"Result:\", ans\n")

    hp = HeuristicProvider()
    syn = hp.synthesize(prog_file.read_text(), source_path=prog_file)
    outcome = verify_synthesis(syn, source_path=prog_file)
    assert outcome.program is not None, outcome.diagnostics
    assert len(outcome.program.imported_definitions) > 0

    lock_file = sub_dir / "test_prog.meme.lock"
    mgr = LockfileManager(lock_file)
    entry_key = "test_prog.meme"
    mgr.record_outcome(entry_key, prog_file.read_text(), "heuristic", syn, outcome)

    cached = mgr.get_cached_program(entry_key, prog_file.read_text())
    assert cached is not None

    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"{target} failed: {res.stderr}"
    assert res.stdout.strip() == "Result: 42"

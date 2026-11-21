from __future__ import annotations

import pytest

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    CallExpr,
    EmptySetExpr,
    ListLiteralExpr,
    MapLiteralExpr,
    RecordLiteralExpr,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


def test_nested_empty_collections_in_record_literal() -> None:
    src = """
record Node:
    value: Int
    children: List<Node>
    tags: Set<String>
    metadata: Map<String, Int>

define root as Node(value=1, children=empty List<Node>, tags=empty Set<String>, metadata=empty Map<String, Int>)
print root.value
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    stmt = outcome.program.statements[1]
    assert hasattr(stmt, "value") and isinstance(stmt.value, RecordLiteralExpr)
    fields = {f.name: f.value for f in stmt.value.fields}
    assert isinstance(fields["children"], ListLiteralExpr)
    assert fields["children"].elements == []
    assert fields["children"].element_type == "Node"
    assert isinstance(fields["tags"], EmptySetExpr)
    assert fields["tags"].element_type == "String"
    assert isinstance(fields["metadata"], MapLiteralExpr)
    assert fields["metadata"].entries == []
    assert fields["metadata"].key_type == "String"
    assert fields["metadata"].value_type == "Int"


def test_nested_empty_collections_in_call_args() -> None:
    src = """
function helper(a: List<Int>, b: Set<String>, c: Map<Int, String>) -> Int:
    return 42

define res: Int as helper(empty List<Int>, empty Set<String>, empty Map<Int, String>)
print res
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    stmt = outcome.program.statements[1]
    assert hasattr(stmt, "value") and isinstance(stmt.value, CallExpr)
    args = stmt.value.args
    assert isinstance(args[0], ListLiteralExpr) and args[0].elements == []
    assert isinstance(args[1], EmptySetExpr) and args[1].element_type == "String"
    assert isinstance(args[2], MapLiteralExpr) and args[2].entries == []


def test_nested_empty_collections_in_list_literal() -> None:
    src = """
define nested_lists as [empty List<Int>]
define nested_sets as [empty Set<String>]
define nested_maps as [empty Map<String, Int>]
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    s0 = outcome.program.statements[0]
    assert isinstance(s0.value, ListLiteralExpr)
    assert isinstance(s0.value.elements[0], ListLiteralExpr)
    assert s0.value.element_type == "List<Int>"

    s1 = outcome.program.statements[1]
    assert isinstance(s1.value, ListLiteralExpr)
    assert isinstance(s1.value.elements[0], EmptySetExpr)
    assert s1.value.element_type == "Set<String>"

    s2 = outcome.program.statements[2]
    assert isinstance(s2.value, ListLiteralExpr)
    assert isinstance(s2.value.elements[0], MapLiteralExpr)
    assert s2.value.element_type == "Map<String, Int>"


def test_nested_empty_collections_in_comparison_and_complex_types() -> None:
    src = """
record Node:
    value: Int
    children: List<Node>

define root as Node(value=1, children=empty List<Node>)
define is_empty: Bool as root.children == empty List<Node>
define complex_map: Map<String, List<Int>> as empty Map<String, List<Int>>
define nested_lists: List<List<Int>> as empty List<List<Int>>
print is_empty
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics


def test_empty_set_of_in_call_and_record() -> None:
    src = """
record Tagged:
    name: String
    tags: Set<String>

function check_tags(t: Set<String>) -> Bool:
    return t == empty set of String

define item as Tagged(name="test", tags=empty set of String)
define is_empty as check_tags(empty set of String)
print is_empty
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics



def test_canonical_roundtrip_nested_empty_collections() -> None:
    src = """record Node:
    value: Int
    children: List<Node>
    tags: Set<String>
    metadata: Map<String, Int>

define root: Node as Node(value=1, children=empty List<Node>, tags=empty set of String, metadata=empty Map<String, Int>)
print root.value"""
    parsed = HeuristicProvider().synthesize(src)
    outcome = verify_synthesis(parsed)
    assert outcome.program is not None, outcome.diagnostics
    canonical = to_canonical_meme(outcome.program)
    roundtrip_syn = HeuristicProvider().synthesize(canonical)
    roundtrip_out = verify_synthesis(roundtrip_syn)
    assert roundtrip_out.is_unambiguous and roundtrip_out.program is not None
    assert to_canonical_meme(roundtrip_out.program) == canonical


@pytest.mark.parametrize("target", TARGETS)
def test_phase6e_repro_program_parity(target: TargetLang) -> None:
    src = """
record Node:
    value: Int
    children: List<Node>
define root as Node(value=1, children=empty List<Node>)
print root.value
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"{target} failed: {res.stderr}"
    assert res.stdout.replace("\r\n", "\n") == "1\n"


@pytest.mark.parametrize("target", TARGETS)
def test_phase6e_tree_building_parity(target: TargetLang) -> None:
    src = """
record TreeNode:
    id: Int
    name: String
    children: List<TreeNode>

function make_leaf(id: Int, name: String) -> TreeNode:
    return TreeNode(id=id, name=name, children=empty List<TreeNode>)

function count_tree(node: TreeNode) -> Int:
    define cnt: Int as 1
    for each child in node.children:
        set cnt to cnt + count_tree(child)
    return cnt

define leaf1: TreeNode as make_leaf(2, "leaf1")
define leaf2: TreeNode as TreeNode(id=3, name="leaf2", children=empty List<TreeNode>)
define root: TreeNode as TreeNode(id=1, name="root", children=[leaf1, leaf2])

print "Tree count:", count_tree(root)
print "Leaf 1:", leaf1.name
print "Leaf 2:", leaf2.name
print "Root children:", length of root.children
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None, outcome.diagnostics
    res = execute_ir(outcome.program, target)
    assert res.returncode == 0, f"{target} failed: {res.stderr}"
    expected = (
        "Tree count: 3\n"
        "Leaf 1: leaf1\n"
        "Leaf 2: leaf2\n"
        "Root children: 2\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected

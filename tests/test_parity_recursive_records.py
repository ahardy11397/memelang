from __future__ import annotations

import pytest

from memelang.codegen import TARGET_LANGS, TargetLang
from conftest import run_parity

RECURSIVE_RECORDS_PROGRAM = """
record Node:
    name: String
    parent: Optional<Node>
    children: List<Node>

function count_nodes(n: Node) -> Int:
    define count: Int as 1
    for each child in n.children:
        set count to count + count_nodes(child)
    return count

function root_name(n: Node) -> String:
    if n.parent is nothing:
        return n.name
    define p: Node as value of n.parent
    return root_name(p)

define list empty_children as empty List<Node>
define root: Node as Node(name="root", parent=nothing, children=empty_children)
define child_a: Node as Node(name="child_a", parent=optional root, children=empty_children)
define child_b: Node as Node(name="child_b", parent=optional root, children=empty_children)
define list root_kids as [child_a, child_b]
define tree: Node as Node(name="root", parent=nothing, children=root_kids)

print "count:", count_nodes(tree)
print "child_a parent is not nothing:", child_a.parent is not nothing
print "root parent is nothing:", tree.parent is nothing
print "child_a root name:", root_name(child_a)
print "child_b root name:", root_name(child_b)

define fallback_node: Node as Node(name="fallback", parent=nothing, children=empty_children)
define p_val: Node as value of tree.parent or else fallback_node
print "p_val name:", p_val.name

define child_a_dup: Node as Node(name="child_a", parent=optional root, children=empty_children)
print "child_a == child_b:", child_a == child_b
print "child_a == child_a_dup:", child_a == child_a_dup
"""


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_recursive_records_cross_target_parity(target: TargetLang):
    res = run_parity(RECURSIVE_RECORDS_PROGRAM, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "count: 3\n"
        "child_a parent is not nothing: true\n"
        "root parent is nothing: true\n"
        "child_a root name: root\n"
        "child_b root name: root\n"
        "p_val name: fallback\n"
        "child_a == child_b: false\n"
        "child_a == child_a_dup: true\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_locked_538_recursive_optional_parity(target: TargetLang):
    from pathlib import Path
    from memelang.lockfile.manager import LockfileManager
    from memelang.runner.executor import execute_ir

    meme_path = Path("examples/advanced/538_recursive_optional.meme")
    lock_path = Path("examples/advanced/538_recursive_optional.meme.lock")
    src = meme_path.read_text(encoding="utf-8")
    mgr = LockfileManager(lock_path)
    prog = mgr.get_cached_program(str(meme_path), src)
    assert prog is not None
    res = execute_ir(prog, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "count: 3\n"
        "child_a parent is not nothing: true\n"
        "root parent is nothing: true\n"
        "child_a root name: root\n"
        "child_b root name: root\n"
        "p_val name: fallback\n"
        "child_a == child_b: false\n"
        "child_a == child_a_dup: true\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected

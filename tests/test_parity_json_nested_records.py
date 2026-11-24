from __future__ import annotations

import pytest

from memelang.codegen import TARGET_LANGS, TargetLang
from conftest import run_parity

ORDER_PROGRAM = """
record Customer:
    id: Int
    name: String

record Item:
    name: String
    qty: Int

record Order:
    order_id: String
    customer: Customer
    items: List<Item>
    discount_code: Optional<String>
    manager: Optional<Customer>
    item_lookup: Map<String, Item>

define c1 as Customer(id=101, name="Alice")
define i1 as Item(name="Widget", qty=2)
define i2 as Item(name="Gadget", qty=5)
define items_list as [i1, i2]

define item_map as empty Map<String, Item>
set item_map["W1"] to i1
set item_map["G2"] to i2

define ord as Order(order_id="ORD-99", customer=c1, items=items_list, discount_code=optional "SAVE10", manager=nothing, item_lookup=item_map)

write ord as json to file "tmp_order.json"

define fallback_cust as Customer(id=0, name="Nobody")
define empty_items as empty List<Item>
define empty_lookup as empty Map<String, Item>
define fallback_ord as Order(order_id="NONE", customer=fallback_cust, items=empty_items, discount_code=nothing, manager=nothing, item_lookup=empty_lookup)

define ord_opt as read json record Order from file "tmp_order.json" or else nothing
if ord_opt is nothing:
    print "order: nothing"
else:
    define read_ord as value of ord_opt
    print "order_id:", read_ord.order_id
    print "cust name:", read_ord.customer.name
    print "cust id:", read_ord.customer.id
    print "items len:", length of read_ord.items
    for each item in read_ord.items:
        print "item:", item.name, item.qty
    if read_ord.discount_code is not nothing:
        print "discount:", value of read_ord.discount_code
    else:
        print "no discount"
    if read_ord.manager is not nothing:
        define mgr as value of read_ord.manager
        print "manager:", mgr.name
    else:
        print "no manager"
    define w1 as read_ord.item_lookup["W1"]
    print "lookup W1:", w1.name, w1.qty

define bad_ord as read json record Order from file "nonexistent_file.json" or else fallback_ord
print "bad order_id:", bad_ord.order_id
print "bad cust:", bad_ord.customer.name

delete file "tmp_order.json"
"""


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_json_nested_records_cross_target_parity(target: TargetLang):
    res = run_parity(ORDER_PROGRAM, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "order_id: ORD-99\n"
        "cust name: Alice\n"
        "cust id: 101\n"
        "items len: 2\n"
        "item: Widget 2\n"
        "item: Gadget 5\n"
        "discount: SAVE10\n"
        "no manager\n"
        "lookup W1: Widget 2\n"
        "bad order_id: NONE\n"
        "bad cust: Nobody\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


RECURSIVE_NODE_PROGRAM = """
record Node:
    name: String
    parent: Optional<Node>
    children: List<Node>

define empty_nodes as empty List<Node>
define p as Node(name="parent_p", parent=nothing, children=empty_nodes)
define c1 as Node(name="child1", parent=optional p, children=empty_nodes)
define c2 as Node(name="child2", parent=nothing, children=empty_nodes)
define root_children as [c1, c2]
define root as Node(name="root", parent=nothing, children=root_children)

write root as json to file "tmp_node.json"

define fallback_node as Node(name="fallback", parent=nothing, children=empty_nodes)
define node_opt as read json record Node from file "tmp_node.json" or else nothing

if node_opt is nothing:
    print "node: nothing"
else:
    define read_root as value of node_opt
    print "root:", read_root.name
    print "children len:", length of read_root.children
    for each child in read_root.children:
        print "child:", child.name
        if child.parent is not nothing:
            define parent_of_child as value of child.parent
            print "parent:", parent_of_child.name
        else:
            print "no parent"

define bad_node as read json record Node from file "nonexistent_node.json" or else fallback_node
print "bad node:", bad_node.name

delete file "tmp_node.json"
"""


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_json_recursive_node_cross_target_parity(target: TargetLang):
    res = run_parity(RECURSIVE_NODE_PROGRAM, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "root: root\n"
        "children len: 2\n"
        "child: child1\n"
        "parent: parent_p\n"
        "child: child2\n"
        "no parent\n"
        "bad node: fallback\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected

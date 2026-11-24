from __future__ import annotations

import pytest

from memelang.codegen import TARGET_LANGS, TargetLang
from conftest import run_parity

JSON_COLLECTIONS_PROGRAM = """
record Bundle:
    name: String
    scores: List<Int>
    tags: Set<String>
    str_map: Map<String, Int>
    int_map: Map<Int, String>
    notes: Optional<List<String>>

define list s1 as [10, 20, 30]
define t1 as empty set of String
add "beta" to set t1
add "alpha" to set t1
add "gamma" to set t1

define sm1: Map<String, Int> as empty Map<String, Int>
set sm1["k2"] to 200
set sm1["k1"] to 100

define im1: Map<Int, String> as empty Map<Int, String>
set im1[42] to "forty-two"
set im1[7] to "seven"

define list n1 as ["urgent", "review"]
define b1: Bundle as Bundle(name="primary", scores=s1, tags=t1, str_map=sm1, int_map=im1, notes=optional n1)

write b1 as json to file "tmp_bundle_1.json"

define b1_opt as read json record Bundle from file "tmp_bundle_1.json" or else nothing
if b1_opt is nothing:
    print "b1: nothing"
else:
    define b: Bundle as value of b1_opt
    print "b1 name:", b.name
    print "b1 scores len:", length of b.scores
    for each sc in b.scores:
        print "score:", sc
    for each tg in b.tags:
        print "tag:", tg
    print "sm1 k1:", b.str_map["k1"]
    print "sm1 k2:", b.str_map["k2"]
    print "im1 7:", b.int_map[7]
    print "im1 42:", b.int_map[42]
    if b.notes is not nothing:
        define n_list: List<String> as value of b.notes
        for each nt in n_list:
            print "note:", nt

define list empty_scores as empty List<Int>
define empty_tags as empty set of String
define empty_sm: Map<String, Int> as empty Map<String, Int>
define empty_im: Map<Int, String> as empty Map<Int, String>
define b_empty: Bundle as Bundle(name="empty", scores=empty_scores, tags=empty_tags, str_map=empty_sm, int_map=empty_im, notes=nothing)

write b_empty as json to file "tmp_bundle_empty.json"

define be_opt as read json record Bundle from file "tmp_bundle_empty.json" or else nothing
if be_opt is nothing:
    print "be: nothing"
else:
    define be: Bundle as value of be_opt
    print "be name:", be.name
    print "be scores len:", length of be.scores
    print "be tags len:", length of set be.tags
    print "be notes is nothing:", be.notes is nothing

write file "tmp_bundle_bad.json" with "{\\"name\\": \\"bad\\", \\"scores\\": [1, \\"not_an_int\\"], \\"tags\\": [], \\"str_map\\": {}, \\"int_map\\": {}}"
define bad_opt as read json record Bundle from file "tmp_bundle_bad.json" or else nothing
if bad_opt is nothing:
    print "bad scores: returned nothing"

delete file "tmp_bundle_1.json"
delete file "tmp_bundle_empty.json"
delete file "tmp_bundle_bad.json"
"""


@pytest.mark.parametrize("target", list(TARGET_LANGS))
def test_json_collections_cross_target_parity(target: TargetLang):
    res = run_parity(JSON_COLLECTIONS_PROGRAM, target)
    assert res.returncode == 0, res.stderr
    expected = (
        "b1 name: primary\n"
        "b1 scores len: 3\n"
        "score: 10\n"
        "score: 20\n"
        "score: 30\n"
        "tag: alpha\n"
        "tag: beta\n"
        "tag: gamma\n"
        "sm1 k1: 100\n"
        "sm1 k2: 200\n"
        "im1 7: seven\n"
        "im1 42: forty-two\n"
        "note: urgent\n"
        "note: review\n"
        "be name: empty\n"
        "be scores len: 0\n"
        "be tags len: 0\n"
        "be notes is nothing: true\n"
        "bad scores: returned nothing\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected

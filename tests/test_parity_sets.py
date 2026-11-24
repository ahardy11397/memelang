"""Cross-target parity test for first-class Set<T>."""

import pytest
from memelang.analyzer.verifier import StaticVerificationError, verify_synthesis
from memelang.ir.canonical import to_canonical_meme
from memelang.llm.heuristic import HeuristicProvider


SET_PARITY_SRC = """
define s as empty set of String
add "banana" to set s
add "apple" to set s
add "cherry" to set s
add "apple" to set s
add "date" to set s
add "banana" to set s
add "elderberry" to set s

print "s length:", length of set s
if s contains "cherry":
    print "has cherry: true"
else:
    print "has cherry: false"

remove "cherry" from set s

if s contains "cherry":
    print "has cherry after remove: true"
else:
    print "has cherry after remove: false"

print "s length after remove:", length of set s

for each item in s:
    print "fruit:", item

define nums as empty set of Int
add 42 to set nums
add 10 to set nums
add 5 to set nums
add 10 to set nums
add 99 to set nums
add 5 to set nums

print "nums length:", length of set nums
for each n in nums:
    print "num:", n

record Point:
    x: Int
    y: Int

define pts as empty set of Point
add Point(x=2, y=3) to set pts
add Point(x=1, y=1) to set pts
add Point(x=2, y=3) to set pts

print "pts length:", length of set pts
if pts contains Point(x=1, y=1):
    print "has p1: true"
else:
    print "has p1: false"

remove Point(x=1, y=1) from set pts
print "pts length after remove:", length of set pts
if pts contains Point(x=1, y=1):
    print "has p1 after remove: true"
else:
    print "has p1 after remove: false"
"""


def test_sets_verifier_rejects_type_mismatch():
    src = """
define s as empty set of String
add 123 to set s
"""
    with pytest.raises(StaticVerificationError):
        verify_synthesis(HeuristicProvider().synthesize(src))


def test_sets_verifier_rejects_void_element():
    src = """
define s as empty set of Void
"""
    with pytest.raises((StaticVerificationError, Exception)):
        verify_synthesis(HeuristicProvider().synthesize(src))


def test_sets_canonical_roundtrip():
    outcome = verify_synthesis(HeuristicProvider().synthesize(SET_PARITY_SRC))
    assert outcome.program is not None
    canon = to_canonical_meme(outcome.program)
    outcome2 = verify_synthesis(HeuristicProvider().synthesize(canon))
    assert outcome2.program is not None
    canon2 = to_canonical_meme(outcome2.program)
    assert canon == canon2

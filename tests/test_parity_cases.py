"""Table-driven cross-target parity harness.

Each case runs one `.meme` source through HeuristicProvider synthesis →
static verification → `execute_ir` on every target and asserts the exact
stdout / stderr / return code. Cases are migrated from the per-feature
`test_parity_*.py` files; those files keep their per-file
verifier-rejection and canonical-roundtrip unit tests.
"""

from __future__ import annotations

import pytest
from memelang.codegen import TARGET_LANGS, TargetLang

from conftest import run_parity

# Case spec keys:
#   source: `.meme` source text
#   stdout: expected stdout (after \r\n normalization), or None to skip
#   stderr: expected stderr (after \r\n normalization), or None to skip
#   returncode: expected exit code (default 0)
#   argv: forwarded to execute_ir (default None)
CASES: dict[str, dict] = {
    "two_d_lists": {
        "source": """
define grid as [[1, 2], [3, 4]]
print "rows", length of grid
print "cell01", grid[0][1]
set grid[1][0] to 9
print "cell10", grid[1][0]
for each row in grid:
    print "rowlen", length of row
define jag as [[1], [2, 3]]
print "jag11", jag[1][1]
print "jag00", jag[0][0]
""",
        "stdout": (
            "rows 2\n"
            "cell01 2\n"
            "cell10 9\n"
            "rowlen 2\n"
            "rowlen 2\n"
            "jag11 3\n"
            "jag00 1\n"
        ),
    },
    "assert_failure": {
        "source": "assert 1 is 1\nassert 2 > 3\n",
        "stdout": None,
        "stderr": "ASSERT FAILED line 2: 2 > 3\n",
        "returncode": 1,
    },
    "assert_success": {
        "source": "assert 1 is 1\nassert 10 > 2\nprint \"ok\"\n",
        "stdout": "ok\n",
        "stderr": "",
    },
    "char_codes_ascii_roundtrip": {
        "source": (
            "define ok: Bool as true\n"
            "for n from 32 to 126:\n"
            "    define ch: String as character of n\n"
            "    define roundtrip: Int as number of ch\n"
            "    if roundtrip != n:\n"
            "        set ok to false\n"
            "if ok:\n"
            "    print \"ASCII 32..126 roundtrip ok\"\n"
            "else:\n"
            "    print \"roundtrip failed\"\n"
        ),
        "stdout": "ASCII 32..126 roundtrip ok\n",
        "stderr": "",
    },
    "char_codes_basic": {
        "source": (
            "define n: Int as number of \"a\"\n"
            "define c: String as character of 97\n"
            "print n, c\n"
        ),
        "stdout": "97 a\n",
        "stderr": "",
    },
    "clock_and_env": {
        "source": """
define t1 as current epoch seconds
define t2 as current epoch seconds
assert t1 > 0
assert t2 >= t1

define unset_val as environment variable "MEME_TEST_NONEXISTENT_VAR_xyz"
if unset_val is nothing:
    print "unset is nothing: true"
else:
    print "unset is nothing: false"

define fallback_val as environment variable "MEME_TEST_NONEXISTENT_VAR_xyz" or else "default_value"
print "fallback:", fallback_val

define set_fallback as environment variable "PATH" or else "no_path"
assert set_fallback != "no_path"
print "path exists: true"

define path_opt as environment variable "PATH"
if path_opt is nothing:
    print "path is nothing: true"
else:
    print "path is nothing: false"
""",
        "stdout": (
            "unset is nothing: true\n"
            "fallback: default_value\n"
            "path exists: true\n"
            "path is nothing: false\n"
        ),
    },
    "argc_argv_user_vars": {
        "source": """
define argc as argument count
define argv as ["first", "second"]
print "argc is:", argc >= 0
print "argv:", argv[0], argv[1]

test dummy:
    assert 1 == 1
""",
        "stdout": "argc is: true\nargv: first second\n",
    },
    "argc_argv_test_block": {
        "source": """
define argc as argument count
define argv as ["first", "second"]
print "argc is:", argc >= 0
print "argv:", argv[0], argv[1]

test dummy:
    assert 1 == 1
""",
        "argv": ["--meme-test", "dummy"],
        "stdout": None,
    },
    "json_write_float_format_helper": {
        "source": """
record Product:
    name: String
    price: Float

define p as Product(name="Widget", price=19.95)
define ps as [p]
write ps as json to file "products.json"
define content as read string from file "products.json" or else ""
print content
""",
        "stdout": '[{"name":"Widget","price":19.95}]\n',
    },
    "list_copy_semantics": {
        "source": """
define src as [3, 1, 2]
define out as src
sort out ascending
append 99 to out
print "src:", src[0], src[1], src[2], length of src
print "out:", out[0], out[1], out[2], out[3], length of out

define src2 as [10, 20]
define out2 as [999]
set out2 to src2
append 30 to out2
print "src2:", src2[0], src2[1], length of src2
print "out2:", out2[0], out2[1], out2[2], length of out2
""",
        "stdout": (
            "src: 3 1 2 3\n"
            "out: 1 2 3 99 4\n"
            "src2: 10 20 2\n"
            "out2: 10 20 30 3\n"
        ),
    },
    "map_iteration_test_block": {
        "source": """
test map_iter:
    define m as {"banana": 2, "apple": 1, "cherry": 3}
    for each k in m:
        print k
""",
        "argv": ["--meme-test", "map_iter"],
        "stdout": "apple\nbanana\ncherry\n",
    },
    "float_format": {
        "source": (
            "print format 2.345 with 2 decimals\n"
            "print format 2.5 with 0 decimals\n"
            "print format -2.5 with 0 decimals\n"
            "print format 0.005 with 2 decimals\n"
            "print format 10.0 with 2 decimals\n"
            "print format 1000000000.0 with 0 decimals\n"
            "print format -0.001 with 2 decimals\n"
        ),
        "stdout": "2.35\n3\n-3\n0.01\n10.00\n1000000000\n0.00\n",
    },
    "float_of_format": {
        "source": "print format float of 12345 with 2 decimals\n",
        "stdout": "12345.00\n",
        "stderr": "",
    },
    "float_of_money_math": {
        "source": (
            "define cents: Int as 1999\n"
            "define dollars: Float as float of cents / 100.0\n"
            "print \"$\" + (format dollars with 2 decimals)\n"
        ),
        "stdout": "$19.99\n",
        "stderr": "",
    },
    "for_each_expressions": {
        "source": (
            "record Task:\n"
            "    name: String\n"
            "    deps: List<String>\n"
            "\n"
            "function get_items() -> List<Int>:\n"
            "    return [10, 20, 30]\n"
            "\n"
            "define t: Task as Task(name=\"release\", deps=[\"build\", \"test\", \"deploy\"])\n"
            "for each d in t.deps:\n"
            "    print \"dep:\", d\n"
            "\n"
            "for each item in get_items():\n"
            "    print \"item:\", item\n"
            "\n"
            "define grid: List<List<Int>> as [[1, 2, 3], [4, 5, 6]]\n"
            "for each cell in grid[0]:\n"
            "    print \"cell:\", cell\n"
            "\n"
            "for each index i item d in t.deps:\n"
            "    print \"idx:\", i, d\n"
        ),
        "stdout": (
            "dep: build\n"
            "dep: test\n"
            "dep: deploy\n"
            "item: 10\n"
            "item: 20\n"
            "item: 30\n"
            "cell: 1\n"
            "cell: 2\n"
            "cell: 3\n"
            "idx: 0 build\n"
            "idx: 1 test\n"
            "idx: 2 deploy\n"
        ),
        "stderr": "",
    },
    "for_each_expressions_workaround": {
        "source": (
            "record Task:\n"
            "    name: String\n"
            "    deps: List<String>\n"
            "\n"
            "function get_items() -> List<Int>:\n"
            "    return [10, 20, 30]\n"
            "\n"
            "define t: Task as Task(name=\"release\", deps=[\"build\", \"test\", \"deploy\"])\n"
            "define temp_deps: List<String> as t.deps\n"
            "for each d in temp_deps:\n"
            "    print \"dep:\", d\n"
            "\n"
            "define temp_items: List<Int> as get_items()\n"
            "for each item in temp_items:\n"
            "    print \"item:\", item\n"
            "\n"
            "define grid: List<List<Int>> as [[1, 2, 3], [4, 5, 6]]\n"
            "define temp_row: List<Int> as grid[0]\n"
            "for each cell in temp_row:\n"
            "    print \"cell:\", cell\n"
            "\n"
            "for each index i item d in temp_deps:\n"
            "    print \"idx:\", i, d\n"
        ),
        "stdout": (
            "dep: build\n"
            "dep: test\n"
            "dep: deploy\n"
            "item: 10\n"
            "item: 20\n"
            "item: 30\n"
            "cell: 1\n"
            "cell: 2\n"
            "cell: 3\n"
            "idx: 0 build\n"
            "idx: 1 test\n"
            "idx: 2 deploy\n"
        ),
        "stderr": "",
    },
    "mutual_recursion": {
        "source": (
            "function is_even(n: Int) -> Bool:\n"
            "    if n == 0:\n"
            "        return true\n"
            "    return is_odd(n - 1)\n"
            "\n"
            "function is_odd(n: Int) -> Bool:\n"
            "    if n == 0:\n"
            "        return false\n"
            "    return is_even(n - 1)\n"
            "\n"
            "print \"4 is even:\", is_even(4)\n"
            "print \"4 is odd:\", is_odd(4)\n"
            "print \"7 is even:\", is_even(7)\n"
            "print \"7 is odd:\", is_odd(7)\n"
        ),
        "stdout": (
            "4 is even: true\n"
            "4 is odd: false\n"
            "7 is even: false\n"
            "7 is odd: true\n"
        ),
        "stderr": "",
    },
    "optional_io": {
        "source": """
# String reader
define s_missing as read string from file "tmp_opt_missing_530.txt" or else nothing
if s_missing is nothing:
    print "s_missing is nothing: true"
else:
    print "s_missing is nothing: false"

define s_fallback as read string from file "tmp_opt_missing_530.txt" or else "default string"
print "s_fallback:", s_fallback

write file "tmp_opt_existing_530.txt" with "hello memelang"
define s_existing as read string from file "tmp_opt_existing_530.txt" or else nothing
if s_existing is nothing:
    print "s_existing is nothing: true"
else:
    print "s_existing:", value of s_existing

# Lines reader
define l_missing as read lines from file "tmp_opt_missing_530.txt" or else nothing
if l_missing is nothing:
    print "l_missing is nothing: true"
else:
    print "l_missing is nothing: false"

define l_fallback as read lines from file "tmp_opt_missing_530.txt" or else ["fallback_line"]
print "l_fallback length:", length of l_fallback

define l_existing as read lines from file "tmp_opt_existing_530.txt" or else nothing
if l_existing is nothing:
    print "l_existing is nothing: true"
else:
    define lines as value of l_existing
    for each line in lines:
        print "l_existing line:", line

# JSON list reader
define j_missing as read json file "tmp_opt_missing_530.json" as List<Int> or else nothing
if j_missing is nothing:
    print "j_missing is nothing: true"
else:
    print "j_missing is nothing: false"

define j_fallback as read json file "tmp_opt_missing_530.json" as List<Int> or else [42, 43]
print "j_fallback length:", length of j_fallback

write file "tmp_opt_malformed_530.json" with "{ bad json: "
define j_bad as read json file "tmp_opt_malformed_530.json" as List<Int> or else nothing
if j_bad is nothing:
    print "j_bad is nothing: true"
else:
    print "j_bad is nothing: false"

write file "tmp_opt_valid_530.json" with "[10, 20, 30]"
define j_valid as read json file "tmp_opt_valid_530.json" as List<Int> or else nothing
if j_valid is nothing:
    print "j_valid is nothing: true"
else:
    define nums as value of j_valid
    for each num in nums:
        print "j_valid num:", num

delete file "tmp_opt_existing_530.txt"
delete file "tmp_opt_malformed_530.json"
delete file "tmp_opt_valid_530.json"
""",
        "stdout": (
            "s_missing is nothing: true\n"
            "s_fallback: default string\n"
            "s_existing: hello memelang\n"
            "l_missing is nothing: true\n"
            "l_fallback length: 1\n"
            "l_existing line: hello memelang\n"
            "j_missing is nothing: true\n"
            "j_fallback length: 2\n"
            "j_bad is nothing: true\n"
            "j_valid num: 10\n"
            "j_valid num: 20\n"
            "j_valid num: 30\n"
        ),
    },
    "print_error_single_expr": {
        "source": "print error \"hello from stderr\"\n",
        "stdout": "",
        "stderr": "hello from stderr\n",
    },
    "print_error_multi_expr": {
        "source": (
            "define code: Int as 500\n"
            "define active: Bool as true\n"
            "print error \"fatal:\", code, active, \"system failure\"\n"
        ),
        "stdout": "",
        "stderr": "fatal: 500 true system failure\n",
    },
    "print_error_stream_separation": {
        "source": (
            "print \"standard out 1\"\n"
            "print error \"standard err 1\"\n"
            "print \"standard out 2\"\n"
            "print error \"standard err 2\"\n"
        ),
        "stdout": "standard out 1\nstandard out 2\n",
        "stderr": "standard err 1\nstandard err 2\n",
    },
    "sets": {
        "source": """
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
""",
        "stdout": (
            "s length: 5\n"
            "has cherry: true\n"
            "has cherry after remove: false\n"
            "s length after remove: 4\n"
            "fruit: apple\n"
            "fruit: banana\n"
            "fruit: date\n"
            "fruit: elderberry\n"
            "nums length: 4\n"
            "num: 5\n"
            "num: 10\n"
            "num: 42\n"
            "num: 99\n"
            "pts length: 2\n"
            "has p1: true\n"
            "pts length after remove: 1\n"
            "has p1 after remove: false\n"
        ),
    },
}


@pytest.mark.parametrize("target", list(TARGET_LANGS))
@pytest.mark.parametrize("case_name", list(CASES))
def test_parity_case(case_name: str, target: TargetLang) -> None:
    case = CASES[case_name]
    res = run_parity(case["source"], target, argv=case.get("argv"))
    assert res.returncode == case.get("returncode", 0), (
        f"[{case_name} / {target}] stderr: {res.stderr!r}"
    )
    expected_stdout = case.get("stdout")
    if expected_stdout is not None:
        assert res.stdout.replace("\r\n", "\n") == expected_stdout, (
            f"[{case_name} / {target}] stdout mismatch"
        )
    expected_stderr = case.get("stderr")
    if expected_stderr is not None:
        assert res.stderr.replace("\r\n", "\n") == expected_stderr, (
            f"[{case_name} / {target}] stderr mismatch"
        )

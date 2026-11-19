from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    LiteralExpr,
    ProgramIR,
    RecordDefStmt,
    RecordFieldDef,
    RecordFieldInit,
    RecordLiteralExpr,
    VarDeclStmt,
    VarRefExpr,
    WriteJsonStmt,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]

SRC = """
record Person:
    id: Int
    name: String
    score: Float
    active: Bool

define p as Person(id=1, name="Alice", score=95.5, active=true)
write p as json to file "person.json"

define p_opt as read json record Person from file "person.json" or else nothing
if p_opt is nothing:
    print "p: is nothing"
else:
    define pb as value of p_opt
    print "person:", pb.id, pb.name, format pb.score with 1 decimals, pb.active

define p2 as Person(id=2, name="Bob", score=80.0, active=false)
define ps as [p, p2]
write ps as json to file "people.json"

define ps_opt as read json records Person from file "people.json" or else nothing
if ps_opt is nothing:
    print "ps: is nothing"
else:
    define psb as value of ps_opt
    for each user in psb:
        print "people:", user.id, user.name, format user.score with 1 decimals, user.active

record Item:
    id: Int
    tag: Optional<String>
    extra: Optional<Float>

define it1 as Item(id=1, tag=optional "promo", extra=nothing)
define it2 as Item(id=2, tag=nothing, extra=optional 10.5)
define its as [it1, it2]
write its as json to file "items.json"

define its_opt as read json records Item from file "items.json" or else nothing
if its_opt is nothing:
    print "items: is nothing"
else:
    define itsb as value of its_opt
    for each item in itsb:
        define tag_str as "none"
        if item.tag is not nothing:
            set tag_str to value of item.tag
        define extra_str as "none"
        if item.extra is not nothing:
            set extra_str to format value of item.extra with 1 decimals
        print "item:", item.id, tag_str, extra_str
"""

EXPECTED_PERSON_JSON = '{"id":1,"name":"Alice","score":95.5,"active":true}'
EXPECTED_PEOPLE_JSON = '[{"id":1,"name":"Alice","score":95.5,"active":true},{"id":2,"name":"Bob","score":80.0,"active":false}]'
EXPECTED_ITEMS_JSON = '[{"id":1,"tag":"promo","extra":null},{"id":2,"tag":null,"extra":10.5}]'

EXPECTED_STDOUT = (
    "person: 1 Alice 95.5 true\n"
    "people: 1 Alice 95.5 true\n"
    "people: 2 Bob 80.0 false\n"
    "item: 1 promo none\n"
    "item: 2 none 10.5\n"
)


@pytest.mark.parametrize("target", TARGETS)
def test_json_write_cross_target_parity(target: TargetLang, tmp_path):
    target_dir = tmp_path / target
    target_dir.mkdir(parents=True, exist_ok=True)
    outcome = verify_synthesis(HeuristicProvider().synthesize(SRC))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target, cwd=target_dir)
    assert res.returncode == 0, res.stderr
    assert res.stdout.replace("\r\n", "\n") == EXPECTED_STDOUT

    person_content = (target_dir / "person.json").read_text(encoding="utf-8")
    assert person_content == EXPECTED_PERSON_JSON

    people_content = (target_dir / "people.json").read_text(encoding="utf-8")
    assert people_content == EXPECTED_PEOPLE_JSON

    items_content = (target_dir / "items.json").read_text(encoding="utf-8")
    assert items_content == EXPECTED_ITEMS_JSON


def test_json_write_all_targets_byte_identical(tmp_path):
    outcome = verify_synthesis(HeuristicProvider().synthesize(SRC))
    assert outcome.program is not None

    person_files: dict[TargetLang, bytes] = {}
    people_files: dict[TargetLang, bytes] = {}
    items_files: dict[TargetLang, bytes] = {}

    for target in TARGETS:
        target_dir = tmp_path / target
        target_dir.mkdir(parents=True, exist_ok=True)
        res = execute_ir(outcome.program, target, cwd=target_dir)
        assert res.returncode == 0, f"Target {target} failed: {res.stderr}"

        person_files[target] = (target_dir / "person.json").read_bytes()
        people_files[target] = (target_dir / "people.json").read_bytes()
        items_files[target] = (target_dir / "items.json").read_bytes()

    # Compare all to python output
    py_person = person_files["python"]
    py_people = people_files["python"]
    py_items = items_files["python"]

    for target in TARGETS:
        assert person_files[target] == py_person, f"person.json mismatch in {target}"
        assert people_files[target] == py_people, f"people.json mismatch in {target}"
        assert items_files[target] == py_items, f"items.json mismatch in {target}"


def test_json_write_verifier_rejects_non_record_target():
    prog = ProgramIR(
        statements=[
            WriteJsonStmt(
                target=LiteralExpr(value=42, data_type="Int"),
                filepath=LiteralExpr(value="out.json", data_type="String"),
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="must be a Record or List<Record>"):
        verify_program(prog)


def test_json_write_verifier_rejects_non_string_filepath():
    prog = ProgramIR(
        statements=[
            RecordDefStmt(
                name="R",
                fields=[RecordFieldDef(name="x", field_type="Int")],
            ),
            VarDeclStmt(
                name="r",
                var_type="R",
                value=RecordLiteralExpr(
                    record_name="R",
                    fields=[RecordFieldInit(name="x", value=LiteralExpr(value=0, data_type="Int"))],
                ),
            ),
            WriteJsonStmt(
                target=VarRefExpr(name="r"),
                filepath=LiteralExpr(value=123, data_type="Int"),
            ),
        ]
    )
    with pytest.raises(StaticVerificationError, match="filepath must be String"):
        verify_program(prog)


def test_json_write_verifier_rejects_nested_record():
    prog = ProgramIR(
        statements=[
            RecordDefStmt(
                name="Inner",
                fields=[RecordFieldDef(name="a", field_type="Int")],
            ),
            RecordDefStmt(
                name="Outer",
                fields=[RecordFieldDef(name="inner", field_type="Inner")],
            ),
            VarDeclStmt(
                name="o",
                var_type="Outer",
                value=RecordLiteralExpr(
                    record_name="Outer",
                    fields=[
                        RecordFieldInit(
                            name="inner",
                            value=RecordLiteralExpr(
                                record_name="Inner",
                                fields=[RecordFieldInit(name="a", value=LiteralExpr(value=1, data_type="Int"))],
                            ),
                        )
                    ],
                ),
            ),
            WriteJsonStmt(
                target=VarRefExpr(name="o"),
                filepath=LiteralExpr(value="out.json", data_type="String"),
            ),
        ]
    )
    with pytest.raises(StaticVerificationError, match="nested record"):
        verify_program(prog)


def test_json_write_canonical_roundtrip():
    prog = ProgramIR(
        statements=[
            RecordDefStmt(
                name="R",
                fields=[RecordFieldDef(name="x", field_type="Int")],
            ),
            VarDeclStmt(
                name="r",
                var_type="R",
                value=RecordLiteralExpr(
                    record_name="R",
                    fields=[RecordFieldInit(name="x", value=LiteralExpr(value=0, data_type="Int"))],
                ),
            ),
            WriteJsonStmt(
                target=VarRefExpr(name="r"),
                filepath=LiteralExpr(value="out.json", data_type="String"),
            ),
        ]
    )
    canonical = to_canonical_meme(prog)
    assert 'write r as json to file "out.json"' in canonical

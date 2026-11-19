from __future__ import annotations

import pytest

from memelang.analyzer.verifier import StaticVerificationError, verify_program, verify_synthesis
from memelang.codegen import TargetLang
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    ReadJsonRecordExpr,
    ReadJsonRecordsExpr,
    RecordDefStmt,
    RecordFieldDef,
)
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import execute_ir

TARGETS: list[TargetLang] = ["python", "rust", "cpp", "go", "c", "ts"]


@pytest.mark.parametrize("target", TARGETS)
def test_json_records_cross_target_parity(target: TargetLang, tmp_path):
    (tmp_path / "single.json").write_text(
        '{"id": 1, "name": "Alice", "score": 95.5, "active": true, "extra": "ignored"}',
        encoding="utf-8",
    )
    (tmp_path / "list.json").write_text(
        '[{"id": 1, "name": "Alice", "score": 95.5, "active": true}, {"id": 2, "name": "Bob", "score": 80.0, "active": false}]',
        encoding="utf-8",
    )
    (tmp_path / "malformed.json").write_text('{id: 1, name: "Alice"', encoding="utf-8")
    (tmp_path / "missing_field.json").write_text('{"id": 1, "name": "Alice", "score": 95.5}', encoding="utf-8")
    (tmp_path / "wrong_type.json").write_text(
        '{"id": "not an int", "name": "Alice", "score": 95.5, "active": true}',
        encoding="utf-8",
    )
    (tmp_path / "null_field.json").write_text(
        '{"id": null, "name": "Alice", "score": 95.5, "active": true}',
        encoding="utf-8",
    )
    (tmp_path / "array_of_scalars.json").write_text("[1, 2, 3]", encoding="utf-8")

    src = """
record User:
    id: Int
    name: String
    score: Float
    active: Bool

define u_opt as read json record User from file "single.json" or else nothing
if u_opt is nothing:
    print "single: is nothing"
else:
    define u as value of u_opt
    print "single user:", u.id, u.name, format u.score with 1 decimals, u.active

define us_opt as read json records User from file "list.json" or else nothing
if us_opt is nothing:
    print "list: is nothing"
else:
    define us as value of us_opt
    for each user in us:
        print "list user:", user.id, user.name, format user.score with 1 decimals, user.active

define bad1 as read json record User from file "malformed.json" or else nothing
if bad1 is nothing:
    print "bad1: is nothing"

define bad2 as read json record User from file "missing_field.json" or else nothing
if bad2 is nothing:
    print "bad2: is nothing"

define bad3 as read json record User from file "wrong_type.json" or else nothing
if bad3 is nothing:
    print "bad3: is nothing"

define bad4 as read json record User from file "null_field.json" or else nothing
if bad4 is nothing:
    print "bad4: is nothing"

define bad5 as read json records User from file "array_of_scalars.json" or else nothing
if bad5 is nothing:
    print "bad5: is nothing"
"""
    outcome = verify_synthesis(HeuristicProvider().synthesize(src))
    assert outcome.program is not None
    res = execute_ir(outcome.program, target, source_dir=tmp_path)
    assert res.returncode == 0, res.stderr
    expected = (
        "single user: 1 Alice 95.5 true\n"
        "list user: 1 Alice 95.5 true\n"
        "list user: 2 Bob 80.0 false\n"
        "bad1: is nothing\n"
        "bad2: is nothing\n"
        "bad3: is nothing\n"
        "bad4: is nothing\n"
        "bad5: is nothing\n"
    )
    assert res.stdout.replace("\r\n", "\n") == expected


def test_json_records_verifier_rejects_nested_record():
    prog = ProgramIR(
        statements=[
            RecordDefStmt(
                name="Inner",
                fields=[RecordFieldDef(name="x", field_type="Int")],
            ),
            RecordDefStmt(
                name="Outer",
                fields=[RecordFieldDef(name="inner", field_type="Inner")],
            ),
            PrintStmt(
                expressions=[
                    ReadJsonRecordExpr(
                        record_name="Outer",
                        filepath=LiteralExpr(value="outer.json", data_type="String"),
                    )
                ]
            ),
        ]
    )
    with pytest.raises(StaticVerificationError, match="nested record"):
        verify_program(prog)


def test_json_records_verifier_rejects_list_field():
    prog = ProgramIR(
        statements=[
            RecordDefStmt(
                name="HasList",
                fields=[RecordFieldDef(name="items", field_type="List<Int>")],
            ),
            PrintStmt(
                expressions=[
                    ReadJsonRecordExpr(
                        record_name="HasList",
                        filepath=LiteralExpr(value="list.json", data_type="String"),
                    )
                ]
            ),
        ]
    )
    with pytest.raises(StaticVerificationError, match="record field cannot be List or Map"):
        verify_program(prog)


def test_json_records_verifier_rejects_unknown_record():
    prog = ProgramIR(
        statements=[
            PrintStmt(
                expressions=[
                    ReadJsonRecordExpr(
                        record_name="Ghost",
                        filepath=LiteralExpr(value="ghost.json", data_type="String"),
                    )
                ]
            )
        ]
    )
    with pytest.raises(StaticVerificationError, match="Unknown record"):
        verify_program(prog)


def test_json_records_canonical_roundtrip():
    prog = ProgramIR(
        statements=[
            RecordDefStmt(
                name="User",
                fields=[
                    RecordFieldDef(name="id", field_type="Int"),
                    RecordFieldDef(name="name", field_type="String"),
                ],
            ),
            PrintStmt(
                expressions=[
                    ReadJsonRecordExpr(
                        record_name="User",
                        filepath=LiteralExpr(value="user.json", data_type="String"),
                    )
                ]
            ),
            PrintStmt(
                expressions=[
                    ReadJsonRecordsExpr(
                        record_name="User",
                        filepath=LiteralExpr(value="users.json", data_type="String"),
                    )
                ]
            ),
        ]
    )
    canonical = to_canonical_meme(prog)
    assert 'read json record User from file "user.json" or else nothing' in canonical
    assert 'read json records User from file "users.json" or else nothing' in canonical

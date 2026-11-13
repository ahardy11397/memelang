"""Canonical Structured English decompiler for Memelang ProgramIR."""

from __future__ import annotations

import json
from memelang.ir.schema import (
    AppendFileStmt,
    ArgAtExpr,
    ArgCountExpr,
    AssignStmt,
    BinaryOpExpr,
    BreakStmt,
    CallExpr,
    CallStmt,
    ClampCollectionStmt,
    CompoundAssignStmt,
    ContinueStmt,
    CopyFileStmt,
    CreateDirectoryStmt,
    DeleteFileStmt,
    ExitStmt,
    FailStmt,
    FileExistsExpr,
    FilterCollectionStmt,
    ForEachStmt,
    FormatIntExpr,
    ForRangeStmt,
    FuncDefStmt,
    IRExpr,
    IRStatement,
    IfStmt,
    ImportStmt,
    IsDigitExpr,
    IsLetterExpr,
    IsUpperExpr,
    IsLowerExpr,
    ListAppendStmt,
    ListFilesExpr,
    ListIndexExpr,
    ListInsertStmt,
    ListLengthExpr,
    ListLiteralExpr,
    ListRemoveStmt,
    ListSetIndexStmt,
    LiteralExpr,
    MapEntry,
    MapGetExpr,
    MapHasKeyExpr,
    MapLiteralExpr,
    MapSetStmt,
    MoveFileStmt,
    OptionalIsNothingExpr,
    OptionalNoneExpr,
    OptionalUnwrapExpr,
    OptionalUnwrapOrDefaultExpr,
    OptionalWrapExpr,
    ParseIntExpr,
    ParseIntOrDefaultExpr,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadFileStringExpr,
    ReadFileLinesExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    RenameFileStmt,
    RecordDefStmt,
    RecordFieldDef,
    RecordFieldExpr,
    RecordFieldInit,
    RecordLiteralExpr,
    RecordSetFieldStmt,
    ReturnStmt,
    SortCollectionStmt,
    StrContainsExpr,
    StrEndsWithExpr,
    StrStartsWithExpr,
    StringCharAtExpr,
    StringIndexOfExpr,
    StringJoinExpr,
    StringLengthExpr,
    StringLowerExpr,
    StringReplaceExpr,
    StringSliceExpr,
    StringSplitExpr,
    StringTrimExpr,
    StringUpperExpr,
    SwitchCase,
    SwitchStmt,
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
    WriteFileStmt,
)


def format_expr(expr: IRExpr, parent_prec: int = 0) -> str:
    if isinstance(expr, LiteralExpr):
        if expr.data_type == "Bool":
            return "true" if expr.value else "false"
        if expr.data_type == "String":
            return json.dumps(expr.value)
        return str(expr.value)

    if isinstance(expr, ListLiteralExpr):
        if not expr.elements:
            return f"empty List<{expr.element_type}>"
        inner = ", ".join(format_expr(e) for e in expr.elements)
        return f"[{inner}]"

    if isinstance(expr, VarRefExpr):
        return expr.name

    if isinstance(expr, RandomIntExpr):
        return f"random integer between {format_expr(expr.min_val)} and {format_expr(expr.max_val)}"

    if isinstance(expr, RandomListExpr):
        return (
            f"{format_expr(expr.count)} random integers between "
            f"{format_expr(expr.min_val)} and {format_expr(expr.max_val)}"
        )

    if isinstance(expr, UnaryOpExpr):
        if expr.op == "not":
            res = f"not {format_expr(expr.operand, 5)}"
        else:
            res = f"-{format_expr(expr.operand, 5)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, BinaryOpExpr):
        prec_map = {
            "or": 1,
            "and": 2,
            "==": 3,
            "!=": 3,
            "<": 3,
            "<=": 3,
            ">": 3,
            ">=": 3,
            "+": 4,
            "-": 4,
            "*": 5,
            "/": 5,
            "%": 5,
        }
        prec = prec_map[expr.op]
        left_s = format_expr(expr.left, prec)
        right_s = format_expr(expr.right, prec + 1)
        res = f"{left_s} {expr.op} {right_s}"
        return f"({res})" if prec < parent_prec else res

    if isinstance(expr, ListLengthExpr):
        return f"length of {format_expr(expr.target)}"

    if isinstance(expr, ListIndexExpr):
        return f"{format_expr(expr.target)}[{format_expr(expr.index)}]"

    if isinstance(expr, CallExpr):
        args_s = ", ".join(format_expr(a) for a in expr.args)
        return f"{expr.func_name}({args_s})"

    if isinstance(expr, ReadInputExpr):
        return f"read {expr.target_type} with prompt {json.dumps(expr.prompt)}"

    if isinstance(expr, StrEndsWithExpr):
        res = f"{format_expr(expr.target, 3)} ends with {format_expr(expr.suffix, 4)}"
        return f"({res})" if parent_prec > 3 else res

    if isinstance(expr, StrStartsWithExpr):
        res = f"{format_expr(expr.target, 3)} starts with {format_expr(expr.prefix, 4)}"
        return f"({res})" if parent_prec > 3 else res

    if isinstance(expr, StrContainsExpr):
        res = f"{format_expr(expr.target, 3)} contains {format_expr(expr.substring, 4)}"
        return f"({res})" if parent_prec > 3 else res

    if isinstance(expr, StringReplaceExpr):
        res = (
            f"replace {format_expr(expr.old, 6)} with {format_expr(expr.new, 6)} "
            f"in {format_expr(expr.target, 6)}"
        )
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, StringUpperExpr):
        res = f"upper {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, StringLowerExpr):
        res = f"lower {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, StringTrimExpr):
        res = f"trim {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, StringSplitExpr):
        res = f"split {format_expr(expr.target, 6)} by {format_expr(expr.separator, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, StringJoinExpr):
        res = f"join {format_expr(expr.items, 6)} with {format_expr(expr.separator, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, StringIndexOfExpr):
        res = f"index of {format_expr(expr.substring, 6)} in {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, StringCharAtExpr):
        res = f"char at {format_expr(expr.index, 6)} of {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, FileExistsExpr):
        res = f"file exists {format_expr(expr.filepath, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, ReadFileStringExpr):
        res = f"read string from file {format_expr(expr.filepath, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, ReadFileLinesExpr):
        res = f"read lines from file {format_expr(expr.filepath, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, ListFilesExpr):
        res = f"list files in {format_expr(expr.path, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, ArgCountExpr):
        return "argument count"

    if isinstance(expr, ArgAtExpr):
        res = f"argument {format_expr(expr.index, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, ReadJsonListExpr):
        if expr.explicit_type or expr.element_type != "Float":
            res = f"read json file {format_expr(expr.filepath, 6)} as List<{expr.element_type}>"
            return f"({res})" if parent_prec > 5 else res
        return f"read JSON number list from {format_expr(expr.filepath)}"

    if isinstance(expr, StringLengthExpr):
        return f"length of string {format_expr(expr.target)}"

    if isinstance(expr, StringSliceExpr):
        return f"slice {format_expr(expr.target)} from {format_expr(expr.start)} to {format_expr(expr.end)}"

    if isinstance(expr, ParseIntExpr):
        res = f"integer value of {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, ParseIntOrDefaultExpr):
        res = f"integer value of {format_expr(expr.target, 6)} or else {format_expr(expr.default_val, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, IsDigitExpr):
        res = f"is digit {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, IsLetterExpr):
        res = f"is letter {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, IsUpperExpr):
        res = f"is upper {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, IsLowerExpr):
        res = f"is lower {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, FormatIntExpr):
        res = f"text of {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, RecordLiteralExpr):
        fields_str = ", ".join(f"{f.name}={format_expr(f.value)}" for f in expr.fields)
        return f"{expr.record_name}({fields_str})"

    if isinstance(expr, RecordFieldExpr):
        return f"{format_expr(expr.target, 6)}.{expr.field_name}"

    if isinstance(expr, MapLiteralExpr):
        if not expr.entries:
            return f"empty Map<{expr.key_type}, {expr.value_type}>"
        entries_str = ", ".join(f"{format_expr(e.key)}: {format_expr(e.value)}" for e in expr.entries)
        return f"{{{entries_str}}}"

    if isinstance(expr, MapGetExpr):
        base = f"{format_expr(expr.target, 6)}[{format_expr(expr.key)}]"
        if expr.default_val is not None:
            res = f"{base} default {format_expr(expr.default_val, 6)}"
            return f"({res})" if parent_prec > 5 else res
        return base

    if isinstance(expr, MapHasKeyExpr):
        res = f"{format_expr(expr.target, 3)} has key {format_expr(expr.key, 4)}"
        return f"({res})" if parent_prec > 3 else res

    if isinstance(expr, OptionalNoneExpr):
        return "nothing"

    if isinstance(expr, OptionalWrapExpr):
        res = f"optional {format_expr(expr.value, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, OptionalIsNothingExpr):
        kw = "is not nothing" if expr.negated else "is nothing"
        res = f"{format_expr(expr.target, 3)} {kw}"
        return f"({res})" if parent_prec > 3 else res

    if isinstance(expr, OptionalUnwrapExpr):
        res = f"value of {format_expr(expr.target, 6)}"
        return f"({res})" if parent_prec > 5 else res

    if isinstance(expr, OptionalUnwrapOrDefaultExpr):
        res = f"value of {format_expr(expr.target, 6)} or else {format_expr(expr.default_val, 6)}"
        return f"({res})" if parent_prec > 5 else res

    raise TypeError(f"Unsupported expression node: {type(expr)!r}")


def _format_stmt(stmt: IRStatement, indent: int = 0) -> list[str]:
    pad = "    " * indent

    if isinstance(stmt, VarDeclStmt):
        if stmt.var_type.startswith("List<"):
            return [f"{pad}define list {stmt.name} as {format_expr(stmt.value)}"]
        return [f"{pad}define {stmt.name}: {stmt.var_type} as {format_expr(stmt.value)}"]

    if isinstance(stmt, AssignStmt):
        return [f"{pad}set {stmt.name} to {format_expr(stmt.value)}"]

    if isinstance(stmt, CompoundAssignStmt):
        val_s = format_expr(stmt.value)
        if stmt.operator == "+":
            return [f"{pad}add {val_s} to {stmt.target}"]
        if stmt.operator == "-":
            return [f"{pad}subtract {val_s} from {stmt.target}"]
        if stmt.operator == "*":
            return [f"{pad}multiply {stmt.target} by {val_s}"]
        if stmt.operator == "/":
            return [f"{pad}divide {stmt.target} by {val_s}"]

    if isinstance(stmt, SortCollectionStmt):
        return [f"{pad}sort {stmt.target} {stmt.direction}"]

    if isinstance(stmt, ClampCollectionStmt):
        return [
            f"{pad}clamp {stmt.target} between {format_expr(stmt.min_val)} and {format_expr(stmt.max_val)}"
        ]

    if isinstance(stmt, FilterCollectionStmt):
        return [f"{pad}filter {stmt.target} where {format_expr(stmt.predicate)}"]

    if isinstance(stmt, ListAppendStmt):
        return [f"{pad}append {format_expr(stmt.value)} to {stmt.target}"]

    if isinstance(stmt, ListInsertStmt):
        return [
            f"{pad}insert {format_expr(stmt.value)} into {stmt.target} at {format_expr(stmt.index)}"
        ]

    if isinstance(stmt, ListSetIndexStmt):
        return [f"{pad}set {stmt.target}[{format_expr(stmt.index)}] to {format_expr(stmt.value)}"]

    if isinstance(stmt, ListRemoveStmt):
        if stmt.index is not None:
            return [f"{pad}remove item {format_expr(stmt.index)} from {stmt.target}"]
        return [f"{pad}remove last item from {stmt.target}"]

    if isinstance(stmt, FailStmt):
        return [f"{pad}fail with {format_expr(stmt.message)}"]

    if isinstance(stmt, ExitStmt):
        return [f"{pad}exit with code {format_expr(stmt.code)}"]

    if isinstance(stmt, PrintStmt):
        exprs = ", ".join(format_expr(e) for e in stmt.expressions)
        return [f"{pad}print {exprs}"]

    if isinstance(stmt, IfStmt):
        lines = [f"{pad}if {format_expr(stmt.condition)}:"]
        for child in stmt.then_body:
            lines.extend(_format_stmt(child, indent + 1))
        if stmt.else_body:
            lines.append(f"{pad}else:")
            for child in stmt.else_body:
                lines.extend(_format_stmt(child, indent + 1))
        return lines

    if isinstance(stmt, SwitchStmt):
        lines = [f"{pad}match {format_expr(stmt.target)}:"]
        for case in stmt.cases:
            lines.append(f"{pad}    when {format_expr(case.value)}:")
            for ch in case.body:
                lines.extend(_format_stmt(ch, indent + 2))
        if stmt.default_body:
            lines.append(f"{pad}    otherwise:")
            for ch in stmt.default_body:
                lines.extend(_format_stmt(ch, indent + 2))
        return lines

    if isinstance(stmt, ForEachStmt):
        if stmt.index_var is not None:
            lines = [
                f"{pad}for each index {stmt.index_var} item {stmt.item_var} in {stmt.collection}:"
            ]
        else:
            lines = [f"{pad}for each {stmt.item_var} in {stmt.collection}:"]
        for child in stmt.body:
            lines.extend(_format_stmt(child, indent + 1))
        return lines

    if isinstance(stmt, ForRangeStmt):
        lines = [
            f"{pad}for {stmt.loop_var} from {format_expr(stmt.start)} to {format_expr(stmt.end)}:"
        ]
        for child in stmt.body:
            lines.extend(_format_stmt(child, indent + 1))
        return lines

    if isinstance(stmt, WhileStmt):
        lines = [f"{pad}while {format_expr(stmt.condition)}:"]
        for child in stmt.body:
            lines.extend(_format_stmt(child, indent + 1))
        return lines

    if isinstance(stmt, BreakStmt):
        return [f"{pad}break"]

    if isinstance(stmt, ContinueStmt):
        return [f"{pad}continue"]

    if isinstance(stmt, FuncDefStmt):
        params = ", ".join(f"{p.name}: {p.param_type}" for p in stmt.params)
        lines = [f"{pad}function {stmt.name}({params}) -> {stmt.return_type}:"]
        for child in stmt.body:
            lines.extend(_format_stmt(child, indent + 1))
        return lines

    if isinstance(stmt, ReturnStmt):
        if stmt.value is None:
            return [f"{pad}return"]
        return [f"{pad}return {format_expr(stmt.value)}"]

    if isinstance(stmt, RecordDefStmt):
        lines = [f"{pad}record {stmt.name}:"]
        if not stmt.fields:
            lines.append(f"{pad}    pass")
        for f in stmt.fields:
            lines.append(f"{pad}    {f.name}: {f.field_type}")
        return lines

    if isinstance(stmt, RecordSetFieldStmt):
        return [f"{pad}set {stmt.target}.{stmt.field_name} to {format_expr(stmt.value)}"]

    if isinstance(stmt, MapSetStmt):
        return [f"{pad}set {stmt.target}[{format_expr(stmt.key)}] to {format_expr(stmt.value)}"]

    if isinstance(stmt, WriteFileStmt):
        return [f"{pad}write file {format_expr(stmt.filepath)} with {format_expr(stmt.content)}"]

    if isinstance(stmt, AppendFileStmt):
        return [f"{pad}append {format_expr(stmt.content)} to file {format_expr(stmt.filepath)}"]

    if isinstance(stmt, CopyFileStmt):
        return [f"{pad}copy file {format_expr(stmt.src)} to {format_expr(stmt.dst)}"]

    if isinstance(stmt, MoveFileStmt):
        return [f"{pad}move file {format_expr(stmt.src)} to {format_expr(stmt.dst)}"]

    if isinstance(stmt, RenameFileStmt):
        return [f"{pad}rename file {format_expr(stmt.path)} to {format_expr(stmt.new_name)}"]

    if isinstance(stmt, DeleteFileStmt):
        return [f"{pad}delete file {format_expr(stmt.path)}"]

    if isinstance(stmt, CreateDirectoryStmt):
        return [f"{pad}create directory {format_expr(stmt.path)}"]

    if isinstance(stmt, ImportStmt):
        return [f"{pad}use {stmt.module}"]

    if isinstance(stmt, CallStmt):
        args_s = ", ".join(format_expr(a) for a in stmt.args)
        return [f"{pad}call {stmt.func_name}({args_s})"]

    raise TypeError(f"Unsupported statement node: {type(stmt)!r}")


def to_canonical_meme(program: ProgramIR) -> str:
    lines: list[str] = []
    for stmt in program.statements:
        lines.extend(_format_stmt(stmt, indent=0))
    return "\n".join(lines)

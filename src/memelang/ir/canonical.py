"""Canonical Structured English decompiler for Memelang ProgramIR."""

from __future__ import annotations

import json
from memelang.ir.schema import (
    AssignStmt,
    BinaryOpExpr,
    CallExpr,
    ClampCollectionStmt,
    FilterCollectionStmt,
    ForEachStmt,
    ForRangeStmt,
    FuncDefStmt,
    IRExpr,
    IRStatement,
    IfStmt,
    ListAppendStmt,
    ListIndexExpr,
    ListLengthExpr,
    ListLiteralExpr,
    LiteralExpr,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadInputExpr,
    ReturnStmt,
    SortCollectionStmt,
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
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

    raise TypeError(f"Unsupported expression node: {type(expr)!r}")


def _format_stmt(stmt: IRStatement, indent: int = 0) -> list[str]:
    pad = "    " * indent

    if isinstance(stmt, VarDeclStmt):
        if stmt.var_type.startswith("List<"):
            return [f"{pad}define list {stmt.name} as {format_expr(stmt.value)}"]
        return [f"{pad}define {stmt.name}: {stmt.var_type} as {format_expr(stmt.value)}"]

    if isinstance(stmt, AssignStmt):
        return [f"{pad}set {stmt.name} to {format_expr(stmt.value)}"]

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

    if isinstance(stmt, ForEachStmt):
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

    raise TypeError(f"Unsupported statement node: {type(stmt)!r}")


def to_canonical_meme(program: ProgramIR) -> str:
    lines: list[str] = []
    for stmt in program.statements:
        lines.extend(_format_stmt(stmt, indent=0))
    return "\n".join(lines)

"""Generic child-enumeration utilities for the Memelang IR.

Single source of truth for IR traversal: the verifier's reference and
mutation analyses, the runner's input-usage analysis, and corpus tooling
all walk the IR through these helpers instead of maintaining drifted
per-class ``isinstance`` chains. The walkers are built directly on the
pydantic model fields of :mod:`memelang.ir.schema`, so newly added IR
node kinds are traversed automatically.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from memelang.ir.schema import IRNode


def _is_expr(node: Any) -> bool:
    """Expressions carry an ``expr_type`` discriminant field."""
    return isinstance(node, IRNode) and hasattr(node, "expr_type")


def _is_stmt(node: Any) -> bool:
    """Statements carry an ``op`` discriminant field."""
    return isinstance(node, IRNode) and hasattr(node, "op")


def _iter_expr_fields(node: IRNode) -> Iterator[IRNode]:
    """Yield the direct child expressions of an IR node.

    Descends through pure container nodes (``RecordFieldInit``,
    ``MapEntry``, ...) so e.g. a record literal yields each field's value
    expression, but does NOT descend into nested statement bodies.
    """
    for field_name in type(node).model_fields:
        value = getattr(node, field_name)
        if isinstance(value, IRNode):
            if _is_expr(value):
                yield value
            elif not _is_stmt(value):
                yield from _iter_expr_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, IRNode):
                    if _is_expr(item):
                        yield item
                    elif not _is_stmt(item):
                        yield from _iter_expr_fields(item)


def iter_child_exprs(expr: IRNode) -> Iterator[IRNode]:
    """Yield the direct child expressions of an IR expression (or statement).

    Accepts any IR node; for an ``IRExpr`` it yields every expression held
    by its fields (descending through container nodes such as
    ``RecordFieldInit`` / ``MapEntry``), and for an ``IRStatement`` it
    yields the statement's direct child expressions (``SwitchCase.value``
    included) without descending into nested statement bodies.
    """
    yield from _iter_expr_fields(expr)


def iter_stmt_bodies(stmt: IRNode) -> Iterator[list[IRNode]]:
    """Yield the statement-list bodies held by an IR statement.

    Covers ``IfStmt`` (then/else), ``SwitchStmt`` (per-case bodies via
    ``SwitchCase`` plus the default body), ``ForEachStmt``,
    ``ForRangeStmt``, ``WhileStmt``, ``FuncDefStmt``, ``TestBlockStmt``,
    and ``ProgramIR`` (statements + imported definitions). Plain
    expression fields are skipped; container nodes (``SwitchCase``,
    ``AmbiguityCandidate``, ...) are descended.
    """
    for field_name in type(stmt).model_fields:
        value = getattr(stmt, field_name)
        if isinstance(value, list):
            if value and all(isinstance(item, IRNode) and _is_stmt(item) for item in value):
                yield value
            else:
                for item in value:
                    if (
                        isinstance(item, IRNode)
                        and not _is_stmt(item)
                        and not _is_expr(item)
                    ):
                        yield from iter_stmt_bodies(item)
        elif isinstance(value, IRNode) and not _is_stmt(value) and not _is_expr(value):
            yield from iter_stmt_bodies(value)

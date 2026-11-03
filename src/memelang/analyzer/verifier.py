"""Deterministic static type/scope verifier and structural ambiguity safety net."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    AmbiguityCandidate,
    AmbiguityDiagnostic,
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
    MemeType,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadInputExpr,
    ReturnStmt,
    SortCollectionStmt,
    SynthesisItem,
    SynthesisResult,
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
)


class StaticVerificationError(Exception):
    """Raised when IR fails static scope, type, or safety verification."""

    def __init__(self, message: str, statement_index: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.statement_index = statement_index


@dataclass
class VerificationOutcome:
    program: ProgramIR | None
    ambiguities: list[AmbiguityDiagnostic]
    normalized_items: list[SynthesisItem] = field(default_factory=list)

    @property
    def is_unambiguous(self) -> bool:
        return len(self.ambiguities) == 0 and self.program is not None


class _Scope:
    def __init__(self, parent: _Scope | None = None) -> None:
        self.parent = parent
        self.symbols: dict[str, MemeType] = {}

    def lookup(self, name: str) -> MemeType | None:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        return None

    def define(self, name: str, meme_type: MemeType) -> None:
        self.symbols[name] = meme_type


def _element_type_of(list_type: MemeType) -> MemeType | None:
    mapping: dict[str, MemeType] = {
        "List<Int>": "Int",
        "List<Float>": "Float",
        "List<Bool>": "Bool",
        "List<String>": "String",
    }
    return mapping.get(list_type)


def _find_collection_mutations(stmts: list[IRStatement], collection: str) -> list[IRStatement]:
    hits: list[IRStatement] = []
    for s in stmts:
        if isinstance(
            s,
            (SortCollectionStmt, ClampCollectionStmt, FilterCollectionStmt, ListAppendStmt),
        ) and s.target == collection:
            hits.append(s)
        elif isinstance(s, IfStmt):
            hits.extend(_find_collection_mutations(s.then_body, collection))
            hits.extend(_find_collection_mutations(s.else_body, collection))
        elif isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt)):
            hits.extend(_find_collection_mutations(s.body, collection))
    return hits


def _build_loop_collision_ambiguity(
    statement_id: int,
    loop_stmt: ForEachStmt,
    preceding_stmts: list[IRStatement],
    following_stmts: list[IRStatement],
) -> AmbiguityDiagnostic:
    target = loop_stmt.collection
    direction = "ascending"
    min_bound = LiteralExpr(value=1, data_type="Int")
    max_bound = LiteralExpr(value=10, data_type="Int")

    for s in loop_stmt.body:
        if isinstance(s, SortCollectionStmt) and s.target == target:
            direction = s.direction
        elif isinstance(s, ClampCollectionStmt) and s.target == target:
            min_bound = s.min_val
            max_bound = s.max_val

    opt1_ir: list[IRStatement] = [SortCollectionStmt(target=target, direction=direction)]
    opt2_ir: list[IRStatement] = [
        ClampCollectionStmt(target=target, min_val=min_bound, max_val=max_bound),
        SortCollectionStmt(target=target, direction=direction),
    ]

    candidates: list[AmbiguityCandidate] = [
        AmbiguityCandidate(
            option=1,
            description=f"Mutate `{target}` by sorting all elements in {direction} order",
            canonical_meme=to_canonical_meme(ProgramIR(statements=opt1_ir)),
            replacement_ir=opt1_ir,
            replaces_whole_program=False,
        ),
        AmbiguityCandidate(
            option=2,
            description=f"Clamp each item in `{target}` to [1, 10], then sort {direction}",
            canonical_meme=to_canonical_meme(ProgramIR(statements=opt2_ir)),
            replacement_ir=opt2_ir,
            replaces_whole_program=False,
        ),
    ]

    # Check if an earlier VarDeclStmt initialized `target` with a RandomListExpr
    rebuilt_whole: list[IRStatement] = []
    found_random_decl = False
    for prev in preceding_stmts:
        if (
            isinstance(prev, VarDeclStmt)
            and prev.name == target
            and isinstance(prev.value, RandomListExpr)
        ):
            found_random_decl = True
            rebuilt_whole.append(
                VarDeclStmt(
                    name=prev.name,
                    var_type=prev.var_type,
                    value=RandomListExpr(
                        count=prev.value.count,
                        min_val=min_bound,
                        max_val=max_bound,
                        implicit_bounds=False,
                    ),
                    source_line=prev.source_line,
                )
            )
        else:
            rebuilt_whole.append(prev)

    if found_random_decl:
        rebuilt_whole.append(SortCollectionStmt(target=target, direction=direction))
        rebuilt_whole.extend(following_stmts)
        candidates.append(
            AmbiguityCandidate(
                option=3,
                description=f"Generate random integers restricted to [1, 10] for `{target}` and sort {direction}",
                canonical_meme=to_canonical_meme(ProgramIR(statements=rebuilt_whole)),
                replacement_ir=rebuilt_whole,
                replaces_whole_program=True,
            )
        )

    return AmbiguityDiagnostic(
        statement_id=statement_id,
        source_line=loop_stmt.source_line or statement_id,
        source_text=f"for each {loop_stmt.item_var} in {target}: <mutates {target}>",
        reason=(
            f"Looping over `{target}` while performing a whole-collection mutation on `{target}` "
            "inside the loop body is semantically ambiguous."
        ),
        candidates=candidates,
    )


class _StaticChecker:
    def __init__(self) -> None:
        self.functions: dict[str, tuple[list[MemeType], MemeType]] = {}

    def infer_expr_type(self, expr: IRExpr, scope: _Scope, stmt_idx: int | None) -> MemeType:
        if isinstance(expr, LiteralExpr):
            return expr.data_type

        if isinstance(expr, ListLiteralExpr):
            for el in expr.elements:
                el_t = self.infer_expr_type(el, scope, stmt_idx)
                if el_t != expr.element_type:
                    raise StaticVerificationError(
                        f"List literal expected {expr.element_type} elements, got {el_t}",
                        stmt_idx,
                    )
            return cast(MemeType, f"List<{expr.element_type}>")

        if isinstance(expr, VarRefExpr):
            found = scope.lookup(expr.name)
            if found is None:
                raise StaticVerificationError(
                    f"Reference to undeclared variable `{expr.name}`", stmt_idx
                )
            return found

        if isinstance(expr, RandomIntExpr):
            lo_t = self.infer_expr_type(expr.min_val, scope, stmt_idx)
            hi_t = self.infer_expr_type(expr.max_val, scope, stmt_idx)
            if lo_t != "Int" or hi_t != "Int":
                raise StaticVerificationError(
                    f"RandomIntExpr bounds must be Int, got ({lo_t}, {hi_t})", stmt_idx
                )
            return "Int"

        if isinstance(expr, RandomListExpr):
            c_t = self.infer_expr_type(expr.count, scope, stmt_idx)
            lo_t = self.infer_expr_type(expr.min_val, scope, stmt_idx)
            hi_t = self.infer_expr_type(expr.max_val, scope, stmt_idx)
            if c_t != "Int" or lo_t != "Int" or hi_t != "Int":
                raise StaticVerificationError(
                    f"RandomListExpr count and bounds must be Int, got ({c_t}, {lo_t}, {hi_t})",
                    stmt_idx,
                )
            return "List<Int>"

        if isinstance(expr, UnaryOpExpr):
            op_t = self.infer_expr_type(expr.operand, scope, stmt_idx)
            if expr.op == "not":
                if op_t != "Bool":
                    raise StaticVerificationError(
                        f"`not` requires Bool operand, got {op_t}", stmt_idx
                    )
                return "Bool"
            if op_t not in ("Int", "Float"):
                raise StaticVerificationError(
                    f"Unary `-` requires numeric operand, got {op_t}", stmt_idx
                )
            return op_t

        if isinstance(expr, BinaryOpExpr):
            left_t = self.infer_expr_type(expr.left, scope, stmt_idx)
            right_t = self.infer_expr_type(expr.right, scope, stmt_idx)

            if expr.op in ("/", "%") and isinstance(expr.right, LiteralExpr):
                if expr.right.value in (0, 0.0) and not isinstance(expr.right.value, bool):
                    raise StaticVerificationError(
                        f"Division or modulo by literal zero (`{expr.op} 0`)", stmt_idx
                    )

            if expr.op == "+":
                if left_t == right_t and left_t in ("Int", "Float", "String"):
                    return left_t
                raise StaticVerificationError(
                    f"Incompatible operand types for `+`: {left_t} and {right_t}", stmt_idx
                )

            if expr.op in ("-", "*", "/"):
                if left_t == right_t and left_t in ("Int", "Float"):
                    return left_t
                raise StaticVerificationError(
                    f"Incompatible operand types for `{expr.op}`: {left_t} and {right_t}",
                    stmt_idx,
                )

            if expr.op == "%":
                if left_t == "Int" and right_t == "Int":
                    return "Int"
                raise StaticVerificationError(
                    f"Modulo `%` requires Int operands, got {left_t} and {right_t}", stmt_idx
                )

            if expr.op in ("<", "<=", ">", ">="):
                if left_t == right_t and left_t in ("Int", "Float", "String"):
                    return "Bool"
                raise StaticVerificationError(
                    f"Incompatible comparison `{expr.op}` between {left_t} and {right_t}",
                    stmt_idx,
                )

            if expr.op in ("==", "!="):
                if left_t == right_t and left_t != "Void":
                    return "Bool"
                raise StaticVerificationError(
                    f"Incompatible equality check `{expr.op}` between {left_t} and {right_t}",
                    stmt_idx,
                )

            if expr.op in ("and", "or"):
                if left_t == "Bool" and right_t == "Bool":
                    return "Bool"
                raise StaticVerificationError(
                    f"Logical `{expr.op}` requires Bool operands, got {left_t} and {right_t}",
                    stmt_idx,
                )

        if isinstance(expr, ListLengthExpr):
            target_t = self.infer_expr_type(expr.target, scope, stmt_idx)
            if _element_type_of(target_t) is None:
                raise StaticVerificationError(
                    f"`list_length` requires a List target, got {target_t}", stmt_idx
                )
            return "Int"

        if isinstance(expr, ListIndexExpr):
            target_t = self.infer_expr_type(expr.target, scope, stmt_idx)
            elem_t = _element_type_of(target_t)
            if elem_t is None:
                raise StaticVerificationError(
                    f"`list_index` requires a List target, got {target_t}", stmt_idx
                )
            idx_t = self.infer_expr_type(expr.index, scope, stmt_idx)
            if idx_t != "Int":
                raise StaticVerificationError(
                    f"List index must be Int, got {idx_t}", stmt_idx
                )
            return elem_t

        if isinstance(expr, CallExpr):
            if expr.func_name not in self.functions:
                raise StaticVerificationError(
                    f"Call to undeclared function `{expr.func_name}`", stmt_idx
                )
            param_types, ret_type = self.functions[expr.func_name]
            if len(expr.args) != len(param_types):
                raise StaticVerificationError(
                    f"Function `{expr.func_name}` expects {len(param_types)} args, got {len(expr.args)}",
                    stmt_idx,
                )
            for arg_e, expected_t in zip(expr.args, param_types, strict=True):
                actual_t = self.infer_expr_type(arg_e, scope, stmt_idx)
                if actual_t != expected_t:
                    raise StaticVerificationError(
                        f"Argument to `{expr.func_name}` expected {expected_t}, got {actual_t}",
                        stmt_idx,
                    )
            if ret_type == "Void":
                raise StaticVerificationError(
                    f"Void function `{expr.func_name}` cannot be used as an expression value",
                    stmt_idx,
                )
            return ret_type

        if isinstance(expr, ReadInputExpr):
            return expr.target_type

        raise StaticVerificationError(f"Unsupported expression node: {type(expr)!r}", stmt_idx)

    def check_stmt(
        self,
        stmt: IRStatement,
        scope: _Scope,
        stmt_idx: int | None,
        expected_return: MemeType | None = None,
    ) -> bool:
        """Validates `stmt`; returns True if statement guarantees/contains a return."""
        if isinstance(stmt, VarDeclStmt):
            if stmt.var_type == "Void":
                raise StaticVerificationError(
                    f"Variable `{stmt.name}` cannot have type Void", stmt_idx
                )
            val_t = self.infer_expr_type(stmt.value, scope, stmt_idx)
            if val_t != stmt.var_type:
                raise StaticVerificationError(
                    f"Variable `{stmt.name}` declared as {stmt.var_type} but initialized with {val_t}",
                    stmt_idx,
                )
            scope.define(stmt.name, stmt.var_type)
            return False

        if isinstance(stmt, AssignStmt):
            existing = scope.lookup(stmt.name)
            if existing is None:
                raise StaticVerificationError(
                    f"Assignment to undeclared variable `{stmt.name}`", stmt_idx
                )
            val_t = self.infer_expr_type(stmt.value, scope, stmt_idx)
            if val_t != existing:
                raise StaticVerificationError(
                    f"Cannot assign {val_t} to variable `{stmt.name}` of type {existing}",
                    stmt_idx,
                )
            return False

        if isinstance(stmt, SortCollectionStmt):
            target_t = scope.lookup(stmt.target)
            if target_t is None:
                raise StaticVerificationError(
                    f"Cannot sort undeclared variable `{stmt.target}`", stmt_idx
                )
            if _element_type_of(target_t) is None:
                raise StaticVerificationError(
                    f"`sort` requires a List variable, but `{stmt.target}` has type {target_t}",
                    stmt_idx,
                )
            return False

        if isinstance(stmt, ClampCollectionStmt):
            target_t = scope.lookup(stmt.target)
            if target_t is None:
                raise StaticVerificationError(
                    f"Cannot clamp undeclared variable `{stmt.target}`", stmt_idx
                )
            elem_t = _element_type_of(target_t)
            if elem_t not in ("Int", "Float"):
                raise StaticVerificationError(
                    f"`clamp` requires List<Int> or List<Float>, got {target_t}", stmt_idx
                )
            lo_t = self.infer_expr_type(stmt.min_val, scope, stmt_idx)
            hi_t = self.infer_expr_type(stmt.max_val, scope, stmt_idx)
            if lo_t != elem_t or hi_t != elem_t:
                raise StaticVerificationError(
                    f"Clamp bounds ({lo_t}, {hi_t}) must match element type {elem_t}", stmt_idx
                )
            return False

        if isinstance(stmt, FilterCollectionStmt):
            target_t = scope.lookup(stmt.target)
            if target_t is None:
                raise StaticVerificationError(
                    f"Cannot filter undeclared variable `{stmt.target}`", stmt_idx
                )
            elem_t = _element_type_of(target_t)
            if elem_t is None:
                raise StaticVerificationError(
                    f"`filter` requires a List variable, got {target_t}", stmt_idx
                )
            pred_scope = _Scope(parent=scope)
            pred_scope.define(stmt.item_var, elem_t)
            pred_t = self.infer_expr_type(stmt.predicate, pred_scope, stmt_idx)
            if pred_t != "Bool":
                raise StaticVerificationError(
                    f"Filter predicate must evaluate to Bool, got {pred_t}", stmt_idx
                )
            return False

        if isinstance(stmt, ListAppendStmt):
            target_t = scope.lookup(stmt.target)
            if target_t is None:
                raise StaticVerificationError(
                    f"Cannot append to undeclared variable `{stmt.target}`", stmt_idx
                )
            elem_t = _element_type_of(target_t)
            if elem_t is None:
                raise StaticVerificationError(
                    f"`append` requires a List variable, got {target_t}", stmt_idx
                )
            val_t = self.infer_expr_type(stmt.value, scope, stmt_idx)
            if val_t != elem_t:
                raise StaticVerificationError(
                    f"Cannot append {val_t} to `{stmt.target}` of type {target_t}", stmt_idx
                )
            return False

        if isinstance(stmt, PrintStmt):
            if not stmt.expressions:
                raise StaticVerificationError("`print` requires at least one expression", stmt_idx)
            for e in stmt.expressions:
                self.infer_expr_type(e, scope, stmt_idx)
            return False

        if isinstance(stmt, IfStmt):
            cond_t = self.infer_expr_type(stmt.condition, scope, stmt_idx)
            if cond_t != "Bool":
                raise StaticVerificationError(
                    f"`if` condition must evaluate to Bool, got {cond_t}", stmt_idx
                )
            then_scope = _Scope(parent=scope)
            has_ret = False
            for child in stmt.then_body:
                has_ret = self.check_stmt(child, then_scope, stmt_idx, expected_return) or has_ret
            if stmt.else_body:
                else_scope = _Scope(parent=scope)
                for child in stmt.else_body:
                    has_ret = (
                        self.check_stmt(child, else_scope, stmt_idx, expected_return) or has_ret
                    )
            return has_ret

        if isinstance(stmt, ForEachStmt):
            col_t = scope.lookup(stmt.collection)
            if col_t is None:
                raise StaticVerificationError(
                    f"`for each` references undeclared collection `{stmt.collection}`", stmt_idx
                )
            elem_t = _element_type_of(col_t)
            if elem_t is None:
                raise StaticVerificationError(
                    f"`for each` requires a List collection, got {col_t}", stmt_idx
                )
            loop_scope = _Scope(parent=scope)
            loop_scope.define(stmt.item_var, elem_t)
            has_ret = False
            for child in stmt.body:
                has_ret = self.check_stmt(child, loop_scope, stmt_idx, expected_return) or has_ret
            return has_ret

        if isinstance(stmt, ForRangeStmt):
            s_t = self.infer_expr_type(stmt.start, scope, stmt_idx)
            e_t = self.infer_expr_type(stmt.end, scope, stmt_idx)
            if s_t != "Int" or e_t != "Int":
                raise StaticVerificationError(
                    f"`for_range` bounds must be Int, got ({s_t}, {e_t})", stmt_idx
                )
            loop_scope = _Scope(parent=scope)
            loop_scope.define(stmt.loop_var, "Int")
            has_ret = False
            for child in stmt.body:
                has_ret = self.check_stmt(child, loop_scope, stmt_idx, expected_return) or has_ret
            return has_ret

        if isinstance(stmt, WhileStmt):
            cond_t = self.infer_expr_type(stmt.condition, scope, stmt_idx)
            if cond_t != "Bool":
                raise StaticVerificationError(
                    f"`while` condition must evaluate to Bool, got {cond_t}", stmt_idx
                )
            loop_scope = _Scope(parent=scope)
            has_ret = False
            for child in stmt.body:
                has_ret = self.check_stmt(child, loop_scope, stmt_idx, expected_return) or has_ret
            return has_ret

        if isinstance(stmt, FuncDefStmt):
            if expected_return is not None:
                raise StaticVerificationError("Nested function definitions are not supported", stmt_idx)
            if stmt.name in self.functions:
                raise StaticVerificationError(
                    f"Duplicate function definition `{stmt.name}`", stmt_idx
                )
            param_types: list[MemeType] = []
            fn_scope = _Scope(parent=scope)
            for p in stmt.params:
                if p.param_type == "Void":
                    raise StaticVerificationError(
                        f"Parameter `{p.name}` cannot have type Void", stmt_idx
                    )
                param_types.append(p.param_type)
                fn_scope.define(p.name, p.param_type)
            self.functions[stmt.name] = (param_types, stmt.return_type)

            saw_return = False
            for child in stmt.body:
                saw_return = self.check_stmt(child, fn_scope, stmt_idx, stmt.return_type) or saw_return
            if stmt.return_type != "Void" and not saw_return:
                raise StaticVerificationError(
                    f"Function `{stmt.name}` has return type {stmt.return_type} but no return statement",
                    stmt_idx,
                )
            return False

        if isinstance(stmt, ReturnStmt):
            if expected_return is None:
                raise StaticVerificationError("`return` statement outside of a function", stmt_idx)
            if expected_return == "Void":
                if stmt.value is not None:
                    raise StaticVerificationError(
                        "Void function cannot return a value", stmt_idx
                    )
                return True
            if stmt.value is None:
                raise StaticVerificationError(
                    f"Function expects return value of type {expected_return}", stmt_idx
                )
            ret_t = self.infer_expr_type(stmt.value, scope, stmt_idx)
            if ret_t != expected_return:
                raise StaticVerificationError(
                    f"Return value has type {ret_t}, expected {expected_return}", stmt_idx
                )
            return True

        raise StaticVerificationError(f"Unsupported statement node: {type(stmt)!r}", stmt_idx)


def verify_program(program: ProgramIR) -> ProgramIR:
    checker = _StaticChecker()
    root_scope = _Scope()
    for idx, stmt in enumerate(program.statements, start=1):
        checker.check_stmt(stmt, root_scope, stmt_idx=idx)
    return program


def verify_synthesis(result: SynthesisResult) -> VerificationOutcome:
    normalized: list[SynthesisItem] = []
    ambiguities: list[AmbiguityDiagnostic] = []

    # Pass 1: Structural collision safety net on top-level statements
    concrete_prefix: list[IRStatement] = []
    for idx, item in enumerate(result.items):
        stmt_id = idx + 1
        if isinstance(item, AmbiguityDiagnostic):
            normalized.append(item)
            ambiguities.append(item)
            continue

        if isinstance(item, ForEachStmt) and _find_collection_mutations(item.body, item.collection):
            following = [
                x for x in result.items[idx + 1 :] if not isinstance(x, AmbiguityDiagnostic)
            ]
            upgraded = _build_loop_collision_ambiguity(
                statement_id=stmt_id,
                loop_stmt=item,
                preceding_stmts=list(concrete_prefix),
                following_stmts=following,
            )
            normalized.append(upgraded)
            ambiguities.append(upgraded)
            continue

        normalized.append(item)
        concrete_prefix.append(item)

    if ambiguities:
        return VerificationOutcome(
            program=None,
            ambiguities=ambiguities,
            normalized_items=normalized,
        )

    # Pass 2: Full lexical scope & static type verification
    concrete_stmts = [cast(IRStatement, x) for x in normalized]
    prog = verify_program(ProgramIR(statements=concrete_stmts))
    return VerificationOutcome(
        program=prog,
        ambiguities=[],
        normalized_items=normalized,
    )

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
    FailStmt,
    FilterCollectionStmt,
    ForEachStmt,
    ForRangeStmt,
    FuncDefStmt,
    IRExpr,
    IRStatement,
    IfStmt,
    ListAppendStmt,
    ListIndexExpr,
    ListInsertStmt,
    ListLengthExpr,
    ListLiteralExpr,
    ListSetIndexStmt,
    LiteralExpr,
    MemeType,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    ReturnStmt,
    SortCollectionStmt,
    StrEndsWithExpr,
    StringLengthExpr,
    StringSliceExpr,
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

    @property
    def passed(self) -> bool:
        return self.is_unambiguous


class _Scope:
    def __init__(self, parent: _Scope | None = None) -> None:
        self.parent = parent
        self.symbols: dict[str, MemeType] = {}
        self.empty_lists: set[str] = set()

    def lookup(self, name: str) -> MemeType | None:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        return None

    def define(self, name: str, meme_type: MemeType, is_empty_list: bool = False) -> None:
        self.symbols[name] = meme_type
        if is_empty_list:
            self.empty_lists.add(name)

    def mark_populated(self, name: str) -> None:
        if name in self.symbols:
            self.empty_lists.discard(name)
        elif self.parent is not None:
            self.parent.mark_populated(name)

    def is_unpopulated_empty_list(self, name: str) -> bool:
        if name in self.symbols:
            return name in self.empty_lists
        if self.parent is not None:
            return self.parent.is_unpopulated_empty_list(name)
        return False


def _element_type_of(list_type: MemeType) -> MemeType | None:
    if list_type.startswith("List<") and list_type.endswith(">"):
        return cast(MemeType, list_type[5:-1])
    return None


def _find_collection_mutations(stmts: list[IRStatement], collection: str) -> list[IRStatement]:
    hits: list[IRStatement] = []
    for s in stmts:
        if isinstance(
            s,
            (
                SortCollectionStmt,
                ClampCollectionStmt,
                FilterCollectionStmt,
                ListAppendStmt,
                ListInsertStmt,
                ListSetIndexStmt,
            ),
        ) and s.target == collection:
            hits.append(s)
        elif isinstance(s, IfStmt):
            hits.extend(_find_collection_mutations(s.then_body, collection))
            hits.extend(_find_collection_mutations(s.else_body, collection))
        elif isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt)):
            hits.extend(_find_collection_mutations(s.body, collection))
    return hits


def _branch_adds_to(stmts: list[IRStatement], target: str) -> bool:
    for s in stmts:
        if isinstance(s, (ListInsertStmt, ListAppendStmt)) and s.target == target:
            return True
        if isinstance(s, IfStmt) and (
            _branch_adds_to(s.then_body, target) or _branch_adds_to(s.else_body, target)
        ):
            return True
        if isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt)) and _branch_adds_to(
            s.body, target
        ):
            return True
    return False


def _has_asymmetric_insert(stmts: list[IRStatement], target: str) -> bool:
    for s in stmts:
        if isinstance(s, IfStmt):
            t_adds = _branch_adds_to(s.then_body, target)
            e_adds = _branch_adds_to(s.else_body, target)
            if t_adds != e_adds:
                return True
            if _has_asymmetric_insert(s.then_body, target) or _has_asymmetric_insert(
                s.else_body, target
            ):
                return True
        elif isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt)):
            if _has_asymmetric_insert(s.body, target):
                return True
    return False


def _contains_loop_with_asymmetric_insert(stmts: list[IRStatement], target: str) -> bool:
    for s in stmts:
        if isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt)):
            if _has_asymmetric_insert(s.body, target) or _contains_loop_with_asymmetric_insert(
                s.body, target
            ):
                return True
        elif isinstance(s, IfStmt):
            if _contains_loop_with_asymmetric_insert(
                s.then_body, target
            ) or _contains_loop_with_asymmetric_insert(s.else_body, target):
                return True
    return False


def _returns_index_of(stmts: list[IRStatement], target: str) -> bool:
    for s in stmts:
        if isinstance(s, ReturnStmt) and isinstance(s.value, ListIndexExpr):
            if isinstance(s.value.target, VarRefExpr) and s.value.target.name == target:
                return True
        elif isinstance(s, IfStmt):
            if _returns_index_of(s.then_body, target) or _returns_index_of(s.else_body, target):
                return True
        elif isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt)):
            if _returns_index_of(s.body, target):
                return True
    return False


def _collect_empty_list_decls(stmts: list[IRStatement]) -> list[str]:
    names: list[str] = []
    for s in stmts:
        if (
            isinstance(s, VarDeclStmt)
            and isinstance(s.value, ListLiteralExpr)
            and len(s.value.elements) == 0
        ):
            names.append(s.name)
        elif isinstance(s, IfStmt):
            names.extend(_collect_empty_list_decls(s.then_body))
            names.extend(_collect_empty_list_decls(s.else_body))
    return names


def _build_lossy_partial_sort_ambiguity(
    statement_id: int,
    func_stmt: FuncDefStmt,
) -> AmbiguityDiagnostic | None:
    if len(func_stmt.params) != 1:
        return None
    param = func_stmt.params[0]
    elem_t = _element_type_of(param.param_type)
    if elem_t is None or elem_t != func_stmt.return_type:
        return None

    empty_lists = _collect_empty_list_decls(func_stmt.body)
    acc_name: str | None = None
    for cand_acc in empty_lists:
        if _contains_loop_with_asymmetric_insert(func_stmt.body, cand_acc) and _returns_index_of(
            func_stmt.body, cand_acc
        ):
            acc_name = cand_acc
            break

    if acc_name is None:
        return None

    # Ensure the literal function itself is type-valid before offering it as Option 2
    checker = _StaticChecker()
    checker.check_stmt(func_stmt, _Scope(), stmt_idx=statement_id)

    copy_var = "unsorted" if param.name != "unsorted" else "sorted_copy"
    opt1_fn = FuncDefStmt(
        name=func_stmt.name,
        params=func_stmt.params,
        return_type=func_stmt.return_type,
        source_line=func_stmt.source_line,
        body=[
            IfStmt(
                condition=BinaryOpExpr(
                    op="==",
                    left=ListLengthExpr(target=VarRefExpr(name=param.name)),
                    right=LiteralExpr(value=0, data_type="Int"),
                ),
                then_body=[FailStmt(message=LiteralExpr(value="Empty list", data_type="String"))],
                else_body=[],
            ),
            VarDeclStmt(
                name=copy_var,
                var_type=param.param_type,
                value=VarRefExpr(name=param.name),
            ),
            SortCollectionStmt(target=copy_var, direction="ascending"),
            ReturnStmt(
                value=ListIndexExpr(
                    target=VarRefExpr(name=copy_var),
                    index=BinaryOpExpr(
                        op="-",
                        left=ListLengthExpr(target=VarRefExpr(name=copy_var)),
                        right=LiteralExpr(value=1, data_type="Int"),
                    ),
                )
            ),
        ],
    )

    return AmbiguityDiagnostic(
        statement_id=statement_id,
        source_line=func_stmt.source_line or statement_id,
        source_text=f"function {func_stmt.name}({param.name})",
        reason=(
            f"Loop in `{func_stmt.name}` only inserts items into `{acc_name}` on one branch "
            f"(skipping larger elements in `else`), contradicting full-sort / largest-element intent."
        ),
        candidates=[
            AmbiguityCandidate(
                option=1,
                description=f"Sort all elements of `{param.name}` ascending and return the last (largest) item",
                canonical_meme=to_canonical_meme(ProgramIR(statements=[opt1_fn])),
                replacement_ir=[opt1_fn],
                replaces_whole_program=False,
            ),
            AmbiguityCandidate(
                option=2,
                description=f"Execute partial insertion into `{acc_name}` literally (skipping larger elements) and return `{acc_name}`'s last item",
                canonical_meme=to_canonical_meme(ProgramIR(statements=[func_stmt])),
                replacement_ir=[func_stmt],
                replaces_whole_program=False,
            ),
        ],
    )


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


def _check_literal_bounds(lo: IRExpr, hi: IRExpr, stmt_idx: int | None) -> None:
    if (
        isinstance(lo, LiteralExpr)
        and isinstance(hi, LiteralExpr)
        and isinstance(lo.value, (int, float))
        and isinstance(hi.value, (int, float))
        and not isinstance(lo.value, bool)
        and not isinstance(hi.value, bool)
        and lo.value > hi.value
    ):
        raise StaticVerificationError(
            f"Minimum bound ({lo.value}) cannot exceed maximum bound ({hi.value})",
            stmt_idx,
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
            _check_literal_bounds(expr.min_val, expr.max_val, stmt_idx)
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
            _check_literal_bounds(expr.min_val, expr.max_val, stmt_idx)
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

            if expr.op in ("-", "*", "/", "%"):
                if left_t == right_t and left_t in ("Int", "Float"):
                    return left_t
                raise StaticVerificationError(
                    f"Incompatible operand types for `{expr.op}`: {left_t} and {right_t}",
                    stmt_idx,
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
            if isinstance(expr.target, VarRefExpr) and scope.is_unpopulated_empty_list(
                expr.target.name
            ):
                raise StaticVerificationError(
                    f"Indexing into list `{expr.target.name}` which was initialized empty and never populated",
                    stmt_idx,
                )
            idx_t = self.infer_expr_type(expr.index, scope, stmt_idx)
            if idx_t != "Int":
                raise StaticVerificationError(
                    f"List index must be Int, got {idx_t}", stmt_idx
                )
            if (
                isinstance(expr.index, LiteralExpr)
                and isinstance(expr.index.value, int)
                and not isinstance(expr.index.value, bool)
                and expr.index.value < 0
            ):
                raise StaticVerificationError(
                    f"Negative list index ({expr.index.value}) is not allowed", stmt_idx
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

        if isinstance(expr, StrEndsWithExpr):
            t_t = self.infer_expr_type(expr.target, scope, stmt_idx)
            s_t = self.infer_expr_type(expr.suffix, scope, stmt_idx)
            if t_t != "String" or s_t != "String":
                raise StaticVerificationError(
                    f"`str_ends_with` requires String operands, got ({t_t}, {s_t})", stmt_idx
                )
            return "Bool"

        if isinstance(expr, ReadJsonListExpr):
            fp_t = self.infer_expr_type(expr.filepath, scope, stmt_idx)
            if fp_t != "String":
                raise StaticVerificationError(
                    f"`read_json_list` requires String filepath, got {fp_t}", stmt_idx
                )
            return "List<Float>"

        if isinstance(expr, StringLengthExpr):
            target_t = self.infer_expr_type(expr.target, scope, stmt_idx)
            if target_t != "String":
                raise StaticVerificationError(
                    f"`string_length` requires a String target, got {target_t}", stmt_idx
                )
            return "Int"

        if isinstance(expr, StringSliceExpr):
            target_t = self.infer_expr_type(expr.target, scope, stmt_idx)
            if target_t != "String":
                raise StaticVerificationError(
                    f"`string_slice` requires a String target, got {target_t}", stmt_idx
                )
            start_t = self.infer_expr_type(expr.start, scope, stmt_idx)
            end_t = self.infer_expr_type(expr.end, scope, stmt_idx)
            if start_t != "Int" or end_t != "Int":
                raise StaticVerificationError(
                    f"`string_slice` indices must be Int, got ({start_t}, {end_t})", stmt_idx
                )
            if (
                isinstance(expr.start, LiteralExpr)
                and isinstance(expr.start.value, int)
                and not isinstance(expr.start.value, bool)
                and expr.start.value < 0
            ) or (
                isinstance(expr.end, LiteralExpr)
                and isinstance(expr.end.value, int)
                and not isinstance(expr.end.value, bool)
                and expr.end.value < 0
            ):
                raise StaticVerificationError(
                    "Negative string slice index is not allowed", stmt_idx
                )
            _check_literal_bounds(expr.start, expr.end, stmt_idx)
            return "String"

        raise StaticVerificationError(f"Unsupported expression node: {type(expr)!r}", stmt_idx)

    def check_stmt(
        self,
        stmt: IRStatement,
        scope: _Scope,
        stmt_idx: int | None,
        expected_return: MemeType | None = None,
    ) -> bool:
        """Validates `stmt`; returns True iff statement guarantees a return on all paths."""
        if isinstance(stmt, VarDeclStmt):
            if stmt.var_type == "Void":
                raise StaticVerificationError(
                    f"Variable `{stmt.name}` cannot have type Void", stmt_idx
                )
            if stmt.name in scope.symbols:
                raise StaticVerificationError(
                    f"Variable `{stmt.name}` is already declared in this scope", stmt_idx
                )
            val_t = self.infer_expr_type(stmt.value, scope, stmt_idx)
            if val_t != stmt.var_type:
                raise StaticVerificationError(
                    f"Variable `{stmt.name}` declared as {stmt.var_type} but initialized with {val_t}",
                    stmt_idx,
                )
            is_empty = isinstance(stmt.value, ListLiteralExpr) and len(stmt.value.elements) == 0
            scope.define(stmt.name, stmt.var_type, is_empty_list=is_empty)
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
            if not (isinstance(stmt.value, ListLiteralExpr) and len(stmt.value.elements) == 0):
                scope.mark_populated(stmt.name)
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
            _check_literal_bounds(stmt.min_val, stmt.max_val, stmt_idx)
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
            scope.mark_populated(stmt.target)
            return False

        if isinstance(stmt, ListInsertStmt):
            target_t = scope.lookup(stmt.target)
            if target_t is None:
                raise StaticVerificationError(
                    f"Cannot insert into undeclared variable `{stmt.target}`", stmt_idx
                )
            elem_t = _element_type_of(target_t)
            if elem_t is None:
                raise StaticVerificationError(
                    f"`list_insert` requires a List variable, got {target_t}", stmt_idx
                )
            idx_t = self.infer_expr_type(stmt.index, scope, stmt_idx)
            if idx_t != "Int":
                raise StaticVerificationError(
                    f"`list_insert` index must be Int, got {idx_t}", stmt_idx
                )
            if (
                isinstance(stmt.index, LiteralExpr)
                and isinstance(stmt.index.value, int)
                and not isinstance(stmt.index.value, bool)
                and stmt.index.value < 0
            ):
                raise StaticVerificationError(
                    f"Negative list insert index ({stmt.index.value}) is not allowed", stmt_idx
                )
            val_t = self.infer_expr_type(stmt.value, scope, stmt_idx)
            if val_t != elem_t:
                raise StaticVerificationError(
                    f"Cannot insert {val_t} into `{stmt.target}` of type {target_t}", stmt_idx
                )
            scope.mark_populated(stmt.target)
            return False

        if isinstance(stmt, ListSetIndexStmt):
            target_t = scope.lookup(stmt.target)
            if target_t is None:
                raise StaticVerificationError(
                    f"Cannot set index of undeclared variable `{stmt.target}`", stmt_idx
                )
            elem_t = _element_type_of(target_t)
            if elem_t is None:
                raise StaticVerificationError(
                    f"`list_set_index` requires a List variable, got {target_t}", stmt_idx
                )
            idx_t = self.infer_expr_type(stmt.index, scope, stmt_idx)
            if idx_t != "Int":
                raise StaticVerificationError(
                    f"`list_set_index` index must be Int, got {idx_t}", stmt_idx
                )
            if (
                isinstance(stmt.index, LiteralExpr)
                and isinstance(stmt.index.value, int)
                and not isinstance(stmt.index.value, bool)
                and stmt.index.value < 0
            ):
                raise StaticVerificationError(
                    f"Negative list set index ({stmt.index.value}) is not allowed", stmt_idx
                )
            val_t = self.infer_expr_type(stmt.value, scope, stmt_idx)
            if val_t != elem_t:
                raise StaticVerificationError(
                    f"Cannot assign {val_t} to element of {target_t}", stmt_idx
                )
            scope.mark_populated(stmt.target)
            return False

        if isinstance(stmt, FailStmt):
            msg_t = self.infer_expr_type(stmt.message, scope, stmt_idx)
            if msg_t != "String":
                raise StaticVerificationError(
                    f"`fail_stmt` requires String message, got {msg_t}", stmt_idx
                )
            return True

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
            then_ret = False
            for child in stmt.then_body:
                then_ret = self.check_stmt(child, then_scope, stmt_idx, expected_return) or then_ret
            else_ret = False
            if stmt.else_body:
                else_scope = _Scope(parent=scope)
                for child in stmt.else_body:
                    else_ret = (
                        self.check_stmt(child, else_scope, stmt_idx, expected_return) or else_ret
                    )
            return then_ret and bool(stmt.else_body) and else_ret

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
            for child in stmt.body:
                self.check_stmt(child, loop_scope, stmt_idx, expected_return)
            return False

        if isinstance(stmt, ForRangeStmt):
            s_t = self.infer_expr_type(stmt.start, scope, stmt_idx)
            e_t = self.infer_expr_type(stmt.end, scope, stmt_idx)
            if s_t != "Int" or e_t != "Int":
                raise StaticVerificationError(
                    f"`for_range` bounds must be Int, got ({s_t}, {e_t})", stmt_idx
                )
            loop_scope = _Scope(parent=scope)
            loop_scope.define(stmt.loop_var, "Int")
            for child in stmt.body:
                self.check_stmt(child, loop_scope, stmt_idx, expected_return)
            return False

        if isinstance(stmt, WhileStmt):
            cond_t = self.infer_expr_type(stmt.condition, scope, stmt_idx)
            if cond_t != "Bool":
                raise StaticVerificationError(
                    f"`while` condition must evaluate to Bool, got {cond_t}", stmt_idx
                )
            loop_scope = _Scope(parent=scope)
            for child in stmt.body:
                self.check_stmt(child, loop_scope, stmt_idx, expected_return)
            return False

        if isinstance(stmt, FuncDefStmt):
            if expected_return is not None:
                raise StaticVerificationError("Nested function definitions are not supported", stmt_idx)
            if stmt.name in self.functions:
                raise StaticVerificationError(
                    f"Duplicate function definition `{stmt.name}`", stmt_idx
                )
            param_types: list[MemeType] = []
            fn_scope = _Scope(parent=None)
            for p in stmt.params:
                if p.param_type == "Void":
                    raise StaticVerificationError(
                        f"Parameter `{p.name}` cannot have type Void", stmt_idx
                    )
                if p.name in fn_scope.symbols:
                    raise StaticVerificationError(
                        f"Duplicate parameter name `{p.name}` in function `{stmt.name}`", stmt_idx
                    )
                param_types.append(p.param_type)
                fn_scope.define(p.name, p.param_type)
            self.functions[stmt.name] = (param_types, stmt.return_type)

            saw_return = False
            for child in stmt.body:
                saw_return = self.check_stmt(child, fn_scope, stmt_idx, stmt.return_type) or saw_return
            if stmt.return_type != "Void" and not saw_return:
                raise StaticVerificationError(
                    f"Function `{stmt.name}` has return type {stmt.return_type} but does not return on all control paths",
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


def _expr_references_var(expr: IRExpr, name: str) -> bool:
    if isinstance(expr, VarRefExpr):
        return expr.name == name
    if isinstance(expr, ListLiteralExpr):
        return any(_expr_references_var(e, name) for e in expr.elements)
    if isinstance(expr, RandomIntExpr):
        return _expr_references_var(expr.min_val, name) or _expr_references_var(expr.max_val, name)
    if isinstance(expr, RandomListExpr):
        return (
            _expr_references_var(expr.count, name)
            or _expr_references_var(expr.min_val, name)
            or _expr_references_var(expr.max_val, name)
        )
    if isinstance(expr, BinaryOpExpr):
        return _expr_references_var(expr.left, name) or _expr_references_var(expr.right, name)
    if isinstance(expr, UnaryOpExpr):
        return _expr_references_var(expr.operand, name)
    if isinstance(expr, ListLengthExpr):
        return _expr_references_var(expr.target, name)
    if isinstance(expr, ListIndexExpr):
        return _expr_references_var(expr.target, name) or _expr_references_var(expr.index, name)
    if isinstance(expr, CallExpr):
        return any(_expr_references_var(a, name) for a in expr.args)
    if isinstance(expr, StrEndsWithExpr):
        return _expr_references_var(expr.target, name) or _expr_references_var(expr.suffix, name)
    if isinstance(expr, ReadJsonListExpr):
        return _expr_references_var(expr.filepath, name)
    if isinstance(expr, StringLengthExpr):
        return _expr_references_var(expr.target, name)
    if isinstance(expr, StringSliceExpr):
        return (
            _expr_references_var(expr.target, name)
            or _expr_references_var(expr.start, name)
            or _expr_references_var(expr.end, name)
        )
    return False


def _stmts_reference_var(stmts: list[IRStatement], name: str) -> bool:
    for s in stmts:
        if isinstance(s, VarDeclStmt) and _expr_references_var(s.value, name):
            return True
        if isinstance(s, AssignStmt) and (
            s.name == name or _expr_references_var(s.value, name)
        ):
            return True
        if isinstance(s, ListAppendStmt) and (
            s.target == name or _expr_references_var(s.value, name)
        ):
            return True
        if isinstance(s, (ListInsertStmt, ListSetIndexStmt)) and (
            s.target == name
            or _expr_references_var(s.index, name)
            or _expr_references_var(s.value, name)
        ):
            return True
        if isinstance(s, (SortCollectionStmt, ClampCollectionStmt, FilterCollectionStmt)) and (
            s.target == name
        ):
            return True
        if isinstance(s, ClampCollectionStmt) and (
            _expr_references_var(s.min_val, name) or _expr_references_var(s.max_val, name)
        ):
            return True
        if isinstance(s, FilterCollectionStmt) and _expr_references_var(s.predicate, name):
            return True
        if isinstance(s, FailStmt) and _expr_references_var(s.message, name):
            return True
        if isinstance(s, PrintStmt) and any(
            _expr_references_var(e, name) for e in s.expressions
        ):
            return True
        if isinstance(s, ReturnStmt) and s.value is not None and _expr_references_var(
            s.value, name
        ):
            return True
        if isinstance(s, IfStmt) and (
            _expr_references_var(s.condition, name)
            or _stmts_reference_var(s.then_body, name)
            or _stmts_reference_var(s.else_body, name)
        ):
            return True
        if isinstance(s, ForEachStmt) and (
            s.collection == name or _stmts_reference_var(s.body, name)
        ):
            return True
        if isinstance(s, ForRangeStmt) and (
            _expr_references_var(s.start, name)
            or _expr_references_var(s.end, name)
            or _stmts_reference_var(s.body, name)
        ):
            return True
        if isinstance(s, WhileStmt) and (
            _expr_references_var(s.condition, name) or _stmts_reference_var(s.body, name)
        ):
            return True
    return False


def _stmts_mutate_var(stmts: list[IRStatement], name: str) -> bool:
    for s in stmts:
        if isinstance(s, AssignStmt) and s.name == name:
            return True
        if isinstance(
            s,
            (
                ListAppendStmt,
                ListInsertStmt,
                ListSetIndexStmt,
                SortCollectionStmt,
                ClampCollectionStmt,
                FilterCollectionStmt,
            ),
        ) and s.target == name:
            return True
        if isinstance(s, IfStmt) and (
            _stmts_mutate_var(s.then_body, name) or _stmts_mutate_var(s.else_body, name)
        ):
            return True
        if isinstance(s, (ForEachStmt, ForRangeStmt, WhileStmt)) and _stmts_mutate_var(
            s.body, name
        ):
            return True
    return False


def _normalize_sort_into_empty(stmts: list[IRStatement]) -> list[IRStatement]:
    unmutated_empty: list[str] = [
        s.name
        for s in stmts
        if isinstance(s, VarDeclStmt)
        and isinstance(s.value, ListLiteralExpr)
        and len(s.value.elements) == 0
        and not _stmts_mutate_var(stmts, s.name)
    ]
    out: list[IRStatement] = []
    for idx, s in enumerate(stmts):
        if isinstance(s, FuncDefStmt):
            out.append(
                FuncDefStmt(
                    name=s.name,
                    params=s.params,
                    return_type=s.return_type,
                    body=_normalize_sort_into_empty(s.body),
                    source_line=s.source_line,
                )
            )
            continue
        if isinstance(s, SortCollectionStmt) and unmutated_empty:
            rest = stmts[idx + 1 :]
            declared_before = {
                prev.name for prev in stmts[:idx] if isinstance(prev, VarDeclStmt)
            }
            matched_dst: str | None = None
            for cand in unmutated_empty:
                if (
                    cand != s.target
                    and cand in declared_before
                    and _stmts_reference_var(rest, cand)
                    and not _stmts_reference_var(rest, s.target)
                ):
                    matched_dst = cand
                    break
            if matched_dst is not None:
                unmutated_empty.remove(matched_dst)
                out.append(
                    AssignStmt(
                        name=matched_dst,
                        value=VarRefExpr(name=s.target),
                        source_line=s.source_line,
                    )
                )
                out.append(
                    SortCollectionStmt(
                        target=matched_dst,
                        direction=s.direction,
                        source_line=s.source_line,
                    )
                )
                continue
        out.append(s)
    return out


def verify_program(program: ProgramIR) -> ProgramIR:
    checker = _StaticChecker()
    root_scope = _Scope()
    for idx, stmt in enumerate(program.statements, start=1):
        checker.check_stmt(stmt, root_scope, stmt_idx=idx)
    return program


def verify_synthesis(
    result: SynthesisResult | ProgramIR,
    detect_implicit_ambiguities: bool = True,
) -> VerificationOutcome:
    if isinstance(result, ProgramIR):
        result = SynthesisResult(items=cast(list[SynthesisItem], result.statements))

    # Unwrap `FuncDefStmt(name="main", params=[], return_type="Void")` if no top-level main statements exist
    has_top_exec = any(
        not isinstance(it, (FuncDefStmt, AmbiguityDiagnostic)) for it in result.items
    )
    items_in: list[SynthesisItem] = []
    for it in result.items:
        if (
            not has_top_exec
            and isinstance(it, FuncDefStmt)
            and it.name == "main"
            and len(it.params) == 0
            and it.return_type == "Void"
        ):
            items_in.extend(it.body)
        else:
            items_in.append(it)

    normalized: list[SynthesisItem] = []
    ambiguities: list[AmbiguityDiagnostic] = []

    # Pass 1: Structural collision safety net on top-level statements
    concrete_prefix: list[IRStatement] = []
    for idx, item in enumerate(items_in):
        stmt_id = idx + 1
        if isinstance(item, AmbiguityDiagnostic):
            normalized.append(item)
            ambiguities.append(item)
            continue

        if detect_implicit_ambiguities:
            if isinstance(item, ForEachStmt) and _find_collection_mutations(
                item.body, item.collection
            ):
                following = [
                    x for x in items_in[idx + 1 :] if not isinstance(x, AmbiguityDiagnostic)
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

            if isinstance(item, FuncDefStmt):
                lossy_diag = _build_lossy_partial_sort_ambiguity(stmt_id, item)
                if lossy_diag is not None:
                    normalized.append(lossy_diag)
                    ambiguities.append(lossy_diag)
                    continue

        normalized.append(item)
        concrete_prefix.append(item)

    if ambiguities:
        return VerificationOutcome(
            program=None,
            ambiguities=ambiguities,
            normalized_items=normalized,
        )

    # Pass 2: Normalize `sort A into B` when `B` is an unmutated empty list, then verify
    concrete_stmts = _normalize_sort_into_empty([cast(IRStatement, x) for x in normalized])
    prog = verify_program(ProgramIR(statements=concrete_stmts))
    return VerificationOutcome(
        program=prog,
        ambiguities=[],
        normalized_items=[*concrete_stmts],
    )

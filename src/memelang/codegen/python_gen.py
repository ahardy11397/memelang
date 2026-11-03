"""Deterministic Python 3 code generator for Memelang ProgramIR."""

from __future__ import annotations

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
    MemeType,
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


class _PyGen:
    def __init__(self) -> None:
        self.uses_random = False
        self.symbols: dict[str, MemeType] = {}
        self.func_returns: dict[str, MemeType] = {}

    def infer_type(self, expr: IRExpr, scope: dict[str, MemeType]) -> MemeType:
        if isinstance(expr, LiteralExpr):
            return expr.data_type
        if isinstance(expr, ListLiteralExpr):
            return f"List<{expr.element_type}>"  # type: ignore[return-value]
        if isinstance(expr, VarRefExpr):
            return scope.get(expr.name, "Int")
        if isinstance(expr, RandomListExpr):
            return "List<Int>"
        if isinstance(expr, (RandomIntExpr, ListLengthExpr)):
            return "Int"
        if isinstance(expr, ListIndexExpr):
            col_t = self.infer_type(expr.target, scope)
            return col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[return-value]
        if isinstance(expr, CallExpr):
            return self.func_returns.get(expr.func_name, "Int")
        if isinstance(expr, ReadInputExpr):
            return expr.target_type
        if isinstance(expr, UnaryOpExpr):
            return "Bool" if expr.op == "not" else self.infer_type(expr.operand, scope)
        if isinstance(expr, BinaryOpExpr):
            if expr.op in ("==", "!=", "<", "<=", ">", ">=", "and", "or"):
                return "Bool"
            return self.infer_type(expr.left, scope)
        return "Int"

    def gen_expr(self, expr: IRExpr, scope: dict[str, MemeType]) -> str:
        if isinstance(expr, LiteralExpr):
            if expr.data_type == "Bool":
                return "True" if expr.value else "False"
            return repr(expr.value)

        if isinstance(expr, ListLiteralExpr):
            inner = ", ".join(self.gen_expr(e, scope) for e in expr.elements)
            return f"[{inner}]"

        if isinstance(expr, VarRefExpr):
            return expr.name

        if isinstance(expr, RandomIntExpr):
            self.uses_random = True
            return f"random.randint({self.gen_expr(expr.min_val, scope)}, {self.gen_expr(expr.max_val, scope)})"

        if isinstance(expr, RandomListExpr):
            self.uses_random = True
            c = self.gen_expr(expr.count, scope)
            lo = self.gen_expr(expr.min_val, scope)
            hi = self.gen_expr(expr.max_val, scope)
            return f"[random.randint({lo}, {hi}) for _ in range({c})]"

        if isinstance(expr, UnaryOpExpr):
            if expr.op == "not":
                return f"(not {self.gen_expr(expr.operand, scope)})"
            return f"(-{self.gen_expr(expr.operand, scope)})"

        if isinstance(expr, BinaryOpExpr):
            left = self.gen_expr(expr.left, scope)
            right = self.gen_expr(expr.right, scope)
            if expr.op == "/" and self.infer_type(expr.left, scope) == "Int":
                return f"int({left} / {right})"
            return f"({left} {expr.op} {right})"

        if isinstance(expr, ListLengthExpr):
            return f"len({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ListIndexExpr):
            return f"{self.gen_expr(expr.target, scope)}[{self.gen_expr(expr.index, scope)}]"

        if isinstance(expr, CallExpr):
            args = ", ".join(self.gen_expr(a, scope) for a in expr.args)
            return f"{expr.func_name}({args})"

        if isinstance(expr, ReadInputExpr):
            raw = f"input({repr(expr.prompt)})"
            if expr.target_type == "Int":
                return f"int({raw}.strip())"
            if expr.target_type == "Float":
                return f"float({raw}.strip())"
            if expr.target_type == "Bool":
                return f"({raw}.strip().lower() in ('true', '1', 'yes'))"
            return raw

        raise TypeError(f"Unsupported IRExpr: {type(expr)!r}")

    def gen_stmt(
        self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 0
    ) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            scope[stmt.name] = stmt.var_type
            return [f"{pad}{stmt.name} = {self.gen_expr(stmt.value, scope)}"]

        if isinstance(stmt, AssignStmt):
            return [f"{pad}{stmt.name} = {self.gen_expr(stmt.value, scope)}"]

        if isinstance(stmt, SortCollectionStmt):
            rev = "True" if stmt.direction == "descending" else "False"
            return [f"{pad}{stmt.target}.sort(reverse={rev})"]

        if isinstance(stmt, ClampCollectionStmt):
            lo = self.gen_expr(stmt.min_val, scope)
            hi = self.gen_expr(stmt.max_val, scope)
            return [
                f"{pad}{stmt.target} = [min(max(_x, {lo}), {hi}) for _x in {stmt.target}]"
            ]

        if isinstance(stmt, FilterCollectionStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.target, "List<Int>")
            sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
            pred = self.gen_expr(stmt.predicate, sub)
            return [
                f"{pad}{stmt.target} = [{stmt.item_var} for {stmt.item_var} in {stmt.target} if {pred}]"
            ]

        if isinstance(stmt, ListAppendStmt):
            return [f"{pad}{stmt.target}.append({self.gen_expr(stmt.value, scope)})"]

        if isinstance(stmt, PrintStmt):
            parts = ", ".join(f"_meme_fmt({self.gen_expr(e, scope)})" for e in stmt.expressions)
            return [f"{pad}print({parts})"]

        if isinstance(stmt, IfStmt):
            lines = [f"{pad}if {self.gen_expr(stmt.condition, scope)}:"]
            then_scope = dict(scope)
            if stmt.then_body:
                for ch in stmt.then_body:
                    lines.extend(self.gen_stmt(ch, then_scope, indent + 1))
            else:
                lines.append(f"{pad}    pass")
            if stmt.else_body:
                lines.append(f"{pad}else:")
                else_scope = dict(scope)
                for ch in stmt.else_body:
                    lines.extend(self.gen_stmt(ch, else_scope, indent + 1))
            return lines

        if isinstance(stmt, ForEachStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.collection, "List<Int>")
            sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
            lines = [f"{pad}for {stmt.item_var} in list({stmt.collection}):"]
            if stmt.body:
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 1))
            else:
                lines.append(f"{pad}    pass")
            return lines

        if isinstance(stmt, ForRangeStmt):
            sub = dict(scope)
            sub[stmt.loop_var] = "Int"
            start_s = self.gen_expr(stmt.start, scope)
            end_s = self.gen_expr(stmt.end, scope)
            lines = [f"{pad}for {stmt.loop_var} in range({start_s}, ({end_s}) + 1):"]
            if stmt.body:
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 1))
            else:
                lines.append(f"{pad}    pass")
            return lines

        if isinstance(stmt, WhileStmt):
            lines = [f"{pad}while {self.gen_expr(stmt.condition, scope)}:"]
            sub = dict(scope)
            if stmt.body:
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 1))
            else:
                lines.append(f"{pad}    pass")
            return lines

        if isinstance(stmt, FuncDefStmt):
            self.func_returns[stmt.name] = stmt.return_type
            params = ", ".join(p.name for p in stmt.params)
            fn_scope = dict(scope)
            for p in stmt.params:
                fn_scope[p.name] = p.param_type
            lines = [f"{pad}def {stmt.name}({params}):"]
            if stmt.body:
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, fn_scope, indent + 1))
            else:
                lines.append(f"{pad}    pass")
            return lines

        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                return [f"{pad}return"]
            return [f"{pad}return {self.gen_expr(stmt.value, scope)}"]

        raise TypeError(f"Unsupported IRStatement: {type(stmt)!r}")


def generate_python(ir: ProgramIR) -> str:
    gen = _PyGen()
    body_lines: list[str] = []
    for stmt in ir.statements:
        body_lines.extend(gen.gen_stmt(stmt, gen.symbols, indent=1))
    if not body_lines:
        body_lines.append("    pass")

    header: list[str] = []
    if gen.uses_random:
        header.append("import random")
        header.append("")

    header.extend(
        [
            "def _meme_fmt(val):",
            "    if isinstance(val, bool):",
            "        return 'true' if val else 'false'",
            "    if isinstance(val, list):",
            "        return '[' + ', '.join(_meme_fmt(x) for x in val) + ']'",
            "    return str(val)",
            "",
            "def main() -> None:",
        ]
    )
    header.extend(body_lines)
    header.extend(["", 'if __name__ == "__main__":', "    main()", ""])
    return "\n".join(header)

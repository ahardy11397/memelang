"""Deterministic Python 3 code generator for Memelang ProgramIR."""

from __future__ import annotations

import keyword

from memelang.ir.schema import (
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
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
)


def _py_ident(name: str) -> str:
    return f"meme_{name}" if keyword.iskeyword(name) or name.startswith("_meme_") else name


class _PyGen:
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_math = False
        self.uses_json_io = False
        self.uses_input_helpers = False
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
        if isinstance(expr, ReadJsonListExpr):
            return "List<Float>"
        if isinstance(expr, StrEndsWithExpr):
            return "Bool"
        if isinstance(expr, (RandomIntExpr, ListLengthExpr, StringLengthExpr)):
            return "Int"
        if isinstance(expr, StringSliceExpr):
            return "String"
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
            return _py_ident(expr.name)

        if isinstance(expr, RandomIntExpr):
            self.uses_random = True
            return f"_meme_rand_int({self.gen_expr(expr.min_val, scope)}, {self.gen_expr(expr.max_val, scope)})"

        if isinstance(expr, RandomListExpr):
            self.uses_random = True
            c = self.gen_expr(expr.count, scope)
            lo = self.gen_expr(expr.min_val, scope)
            hi = self.gen_expr(expr.max_val, scope)
            return f"[_meme_rand_int({lo}, {hi}) for _ in _meme_builtins.range({c})]"

        if isinstance(expr, UnaryOpExpr):
            if expr.op == "not":
                return f"(not {self.gen_expr(expr.operand, scope)})"
            return f"(-{self.gen_expr(expr.operand, scope)})"

        if isinstance(expr, BinaryOpExpr):
            left = self.gen_expr(expr.left, scope)
            right = self.gen_expr(expr.right, scope)
            left_t = self.infer_type(expr.left, scope)
            if expr.op == "/" and left_t == "Int":
                self.uses_math = True
                return f"_meme_int_div({left}, {right})"
            if expr.op == "%" and left_t == "Int":
                self.uses_math = True
                return f"_meme_int_mod({left}, {right})"
            if expr.op == "%" and left_t == "Float":
                self.uses_math = True
                return f"_meme_math.fmod({left}, {right})"
            return f"({left} {expr.op} {right})"

        if isinstance(expr, ListLengthExpr):
            return f"_meme_builtins.len({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ListIndexExpr):
            return f"{self.gen_expr(expr.target, scope)}[{self.gen_expr(expr.index, scope)}]"

        if isinstance(expr, CallExpr):
            args = ", ".join(self.gen_expr(a, scope) for a in expr.args)
            return f"{_py_ident(expr.func_name)}({args})"

        if isinstance(expr, ReadInputExpr):
            raw = f"_meme_builtins.input({repr(expr.prompt)})"
            if expr.target_type == "Int":
                self.uses_input_helpers = True
                return f"_meme_parse_int({raw})"
            if expr.target_type == "Float":
                self.uses_input_helpers = True
                return f"_meme_parse_float({raw})"
            if expr.target_type == "Bool":
                return f"({raw}.strip().lower() in ('true', '1', 'yes'))"
            return raw

        if isinstance(expr, StrEndsWithExpr):
            tgt = self.gen_expr(expr.target, scope)
            suf = self.gen_expr(expr.suffix, scope)
            return f"({tgt}.strip().lower().endswith({suf}.lower()))"

        if isinstance(expr, StringLengthExpr):
            return f"_meme_builtins.len({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringSliceExpr):
            tgt = self.gen_expr(expr.target, scope)
            s = self.gen_expr(expr.start, scope)
            e = self.gen_expr(expr.end, scope)
            return f"{tgt}[_meme_builtins.int({s}):_meme_builtins.int({e})]"

        if isinstance(expr, ReadJsonListExpr):
            self.uses_json_io = True
            return f"_meme_read_json_list({self.gen_expr(expr.filepath, scope)})"

        raise TypeError(f"Unsupported IRExpr: {type(expr)!r}")

    def gen_stmt(
        self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 0
    ) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            val_code = self.gen_expr(stmt.value, scope)
            if isinstance(stmt.value, VarRefExpr) and stmt.var_type.startswith("List<"):
                val_code = f"_meme_builtins.list({val_code})"
            scope[stmt.name] = stmt.var_type
            return [f"{pad}{_py_ident(stmt.name)} = {val_code}"]

        if isinstance(stmt, AssignStmt):
            val_code = self.gen_expr(stmt.value, scope)
            if isinstance(stmt.value, VarRefExpr) and scope.get(stmt.name, "").startswith("List<"):
                val_code = f"_meme_builtins.list({val_code})"
            return [f"{pad}{_py_ident(stmt.name)} = {val_code}"]

        if isinstance(stmt, SortCollectionStmt):
            rev = "True" if stmt.direction == "descending" else "False"
            return [f"{pad}{_py_ident(stmt.target)}.sort(reverse={rev})"]

        if isinstance(stmt, ClampCollectionStmt):
            tgt = _py_ident(stmt.target)
            lo = self.gen_expr(stmt.min_val, scope)
            hi = self.gen_expr(stmt.max_val, scope)
            return [
                f"{pad}{tgt} = [_meme_builtins.min(_meme_builtins.max(_x, {lo}), {hi}) for _x in {tgt}]"
            ]

        if isinstance(stmt, FilterCollectionStmt):
            tgt = _py_ident(stmt.target)
            iv = _py_ident(stmt.item_var)
            sub = dict(scope)
            col_t = scope.get(stmt.target, "List<Int>")
            sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
            pred = self.gen_expr(stmt.predicate, sub)
            return [
                f"{pad}{tgt} = [{iv} for {iv} in {tgt} if {pred}]"
            ]

        if isinstance(stmt, ListAppendStmt):
            return [f"{pad}{_py_ident(stmt.target)}.append({self.gen_expr(stmt.value, scope)})"]

        if isinstance(stmt, ListInsertStmt):
            return [
                f"{pad}{_py_ident(stmt.target)}.insert({self.gen_expr(stmt.index, scope)}, {self.gen_expr(stmt.value, scope)})"
            ]

        if isinstance(stmt, ListSetIndexStmt):
            tgt = _py_ident(stmt.target)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt}[_meme_builtins.int({idx})] = {val}"]

        if isinstance(stmt, FailStmt):
            return [
                f"{pad}_meme_builtins.print(_meme_fmt({self.gen_expr(stmt.message, scope)}))",
                f"{pad}raise _meme_builtins.SystemExit(0)",
            ]

        if isinstance(stmt, PrintStmt):
            parts = ", ".join(f"_meme_fmt({self.gen_expr(e, scope)})" for e in stmt.expressions)
            return [f"{pad}_meme_builtins.print({parts})"]

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
            lines = [f"{pad}for {_py_ident(stmt.item_var)} in {_py_ident(stmt.collection)}[:]:"]
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
            lines = [f"{pad}for {_py_ident(stmt.loop_var)} in _meme_builtins.range({start_s}, ({end_s}) + 1):"]
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
            params = ", ".join(_py_ident(p.name) for p in stmt.params)
            fn_scope = dict(scope)
            for p in stmt.params:
                fn_scope[p.name] = p.param_type
            lines = [f"{pad}def {_py_ident(stmt.name)}({params}):"]
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
    for stmt in ir.statements:
        if isinstance(stmt, FuncDefStmt):
            gen.func_returns[stmt.name] = stmt.return_type
    body_lines: list[str] = []
    for stmt in ir.statements:
        body_lines.extend(gen.gen_stmt(stmt, gen.symbols, indent=1))
    if not body_lines:
        body_lines.append("    pass")

    header: list[str] = ["import builtins as _meme_builtins"]
    if gen.uses_json_io:
        header.append("import json as _meme_json")
        header.append("import os as _meme_os")
        header.append("import sys as _meme_sys")
    if gen.uses_math:
        header.append("import math as _meme_math")
    if gen.uses_random:
        header.append("import random as _meme_random")
    header.append("")

    if gen.uses_json_io:
        header.extend(
            [
                "def _meme_resolve_path(path: str) -> str:",
                "    _p = path.strip()",
                "    if _meme_os.path.exists(_p) or _meme_os.path.isabs(_p):",
                "        return _p",
                "    _sd = _meme_os.environ.get('MEME_SOURCE_DIR', '').strip()",
                "    if _sd:",
                "        _cand = _meme_os.path.join(_sd, _p)",
                "        if _meme_os.path.exists(_cand):",
                "            return _cand",
                "    return _p",
                "",
                "def _meme_read_json_list(path: str) -> list[float]:",
                "    try:",
                "        with _meme_builtins.open(_meme_resolve_path(path), 'r', encoding='utf-8') as _f:",
                "            _data = _meme_json.load(_f)",
                "        if not _meme_builtins.isinstance(_data, _meme_builtins.list):",
                "            raise _meme_builtins.ValueError('Expected JSON list')",
                "        return [_meme_builtins.float(_x) for _x in _data if not _meme_builtins.isinstance(_x, _meme_builtins.bool)]",
                "    except _meme_builtins.Exception as _e:",
                "        _meme_builtins.print(f'Error reading JSON file: {_e}', file=_meme_sys.stderr)",
                "        raise _meme_builtins.SystemExit(1)",
                "",
            ]
        )

    if gen.uses_math:
        header.extend(
            [
                "def _meme_int_div(a: int, b: int) -> int:",
                "    return -((-a) // b) if (a < 0) ^ (b < 0) else a // b",
                "",
                "def _meme_int_mod(a: int, b: int) -> int:",
                "    return a - _meme_int_div(a, b) * b",
                "",
            ]
        )

    if gen.uses_input_helpers:
        header.extend(
            [
                "def _meme_parse_int(s: str) -> int:",
                "    try:",
                "        return _meme_builtins.int(s.strip())",
                "    except _meme_builtins.ValueError:",
                "        return 0",
                "",
                "def _meme_parse_float(s: str) -> float:",
                "    try:",
                "        return _meme_builtins.float(s.strip())",
                "    except _meme_builtins.ValueError:",
                "        return 0.0",
                "",
            ]
        )

    if gen.uses_random:
        header.extend(
            [
                "def _meme_rand_int(lo: int, hi: int) -> int:",
                "    return lo if hi <= lo else _meme_random.randint(lo, hi)",
                "",
            ]
        )

    header.extend(
        [
            "def _meme_fmt(val):",
            "    if _meme_builtins.isinstance(val, _meme_builtins.bool):",
            "        return 'true' if val else 'false'",
            "    if _meme_builtins.isinstance(val, _meme_builtins.float) and val.is_integer():",
            "        return _meme_builtins.str(_meme_builtins.int(val))",
            "    if _meme_builtins.isinstance(val, _meme_builtins.list):",
            "        return '[' + ', '.join(_meme_fmt(x) for x in val) + ']'",
            "    return _meme_builtins.str(val)",
            "",
            "def main() -> None:",
        ]
    )
    header.extend(body_lines)
    header.extend(["", 'if __name__ == "__main__":', "    main()", ""])
    return "\n".join(header)

"""Deterministic TypeScript (`tsc` -> Node.js) code generator for Memelang ProgramIR.

Emits clean, standard TypeScript code covering the full Memelang surface:
- Records -> interfaces + object literals with `_meme_type` tags and deep equality
- Lists -> standard JS Array<T>
- Maps -> standard JS Map<K, V> with sorted-key iteration snapshots
- Optional<T> -> (T | null) with lazy `_meme_unwrap_or_else`
- Numbers -> JS number (safe integer range up to 2^53; integral floats format as ints)
- File I/O -> node:fs via minimal ambient declarations (no @types/node required)
- argv -> process.argv.slice(1) matching argc/argv conventions
- Strings -> JS strings (ASCII byte parity across all test fixtures)
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from memelang.ir.schema import (
    AppendFileStmt,
    ArgAtExpr,
    ArgCountExpr,
    AssignStmt,
    BinaryOpExpr,
    BreakStmt,
    CallExpr,
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
    FuncParam,
    IRExpr,
    IRStatement,
    IfStmt,
    ImportStmt,
    IsDigitExpr,
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
    MemeType,
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

_TS_KEYWORDS = {
    "abstract", "any", "as", "asserts", "async", "await", "boolean", "break",
    "case", "catch", "class", "const", "continue", "debugger", "declare",
    "default", "delete", "do", "else", "enum", "export", "extends", "false",
    "finally", "for", "from", "function", "get", "if", "implements", "import",
    "in", "infer", "instanceof", "interface", "is", "keyof", "let", "module",
    "namespace", "never", "new", "null", "number", "object", "of", "package",
    "private", "protected", "public", "readonly", "require", "return", "set",
    "static", "string", "super", "switch", "symbol", "this", "throw", "true",
    "try", "type", "typeof", "undefined", "unique", "unknown", "var", "void",
    "while", "with", "yield",
}


def _ts_ident(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if clean in _TS_KEYWORDS or (clean and clean[0].isdigit()):
        return f"_{clean}"
    return clean


def _split_map_types(map_type_str: str) -> tuple[str, str]:
    assert map_type_str.startswith("Map<") and map_type_str.endswith(">")
    inner = map_type_str[4:-1]
    depth = 0
    split_idx = -1
    for i, ch in enumerate(inner):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            split_idx = i
            break
    if split_idx == -1:
        return "String", "String"
    return inner[:split_idx].strip(), inner[split_idx + 1:].strip()


def _map_types_of(type_str: str) -> tuple[str, str] | None:
    if type_str.startswith("Map<") and type_str.endswith(">"):
        return _split_map_types(type_str)
    return None


def _ts_type(t: str) -> str:
    if t == "Int" or t == "Float":
        return "number"
    if t == "String":
        return "string"
    if t == "Bool":
        return "boolean"
    if t == "Void":
        return "void"
    if t.startswith("List<") and t.endswith(">"):
        inner = t[5:-1]
        return f"{_ts_type(inner)}[]"
    if t.startswith("Map<") and t.endswith(">"):
        k, v = _split_map_types(t)
        return f"Map<{_ts_type(k)}, {_ts_type(v)}>"
    if t.startswith("Optional<") and t.endswith(">"):
        inner = t[9:-1]
        return f"({_ts_type(inner)} | null)"
    return _ts_ident(t)


class _TSGen:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, str]] = {}
        self.func_returns: dict[str, str] = {}
        self.func_params: dict[str, list[FuncParam]] = {}
        self.current_func_return: str | None = None
        self._match_counter = 0

    def infer_type(self, expr: IRExpr, scope: dict[str, MemeType]) -> str:
        if isinstance(expr, LiteralExpr):
            return expr.data_type
        if isinstance(expr, VarRefExpr):
            return scope.get(expr.name, "String")
        if isinstance(expr, ListLiteralExpr):
            return f"List<{expr.element_type}>"
        if isinstance(expr, MapLiteralExpr):
            return f"Map<{expr.key_type}, {expr.value_type}>"
        if isinstance(expr, RecordLiteralExpr):
            return expr.record_name
        if isinstance(expr, OptionalWrapExpr):
            inner = self.infer_type(expr.value, scope)
            return f"Optional<{inner}>"
        if isinstance(expr, OptionalNoneExpr):
            return "Optional<Void>"
        if isinstance(expr, OptionalIsNothingExpr):
            return "Bool"
        if isinstance(expr, (OptionalUnwrapExpr, OptionalUnwrapOrDefaultExpr)):
            tgt_t = self.infer_type(expr.target, scope)
            if tgt_t.startswith("Optional<") and tgt_t.endswith(">"):
                return tgt_t[9:-1]
            if isinstance(expr, OptionalUnwrapOrDefaultExpr):
                return self.infer_type(expr.default_val, scope)
            return "Int"
        if isinstance(expr, (StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr, FileExistsExpr, IsDigitExpr)):
            return "Bool"
        if isinstance(expr, (RandomIntExpr, ListLengthExpr, StringLengthExpr, StringIndexOfExpr, ArgCountExpr, ParseIntExpr, ParseIntOrDefaultExpr)):
            return "Int"
        if isinstance(expr, (StringSliceExpr, StringReplaceExpr, StringUpperExpr, StringLowerExpr,
                             StringTrimExpr, StringJoinExpr, StringCharAtExpr, ReadFileStringExpr, ArgAtExpr, FormatIntExpr)):
            return "String"
        if isinstance(expr, (StringSplitExpr, ListFilesExpr)):
            return "List<String>"
        if isinstance(expr, ReadJsonListExpr):
            return f"List<{expr.element_type}>"
        if isinstance(expr, ReadInputExpr):
            return expr.target_type
        if isinstance(expr, CallExpr):
            return self.func_returns.get(expr.func_name, "Void")
        if isinstance(expr, RecordFieldExpr):
            tgt_t = self.infer_type(expr.target, scope)
            return self.records.get(tgt_t, {}).get(expr.field_name, "String")
        if isinstance(expr, MapGetExpr):
            tgt_t = self.infer_type(expr.target, scope)
            map_t = _map_types_of(tgt_t)
            return map_t[1] if map_t else "String"
        if isinstance(expr, MapHasKeyExpr):
            return "Bool"
        if isinstance(expr, ListIndexExpr):
            tgt_t = self.infer_type(expr.target, scope)
            return tgt_t[5:-1] if tgt_t.startswith("List<") else "Int"
        if isinstance(expr, UnaryOpExpr):
            return "Bool" if expr.op == "not" else self.infer_type(expr.operand, scope)
        if isinstance(expr, BinaryOpExpr):
            if expr.op in ("==", "!=", "<", "<=", ">", ">=", "and", "or"):
                return "Bool"
            lt = self.infer_type(expr.left, scope)
            rt = self.infer_type(expr.right, scope)
            if lt == "String" or rt == "String":
                return "String"
            if lt == "Float" or rt == "Float":
                return "Float"
            return "Int"
        return "String"

    def gen_expr(self, expr: IRExpr, scope: dict[str, MemeType], expected_type: str | None = None) -> str:
        if isinstance(expr, LiteralExpr):
            if expr.data_type == "Bool":
                return "true" if expr.value else "false"
            if expr.data_type == "Int":
                return str(int(expr.value))
            if expr.data_type == "Float":
                f_val = float(expr.value)
                if math.isnan(f_val):
                    return "NaN"
                if math.isinf(f_val):
                    return "-Infinity" if f_val < 0 else "Infinity"
                return str(f_val)
            if expr.data_type == "String":
                return json.dumps(str(expr.value))
            return json.dumps(str(expr.value))

        if isinstance(expr, VarRefExpr):
            return _ts_ident(expr.name)

        if isinstance(expr, BinaryOpExpr):
            left_t = self.infer_type(expr.left, scope)
            right_t = self.infer_type(expr.right, scope)
            left = self.gen_expr(expr.left, scope)
            right = self.gen_expr(expr.right, scope)

            if expr.op == "+":
                if left_t == "String" or right_t == "String":
                    return f"({left} + {right})"
                return f"({left} + {right})"
            if expr.op == "-":
                return f"({left} - {right})"
            if expr.op == "*":
                return f"({left} * {right})"
            if expr.op == "/":
                if left_t == "Int" and right_t == "Int":
                    return f"Math.trunc({left} / {right})"
                return f"({left} / {right})"
            if expr.op == "%":
                return f"({left} % {right})"
            if expr.op == "==":
                return f"_meme_eq({left}, {right})"
            if expr.op == "!=":
                return f"(!_meme_eq({left}, {right}))"
            if expr.op == "<":
                return f"({left} < {right})"
            if expr.op == "<=":
                return f"({left} <= {right})"
            if expr.op == ">":
                return f"({left} > {right})"
            if expr.op == ">=":
                return f"({left} >= {right})"
            if expr.op == "and":
                return f"({left} && {right})"
            if expr.op == "or":
                return f"({left} || {right})"
            return f"({left} {expr.op} {right})"

        if isinstance(expr, UnaryOpExpr):
            op = self.gen_expr(expr.operand, scope)
            if expr.op == "not":
                return f"(!{op})"
            if expr.op == "-":
                return f"(-{op})"
            return f"({expr.op}{op})"

        if isinstance(expr, CallExpr):
            args = ", ".join(self.gen_expr(a, scope) for a in expr.args)
            return f"{_ts_ident(expr.func_name)}({args})"

        if isinstance(expr, ListLiteralExpr):
            elems = ", ".join(self.gen_expr(e, scope, expr.element_type) for e in expr.elements)
            return f"[{elems}]"

        if isinstance(expr, ListIndexExpr):
            tgt_t = self.infer_type(expr.target, scope)
            idx = self.gen_expr(expr.index, scope)
            tgt = self.gen_expr(expr.target, scope)
            if tgt_t.startswith("Map<"):
                return f"_meme_map_get({tgt}, {idx})"
            return f"_meme_list_get({tgt}, {idx})"

        if isinstance(expr, ListLengthExpr):
            tgt_t = self.infer_type(expr.target, scope)
            tgt = self.gen_expr(expr.target, scope)
            if tgt_t.startswith("Map<"):
                return f"{tgt}.size"
            return f"{tgt}.length"

        if isinstance(expr, MapLiteralExpr):
            entries = ", ".join(
                f"[{self.gen_expr(e.key, scope, expr.key_type)}, {self.gen_expr(e.value, scope, expr.value_type)}]"
                for e in expr.entries
            )
            return f"new Map([{entries}])"

        if isinstance(expr, MapGetExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            if expr.default_val is not None:
                dflt = self.gen_expr(expr.default_val, scope)
                return f"_meme_map_get({tgt}, {k}, {dflt})"
            return f"_meme_map_get({tgt}, {k})"

        if isinstance(expr, MapHasKeyExpr):
            return f"{self.gen_expr(expr.target, scope)}.has({self.gen_expr(expr.key, scope)})"

        if isinstance(expr, RecordLiteralExpr):
            field_init: list[str] = [f"_meme_type: {json.dumps(expr.record_name)}"]
            r_schema = self.records.get(expr.record_name, {})
            for f in expr.fields:
                f_type = r_schema.get(f.name)
                field_init.append(f"{_ts_ident(f.name)}: {self.gen_expr(f.value, scope, f_type)}")
            return f"({{ {', '.join(field_init)} }})"

        if isinstance(expr, RecordFieldExpr):
            return f"({self.gen_expr(expr.target, scope)}).{_ts_ident(expr.field_name)}"

        if isinstance(expr, OptionalNoneExpr):
            return "null"

        if isinstance(expr, OptionalWrapExpr):
            return self.gen_expr(expr.value, scope)

        if isinstance(expr, OptionalIsNothingExpr):
            tgt = self.gen_expr(expr.target, scope)
            if expr.negated:
                return f"({tgt} !== null)"
            return f"({tgt} === null)"

        if isinstance(expr, OptionalUnwrapExpr):
            return f"_meme_unwrap({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, OptionalUnwrapOrDefaultExpr):
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_unwrap_or_else({tgt}, () => {dflt})"

        if isinstance(expr, StrContainsExpr):
            return f"({self.gen_expr(expr.target, scope)}).includes({self.gen_expr(expr.substring, scope)})"

        if isinstance(expr, StrStartsWithExpr):
            return f"({self.gen_expr(expr.target, scope)}).startsWith({self.gen_expr(expr.prefix, scope)})"

        if isinstance(expr, StrEndsWithExpr):
            return f"({self.gen_expr(expr.target, scope)}).endsWith({self.gen_expr(expr.suffix, scope)})"

        if isinstance(expr, StringReplaceExpr):
            return f"_meme_str_replace({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.old, scope)}, {self.gen_expr(expr.new, scope)})"

        if isinstance(expr, StringUpperExpr):
            return f"({self.gen_expr(expr.target, scope)}).toUpperCase()"

        if isinstance(expr, StringLowerExpr):
            return f"({self.gen_expr(expr.target, scope)}).toLowerCase()"

        if isinstance(expr, StringTrimExpr):
            return f"({self.gen_expr(expr.target, scope)}).trim()"

        if isinstance(expr, StringSplitExpr):
            return f"_meme_str_split({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.separator, scope)})"

        if isinstance(expr, StringJoinExpr):
            return f"({self.gen_expr(expr.items, scope)}).join({self.gen_expr(expr.separator, scope)})"

        if isinstance(expr, StringIndexOfExpr):
            return f"({self.gen_expr(expr.target, scope)}).indexOf({self.gen_expr(expr.substring, scope)})"

        if isinstance(expr, StringCharAtExpr):
            return f"_meme_char_at({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.index, scope)})"

        if isinstance(expr, StringLengthExpr):
            return f"({self.gen_expr(expr.target, scope)}).length"

        if isinstance(expr, StringSliceExpr):
            return f"_meme_str_slice({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.start, scope)}, {self.gen_expr(expr.end, scope)})"

        if isinstance(expr, ParseIntExpr):
            return f"_meme_parse_int({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ParseIntOrDefaultExpr):
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_parse_int_or_else({tgt}, () => {dflt})"

        if isinstance(expr, IsDigitExpr):
            return f"_meme_is_digit({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, FormatIntExpr):
            return f"String({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, FileExistsExpr):
            return f"_meme_file_exists({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ReadFileStringExpr):
            return f"_meme_read_file_string({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ListFilesExpr):
            return f"_meme_list_files({self.gen_expr(expr.path, scope)})"

        if isinstance(expr, ReadJsonListExpr):
            return f"_meme_read_json_list_{expr.element_type.lower()}({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ArgCountExpr):
            return "_meme_argv.length"

        if isinstance(expr, ArgAtExpr):
            return f"_meme_arg_at({self.gen_expr(expr.index, scope)})"

        if isinstance(expr, RandomIntExpr):
            return f"_meme_rand_int({self.gen_expr(expr.min_val, scope)}, {self.gen_expr(expr.max_val, scope)})"

        if isinstance(expr, RandomListExpr):
            c = self.gen_expr(expr.count, scope)
            lo = self.gen_expr(expr.min_val, scope)
            hi = self.gen_expr(expr.max_val, scope)
            return f"_meme_rand_list({c}, {lo}, {hi})"

        if isinstance(expr, ReadInputExpr):
            raw = f"_meme_read_line({json.dumps(expr.prompt)})"
            if expr.target_type == "Int":
                return f"_meme_parse_int({raw})"
            if expr.target_type == "Float":
                return f"_meme_parse_float({raw})"
            if expr.target_type == "Bool":
                return f"_meme_parse_bool({raw})"
            return raw

        raise TypeError(f"Unsupported IRExpr: {type(expr)!r}")

    def gen_stmt(self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 1) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            name = _ts_ident(stmt.name)
            scope[stmt.name] = stmt.var_type
            t = _ts_type(stmt.var_type)
            val = self.gen_expr(stmt.value, scope, stmt.var_type)
            return [f"{pad}let {name}: {t} = {val};"]

        if isinstance(stmt, AssignStmt):
            name = _ts_ident(stmt.name)
            val = self.gen_expr(stmt.value, scope, scope.get(stmt.name))
            return [f"{pad}{name} = {val};"]

        if isinstance(stmt, CompoundAssignStmt):
            tgt = _ts_ident(stmt.target)
            tgt_t = scope.get(stmt.target, "Int")
            val = self.gen_expr(stmt.value, scope, tgt_t)
            op = stmt.operator
            if op == "/":
                if tgt_t == "Int":
                    return [f"{pad}{tgt} = Math.trunc({tgt} / {val});"]
                return [f"{pad}{tgt} /= {val};"]
            elif op == "%":
                return [f"{pad}{tgt} %= {val};"]
            else:
                return [f"{pad}{tgt} {op}= {val};"]

        if isinstance(stmt, PrintStmt):
            if not stmt.expressions:
                return [f'{pad}console.log("");']
            args = ", ".join(f"_meme_fmt({self.gen_expr(e, scope)})" for e in stmt.expressions)
            return [f"{pad}console.log([{args}].join(\" \"));"]

        if isinstance(stmt, IfStmt):
            cond = self.gen_expr(stmt.condition, scope)
            lines = [f"{pad}if ({cond}) {{"]
            then_scope = dict(scope)
            for ch in stmt.then_body:
                lines.extend(self.gen_stmt(ch, then_scope, indent + 1))
            if stmt.else_body:
                lines.append(f"{pad}}} else {{")
                else_scope = dict(scope)
                for ch in stmt.else_body:
                    lines.extend(self.gen_stmt(ch, else_scope, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, WhileStmt):
            cond = self.gen_expr(stmt.condition, scope)
            lines = [f"{pad}while ({cond}) {{"]
            b_scope = dict(scope)
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, b_scope, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, ForRangeStmt):
            lv = _ts_ident(stmt.loop_var)
            start = self.gen_expr(stmt.start, scope)
            end = self.gen_expr(stmt.end, scope)
            lines = [
                f"{pad}{{",
                f"{pad}    const _start = {start};",
                f"{pad}    const _end = {end};",
                f"{pad}    for (let {lv} = _start; {lv} <= _end; {lv}++) {{",
            ]
            b_scope = dict(scope)
            b_scope[stmt.loop_var] = "Int"
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, b_scope, indent + 2))
            lines.append(f"{pad}    }}")
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, ForEachStmt):
            col_t = scope.get(stmt.collection, "List<Int>")
            map_t = _map_types_of(col_t)
            col_ident = _ts_ident(stmt.collection)
            b_scope = dict(scope)

            if map_t is not None:
                b_scope[stmt.item_var] = map_t[0]
                iter_expr = f"_meme_map_sorted_keys({col_ident})"
            else:
                b_scope[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"
                iter_expr = f"{col_ident}.slice()"

            item_v = _ts_ident(stmt.item_var)
            if stmt.index_var is not None:
                idx_v = _ts_ident(stmt.index_var)
                b_scope[stmt.index_var] = "Int"
                lines = [
                    f"{pad}{{",
                    f"{pad}    const _iter = {iter_expr};",
                    f"{pad}    for (let {idx_v} = 0; {idx_v} < _iter.length; {idx_v}++) {{",
                    f"{pad}        const {item_v} = _iter[{idx_v}];",
                ]
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, b_scope, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines
            else:
                lines = [f"{pad}for (const {item_v} of {iter_expr}) {{"]
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, b_scope, indent + 1))
                lines.append(f"{pad}}}")
                return lines

        if isinstance(stmt, SwitchStmt):
            self._match_counter += 1
            m_var = f"_meme_m{self._match_counter}"
            tgt = self.gen_expr(stmt.target, scope)
            lines = [
                f"{pad}{{",
                f"{pad}    const {m_var} = {tgt};",
            ]
            for i, case in enumerate(stmt.cases):
                kw = "if" if i == 0 else "} else if"
                case_val = self.gen_expr(case.value, scope)
                lines.append(f"{pad}    {kw} (_meme_eq({m_var}, {case_val})) {{")
                case_scope = dict(scope)
                for ch in case.body:
                    lines.extend(self.gen_stmt(ch, case_scope, indent + 2))
            if stmt.default_body:
                kw = "} else" if stmt.cases else "if (true)"
                lines.append(f"{pad}    {kw} {{")
                def_scope = dict(scope)
                for ch in stmt.default_body:
                    lines.extend(self.gen_stmt(ch, def_scope, indent + 2))
            if stmt.cases or stmt.default_body:
                lines.append(f"{pad}    }}")
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                val = self.gen_expr(stmt.value, scope, self.current_func_return)
                return [f"{pad}return {val};"]
            return [f"{pad}return;"]

        if isinstance(stmt, BreakStmt):
            return [f"{pad}break;"]

        if isinstance(stmt, ContinueStmt):
            return [f"{pad}continue;"]

        if isinstance(stmt, ExitStmt):
            code = self.gen_expr(stmt.code, scope)
            return [f"{pad}process.exit(({code}) & 0xFF);"]

        if isinstance(stmt, FailStmt):
            msg = self.gen_expr(stmt.message, scope)
            return [
                f"{pad}console.log(_meme_fmt({msg}));",
                f"{pad}process.exit(1);",
            ]

        if isinstance(stmt, ListAppendStmt):
            tgt = _ts_ident(stmt.target)
            tgt_t = scope.get(stmt.target, "List<Int>")
            el_t = tgt_t[5:-1] if tgt_t.startswith("List<") else "Int"
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}{tgt}.push({val});"]

        if isinstance(stmt, ListInsertStmt):
            tgt = _ts_ident(stmt.target)
            tgt_t = scope.get(stmt.target, "List<Int>")
            el_t = tgt_t[5:-1] if tgt_t.startswith("List<") else "Int"
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}_meme_list_insert({tgt}, {idx}, {val});"]

        if isinstance(stmt, ListSetIndexStmt):
            tgt = _ts_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            idx = self.gen_expr(stmt.index, scope)
            if col_t.startswith("Map<"):
                val = self.gen_expr(stmt.value, scope)
                return [f"{pad}{tgt}.set({idx}, {val});"]
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}_meme_list_set({tgt}, {idx}, {val});"]

        if isinstance(stmt, ListRemoveStmt):
            tgt = _ts_ident(stmt.target)
            if stmt.index is not None:
                idx = self.gen_expr(stmt.index, scope)
                return [f"{pad}_meme_list_remove({tgt}, {idx});"]
            return [f"{pad}_meme_list_remove_last({tgt});"]

        if isinstance(stmt, FilterCollectionStmt):
            tgt = _ts_ident(stmt.target)
            iv = _ts_ident(stmt.item_var)
            sub = dict(scope)
            col_t = scope.get(stmt.target, "List<Int>")
            sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"
            pred = self.gen_expr(stmt.predicate, sub)
            return [f"{pad}{tgt} = {tgt}.filter(({iv}) => {pred});"]

        if isinstance(stmt, ClampCollectionStmt):
            tgt = _ts_ident(stmt.target)
            lo = self.gen_expr(stmt.min_val, scope)
            hi = self.gen_expr(stmt.max_val, scope)
            return [f"{pad}{tgt} = {tgt}.map((_x) => Math.min(Math.max(_x, {lo}), {hi}));"]

        if isinstance(stmt, SortCollectionStmt):
            tgt = _ts_ident(stmt.target)
            desc = "true" if stmt.direction == "descending" else "false"
            return [f"{pad}_meme_sort({tgt}, {desc});"]

        if isinstance(stmt, MapSetStmt):
            tgt = _ts_ident(stmt.target)
            tgt_t = scope.get(stmt.target, "Map<String, String>")
            map_t = _map_types_of(tgt_t)
            k_t = map_t[0] if map_t else "String"
            v_t = map_t[1] if map_t else "String"
            key = self.gen_expr(stmt.key, scope, k_t)
            val = self.gen_expr(stmt.value, scope, v_t)
            return [f"{pad}{tgt}.set({key}, {val});"]

        if isinstance(stmt, RecordSetFieldStmt):
            tgt = _ts_ident(stmt.target)
            r_type = scope.get(stmt.target, "")
            f_type = self.records.get(r_type, {}).get(stmt.field_name)
            val = self.gen_expr(stmt.value, scope, f_type)
            return [f"{pad}{tgt}.{_ts_ident(stmt.field_name)} = {val};"]

        if isinstance(stmt, WriteFileStmt):
            p = self.gen_expr(stmt.filepath, scope)
            c = self.gen_expr(stmt.content, scope)
            return [f"{pad}_meme_write_file({p}, {c});"]

        if isinstance(stmt, AppendFileStmt):
            p = self.gen_expr(stmt.filepath, scope)
            c = self.gen_expr(stmt.content, scope)
            return [f"{pad}_meme_append_file({p}, {c});"]

        if isinstance(stmt, CopyFileStmt):
            s = self.gen_expr(stmt.src, scope)
            d = self.gen_expr(stmt.dst, scope)
            return [f"{pad}_meme_copy_file({s}, {d});"]

        if isinstance(stmt, MoveFileStmt):
            s = self.gen_expr(stmt.src, scope)
            d = self.gen_expr(stmt.dst, scope)
            return [f"{pad}_meme_move_file({s}, {d});"]

        if isinstance(stmt, RenameFileStmt):
            p = self.gen_expr(stmt.path, scope)
            nn = self.gen_expr(stmt.new_name, scope)
            return [f"{pad}_meme_rename_file({p}, {nn});"]

        if isinstance(stmt, DeleteFileStmt):
            p = self.gen_expr(stmt.path, scope)
            return [f"{pad}_meme_delete_file({p});"]

        if isinstance(stmt, CreateDirectoryStmt):
            p = self.gen_expr(stmt.path, scope)
            return [f"{pad}_meme_create_directory({p});"]

        if isinstance(stmt, (RecordDefStmt, FuncDefStmt, ImportStmt)):
            return []

        raise TypeError(f"Unsupported IRStatement: {type(stmt)!r}")

    def gen_func(self, fn: FuncDefStmt) -> list[str]:
        fn_name = _ts_ident(fn.name)
        self.current_func_return = fn.return_type
        params_str = ", ".join(f"{_ts_ident(p.name)}: {_ts_type(p.param_type)}" for p in fn.params)
        ret_t = _ts_type(fn.return_type)

        fn_scope: dict[str, MemeType] = {}
        for p in fn.params:
            fn_scope[p.name] = p.param_type

        lines = [f"function {fn_name}({params_str}): {ret_t} {{"]
        for ch in fn.body:
            lines.extend(self.gen_stmt(ch, fn_scope, indent=1))
        if fn.return_type != "Void" and not (fn.body and isinstance(fn.body[-1], ReturnStmt)):
            lines.append("    return undefined as any;")
        lines.append("}")
        self.current_func_return = None
        return lines


def generate_ts(ir: ProgramIR) -> str:
    gen = _TSGen()
    records: list[RecordDefStmt] = []
    funcs: list[FuncDefStmt] = []
    main_stmts: list[IRStatement] = []

    all_stmts = [*ir.imported_definitions, *ir.statements]
    for stmt in all_stmts:
        if isinstance(stmt, RecordDefStmt):
            gen.records[stmt.name] = {f.name: f.field_type for f in stmt.fields}
            records.append(stmt)
        elif isinstance(stmt, FuncDefStmt):
            gen.func_returns[stmt.name] = stmt.return_type
            gen.func_params[stmt.name] = stmt.params
            funcs.append(stmt)
        elif isinstance(stmt, ImportStmt):
            continue
        else:
            main_stmts.append(stmt)

    preamble = [
        "// Generated by Memelang TypeScript Backend",
        "// Ambient declarations for Node builtins (no @types/node required)",
        "declare const process: {",
        "    argv: string[];",
        "    exit(code?: number): never;",
        "    env: Record<string, string | undefined>;",
        "    stdout: { write(str: string): boolean };",
        "};",
        "declare const Buffer: any;",
        "declare function require(name: string): any;",
        "const _fs = require(\"node:fs\");",
        "const _path = require(\"node:path\");",
        "",
        "const _meme_argv: string[] = process.argv.slice(1);",
        "function _meme_arg_at(idx: number): string {",
        "    if (idx < 0 || idx >= _meme_argv.length) {",
        "        console.log(`Error: argument index ${idx} out of range`);",
        "        process.exit(1);",
        "    }",
        "    return _meme_argv[idx];",
        "}",
        "",
        "const _meme_record_formatters: Record<string, (r: any) => string> = {};",
        "",
        "function _meme_fmt(val: any): string {",
        "    if (val === null || val === undefined) {",
        "        return \"None\";",
        "    }",
        "    if (typeof val === \"boolean\") {",
        "        return val ? \"true\" : \"false\";",
        "    }",
        "    if (typeof val === \"number\") {",
        "        if (Number.isNaN(val)) return \"nan\";",
        "        if (val === Infinity) return \"inf\";",
        "        if (val === -Infinity) return \"-inf\";",
        "        if (Number.isFinite(val) && Math.trunc(val) === val && val >= -9007199254740992 && val <= 9007199254740992) {",
        "            return Object.is(val, -0) ? \"-0\" : String(Math.trunc(val));",
        "        }",
        "        return String(val);",
        "    }",
        "    if (typeof val === \"string\") {",
        "        return val;",
        "    }",
        "    if (Array.isArray(val)) {",
        "        return \"[\" + val.map((x) => _meme_fmt(x)).join(\", \") + \"]\";",
        "    }",
        "    if (val instanceof Map) {",
        "        const entries: [string, string][] = [];",
        "        for (const [k, v] of val.entries()) {",
        "            entries.push([_meme_fmt(k), _meme_fmt(v)]);",
        "        }",
        "        entries.sort((a, b) => (a[0] < b[0] ? -1 : (a[0] > b[0] ? 1 : 0)));",
        "        return \"{\" + entries.map(([k, v]) => `${k}: ${v}`).join(\", \") + \"}\";",
        "    }",
        "    if (typeof val === \"object\" && \"_meme_type\" in val && typeof _meme_record_formatters[val._meme_type] === \"function\") {",
        "        return _meme_record_formatters[val._meme_type](val);",
        "    }",
        "    return String(val);",
        "}",
        "",
        "function _meme_eq(a: any, b: any): boolean {",
        "    if (a === b) return true;",
        "    if (a === null || a === undefined || b === null || b === undefined) return a === b;",
        "    if (typeof a !== \"object\" || typeof b !== \"object\") return false;",
        "    if (Array.isArray(a) && Array.isArray(b)) {",
        "        if (a.length !== b.length) return false;",
        "        for (let i = 0; i < a.length; i++) {",
        "            if (!_meme_eq(a[i], b[i])) return false;",
        "        }",
        "        return true;",
        "    }",
        "    if (a instanceof Map && b instanceof Map) {",
        "        if (a.size !== b.size) return false;",
        "        for (const [k, v] of a.entries()) {",
        "            if (!b.has(k) || !_meme_eq(v, b.get(k))) return false;",
        "        }",
        "        return true;",
        "    }",
        "    if (\"_meme_type\" in a && \"_meme_type\" in b) {",
        "        if (a._meme_type !== b._meme_type) return false;",
        "        const keysA = Object.keys(a);",
        "        const keysB = Object.keys(b);",
        "        if (keysA.length !== keysB.length) return false;",
        "        for (const k of keysA) {",
        "            if (!_meme_eq(a[k], b[k])) return false;",
        "        }",
        "        return true;",
        "    }",
        "    return false;",
        "}",
        "",
        "function _meme_list_get<T>(arr: T[], idx: number): T {",
        "    if (idx < 0 || idx >= arr.length) {",
        "        console.log(\"Error: list index out of range\");",
        "        process.exit(1);",
        "    }",
        "    return arr[idx];",
        "}",
        "",
        "function _meme_list_set<T>(arr: T[], idx: number, val: T): void {",
        "    if (idx < 0 || idx >= arr.length) {",
        "        console.log(\"Error: list index out of range\");",
        "        process.exit(1);",
        "    }",
        "    arr[idx] = val;",
        "}",
        "",
        "function _meme_list_insert<T>(arr: T[], idx: number, val: T): void {",
        "    if (idx < 0) idx = 0;",
        "    if (idx > arr.length) idx = arr.length;",
        "    arr.splice(idx, 0, val);",
        "}",
        "",
        "function _meme_list_remove<T>(arr: T[], idx: number): void {",
        "    if (idx < 0 || idx >= arr.length) {",
        "        console.log(\"Error: list index out of range\");",
        "        process.exit(1);",
        "    }",
        "    arr.splice(idx, 1);",
        "}",
        "",
        "function _meme_list_remove_last<T>(arr: T[]): void {",
        "    if (arr.length === 0) {",
        "        console.log(\"Error: list index out of range\");",
        "        process.exit(1);",
        "    }",
        "    arr.pop();",
        "}",
        "",
        "function _meme_sort<T>(arr: T[], desc: boolean): void {",
        "    const withIdx = arr.map((val, idx) => ({ val, idx }));",
        "    withIdx.sort((a, b) => {",
        "        let cmp = 0;",
        "        if (typeof a.val === \"string\" && typeof b.val === \"string\") {",
        "            cmp = a.val < b.val ? -1 : (a.val > b.val ? 1 : 0);",
        "        } else if (typeof a.val === \"number\" && typeof b.val === \"number\") {",
        "            cmp = a.val < b.val ? -1 : (a.val > b.val ? 1 : 0);",
        "        } else if (typeof a.val === \"boolean\" && typeof b.val === \"boolean\") {",
        "            cmp = Number(a.val) - Number(b.val);",
        "        }",
        "        if (desc) cmp = -cmp;",
        "        if (cmp !== 0) return cmp;",
        "        return a.idx - b.idx;",
        "    });",
        "    for (let i = 0; i < arr.length; i++) {",
        "        arr[i] = withIdx[i].val;",
        "    }",
        "}",
        "",
        "function _meme_map_get<K, V>(m: Map<K, V>, key: K, dflt?: V): V {",
        "    if (m.has(key)) {",
        "        return m.get(key)!;",
        "    }",
        "    if (dflt !== undefined) {",
        "        return dflt;",
        "    }",
        "    console.log(\"Error: key not found in map\");",
        "    process.exit(1);",
        "    throw new Error();",
        "}",
        "",
        "function _meme_map_sorted_keys<K>(m: Map<K, any>): K[] {",
        "    const keys = Array.from(m.keys());",
        "    keys.sort((a, b) => {",
        "        if (typeof a === \"string\" && typeof b === \"string\") {",
        "            return a < b ? -1 : (a > b ? 1 : 0);",
        "        }",
        "        return (a as any) < (b as any) ? -1 : ((a as any) > (b as any) ? 1 : 0);",
        "    });",
        "    return keys;",
        "}",
        "",
        "function _meme_unwrap<T>(opt: T): NonNullable<T> {",
        "    if (opt === null || opt === undefined) {",
        "        console.log(\"Unwrap failed: Optional value is nothing\");",
        "        process.exit(1);",
        "    }",
        "    return opt as NonNullable<T>;",
        "}",
        "",
        "function _meme_unwrap_or_else<T, D>(opt: T, dflt: () => D): NonNullable<T> | D {",
        "    if (opt !== null && opt !== undefined) {",
        "        return opt as NonNullable<T>;",
        "    }",
        "    return dflt();",
        "}",
        "",
        "function _meme_char_at(s: string, idx: number): string {",
        "    if (idx < 0 || idx >= s.length) {",
        "        console.log(`Error: string index ${idx} out of range`);",
        "        process.exit(1);",
        "    }",
        "    return s.charAt(idx);",
        "}",
        "",
        "function _meme_str_slice(s: string, start: number, end: number): string {",
        "    if (start < 0) start = 0;",
        "    if (end <= start) return \"\";",
        "    return s.slice(start, end);",
        "}",
        "",
        "function _meme_str_replace(s: string, old_sub: string, new_sub: string): string {",
        "    if (old_sub === \"\") {",
        "        return new_sub + s.split(\"\").join(new_sub) + new_sub;",
        "    }",
        "    return s.split(old_sub).join(new_sub);",
        "}",
        "",
        "function _meme_str_split(s: string, sep: string): string[] {",
        "    if (sep === \"\") {",
        "        console.log(\"Error: empty separator in split\");",
        "        process.exit(1);",
        "    }",
        "    return s.split(sep);",
        "}",
        "",
        "function _meme_resolve_path(filePath: string): string {",
        "    const p = filePath.trim();",
        "    if (_fs.existsSync(p) || p.startsWith(\"/\")) return p;",
        "    const sd = process.env[\"MEME_SOURCE_DIR\"];",
        "    if (sd) {",
        "        const sds = sd.trim();",
        "        if (sds.length > 0) {",
        "            const cand = sds + \"/\" + p;",
        "            if (_fs.existsSync(cand)) return cand;",
        "        }",
        "    }",
        "    return p;",
        "}",
        "",
        "function _meme_file_exists(filePath: string): boolean {",
        "    const rp = _meme_resolve_path(filePath);",
        "    try {",
        "        const st = _fs.statSync(rp);",
        "        return st.isFile();",
        "    } catch {",
        "        return false;",
        "    }",
        "}",
        "",
        "function _meme_read_file_string(filePath: string): string {",
        "    const rp = _meme_resolve_path(filePath);",
        "    try {",
        "        const st = _fs.statSync(rp);",
        "        if (!st.isFile()) {",
        "            console.log(`Error reading file: ${filePath}`);",
        "            process.exit(1);",
        "        }",
        "        return _fs.readFileSync(rp, \"utf-8\");",
        "    } catch {",
        "        console.log(`Error reading file: ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_write_file(filePath: string, content: string): void {",
        "    const p = filePath.trim();",
        "    try {",
        "        _fs.writeFileSync(p, content, \"utf-8\");",
        "    } catch {",
        "        console.log(`Error writing file: ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_append_file(filePath: string, content: string): void {",
        "    const p = filePath.trim();",
        "    try {",
        "        _fs.appendFileSync(p, content, \"utf-8\");",
        "    } catch {",
        "        console.log(`Error writing file: ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_copy_file(src: string, dst: string): void {",
        "    const sp = _meme_resolve_path(src);",
        "    try {",
        "        if (!_fs.statSync(sp).isFile()) {",
        "            console.log(`Error copying file: ${src}`);",
        "            process.exit(1);",
        "        }",
        "        _fs.copyFileSync(sp, dst.trim());",
        "    } catch {",
        "        console.log(`Error copying file: ${src}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_move_file(src: string, dst: string): void {",
        "    const sp = _meme_resolve_path(src);",
        "    try {",
        "        if (!_fs.statSync(sp).isFile()) {",
        "            console.log(`Error moving file: ${src}`);",
        "            process.exit(1);",
        "        }",
        "        const target = dst.trim();",
        "        try {",
        "            _fs.renameSync(sp, target);",
        "        } catch {",
        "            _fs.copyFileSync(sp, target);",
        "            _fs.unlinkSync(sp);",
        "        }",
        "    } catch {",
        "        console.log(`Error moving file: ${src}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_rename_file(filePath: string, newName: string): void {",
        "    const sp = _meme_resolve_path(filePath);",
        "    try {",
        "        if (!_fs.statSync(sp).isFile()) {",
        "            console.log(`Error renaming file: ${filePath}`);",
        "            process.exit(1);",
        "        }",
        "        const p = filePath.trim();",
        "        const dir = _path.dirname(p);",
        "        const nn = _path.basename(newName.trim());",
        "        const target = dir === \".\" || dir === \"\" ? nn : _path.join(dir, nn);",
        "        try {",
        "            _fs.renameSync(sp, target);",
        "        } catch {",
        "            _fs.copyFileSync(sp, target);",
        "            _fs.unlinkSync(sp);",
        "        }",
        "    } catch {",
        "        console.log(`Error renaming file: ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_delete_file(filePath: string): void {",
        "    const sp = _meme_resolve_path(filePath);",
        "    try {",
        "        if (!_fs.statSync(sp).isFile()) {",
        "            console.log(`Error deleting file: ${filePath}`);",
        "            process.exit(1);",
        "        }",
        "        _fs.unlinkSync(sp);",
        "    } catch {",
        "        console.log(`Error deleting file: ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_create_directory(dirPath: string): void {",
        "    try {",
        "        _fs.mkdirSync(dirPath.trim(), { recursive: true });",
        "    } catch {",
        "        console.log(`Error creating directory: ${dirPath}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_list_files(dirPath: string): string[] {",
        "    const rp = _meme_resolve_path(dirPath);",
        "    try {",
        "        if (!_fs.statSync(rp).isDirectory()) {",
        "            console.log(`Error listing directory: ${dirPath}`);",
        "            process.exit(1);",
        "        }",
        "        const entries: string[] = _fs.readdirSync(rp);",
        "        entries.sort();",
        "        return entries;",
        "    } catch {",
        "        console.log(`Error listing directory: ${dirPath}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_read_line(prompt: string): string {",
        "    const q = process.env[\"MEME_QUIET_PROMPTS\"] || \"\";",
        "    const quiet = q === \"1\" || q.toLowerCase() === \"true\" || q.toLowerCase() === \"yes\";",
        "    if (prompt && !quiet) {",
        "        process.stdout.write(prompt);",
        "    }",
        "    const buf = Buffer.alloc(1);",
        "    let line = \"\";",
        "    while (true) {",
        "        let n = 0;",
        "        try {",
        "            n = _fs.readSync(0, buf, 0, 1, null);",
        "        } catch {",
        "            break;",
        "        }",
        "        if (n === 0) break;",
        "        const ch = String.fromCharCode(buf[0]);",
        "        if (ch === \"\\r\") continue;",
        "        if (ch === \"\\n\") break;",
        "        line += ch;",
        "    }",
        "    return line;",
        "}",
        "",
        "function _meme_parse_int(s: string): number {",
        "    const ts = s.trim();",
        "    if (!/^[+-]?\\d+$/.test(ts)) {",
        "        console.log(`Error parsing integer: ${s}`);",
        "        process.exit(1);",
        "    }",
        "    try {",
        "        const b = BigInt(ts);",
        "        if (b < -9223372036854775808n || b > 9223372036854775807n) {",
        "            console.log(`Error parsing integer: ${s}`);",
        "            process.exit(1);",
        "        }",
        "        return Number(b);",
        "    } catch {",
        "        console.log(`Error parsing integer: ${s}`);",
        "        process.exit(1);",
        "    }",
        "}",
        "",
        "function _meme_parse_int_or_else(s: string, defaultFn: () => number): number {",
        "    const ts = s.trim();",
        "    if (!/^[+-]?\\d+$/.test(ts)) {",
        "        return defaultFn();",
        "    }",
        "    try {",
        "        const b = BigInt(ts);",
        "        if (b < -9223372036854775808n || b > 9223372036854775807n) {",
        "            return defaultFn();",
        "        }",
        "        return Number(b);",
        "    } catch {",
        "        return defaultFn();",
        "    }",
        "}",
        "",
        "function _meme_is_digit(s: string): boolean {",
        "    return s.length === 1 && s >= \"0\" && s <= \"9\";",
        "}",
        "",
        "function _meme_parse_float(s: string): number {",
        "    const v = parseFloat(s.trim());",
        "    return Number.isNaN(v) ? 0 : v;",
        "}",
        "",
        "function _meme_parse_bool(s: string): boolean {",
        "    const t = s.trim().toLowerCase();",
        "    return t === \"true\" || t === \"1\" || t === \"yes\";",
        "}",
        "",
        "let _meme_rng_state = 88172645463325252n;",
        "function _meme_rand_int(lo: number, hi: number): number {",
        "    if (hi <= lo) return lo;",
        "    let x = _meme_rng_state;",
        "    x ^= (x << 13n) & 0xFFFFFFFFFFFFFFFFn;",
        "    x ^= (x >> 7n) & 0xFFFFFFFFFFFFFFFFn;",
        "    x ^= (x << 17n) & 0xFFFFFFFFFFFFFFFFn;",
        "    _meme_rng_state = x;",
        "    const range = BigInt(hi - lo + 1);",
        "    const mod = Number(x >= 0n ? x % range : (-x) % range);",
        "    return lo + mod;",
        "}",
        "",
        "function _meme_rand_list(count: number, lo: number, hi: number): number[] {",
        "    const out: number[] = [];",
        "    for (let i = 0; i < count; i++) {",
        "        out.push(_meme_rand_int(lo, hi));",
        "    }",
        "    return out;",
        "}",
        "",
        "function _meme_read_json_list_int(filePath: string): number[] {",
        "    const raw = _meme_read_file_string(filePath);",
        "    let parsed: any;",
        "    try {",
        "        parsed = JSON.parse(raw);",
        "    } catch {",
        "        console.log(`Error reading JSON file: cannot parse JSON in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    if (!Array.isArray(parsed)) {",
        "        console.log(`Error reading JSON file: expected JSON array in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    for (const item of parsed) {",
        "        if (item === null || typeof item !== \"number\" || !Number.isInteger(item) || typeof item === \"boolean\") {",
        "            console.log(`Error reading JSON file: expected Int element, got ${item}`);",
        "            process.exit(1);",
        "        }",
        "    }",
        "    return parsed;",
        "}",
        "",
        "function _meme_read_json_list_float(filePath: string): number[] {",
        "    const raw = _meme_read_file_string(filePath);",
        "    let parsed: any;",
        "    try {",
        "        parsed = JSON.parse(raw);",
        "    } catch {",
        "        console.log(`Error reading JSON file: cannot parse JSON in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    if (!Array.isArray(parsed)) {",
        "        console.log(`Error reading JSON file: expected JSON array in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    for (const item of parsed) {",
        "        if (item === null || typeof item !== \"number\" || typeof item === \"boolean\") {",
        "            console.log(`Error reading JSON file: expected Float element, got ${item}`);",
        "            process.exit(1);",
        "        }",
        "    }",
        "    return parsed;",
        "}",
        "",
        "function _meme_read_json_list_string(filePath: string): string[] {",
        "    const raw = _meme_read_file_string(filePath);",
        "    let parsed: any;",
        "    try {",
        "        parsed = JSON.parse(raw);",
        "    } catch {",
        "        console.log(`Error reading JSON file: cannot parse JSON in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    if (!Array.isArray(parsed)) {",
        "        console.log(`Error reading JSON file: expected JSON array in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    for (const item of parsed) {",
        "        if (typeof item !== \"string\") {",
        "            console.log(`Error reading JSON file: expected String element, got ${item}`);",
        "            process.exit(1);",
        "        }",
        "    }",
        "    return parsed;",
        "}",
        "",
        "function _meme_read_json_list_bool(filePath: string): boolean[] {",
        "    const raw = _meme_read_file_string(filePath);",
        "    let parsed: any;",
        "    try {",
        "        parsed = JSON.parse(raw);",
        "    } catch {",
        "        console.log(`Error reading JSON file: cannot parse JSON in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    if (!Array.isArray(parsed)) {",
        "        console.log(`Error reading JSON file: expected JSON array in ${filePath}`);",
        "        process.exit(1);",
        "    }",
        "    for (const item of parsed) {",
        "        if (typeof item !== \"boolean\") {",
        "            console.log(`Error reading JSON file: expected Bool element, got ${item}`);",
        "            process.exit(1);",
        "        }",
        "    }",
        "    return parsed;",
        "}",
        "",
    ]

    record_blocks: list[str] = []
    for r in records:
        r_name = _ts_ident(r.name)
        record_blocks.append(f"interface {r_name} {{")
        record_blocks.append(f"    _meme_type: {json.dumps(r.name)};")
        for f in r.fields:
            record_blocks.append(f"    {_ts_ident(f.name)}: {_ts_type(f.field_type)};")
        record_blocks.append("}")
        if not r.fields:
            record_blocks.append(f'_meme_record_formatters[{json.dumps(r.name)}] = (r: any) => "{r.name}()";')
        else:
            fmt_parts = [f"`{f.name}=${{_meme_fmt(r.{_ts_ident(f.name)})}}`" for f in r.fields]
            record_blocks.append(
                f'_meme_record_formatters[{json.dumps(r.name)}] = (r: any) => "{r.name}(" + [{", ".join(fmt_parts)}].join(", ") + ")";'
            )
        record_blocks.append("")

    fn_blocks: list[str] = []
    for fn in funcs:
        fn_blocks.extend(gen.gen_func(fn))
        fn_blocks.append("")

    main_scope: dict[str, MemeType] = {}
    main_lines: list[str] = [
        "function main(): void {",
    ]
    for stmt in main_stmts:
        main_lines.extend(gen.gen_stmt(stmt, main_scope, indent=1))
    main_lines.append("}")
    main_lines.append("main();")
    main_lines.append("")

    out = preamble + record_blocks + fn_blocks + main_lines
    return "\n".join(out)

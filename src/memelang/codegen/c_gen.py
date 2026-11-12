"""Deterministic C11 (`gcc -std=c11 -O2 <file>.c -o <bin> -lm`) code generator for Memelang ProgramIR.

Emits clean, standard C11 code covering the full Memelang surface:
- Records -> structs (typedef struct) with per-record equality and formatting
- Lists -> growable typed arrays
- Maps -> sorted dynamic array of key-value pairs (maintains sorted-key invariant at all times)
- Optional<T> -> struct { bool present; T value; } with lazy unwrap-or-else
- File I/O -> stdio (fopen/fread/fwrite/fprintf) and stat()
- argv -> program argv (argc includes program name)
- Memory -> malloc/realloc bounds-checked allocation (CLI-lifetime programs)
"""

from __future__ import annotations

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
    ListAppendStmt,
    ListIndexExpr,
    ListInsertStmt,
    ListLengthExpr,
    ListLiteralExpr,
    ListSetIndexStmt,
    LiteralExpr,
    MapEntry,
    MapGetExpr,
    MapHasKeyExpr,
    MapLiteralExpr,
    MapSetStmt,
    MemeType,
    OptionalIsNothingExpr,
    OptionalNoneExpr,
    OptionalUnwrapExpr,
    OptionalUnwrapOrDefaultExpr,
    OptionalWrapExpr,
    ParseIntExpr,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadFileStringExpr,
    ReadInputExpr,
    ReadJsonListExpr,
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

_C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if",
    "inline", "int", "long", "register", "restrict", "return", "short",
    "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
    "unsigned", "void", "volatile", "while", "_Alignas", "_Alignof",
    "_Atomic", "_Bool", "_Complex", "_Generic", "_Imaginary", "_Noreturn",
    "_Static_assert", "_Thread_local", "main", "stdin", "stdout", "stderr",
    "exit", "free", "malloc", "realloc", "calloc", "abs", "div", "rand",
}


def _escape_c_str(val: str) -> str:
    out: list[str] = ['"']
    for ch in val:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32:
            out.append(f'\\x{ord(ch):02x}""')
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _c_ident(name: str) -> str:
    cleaned = name.replace("-", "_")
    if cleaned in _C_KEYWORDS or cleaned.startswith("_meme_"):
        return f"meme_{cleaned}"
    return cleaned


def _map_types_of(map_type: str) -> tuple[str, str] | None:
    if map_type.startswith("Map<") and map_type.endswith(">"):
        inner = map_type[4:-1]
        depth = 0
        comma = -1
        for i, ch in enumerate(inner):
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
            elif ch == "," and depth == 0:
                comma = i
                break
        if comma != -1:
            return inner[:comma].strip(), inner[comma + 1 :].strip()
    return None


def _mangle_type(meme_type: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]", "_", meme_type)
    return re.sub(r"_+", "_", clean).strip("_")


def _c_type(meme_type: MemeType | str) -> str:
    if meme_type.startswith("List<") and meme_type.endswith(">"):
        inner = meme_type[5:-1]
        return f"meme_list_{_mangle_type(inner)}"
    if meme_type.startswith("Optional<") and meme_type.endswith(">"):
        inner = meme_type[9:-1]
        return f"meme_opt_{_mangle_type(inner)}"
    map_t = _map_types_of(meme_type)
    if map_t is not None:
        return f"meme_map_{_mangle_type(map_t[0])}_{_mangle_type(map_t[1])}"
    mapping = {
        "Int": "int64_t",
        "Float": "double",
        "Bool": "bool",
        "String": "const char*",
        "Void": "void",
    }
    if meme_type in mapping:
        return mapping[meme_type]
    return _c_ident(meme_type)


def _collect_types_from_expr(expr: IRExpr, out: set[str]) -> None:
    if isinstance(expr, ListLiteralExpr):
        out.add(f"List<{expr.element_type}>")
        out.add(expr.element_type)
        for e in expr.elements:
            _collect_types_from_expr(e, out)
    elif isinstance(expr, MapLiteralExpr):
        out.add(f"Map<{expr.key_type}, {expr.value_type}>")
        out.add(expr.key_type)
        out.add(expr.value_type)
        for entry in expr.entries:
            _collect_types_from_expr(entry.key, out)
            _collect_types_from_expr(entry.value, out)
    elif isinstance(expr, ReadJsonListExpr):
        out.add(f"List<{expr.element_type}>")
        out.add(expr.element_type)
        _collect_types_from_expr(expr.filepath, out)
    elif isinstance(expr, StringSplitExpr):
        out.add("List<String>")
        out.add("String")
        _collect_types_from_expr(expr.target, out)
        _collect_types_from_expr(expr.separator, out)
    elif isinstance(expr, BinaryOpExpr):
        _collect_types_from_expr(expr.left, out)
        _collect_types_from_expr(expr.right, out)
    elif isinstance(expr, UnaryOpExpr):
        _collect_types_from_expr(expr.operand, out)
    elif isinstance(expr, CallExpr):
        for a in expr.args:
            _collect_types_from_expr(a, out)
    elif isinstance(expr, ListIndexExpr):
        _collect_types_from_expr(expr.target, out)
        _collect_types_from_expr(expr.index, out)
    elif isinstance(expr, ListLengthExpr):
        _collect_types_from_expr(expr.target, out)
    elif isinstance(expr, RecordLiteralExpr):
        out.add(expr.record_name)
        for f in expr.fields:
            _collect_types_from_expr(f.value, out)
    elif isinstance(expr, RecordFieldExpr):
        _collect_types_from_expr(expr.target, out)
    elif isinstance(expr, MapGetExpr):
        _collect_types_from_expr(expr.target, out)
        _collect_types_from_expr(expr.key, out)
        if expr.default_val is not None:
            _collect_types_from_expr(expr.default_val, out)
    elif isinstance(expr, MapHasKeyExpr):
        _collect_types_from_expr(expr.target, out)
        _collect_types_from_expr(expr.key, out)
    elif isinstance(expr, OptionalWrapExpr):
        _collect_types_from_expr(expr.value, out)
    elif isinstance(expr, OptionalIsNothingExpr):
        _collect_types_from_expr(expr.target, out)
    elif isinstance(expr, OptionalUnwrapExpr):
        _collect_types_from_expr(expr.target, out)
    elif isinstance(expr, OptionalUnwrapOrDefaultExpr):
        _collect_types_from_expr(expr.target, out)
        _collect_types_from_expr(expr.default_val, out)
    elif isinstance(expr, (StringLengthExpr, StringSliceExpr, StringReplaceExpr,
                           StringUpperExpr, StringLowerExpr, StringTrimExpr,
                           StringJoinExpr, StringIndexOfExpr, StringCharAtExpr,
                           StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr,
                           FileExistsExpr, ReadFileStringExpr, ParseIntExpr, FormatIntExpr)):
        for attr in ("target", "substring", "prefix", "suffix", "old", "new",
                     "start", "end", "filepath", "index", "separator", "items"):
            if hasattr(expr, attr):
                val = getattr(expr, attr)
                if hasattr(val, "expr_type"):
                    _collect_types_from_expr(val, out)


def _collect_types_from_stmt(stmt: IRStatement, out: set[str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        out.add(stmt.var_type)
        _collect_types_from_expr(stmt.value, out)
    elif isinstance(stmt, AssignStmt):
        _collect_types_from_expr(stmt.value, out)
    elif isinstance(stmt, CompoundAssignStmt):
        _collect_types_from_expr(stmt.value, out)
    elif isinstance(stmt, RecordDefStmt):
        out.add(stmt.name)
        for f in stmt.fields:
            out.add(f.field_type)
    elif isinstance(stmt, FuncDefStmt):
        out.add(stmt.return_type)
        for p in stmt.params:
            out.add(p.param_type)
        for s in stmt.body:
            _collect_types_from_stmt(s, out)
    elif isinstance(stmt, IfStmt):
        _collect_types_from_expr(stmt.condition, out)
        for s in stmt.then_body:
            _collect_types_from_stmt(s, out)
        for s in stmt.else_body:
            _collect_types_from_stmt(s, out)
    elif isinstance(stmt, SwitchStmt):
        _collect_types_from_expr(stmt.target, out)
        for c in stmt.cases:
            _collect_types_from_expr(c.value, out)
            for s in c.body:
                _collect_types_from_stmt(s, out)
        for s in stmt.default_body:
            _collect_types_from_stmt(s, out)
    elif isinstance(stmt, ForEachStmt):
        for s in stmt.body:
            _collect_types_from_stmt(s, out)
    elif isinstance(stmt, ForRangeStmt):
        _collect_types_from_expr(stmt.start, out)
        _collect_types_from_expr(stmt.end, out)
        for s in stmt.body:
            _collect_types_from_stmt(s, out)
    elif isinstance(stmt, WhileStmt):
        _collect_types_from_expr(stmt.condition, out)
        for s in stmt.body:
            _collect_types_from_stmt(s, out)
    elif isinstance(stmt, PrintStmt):
        for e in stmt.expressions:
            _collect_types_from_expr(e, out)
    elif isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _collect_types_from_expr(stmt.value, out)
    elif isinstance(stmt, FailStmt):
        _collect_types_from_expr(stmt.message, out)
    elif isinstance(stmt, ExitStmt):
        _collect_types_from_expr(stmt.code, out)
    elif isinstance(stmt, (ListAppendStmt, ListInsertStmt, ListSetIndexStmt)):
        _collect_types_from_expr(stmt.value, out)
        if hasattr(stmt, "index"):
            _collect_types_from_expr(stmt.index, out)
    elif isinstance(stmt, ClampCollectionStmt):
        _collect_types_from_expr(stmt.min_val, out)
        _collect_types_from_expr(stmt.max_val, out)
    elif isinstance(stmt, FilterCollectionStmt):
        _collect_types_from_expr(stmt.predicate, out)
    elif isinstance(stmt, RecordSetFieldStmt):
        _collect_types_from_expr(stmt.value, out)
    elif isinstance(stmt, MapSetStmt):
        _collect_types_from_expr(stmt.key, out)
        _collect_types_from_expr(stmt.value, out)
    elif isinstance(stmt, (WriteFileStmt, AppendFileStmt)):
        _collect_types_from_expr(stmt.filepath, out)
        _collect_types_from_expr(stmt.content, out)


class _CGen:
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_input = False
        self.uses_str_helpers = False
        self.uses_json_io = False
        self.uses_file_io = False
        self.uses_argv = False
        self.uses_int_div = False
        self.uses_int_mod = False
        self._match_counter = 0
        self.func_returns: dict[str, MemeType] = {}
        self.func_params: dict[str, list[FuncParam]] = {}
        self.records: dict[str, dict[str, MemeType]] = {}
        self.current_func_return: str | None = None

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
            return f"List<{expr.element_type}>"  # type: ignore[return-value]
        if isinstance(expr, StringSplitExpr):
            return "List<String>"
        if isinstance(expr, (StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr, FileExistsExpr)):
            return "Bool"
        if isinstance(
            expr,
            (RandomIntExpr, ListLengthExpr, StringLengthExpr, StringIndexOfExpr, ArgCountExpr, ParseIntExpr),
        ):
            return "Int"
        if isinstance(
            expr,
            (
                StringSliceExpr,
                StringReplaceExpr,
                StringUpperExpr,
                StringLowerExpr,
                StringTrimExpr,
                StringJoinExpr,
                StringCharAtExpr,
                ReadFileStringExpr,
                ArgAtExpr,
                FormatIntExpr,
            ),
        ):
            return "String"
        if isinstance(expr, ListIndexExpr):
            col_t = self.infer_type(expr.target, scope)
            if col_t.startswith("List<"):
                return col_t[5:-1]  # type: ignore[return-value]
            map_t = _map_types_of(col_t)
            if map_t is not None:
                return map_t[1]  # type: ignore[return-value]
            return "Int"
        if isinstance(expr, CallExpr):
            return self.func_returns.get(expr.func_name, "Int")
        if isinstance(expr, ReadInputExpr):
            return expr.target_type
        if isinstance(expr, RecordLiteralExpr):
            return expr.record_name
        if isinstance(expr, RecordFieldExpr):
            target_t = self.infer_type(expr.target, scope)
            return self.records.get(target_t, {}).get(expr.field_name, "String")
        if isinstance(expr, MapLiteralExpr):
            return f"Map<{expr.key_type}, {expr.value_type}>"
        if isinstance(expr, MapGetExpr):
            target_t = self.infer_type(expr.target, scope)
            mt = _map_types_of(target_t)
            return mt[1] if mt else "String"
        if isinstance(expr, MapHasKeyExpr):
            return "Bool"
        if isinstance(expr, OptionalNoneExpr):
            return "Optional<Void>"
        if isinstance(expr, OptionalWrapExpr):
            return f"Optional<{self.infer_type(expr.value, scope)}>"
        if isinstance(expr, OptionalIsNothingExpr):
            return "Bool"
        if isinstance(expr, (OptionalUnwrapExpr, OptionalUnwrapOrDefaultExpr)):
            tgt_t = self.infer_type(expr.target, scope)
            if tgt_t.startswith("Optional<") and tgt_t.endswith(">"):
                return tgt_t[9:-1]
            if isinstance(expr, OptionalUnwrapOrDefaultExpr):
                return self.infer_type(expr.default_val, scope)
            return "Int"
        if isinstance(expr, UnaryOpExpr):
            return "Bool" if expr.op == "not" else self.infer_type(expr.operand, scope)
        if isinstance(expr, BinaryOpExpr):
            if expr.op in ("==", "!=", "<", "<=", ">", ">=", "and", "or"):
                return "Bool"
            return self.infer_type(expr.left, scope)
        return "Int"

    def gen_expr(self, expr: IRExpr, scope: dict[str, MemeType], expected_type: str | None = None) -> str:
        if isinstance(expr, LiteralExpr):
            if expr.data_type == "Int":
                return f"{expr.value}LL"
            if expr.data_type == "Float":
                f_val = float(expr.value)
                if math.isnan(f_val):
                    return "NAN"
                if math.isinf(f_val):
                    return "-INFINITY" if f_val < 0 else "INFINITY"
                return str(f_val)
            if expr.data_type == "Bool":
                return "true" if expr.value else "false"
            if expr.data_type == "String":
                return _escape_c_str(str(expr.value))

        if isinstance(expr, VarRefExpr):
            return _c_ident(expr.name)

        if isinstance(expr, ListLiteralExpr):
            m_type = _mangle_type(expr.element_type)
            if not expr.elements:
                return f"_meme_list_{m_type}_new()"
            c_elems = ", ".join(self.gen_expr(e, scope, expr.element_type) for e in expr.elements)
            c_elem_type = _c_type(expr.element_type)
            return f"_meme_list_{m_type}_create({len(expr.elements)}LL, ({c_elem_type}[]){{ {c_elems} }})"

        if isinstance(expr, RandomIntExpr):
            self.uses_random = True
            lo = self.gen_expr(expr.min_val, scope)
            hi = self.gen_expr(expr.max_val, scope)
            return f"_meme_rand_int({lo}, {hi})"

        if isinstance(expr, RandomListExpr):
            self.uses_random = True
            count = self.gen_expr(expr.count, scope)
            lo = self.gen_expr(expr.min_val, scope)
            hi = self.gen_expr(expr.max_val, scope)
            return f"_meme_rand_list({count}, {lo}, {hi})"

        if isinstance(expr, UnaryOpExpr):
            if expr.op == "not":
                return f"(!{self.gen_expr(expr.operand, scope)})"
            return f"(-{self.gen_expr(expr.operand, scope)})"

        if isinstance(expr, BinaryOpExpr):
            left_t = self.infer_type(expr.left, scope)
            left = self.gen_expr(expr.left, scope)
            right = self.gen_expr(expr.right, scope)

            if left_t == "String":
                self.uses_str_helpers = True
                if expr.op == "+":
                    return f"_meme_str_concat({left}, {right})"
                if expr.op == "==":
                    return f"(strcmp({left}, {right}) == 0)"
                if expr.op == "!=":
                    return f"(strcmp({left}, {right}) != 0)"
                if expr.op == "<":
                    return f"(strcmp({left}, {right}) < 0)"
                if expr.op == "<=":
                    return f"(strcmp({left}, {right}) <= 0)"
                if expr.op == ">":
                    return f"(strcmp({left}, {right}) > 0)"
                if expr.op == ">=":
                    return f"(strcmp({left}, {right}) >= 0)"

            if left_t in self.records:
                rec_name = _c_ident(left_t)
                if expr.op == "==":
                    return f"{rec_name}_eq({left}, {right})"
                if expr.op == "!=":
                    return f"(!{rec_name}_eq({left}, {right}))"

            if expr.op == "/" and left_t == "Int":
                self.uses_int_div = True
                return f"_meme_int_div({left}, {right})"

            if expr.op == "%" and left_t == "Int":
                self.uses_int_mod = True
                return f"_meme_int_mod({left}, {right})"

            if expr.op == "%" and left_t == "Float":
                return f"fmod({left}, {right})"

            op_map = {"and": "&&", "or": "||"}
            c_op = op_map.get(expr.op, expr.op)
            return f"({left} {c_op} {right})"

        if isinstance(expr, ListLengthExpr):
            tgt = self.gen_expr(expr.target, scope)
            return f"({tgt}.len)"

        if isinstance(expr, ListIndexExpr):
            tgt_t = self.infer_type(expr.target, scope)
            idx = self.gen_expr(expr.index, scope)
            tgt = self.gen_expr(expr.target, scope)
            if tgt_t.startswith("Map<"):
                k_t, v_t = _map_types_of(tgt_t)  # type: ignore[misc]
                m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
                return f"_meme_map_{m_type}_get({tgt}, {idx})"
            if tgt_t.startswith("List<"):
                el_t = tgt_t[5:-1]
                m_type = _mangle_type(el_t)
                return f"_meme_list_{m_type}_get({tgt}, {idx})"
            return f"_meme_list_Int_get({tgt}, {idx})"

        if isinstance(expr, CallExpr):
            param_types = [p.param_type for p in self.func_params.get(expr.func_name, [])]
            args: list[str] = []
            for i, a in enumerate(expr.args):
                expected = param_types[i] if i < len(param_types) else None
                args.append(self.gen_expr(a, scope, expected))
            args_str = ", ".join(args)
            return f"{_c_ident(expr.func_name)}({args_str})"

        if isinstance(expr, ReadInputExpr):
            self.uses_input = True
            raw = f"_meme_read_line({_escape_c_str(expr.prompt)})"
            if expr.target_type == "Int":
                return f"_meme_parse_int({raw})"
            if expr.target_type == "Float":
                return f"_meme_parse_float({raw})"
            if expr.target_type == "Bool":
                return f"_meme_parse_bool({raw})"
            return raw

        if isinstance(expr, StrEndsWithExpr):
            self.uses_str_helpers = True
            return f"_meme_ends_with_ci({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.suffix, scope)})"

        if isinstance(expr, StrStartsWithExpr):
            self.uses_str_helpers = True
            return f"_meme_starts_with({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.prefix, scope)})"

        if isinstance(expr, StrContainsExpr):
            self.uses_str_helpers = True
            return f"_meme_str_contains({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.substring, scope)})"

        if isinstance(expr, StringReplaceExpr):
            self.uses_str_helpers = True
            return f"_meme_str_replace({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.old, scope)}, {self.gen_expr(expr.new, scope)})"

        if isinstance(expr, StringUpperExpr):
            self.uses_str_helpers = True
            return f"_meme_str_upper({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringLowerExpr):
            self.uses_str_helpers = True
            return f"_meme_str_lower({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringTrimExpr):
            self.uses_str_helpers = True
            return f"_meme_trim({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringSplitExpr):
            self.uses_str_helpers = True
            return f"_meme_str_split({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.separator, scope)})"

        if isinstance(expr, StringJoinExpr):
            self.uses_str_helpers = True
            return f"_meme_str_join({self.gen_expr(expr.items, scope)}, {self.gen_expr(expr.separator, scope)})"

        if isinstance(expr, StringIndexOfExpr):
            self.uses_str_helpers = True
            return f"_meme_str_index_of({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.substring, scope)})"

        if isinstance(expr, StringCharAtExpr):
            self.uses_str_helpers = True
            return f"_meme_char_at({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.index, scope)})"

        if isinstance(expr, StringLengthExpr):
            self.uses_str_helpers = True
            return f"_meme_str_len({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringSliceExpr):
            self.uses_str_helpers = True
            tgt = self.gen_expr(expr.target, scope)
            start = self.gen_expr(expr.start, scope)
            end = self.gen_expr(expr.end, scope)
            return f"_meme_str_slice({tgt}, {start}, {end})"

        if isinstance(expr, ParseIntExpr):
            self.uses_input_helpers = True
            self.uses_str_helpers = True
            return f"_meme_parse_int({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, FormatIntExpr):
            return f"_meme_fmt_int({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ReadJsonListExpr):
            self.uses_str_helpers = True
            self.uses_json_io = True
            return f"_meme_read_json_list_{expr.element_type.lower()}({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, FileExistsExpr):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return f"_meme_file_exists({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ReadFileStringExpr):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return f"_meme_read_file_string({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ArgCountExpr):
            self.uses_argv = True
            return "((int64_t)_meme_argc)"

        if isinstance(expr, ArgAtExpr):
            self.uses_argv = True
            return f"_meme_arg_at({self.gen_expr(expr.index, scope)})"

        if isinstance(expr, RecordLiteralExpr):
            rec_def = self.records.get(expr.record_name)
            if rec_def:
                field_map = {f.name: f.value for f in expr.fields}
                ordered_fields = [
                    (fname, field_map[fname]) for fname in rec_def if fname in field_map
                ]
            else:
                ordered_fields = [(f.name, f.value) for f in expr.fields]
            field_inits = ", ".join(
                f".{_c_ident(fname)} = {self.gen_expr(fval, scope, rec_def.get(fname) if rec_def else None)}"
                for fname, fval in ordered_fields
            )
            return f"({_c_ident(expr.record_name)}){{ {field_inits} }}"

        if isinstance(expr, RecordFieldExpr):
            return f"{self.gen_expr(expr.target, scope)}.{_c_ident(expr.field_name)}"

        if isinstance(expr, MapLiteralExpr):
            m_type = f"{_mangle_type(expr.key_type)}_{_mangle_type(expr.value_type)}"
            if not expr.entries:
                return f"_meme_map_{m_type}_new()"
            entry_type = f"meme_entry_{m_type}"
            entries_str = ", ".join(
                f"{{ {self.gen_expr(e.key, scope, expr.key_type)}, {self.gen_expr(e.value, scope, expr.value_type)} }}"
                for e in expr.entries
            )
            return f"_meme_map_{m_type}_literal({len(expr.entries)}LL, ({entry_type}[]){{ {entries_str} }})"

        if isinstance(expr, MapGetExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            tgt_t = self.infer_type(expr.target, scope)
            k_t, v_t = _map_types_of(tgt_t) if _map_types_of(tgt_t) else ("String", "Int")
            m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
            if expr.default_val is not None:
                def_val = self.gen_expr(expr.default_val, scope, v_t)
                return f"_meme_map_{m_type}_get_default({tgt}, {k}, {def_val})"
            return f"_meme_map_{m_type}_get({tgt}, {k})"

        if isinstance(expr, MapHasKeyExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            tgt_t = self.infer_type(expr.target, scope)
            k_t, v_t = _map_types_of(tgt_t) if _map_types_of(tgt_t) else ("String", "Int")
            m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
            return f"_meme_map_{m_type}_has_key({tgt}, {k})"

        if isinstance(expr, OptionalNoneExpr):
            if expected_type and expected_type.startswith("Optional<"):
                return f"({_c_type(expected_type)}){{0}}"
            return "{0}"

        if isinstance(expr, OptionalWrapExpr):
            inner_t = self.infer_type(expr.value, scope)
            if expected_type and expected_type.startswith("Optional<"):
                inner_t = expected_type[9:-1]
            m_type = _mangle_type(inner_t)
            val = self.gen_expr(expr.value, scope, inner_t)
            return f"_meme_opt_{m_type}_some({val})"

        if isinstance(expr, OptionalIsNothingExpr):
            tgt = self.gen_expr(expr.target, scope)
            if expr.negated:
                return f"(({tgt}).present)"
            return f"(!({tgt}).present)"

        if isinstance(expr, OptionalUnwrapExpr):
            tgt_t = self.infer_type(expr.target, scope)
            inner_t = tgt_t[9:-1] if tgt_t.startswith("Optional<") else "Int"
            m_type = _mangle_type(inner_t)
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_opt_{m_type}_unwrap({tgt})"

        if isinstance(expr, OptionalUnwrapOrDefaultExpr):
            tgt_t = self.infer_type(expr.target, scope)
            inner_t = tgt_t[9:-1] if tgt_t.startswith("Optional<") else "Int"
            tgt = self.gen_expr(expr.target, scope)
            def_val = self.gen_expr(expr.default_val, scope, inner_t)
            return f"(({tgt}).present ? ({tgt}).value : ({def_val}))"

        raise NotImplementedError(f"Unsupported expression: {type(expr).__name__}")

    def gen_stmt(self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 1) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            scope[stmt.name] = stmt.var_type
            ident = _c_ident(stmt.name)
            c_t = _c_type(stmt.var_type)
            val = self.gen_expr(stmt.value, scope, stmt.var_type)
            return [
                f"{pad}{c_t} {ident} = {val};",
                f"{pad}(void){ident};",
            ]

        if isinstance(stmt, AssignStmt):
            ident = _c_ident(stmt.name)
            tgt_t = scope.get(stmt.name)
            val = self.gen_expr(stmt.value, scope, tgt_t)
            return [f"{pad}{ident} = {val};"]

        if isinstance(stmt, CompoundAssignStmt):
            ident = _c_ident(stmt.target)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{ident} {stmt.operator}= {val};"]

        if isinstance(stmt, SortCollectionStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            m_type = _mangle_type(el_t)
            desc_flag = "true" if stmt.direction == "descending" else "false"
            return [f"{pad}_meme_list_{m_type}_sort(&{tgt}, {desc_flag});"]

        if isinstance(stmt, ClampCollectionStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            c_elem = _c_type(el_t)
            lo = self.gen_expr(stmt.min_val, scope, el_t)
            hi = self.gen_expr(stmt.max_val, scope, el_t)
            return [
                f"{pad}{{",
                f"{pad}    {c_elem} _lo = {lo};",
                f"{pad}    {c_elem} _hi = {hi};",
                f"{pad}    if (_lo <= _hi) {{",
                f"{pad}        for (int64_t _i = 0; _i < {tgt}.len; ++_i) {{",
                f"{pad}            if ({tgt}.data[_i] < _lo) {tgt}.data[_i] = _lo;",
                f"{pad}            else if ({tgt}.data[_i] > _hi) {tgt}.data[_i] = _hi;",
                f"{pad}        }}",
                f"{pad}    }}",
                f"{pad}}}",
            ]

        if isinstance(stmt, FilterCollectionStmt):
            tgt = _c_ident(stmt.target)
            iv = _c_ident(stmt.item_var)
            col_t = scope.get(stmt.target, "List<Int>")
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            c_elem = _c_type(el_t)
            sub = dict(scope)
            sub[stmt.item_var] = el_t  # type: ignore[assignment]
            pred = self.gen_expr(stmt.predicate, sub)
            return [
                f"{pad}{{",
                f"{pad}    int64_t _w = 0;",
                f"{pad}    for (int64_t _r = 0; _r < {tgt}.len; ++_r) {{",
                f"{pad}        {c_elem} {iv} = {tgt}.data[_r];",
                f"{pad}        (void){iv};",
                f"{pad}        if ({pred}) {{",
                f"{pad}            {tgt}.data[_w++] = {tgt}.data[_r];",
                f"{pad}        }}",
                f"{pad}    }}",
                f"{pad}    {tgt}.len = _w;",
                f"{pad}}}",
            ]

        if isinstance(stmt, ListAppendStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            m_type = _mangle_type(el_t)
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}_meme_list_{m_type}_append(&{tgt}, {val});"]

        if isinstance(stmt, ListInsertStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            m_type = _mangle_type(el_t)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}_meme_list_{m_type}_insert(&{tgt}, {idx}, {val});"]

        if isinstance(stmt, ListSetIndexStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            m_type = _mangle_type(el_t)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}_meme_list_{m_type}_set(&{tgt}, {idx}, {val});"]

        if isinstance(stmt, FailStmt):
            msg = self.gen_expr(stmt.message, scope)
            return [
                f"{pad}printf(\"%s\\n\", _meme_fmt_string({msg}));",
                f"{pad}exit(1);",
            ]

        if isinstance(stmt, ExitStmt):
            code = self.gen_expr(stmt.code, scope)
            return [f"{pad}exit((int)(({code}) & 0xFF));"]

        if isinstance(stmt, PrintStmt):
            if not stmt.expressions:
                return [f'{pad}printf("\\n");']
            fmts: list[str] = []
            for e in stmt.expressions:
                t = self.infer_type(e, scope)
                fmt_fn = self._fmt_function_name(t)
                fmts.append(f"{fmt_fn}({self.gen_expr(e, scope)})")
            fmt_str = " ".join(["%s"] * len(stmt.expressions)) + "\\n"
            return [f'{pad}printf("{fmt_str}", {", ".join(fmts)});']

        if isinstance(stmt, IfStmt):
            lines = [f"{pad}if ({self.gen_expr(stmt.condition, scope)}) {{"]
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

        if isinstance(stmt, SwitchStmt):
            self._match_counter += 1
            m_var = f"_meme_m{self._match_counter}"
            tgt_t = self.infer_type(stmt.target, scope)
            c_tgt_t = _c_type(tgt_t)
            lines = [f"{pad}{{"]
            lines.append(f"{pad}    {c_tgt_t} {m_var} = {self.gen_expr(stmt.target, scope)};")
            lines.append(f"{pad}    (void){m_var};")
            if stmt.cases:
                for i, case in enumerate(stmt.cases):
                    kw = "if" if i == 0 else "} else if"
                    case_val = self.gen_expr(case.value, scope, tgt_t)
                    if tgt_t == "String":
                        cond = f"(strcmp({m_var}, {case_val}) == 0)"
                    else:
                        cond = f"({m_var} == {case_val})"
                    lines.append(f"{pad}    {kw} {cond} {{")
                    case_scope = dict(scope)
                    for ch in case.body:
                        lines.extend(self.gen_stmt(ch, case_scope, indent + 2))
                if stmt.default_body:
                    lines.append(f"{pad}    }} else {{")
                    def_scope = dict(scope)
                    for ch in stmt.default_body:
                        lines.extend(self.gen_stmt(ch, def_scope, indent + 2))
                lines.append(f"{pad}    }}")
            elif stmt.default_body:
                def_scope = dict(scope)
                for ch in stmt.default_body:
                    lines.extend(self.gen_stmt(ch, def_scope, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, ForEachStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.collection, "List<Int>")
            col_ident = _c_ident(stmt.collection)
            item_ident = _c_ident(stmt.item_var)
            map_t = _map_types_of(col_t)

            if map_t is not None:
                k_t, v_t = map_t
                sub[stmt.item_var] = k_t  # type: ignore[assignment]
                c_k_t = _c_type(k_t)
                m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
                lines = [
                    f"{pad}{{",
                    f"{pad}    meme_map_{m_type} _meme_col = _meme_map_{m_type}_copy({col_ident});",
                    f"{pad}    for (int64_t _meme_idx = 0; _meme_idx < _meme_col.len; ++_meme_idx) {{",
                    f"{pad}        {c_k_t} {item_ident} = _meme_col.data[_meme_idx].key;",
                    f"{pad}        (void){item_ident};",
                ]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _c_ident(stmt.index_var)
                    lines.append(f"{pad}        int64_t {idx_ident} = _meme_idx;")
                    lines.append(f"{pad}        (void){idx_ident};")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines
            else:
                el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
                sub[stmt.item_var] = el_t  # type: ignore[assignment]
                c_el_t = _c_type(el_t)
                m_type = _mangle_type(el_t)
                lines = [
                    f"{pad}{{",
                    f"{pad}    meme_list_{m_type} _meme_col = _meme_list_{m_type}_copy({col_ident});",
                    f"{pad}    for (int64_t _meme_idx = 0; _meme_idx < _meme_col.len; ++_meme_idx) {{",
                    f"{pad}        {c_el_t} {item_ident} = _meme_col.data[_meme_idx];",
                    f"{pad}        (void){item_ident};",
                ]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _c_ident(stmt.index_var)
                    lines.append(f"{pad}        int64_t {idx_ident} = _meme_idx;")
                    lines.append(f"{pad}        (void){idx_ident};")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines

        if isinstance(stmt, ForRangeStmt):
            lines = [f"{pad}{{"]
            start = self.gen_expr(stmt.start, scope)
            end = self.gen_expr(stmt.end, scope)
            loop_var = _c_ident(stmt.loop_var)
            lines.append(f"{pad}    int64_t _start = {start};")
            lines.append(f"{pad}    int64_t _end = {end};")
            lines.append(f"{pad}    for (int64_t {loop_var} = _start; {loop_var} <= _end; ++{loop_var}) {{")
            sub = dict(scope)
            sub[stmt.loop_var] = "Int"
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, sub, indent + 2))
            lines.append(f"{pad}    }}")
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, WhileStmt):
            lines = [f"{pad}while ({self.gen_expr(stmt.condition, scope)}) {{"]
            sub = dict(scope)
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, sub, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, BreakStmt):
            return [f"{pad}break;"]

        if isinstance(stmt, ContinueStmt):
            return [f"{pad}continue;"]

        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                return [f"{pad}return;"]
            return [f"{pad}return {self.gen_expr(stmt.value, scope, self.current_func_return)};"]

        if isinstance(stmt, RecordDefStmt):
            return []

        if isinstance(stmt, RecordSetFieldStmt):
            tgt = _c_ident(stmt.target)
            fld = _c_ident(stmt.field_name)
            rec_t = scope.get(stmt.target, "")
            expected_f_t = self.records.get(rec_t, {}).get(stmt.field_name)
            val = self.gen_expr(stmt.value, scope, expected_f_t)
            return [f"{pad}{tgt}.{fld} = {val};"]

        if isinstance(stmt, MapSetStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "")
            k_t, v_t = _map_types_of(col_t) if _map_types_of(col_t) else ("String", "Int")
            m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
            k = self.gen_expr(stmt.key, scope, k_t)
            val = self.gen_expr(stmt.value, scope, v_t)
            return [f"{pad}_meme_map_{m_type}_set(&{tgt}, {k}, {val});"]

        if isinstance(stmt, WriteFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            path = self.gen_expr(stmt.filepath, scope)
            content = self.gen_expr(stmt.content, scope)
            return [f"{pad}_meme_write_file({path}, {content});"]

        if isinstance(stmt, AppendFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            path = self.gen_expr(stmt.filepath, scope)
            content = self.gen_expr(stmt.content, scope)
            return [f"{pad}_meme_append_file({path}, {content});"]

        raise NotImplementedError(f"Unsupported statement: {type(stmt).__name__}")

    def _fmt_function_name(self, meme_type: str) -> str:
        if meme_type == "Int":
            return "_meme_fmt_int"
        if meme_type == "Float":
            return "_meme_fmt_float"
        if meme_type == "Bool":
            return "_meme_fmt_bool"
        if meme_type == "String":
            return "_meme_fmt_string"
        if meme_type.startswith("List<") and meme_type.endswith(">"):
            inner = meme_type[5:-1]
            return f"_meme_fmt_list_{_mangle_type(inner)}"
        if meme_type.startswith("Optional<") and meme_type.endswith(">"):
            inner = meme_type[9:-1]
            return f"_meme_fmt_opt_{_mangle_type(inner)}"
        map_t = _map_types_of(meme_type)
        if map_t is not None:
            return f"_meme_fmt_map_{_mangle_type(map_t[0])}_{_mangle_type(map_t[1])}"
        return f"_meme_fmt_{_c_ident(meme_type)}"

    def gen_func(self, fn: FuncDefStmt) -> list[str]:
        self.func_returns[fn.name] = fn.return_type
        self.func_params[fn.name] = fn.params
        self.current_func_return = fn.return_type
        params = ", ".join(f"{_c_type(p.param_type)} {_c_ident(p.name)}" for p in fn.params)
        fn_scope = {p.name: p.param_type for p in fn.params}
        c_ret = _c_type(fn.return_type)
        lines = [f"{c_ret} {_c_ident(fn.name)}({params}) {{"]
        for p in fn.params:
            lines.append(f"    (void){_c_ident(p.name)};")
        for ch in fn.body:
            lines.extend(self.gen_stmt(ch, fn_scope, indent=1))
        if fn.return_type != "Void" and not (fn.body and isinstance(fn.body[-1], ReturnStmt)):
            lines.append(f"    return ({c_ret}){{0}};")
        lines.append("}")
        self.current_func_return = None
        return lines

def _emit_list_type(el_t: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(el_t)
    c_elem = _c_type(el_t)
    is_sortable = el_t in ("Int", "Float", "String", "Bool")
    elem_fmt_call = gen._fmt_function_name(el_t)

    if el_t == "String":
        elem_eq = "(strcmp(a.data[i], b.data[i]) == 0)"
    elif el_t in gen.records:
        elem_eq = f"{_c_ident(el_t)}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("List<") and el_t.endswith(">"):
        inner_m = _mangle_type(el_t[5:-1])
        elem_eq = f"_meme_list_{inner_m}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Map<") and el_t.endswith(">"):
        inner_map = _map_types_of(el_t)
        inner_m = f"{_mangle_type(inner_map[0])}_{_mangle_type(inner_map[1])}" if inner_map else "unknown"
        elem_eq = f"_meme_map_{inner_m}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Optional<") and el_t.endswith(">"):
        inner_m = _mangle_type(el_t[9:-1])
        elem_eq = f"_meme_opt_{inner_m}_eq(a.data[i], b.data[i])"
    else:
        elem_eq = "(a.data[i] == b.data[i])"

    list_lines = [
        f"// List<{el_t}>",
        f"typedef struct {{",
        f"    {c_elem}* data;",
        f"    int64_t len;",
        f"    int64_t cap;",
        f"}} meme_list_{m_type};",
        f"static inline meme_list_{m_type} _meme_list_{m_type}_new(void) {{",
        f"    meme_list_{m_type} l;",
        f"    l.data = NULL; l.len = 0; l.cap = 0;",
        f"    return l;",
        f"}}",
        f"static inline meme_list_{m_type} _meme_list_{m_type}_create(int64_t count, {c_elem} const* items) {{",
        f"    meme_list_{m_type} l;",
        f"    l.len = count;",
        f"    l.cap = count > 0 ? count : 4;",
        f"    l.data = ({c_elem}*)malloc(sizeof({c_elem}) * l.cap);",
        f"    if (count > 0 && items) {{ memcpy(l.data, items, sizeof({c_elem}) * count); }}",
        f"    return l;",
        f"}}",
        f"static inline meme_list_{m_type} _meme_list_{m_type}_copy(meme_list_{m_type} l) {{",
        f"    meme_list_{m_type} res;",
        f"    res.len = l.len;",
        f"    res.cap = l.len > 0 ? l.len : 4;",
        f"    res.data = ({c_elem}*)malloc(sizeof({c_elem}) * res.cap);",
        f"    if (l.len > 0 && l.data) {{ memcpy(res.data, l.data, sizeof({c_elem}) * l.len); }}",
        f"    return res;",
        f"}}",
        f"static inline void _meme_list_{m_type}_append(meme_list_{m_type}* l, {c_elem} val) {{",
        f"    if (l->len >= l->cap) {{",
        f"        l->cap = l->cap == 0 ? 4 : l->cap * 2;",
        f"        l->data = ({c_elem}*)realloc(l->data, sizeof({c_elem}) * l->cap);",
        f"    }}",
        f"    l->data[l->len++] = val;",
        f"}}",
        f"static inline void _meme_list_{m_type}_insert(meme_list_{m_type}* l, int64_t idx, {c_elem} val) {{",
        f"    if (idx < 0) idx = 0;",
        f"    if (idx > l->len) idx = l->len;",
        f"    if (l->len >= l->cap) {{",
        f"        l->cap = l->cap == 0 ? 4 : l->cap * 2;",
        f"        l->data = ({c_elem}*)realloc(l->data, sizeof({c_elem}) * l->cap);",
        f"    }}",
        f"    for (int64_t i = l->len; i > idx; --i) l->data[i] = l->data[i - 1];",
        f"    l->data[idx] = val;",
        f"    l->len++;",
        f"}}",
        f"static inline {c_elem} _meme_list_{m_type}_get(meme_list_{m_type} l, int64_t idx) {{",
        f"    if (idx < 0 || idx >= l.len) {{",
        f"        printf(\"Error: list index out of range\\n\");",
        f"        exit(1);",
        f"    }}",
        f"    return l.data[idx];",
        f"}}",
        f"static inline void _meme_list_{m_type}_set(meme_list_{m_type}* l, int64_t idx, {c_elem} val) {{",
        f"    if (idx < 0 || idx >= l->len) {{",
        f"        printf(\"Error: list index out of range\\n\");",
        f"        exit(1);",
        f"    }}",
        f"    l->data[idx] = val;",
        f"}}",
        f"static inline const char* _meme_fmt_list_{m_type}(meme_list_{m_type} l) {{",
        f"    _MemeSB sb = _meme_sb_new();",
        f"    _meme_sb_append_char(&sb, '[');",
        f"    for (int64_t i = 0; i < l.len; ++i) {{",
        f"        if (i > 0) _meme_sb_append(&sb, \", \");",
        f"        _meme_sb_append(&sb, {elem_fmt_call}(l.data[i]));",
        f"    }}",
        f"    _meme_sb_append_char(&sb, ']');",
        f"    return sb.data;",
        f"}}",
        f"static inline bool _meme_list_{m_type}_eq(meme_list_{m_type} a, meme_list_{m_type} b) {{",
        f"    if (a.len != b.len) return false;",
        f"    for (int64_t i = 0; i < a.len; ++i) {{",
        f"        if (!{elem_eq}) return false;",
        f"    }}",
        f"    return true;",
        f"}}",
    ]

    if is_sortable:
        cmp_fn = f"_cmp_{el_t}"
        list_lines.extend([
            f"static void _meme_merge_sort_{m_type}({c_elem}* arr, {c_elem}* temp, int64_t left, int64_t right, bool desc) {{",
            f"    if (left >= right) return;",
            f"    int64_t mid = left + (right - left) / 2;",
            f"    _meme_merge_sort_{m_type}(arr, temp, left, mid, desc);",
            f"    _meme_merge_sort_{m_type}(arr, temp, mid + 1, right, desc);",
            f"    int64_t i = left, j = mid + 1, k = left;",
            f"    while (i <= mid && j <= right) {{",
            f"        bool take_left = !desc ? ({cmp_fn}(arr[i], arr[j]) <= 0) : ({cmp_fn}(arr[i], arr[j]) >= 0);",
            f"        if (take_left) temp[k++] = arr[i++];",
            f"        else temp[k++] = arr[j++];",
            f"    }}",
            f"    while (i <= mid) temp[k++] = arr[i++];",
            f"    while (j <= right) temp[k++] = arr[j++];",
            f"    for (i = left; i <= right; i++) arr[i] = temp[i];",
            f"}}",
            f"static inline void _meme_list_{m_type}_sort(meme_list_{m_type}* l, bool desc) {{",
            f"    if (l->len <= 1) return;",
            f"    {c_elem}* temp = ({c_elem}*)malloc(sizeof({c_elem}) * l->len);",
            f"    _meme_merge_sort_{m_type}(l->data, temp, 0, l->len - 1, desc);",
            f"    free(temp);",
            f"}}",
        ])
    return list_lines


def _emit_map_type(k_t: str, v_t: str, gen: _CGen) -> list[str]:
    m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
    c_k_t = _c_type(k_t)
    c_v_t = _c_type(v_t)
    cmp_fn = f"_cmp_{k_t}"
    k_fmt_call = gen._fmt_function_name(k_t)
    v_fmt_call = gen._fmt_function_name(v_t)

    if v_t == "String":
        val_eq = "(strcmp(a.data[i].value, b.data[i].value) == 0)"
    elif v_t in gen.records:
        val_eq = f"{_c_ident(v_t)}_eq(a.data[i].value, b.data[i].value)"
    elif v_t.startswith("List<"):
        el_t = v_t[5:-1]
        val_eq = f"_meme_list_{_mangle_type(el_t)}_eq(a.data[i].value, b.data[i].value)"
    else:
        val_eq = "(a.data[i].value == b.data[i].value)"

    return [
        f"// Map<{k_t}, {v_t}>",
        f"typedef struct {{",
        f"    {c_k_t} key;",
        f"    {c_v_t} value;",
        f"}} meme_entry_{m_type};",
        f"typedef struct {{",
        f"    meme_entry_{m_type}* data;",
        f"    int64_t len;",
        f"    int64_t cap;",
        f"}} meme_map_{m_type};",
        f"static inline meme_map_{m_type} _meme_map_{m_type}_new(void) {{",
        f"    meme_map_{m_type} m;",
        f"    m.data = NULL; m.len = 0; m.cap = 0;",
        f"    return m;",
        f"}}",
        f"static inline meme_map_{m_type} _meme_map_{m_type}_copy(meme_map_{m_type} m) {{",
        f"    meme_map_{m_type} res;",
        f"    res.len = m.len;",
        f"    res.cap = m.len > 0 ? m.len : 4;",
        f"    res.data = (meme_entry_{m_type}*)malloc(sizeof(meme_entry_{m_type}) * res.cap);",
        f"    if (m.len > 0 && m.data) {{ memcpy(res.data, m.data, sizeof(meme_entry_{m_type}) * m.len); }}",
        f"    return res;",
        f"}}",
        f"static inline int64_t _meme_map_{m_type}_find(const meme_map_{m_type}* m, {c_k_t} key) {{",
        f"    int64_t lo = 0, hi = m->len - 1;",
        f"    while (lo <= hi) {{",
        f"        int64_t mid = lo + (hi - lo) / 2;",
        f"        int cmp = {cmp_fn}(m->data[mid].key, key);",
        f"        if (cmp == 0) return mid;",
        f"        if (cmp < 0) lo = mid + 1;",
        f"        else hi = mid - 1;",
        f"    }}",
        f"    return -1 - lo;",
        f"}}",
        f"static inline void _meme_map_{m_type}_set(meme_map_{m_type}* m, {c_k_t} key, {c_v_t} value) {{",
        f"    int64_t idx = _meme_map_{m_type}_find(m, key);",
        f"    if (idx >= 0) {{",
        f"        m->data[idx].value = value;",
        f"    }} else {{",
        f"        int64_t ins = -1 - idx;",
        f"        if (m->len >= m->cap) {{",
        f"            m->cap = m->cap == 0 ? 4 : m->cap * 2;",
        f"            m->data = (meme_entry_{m_type}*)realloc(m->data, sizeof(meme_entry_{m_type}) * m->cap);",
        f"        }}",
        f"        for (int64_t i = m->len; i > ins; --i) m->data[i] = m->data[i - 1];",
        f"        m->data[ins].key = key;",
        f"        m->data[ins].value = value;",
        f"        m->len++;",
        f"    }}",
        f"}}",
        f"static inline bool _meme_map_{m_type}_has_key(meme_map_{m_type} m, {c_k_t} key) {{",
        f"    return _meme_map_{m_type}_find(&m, key) >= 0;",
        f"}}",
        f"static inline {c_v_t} _meme_map_{m_type}_get(meme_map_{m_type} m, {c_k_t} key) {{",
        f"    int64_t idx = _meme_map_{m_type}_find(&m, key);",
        f"    if (idx < 0) {{",
        f"        printf(\"Error: key not found in map\\n\");",
        f"        exit(1);",
        f"    }}",
        f"    return m.data[idx].value;",
        f"}}",
        f"static inline {c_v_t} _meme_map_{m_type}_get_default(meme_map_{m_type} m, {c_k_t} key, {c_v_t} default_val) {{",
        f"    int64_t idx = _meme_map_{m_type}_find(&m, key);",
        f"    if (idx >= 0) return m.data[idx].value;",
        f"    return default_val;",
        f"}}",
        f"static inline meme_map_{m_type} _meme_map_{m_type}_literal(int64_t count, const meme_entry_{m_type}* entries) {{",
        f"    meme_map_{m_type} res = _meme_map_{m_type}_new();",
        f"    for (int64_t i = 0; i < count; ++i) {{",
        f"        _meme_map_{m_type}_set(&res, entries[i].key, entries[i].value);",
        f"    }}",
        f"    return res;",
        f"}}",
        f"static inline const char* _meme_fmt_map_{m_type}(meme_map_{m_type} m) {{",
        f"    _MemeSB sb = _meme_sb_new();",
        f"    _meme_sb_append_char(&sb, '{{');",
        f"    for (int64_t i = 0; i < m.len; ++i) {{",
        f"        if (i > 0) _meme_sb_append(&sb, \", \");",
        f"        _meme_sb_append(&sb, {k_fmt_call}(m.data[i].key));",
        f"        _meme_sb_append(&sb, \": \");",
        f"        _meme_sb_append(&sb, {v_fmt_call}(m.data[i].value));",
        f"    }}",
        f"    _meme_sb_append_char(&sb, '}}');",
        f"    return sb.data;",
        f"}}",
        f"static inline bool _meme_map_{m_type}_eq(meme_map_{m_type} a, meme_map_{m_type} b) {{",
        f"    if (a.len != b.len) return false;",
        f"    for (int64_t i = 0; i < a.len; ++i) {{",
        f"        if ({cmp_fn}(a.data[i].key, b.data[i].key) != 0) return false;",
        f"        if (!{val_eq}) return false;",
        f"    }}",
        f"    return true;",
        f"}}",
    ]


def _emit_opt_type(inner: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(inner)
    c_inner = _c_type(inner)
    inner_fmt_call = gen._fmt_function_name(inner)

    if inner == "String":
        val_eq = "(strcmp(a.value, b.value) == 0)"
    elif inner in gen.records:
        val_eq = f"{_c_ident(inner)}_eq(a.value, b.value)"
    elif inner.startswith("List<"):
        el_t = inner[5:-1]
        val_eq = f"_meme_list_{_mangle_type(el_t)}_eq(a.value, b.value)"
    else:
        val_eq = "(a.value == b.value)"

    return [
        f"// Optional<{inner}>",
        f"typedef struct {{",
        f"    bool present;",
        f"    {c_inner} value;",
        f"}} meme_opt_{m_type};",
        f"static inline meme_opt_{m_type} _meme_opt_{m_type}_some({c_inner} val) {{",
        f"    meme_opt_{m_type} o;",
        f"    o.present = true; o.value = val;",
        f"    return o;",
        f"}}",
        f"static inline {c_inner} _meme_opt_{m_type}_unwrap(meme_opt_{m_type} opt) {{",
        f"    if (!opt.present) {{",
        f"        printf(\"Unwrap failed: Optional value is nothing\\n\");",
        f"        exit(1);",
        f"    }}",
        f"    return opt.value;",
        f"}}",
        f"static inline const char* _meme_fmt_opt_{m_type}(meme_opt_{m_type} opt) {{",
        f"    if (opt.present) return {inner_fmt_call}(opt.value);",
        f"    return \"None\";",
        f"}}",
        f"static inline bool _meme_opt_{m_type}_eq(meme_opt_{m_type} a, meme_opt_{m_type} b) {{",
        f"    if (a.present != b.present) return false;",
        f"    if (!a.present) return true;",
        f"    return {val_eq};",
        f"}}",
    ]


def _emit_record(r: RecordDefStmt, gen: _CGen) -> list[str]:
    r_ident = _c_ident(r.name)
    lines = [f"struct {r_ident} {{"]
    for f in r.fields:
        lines.append(f"    {_c_type(f.field_type)} {_c_ident(f.name)};")
    lines.append("};")

    # Record equality
    lines.append(f"static inline bool {r_ident}_eq({r_ident} a, {r_ident} b) {{")
    if not r.fields:
        lines.append("    (void)a; (void)b; return true;")
    else:
        conds: list[str] = []
        for f in r.fields:
            f_ident = _c_ident(f.name)
            if f.field_type == "String":
                conds.append(f"(strcmp(a.{f_ident} ? a.{f_ident} : \"\", b.{f_ident} ? b.{f_ident} : \"\") == 0)")
            elif f.field_type in gen.records:
                conds.append(f"{_c_ident(f.field_type)}_eq(a.{f_ident}, b.{f_ident})")
            elif f.field_type.startswith("List<"):
                el_t = f.field_type[5:-1]
                conds.append(f"_meme_list_{_mangle_type(el_t)}_eq(a.{f_ident}, b.{f_ident})")
            elif f.field_type.startswith("Optional<"):
                el_t = f.field_type[9:-1]
                conds.append(f"_meme_opt_{_mangle_type(el_t)}_eq(a.{f_ident}, b.{f_ident})")
            else:
                conds.append(f"(a.{f_ident} == b.{f_ident})")
        lines.append(f"    return {' && '.join(conds)};")
    lines.append("}")

    # Record formatting
    lines.append(f"static inline const char* _meme_fmt_{r_ident}({r_ident} r) {{")
    if not r.fields:
        lines.append(f"    (void)r; return \"{r.name}()\";")
    else:
        lines.append("    _MemeSB sb = _meme_sb_new();")
        lines.append(f'    _meme_sb_append(&sb, "{r.name}(");')
        for idx, f in enumerate(r.fields):
            f_ident = _c_ident(f.name)
            fmt_fn = gen._fmt_function_name(f.field_type)
            if idx > 0:
                lines.append('    _meme_sb_append(&sb, ", ");')
            lines.append(f'    _meme_sb_append(&sb, "{f.name}=");')
            lines.append(f'    _meme_sb_append(&sb, {fmt_fn}(r.{f_ident}));')
        lines.append("    _meme_sb_append_char(&sb, ')');")
        lines.append("    return sb.data;")
    lines.append("}")
    return lines


def generate_c(ir: ProgramIR) -> str:
    gen = _CGen()
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

    # Collect all types used across the entire IR
    used_types: set[str] = set()
    for stmt in all_stmts:
        _collect_types_from_stmt(stmt, used_types)

    # Expand compound types recursively
    expanded = True
    while expanded:
        prev_len = len(used_types)
        curr = list(used_types)
        for t in curr:
            if t.startswith("List<") and t.endswith(">"):
                inner = t[5:-1]
                used_types.add(inner)
            elif t.startswith("Optional<") and t.endswith(">"):
                inner = t[9:-1]
                used_types.add(inner)
            map_t = _map_types_of(t)
            if map_t is not None:
                used_types.add(map_t[0])
                used_types.add(map_t[1])
            if t in gen.records:
                for f_type in gen.records[t].values():
                    used_types.add(f_type)
        expanded = len(used_types) > prev_len

    # Identify distinct lists, maps, optionals
    list_elem_types: list[str] = ["Int", "Float", "String", "Bool"]
    map_types: list[tuple[str, str]] = []
    opt_types: list[str] = []

    for t in used_types:
        if t.startswith("List<") and t.endswith(">"):
            el_t = t[5:-1]
            if el_t not in list_elem_types:
                list_elem_types.append(el_t)
        elif t.startswith("Optional<") and t.endswith(">"):
            inner = t[9:-1]
            if inner not in opt_types and inner != "Void":
                opt_types.append(inner)
        map_t = _map_types_of(t)
        if map_t is not None and map_t not in map_types:
            map_types.append(map_t)

    list_elem_types.sort(key=lambda x: (x.count("<"), len(x)))

    # Standard headers
    headers: list[str] = [
        "// Generated by Memelang C Backend (C11 standard)",
        "// Leaks are acceptable for CLI-lifetime execution; all helpers are bounds-checked.",
        "#include <stdio.h>",
        "#include <stdlib.h>",
        "#include <stdbool.h>",
        "#include <stdint.h>",
        "#include <string.h>",
        "#include <math.h>",
        "#include <ctype.h>",
        "#include <errno.h>",
        "#include <sys/stat.h>",
        "",
    ]

    # Forward typedefs for records so containers can reference them
    record_fwd_decls: list[str] = []
    for r in records:
        r_ident = _c_ident(r.name)
        record_fwd_decls.append(f"typedef struct {r_ident} {r_ident};")
    if record_fwd_decls:
        record_fwd_decls.append("")

    # Global runtime helpers
    runtime_helpers: list[str] = [
        "// String builder",
        "typedef struct {",
        "    char* data;",
        "    size_t len;",
        "    size_t cap;",
        "} _MemeSB;",
        "",
        "static inline _MemeSB _meme_sb_new(void) {",
        "    _MemeSB sb;",
        "    sb.cap = 64;",
        "    sb.len = 0;",
        "    sb.data = (char*)malloc(sb.cap);",
        "    sb.data[0] = '\\0';",
        "    return sb;",
        "}",
        "",
        "static inline void _meme_sb_append(_MemeSB* sb, const char* s) {",
        "    if (!s) return;",
        "    size_t slen = strlen(s);",
        "    if (sb->len + slen + 1 > sb->cap) {",
        "        sb->cap = (sb->len + slen + 1) * 2;",
        "        sb->data = (char*)realloc(sb->data, sb->cap);",
        "    }",
        "    memcpy(sb->data + sb->len, s, slen);",
        "    sb->len += slen;",
        "    sb->data[sb->len] = '\\0';",
        "}",
        "",
        "static inline void _meme_sb_append_char(_MemeSB* sb, char c) {",
        "    if (sb->len + 2 > sb->cap) {",
        "        sb->cap = (sb->cap + 2) * 2;",
        "        sb->data = (char*)realloc(sb->data, sb->cap);",
        "    }",
        "    sb->data[sb->len++] = c;",
        "    sb->data[sb->len] = '\\0';",
        "}",
        "",
        "// Primitive formatters and comparators",
        "static inline const char* _meme_fmt_bool(bool v) { return v ? \"true\" : \"false\"; }",
        "static inline const char* _meme_fmt_int(int64_t v) {",
        "    char* buf = (char*)malloc(32);",
        "    snprintf(buf, 32, \"%lld\", (long long)v);",
        "    return buf;",
        "}",
        "static inline const char* _meme_fmt_float(double v) {",
        "    if (isnan(v)) return signbit(v) ? \"-nan\" : \"nan\";",
        "    if (isinf(v)) return v < 0 ? \"-inf\" : \"inf\";",
        "    if (isfinite(v) && trunc(v) == v && v >= -9007199254740992.0 && v <= 9007199254740992.0) {",
        "        char* buf = (char*)malloc(32);",
        "        snprintf(buf, 32, \"%lld\", (long long)v);",
        "        return buf;",
        "    }",
        "    char* buf = (char*)malloc(64);",
        "    snprintf(buf, 64, \"%.6g\", v);",
        "    return buf;",
        "}",
        "static inline const char* _meme_fmt_string(const char* s) { return s ? s : \"\"; }",
        "static inline int _cmp_Int(int64_t a, int64_t b) { return (a > b) - (a < b); }",
        "static inline int _cmp_Float(double a, double b) { return (a > b) - (a < b); }",
        "static inline int _cmp_Bool(bool a, bool b) { return (int)a - (int)b; }",
        "static inline int _cmp_String(const char* a, const char* b) { return strcmp(a ? a : \"\", b ? b : \"\"); }",
        "static inline int64_t _meme_int_div(int64_t a, int64_t b) { return a / b; }",
        "static inline int64_t _meme_int_mod(int64_t a, int64_t b) { return a % b; }",
        "",
    ]

    # String verbs preamble
    str_helpers = [
        "static inline const char* _meme_str_concat(const char* a, const char* b) {",
        "    if (!a) a = \"\";",
        "    if (!b) b = \"\";",
        "    size_t la = strlen(a);",
        "    size_t lb = strlen(b);",
        "    char* res = (char*)malloc(la + lb + 1);",
        "    memcpy(res, a, la);",
        "    memcpy(res + la, b, lb);",
        "    res[la + lb] = '\\0';",
        "    return res;",
        "}",
        "static inline const char* _meme_trim(const char* s) {",
        "    if (!s) return \"\";",
        "    size_t a = 0;",
        "    while (s[a] && isspace((unsigned char)s[a])) a++;",
        "    size_t b = strlen(s);",
        "    while (b > a && isspace((unsigned char)s[b - 1])) b--;",
        "    size_t len = b - a;",
        "    char* res = (char*)malloc(len + 1);",
        "    memcpy(res, s + a, len);",
        "    res[len] = '\\0';",
        "    return res;",
        "}",
        "static inline int64_t _meme_str_len(const char* s) {",
        "    if (!s) return 0;",
        "    int64_t count = 0;",
        "    const unsigned char* p = (const unsigned char*)s;",
        "    while (*p) {",
        "        if ((*p & 0xC0) != 0x80) count++;",
        "        p++;",
        "    }",
        "    return count;",
        "}",
        "static inline const char* _meme_str_slice(const char* s, int64_t start, int64_t end) {",
        "    if (!s || start < 0) start = 0;",
        "    if (end <= start) {",
        "        char* empty = (char*)malloc(1);",
        "        empty[0] = '\\0';",
        "        return empty;",
        "    }",
        "    size_t slen = strlen(s);",
        "    size_t byte_start = slen;",
        "    size_t byte_end = slen;",
        "    int64_t cp_idx = 0;",
        "    for (size_t i = 0; i < slen; ++i) {",
        "        unsigned char c = (unsigned char)s[i];",
        "        if ((c & 0xC0) != 0x80) {",
        "            if (cp_idx == start) byte_start = i;",
        "            if (cp_idx == end) { byte_end = i; break; }",
        "            cp_idx++;",
        "        }",
        "    }",
        "    if (byte_start >= slen || byte_end <= byte_start) {",
        "        char* empty = (char*)malloc(1);",
        "        empty[0] = '\\0';",
        "        return empty;",
        "    }",
        "    size_t len = byte_end - byte_start;",
        "    char* res = (char*)malloc(len + 1);",
        "    memcpy(res, s + byte_start, len);",
        "    res[len] = '\\0';",
        "    return res;",
        "}",
        "static inline bool _meme_ends_with_ci(const char* s, const char* suf) {",
        "    const char* ts = _meme_trim(s);",
        "    size_t tlen = strlen(ts);",
        "    size_t slen = strlen(suf);",
        "    if (tlen < slen) return false;",
        "    size_t off = tlen - slen;",
        "    for (size_t i = 0; i < slen; ++i) {",
        "        if (tolower((unsigned char)ts[off + i]) != tolower((unsigned char)suf[i])) return false;",
        "    }",
        "    return true;",
        "}",
        "static inline bool _meme_starts_with(const char* s, const char* pre) {",
        "    if (!s || !pre) return false;",
        "    size_t slen = strlen(s);",
        "    size_t plen = strlen(pre);",
        "    if (slen < plen) return false;",
        "    return strncmp(s, pre, plen) == 0;",
        "}",
        "static inline bool _meme_str_contains(const char* s, const char* sub) {",
        "    if (!s || !sub) return false;",
        "    return strstr(s, sub) != NULL;",
        "}",
        "static inline int64_t _meme_str_index_of(const char* s, const char* sub) {",
        "    if (!s || !sub) return -1;",
        "    const char* p = strstr(s, sub);",
        "    return p ? (int64_t)(p - s) : -1;",
        "}",
        "static inline const char* _meme_char_at(const char* s, int64_t idx) {",
        "    size_t slen = s ? strlen(s) : 0;",
        "    if (idx < 0 || (size_t)idx >= slen) {",
        "        printf(\"Error: string index %lld out of range\\n\", (long long)idx);",
        "        exit(1);",
        "    }",
        "    char* res = (char*)malloc(2);",
        "    res[0] = s[idx];",
        "    res[1] = '\\0';",
        "    return res;",
        "}",
        "static inline const char* _meme_str_upper(const char* s) {",
        "    if (!s) return \"\";",
        "    size_t len = strlen(s);",
        "    char* res = (char*)malloc(len + 1);",
        "    for (size_t i = 0; i < len; ++i) res[i] = (char)toupper((unsigned char)s[i]);",
        "    res[len] = '\\0';",
        "    return res;",
        "}",
        "static inline const char* _meme_str_lower(const char* s) {",
        "    if (!s) return \"\";",
        "    size_t len = strlen(s);",
        "    char* res = (char*)malloc(len + 1);",
        "    for (size_t i = 0; i < len; ++i) res[i] = (char)tolower((unsigned char)s[i]);",
        "    res[len] = '\\0';",
        "    return res;",
        "}",
        "static inline const char* _meme_str_replace(const char* s, const char* old_sub, const char* new_sub) {",
        "    if (!s) return \"\";",
        "    if (!old_sub) old_sub = \"\";",
        "    if (!new_sub) new_sub = \"\";",
        "    size_t old_len = strlen(old_sub);",
        "    size_t new_len = strlen(new_sub);",
        "    size_t s_len = strlen(s);",
        "    if (old_len == 0) {",
        "        size_t cap = (s_len + 1) * new_len + s_len + 1;",
        "        char* res = (char*)malloc(cap);",
        "        size_t w = 0;",
        "        for (size_t i = 0; i < s_len; ++i) {",
        "            memcpy(res + w, new_sub, new_len);",
        "            w += new_len;",
        "            res[w++] = s[i];",
        "        }",
        "        memcpy(res + w, new_sub, new_len);",
        "        w += new_len;",
        "        res[w] = '\\0';",
        "        return res;",
        "    }",
        "    size_t count = 0;",
        "    const char* p = s;",
        "    while ((p = strstr(p, old_sub)) != NULL) {",
        "        count++;",
        "        p += old_len;",
        "    }",
        "    size_t res_len = s_len + count * (new_len - old_len);",
        "    char* res = (char*)malloc(res_len + 1);",
        "    size_t w = 0;",
        "    p = s;",
        "    while (1) {",
        "        const char* next = strstr(p, old_sub);",
        "        if (!next) {",
        "            size_t tail = strlen(p);",
        "            memcpy(res + w, p, tail);",
        "            w += tail;",
        "            break;",
        "        }",
        "        size_t chunk = next - p;",
        "        memcpy(res + w, p, chunk);",
        "        w += chunk;",
        "        memcpy(res + w, new_sub, new_len);",
        "        w += new_len;",
        "        p = next + old_len;",
        "    }",
        "    res[w] = '\\0';",
        "    return res;",
        "}",
        "",
    ]

    # File I/O helpers
    file_helpers = [
        "static inline const char* _meme_resolve_path(const char* path) {",
        "    const char* p = _meme_trim(path);",
        "    struct stat st;",
        "    if (stat(p, &st) == 0 || (p[0] == '/')) return p;",
        "    const char* sd = getenv(\"MEME_SOURCE_DIR\");",
        "    if (sd) {",
        "        const char* sds = _meme_trim(sd);",
        "        if (strlen(sds) > 0) {",
        "            char* cand = (char*)malloc(strlen(sds) + strlen(p) + 2);",
        "            sprintf(cand, \"%s/%s\", sds, p);",
        "            if (stat(cand, &st) == 0) return cand;",
        "        }",
        "    }",
        "    return p;",
        "}",
        "static inline bool _meme_file_exists(const char* path) {",
        "    const char* rp = _meme_resolve_path(path);",
        "    struct stat st;",
        "    if (stat(rp, &st) != 0) return false;",
        "    return S_ISREG(st.st_mode);",
        "}",
        "static inline const char* _meme_read_file_string(const char* path) {",
        "    const char* rp = _meme_resolve_path(path);",
        "    struct stat st;",
        "    if (stat(rp, &st) != 0 || !S_ISREG(st.st_mode)) {",
        "        printf(\"Error reading file: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    FILE* f = fopen(rp, \"rb\");",
        "    if (!f) {",
        "        printf(\"Error reading file: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    size_t sz = (size_t)st.st_size;",
        "    char* buf = (char*)malloc(sz + 1);",
        "    size_t n = fread(buf, 1, sz, f);",
        "    fclose(f);",
        "    buf[n] = '\\0';",
        "    return buf;",
        "}",
        "static inline void _meme_write_file(const char* path, const char* content) {",
        "    const char* p = _meme_trim(path);",
        "    FILE* f = fopen(p, \"wb\");",
        "    if (!f) {",
        "        printf(\"Error writing file: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    if (content) {",
        "        size_t len = strlen(content);",
        "        if (len > 0) {",
        "            size_t written = fwrite(content, 1, len, f);",
        "            if (written != len) {",
        "                fclose(f);",
        "                printf(\"Error writing file: %s\\n\", path);",
        "                exit(1);",
        "            }",
        "        }",
        "    }",
        "    fclose(f);",
        "}",
        "static inline void _meme_append_file(const char* path, const char* content) {",
        "    const char* p = _meme_trim(path);",
        "    FILE* f = fopen(p, \"ab\");",
        "    if (!f) {",
        "        printf(\"Error writing file: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    if (content) {",
        "        size_t len = strlen(content);",
        "        if (len > 0) {",
        "            size_t written = fwrite(content, 1, len, f);",
        "            if (written != len) {",
        "                fclose(f);",
        "                printf(\"Error writing file: %s\\n\", path);",
        "                exit(1);",
        "            }",
        "        }",
        "    }",
        "    fclose(f);",
        "}",
        "",
    ]

    # Input helpers
    input_helpers = [
        "static inline int _meme_strcasecmp(const char* s1, const char* s2) {",
        "    if (!s1) s1 = \"\";",
        "    if (!s2) s2 = \"\";",
        "    while (*s1 && *s2) {",
        "        int d = tolower((unsigned char)*s1) - tolower((unsigned char)*s2);",
        "        if (d != 0) return d;",
        "        s1++; s2++;",
        "    }",
        "    return tolower((unsigned char)*s1) - tolower((unsigned char)*s2);",
        "}",
        "static inline char* _meme_read_line(const char* prompt) {",
        "    const char* q = getenv(\"MEME_QUIET_PROMPTS\");",
        "    bool quiet = false;",
        "    if (q) {",
        "        if (strcmp(q, \"1\") == 0 || _meme_strcasecmp(q, \"true\") == 0 || _meme_strcasecmp(q, \"yes\") == 0) quiet = true;",
        "    }",
        "    if (prompt && prompt[0] != '\\0' && !quiet) {",
        "        printf(\"%s\", prompt);",
        "        fflush(stdout);",
        "    }",
        "    char buf[4096];",
        "    if (!fgets(buf, sizeof(buf), stdin)) {",
        "        char* empty = (char*)malloc(1);",
        "        empty[0] = '\\0';",
        "        return empty;",
        "    }",
        "    size_t len = strlen(buf);",
        "    while (len > 0 && (buf[len - 1] == '\\n' || buf[len - 1] == '\\r')) {",
        "        buf[--len] = '\\0';",
        "    }",
        "    char* res = (char*)malloc(len + 1);",
        "    memcpy(res, buf, len + 1);",
        "    return res;",
        "}",
        "static inline int64_t _meme_parse_int(const char* s) {",
        "    if (!s) {",
        "        printf(\"Error parsing integer: \\n\");",
        "        exit(1);",
        "    }",
        "    const char* ts = _meme_trim(s);",
        "    if (!ts || !*ts) {",
        "        printf(\"Error parsing integer: %s\\n\", s);",
        "        exit(1);",
        "    }",
        "    char* end = NULL;",
        "    errno = 0;",
        "    long long v = strtoll(ts, &end, 10);",
        "    if (errno != 0 || end == ts || *end != '\\0') {",
        "        printf(\"Error parsing integer: %s\\n\", s);",
        "        exit(1);",
        "    }",
        "    return (int64_t)v;",
        "}",
        "static inline double _meme_parse_float(const char* s) {",
        "    if (!s) return 0.0;",
        "    char* end = NULL;",
        "    return strtod(s, &end);",
        "}",
        "static inline bool _meme_parse_bool(const char* s) {",
        "    if (!s) return false;",
        "    const char* ts = _meme_trim(s);",
        "    return (_meme_strcasecmp(ts, \"true\") == 0 || strcmp(ts, \"1\") == 0 || _meme_strcasecmp(ts, \"yes\") == 0);",
        "}",
        "",
    ]

    # Argv helpers
    argv_helpers = [
        "static int _meme_argc = 0;",
        "static char** _meme_argv = NULL;",
        "static inline const char* _meme_arg_at(int64_t idx) {",
        "    if (idx < 0 || idx >= _meme_argc) {",
        "        printf(\"Error: argument index %lld out of range\\n\", (long long)idx);",
        "        exit(1);",
        "    }",
        "    return _meme_argv[idx];",
        "}",
        "",
    ]

    # Random helpers
    random_helpers = [
        "static uint64_t _meme_rng_state = 88172645463325252ULL;",
        "static inline uint64_t _meme_rand64(void) {",
        "    uint64_t x = _meme_rng_state;",
        "    x ^= x << 13;",
        "    x ^= x >> 7;",
        "    x ^= x << 17;",
        "    return _meme_rng_state = x;",
        "}",
        "static inline int64_t _meme_rand_int(int64_t lo, int64_t hi) {",
        "    if (hi <= lo) return lo;",
        "    uint64_t range = (uint64_t)(hi - lo + 1);",
        "    return lo + (int64_t)(_meme_rand64() % range);",
        "}",
        "",
    ]

    # JSON parser helpers
    json_helpers = [
        "typedef enum { _MEME_JSON_STR, _MEME_JSON_BOOL, _MEME_JSON_NUM } _MemeJsonKind;",
        "typedef struct {",
        "    _MemeJsonKind kind;",
        "    char* s;",
        "    bool b;",
        "} _MemeJsonTok;",
        "[[noreturn]] static inline void _meme_json_fail(const char* msg) {",
        "    fprintf(stderr, \"Error reading JSON file: %s\\n\", msg);",
        "    exit(1);",
        "}",
        "static inline void _meme_append_utf8(_MemeSB* sb, unsigned int cp) {",
        "    if (cp <= 0x7F) {",
        "        _meme_sb_append_char(sb, (char)cp);",
        "    } else if (cp <= 0x7FF) {",
        "        _meme_sb_append_char(sb, (char)(0xC0 | (cp >> 6)));",
        "        _meme_sb_append_char(sb, (char)(0x80 | (cp & 0x3F)));",
        "    } else if (cp <= 0xFFFF) {",
        "        _meme_sb_append_char(sb, (char)(0xE0 | (cp >> 12)));",
        "        _meme_sb_append_char(sb, (char)(0x80 | ((cp >> 6) & 0x3F)));",
        "        _meme_sb_append_char(sb, (char)(0x80 | (cp & 0x3F)));",
        "    } else if (cp <= 0x10FFFF) {",
        "        _meme_sb_append_char(sb, (char)(0xF0 | (cp >> 18)));",
        "        _meme_sb_append_char(sb, (char)(0x80 | ((cp >> 12) & 0x3F)));",
        "        _meme_sb_append_char(sb, (char)(0x80 | ((cp >> 6) & 0x3F)));",
        "        _meme_sb_append_char(sb, (char)(0x80 | (cp & 0x3F)));",
        "    }",
        "}",
        "static inline size_t _meme_parse_json_tokens(const char* path, _MemeJsonTok** out_tokens) {",
        "    const char* rp = _meme_resolve_path(path);",
        "    struct stat st;",
        "    if (stat(rp, &st) != 0 || !S_ISREG(st.st_mode)) {",
        "        char buf[256]; snprintf(buf, sizeof(buf), \"cannot open %s\", path); _meme_json_fail(buf);",
        "    }",
        "    FILE* f = fopen(rp, \"rb\");",
        "    if (!f) { char buf[256]; snprintf(buf, sizeof(buf), \"cannot open %s\", path); _meme_json_fail(buf); }",
        "    size_t sz = (size_t)st.st_size;",
        "    char* raw = (char*)malloc(sz + 1);",
        "    size_t n = fread(raw, 1, sz, f); fclose(f); raw[n] = '\\0';",
        "    size_t i = 0;",
        "    while (i < n && isspace((unsigned char)raw[i])) i++;",
        "    if (i >= n || raw[i] != '[') _meme_json_fail(\"expected JSON array\");",
        "    i++;",
        "    while (i < n && isspace((unsigned char)raw[i])) i++;",
        "    size_t cap = 16;",
        "    size_t count = 0;",
        "    _MemeJsonTok* toks = (_MemeJsonTok*)malloc(sizeof(_MemeJsonTok) * cap);",
        "    if (i < n && raw[i] == ']') {",
        "        i++;",
        "        while (i < n && isspace((unsigned char)raw[i])) i++;",
        "        if (i != n) _meme_json_fail(\"trailing data after JSON array\");",
        "        *out_tokens = toks;",
        "        return 0;",
        "    }",
        "    while (true) {",
        "        while (i < n && isspace((unsigned char)raw[i])) i++;",
        "        if (i >= n) _meme_json_fail(\"unterminated JSON array\");",
        "        if (raw[i] == '\"') {",
        "            i++;",
        "            _MemeSB sb = _meme_sb_new();",
        "            while (i < n && raw[i] != '\"') {",
        "                if (raw[i] == '\\\\') {",
        "                    i++;",
        "                    if (i >= n) _meme_json_fail(\"unterminated string escape\");",
        "                    switch (raw[i]) {",
        "                        case '\"': _meme_sb_append_char(&sb, '\"'); break;",
        "                        case '\\\\': _meme_sb_append_char(&sb, '\\\\'); break;",
        "                        case '/': _meme_sb_append_char(&sb, '/'); break;",
        "                        case 'b': _meme_sb_append_char(&sb, '\\b'); break;",
        "                        case 'f': _meme_sb_append_char(&sb, '\\f'); break;",
        "                        case 'n': _meme_sb_append_char(&sb, '\\n'); break;",
        "                        case 'r': _meme_sb_append_char(&sb, '\\r'); break;",
        "                        case 't': _meme_sb_append_char(&sb, '\\t'); break;",
        "                        case 'u': {",
        "                            if (i + 4 >= n) _meme_json_fail(\"invalid unicode escape\");",
        "                            char hex[5] = { raw[i+1], raw[i+2], raw[i+3], raw[i+4], '\\0' };",
        "                            char* hend = NULL;",
        "                            unsigned long cp = strtoul(hex, &hend, 16);",
        "                            if (hend != hex + 4) _meme_json_fail(\"invalid unicode escape\");",
        "                            _meme_append_utf8(&sb, (unsigned int)cp);",
        "                            i += 4;",
        "                            break;",
        "                        }",
        "                        default: _meme_json_fail(\"invalid escape sequence\");",
        "                    }",
        "                } else {",
        "                    _meme_sb_append_char(&sb, raw[i]);",
        "                }",
        "                i++;",
        "            }",
        "            if (i >= n || raw[i] != '\"') _meme_json_fail(\"unterminated string literal\");",
        "            i++;",
        "            if (count >= cap) { cap *= 2; toks = (_MemeJsonTok*)realloc(toks, sizeof(_MemeJsonTok) * cap); }",
        "            toks[count].kind = _MEME_JSON_STR; toks[count].s = sb.data; toks[count].b = false; count++;",
        "        } else {",
        "            size_t start = i;",
        "            while (i < n && !isspace((unsigned char)raw[i]) && raw[i] != ',' && raw[i] != ']') {",
        "                if (raw[i] == '[' || raw[i] == '{' || raw[i] == '}' || raw[i] == '\"') {",
        "                    _meme_json_fail(\"unexpected nested or malformed token\");",
        "                }",
        "                i++;",
        "            }",
        "            if (i == start) _meme_json_fail(\"expected element\");",
        "            size_t tlen = i - start;",
        "            char* tok = (char*)malloc(tlen + 1);",
        "            memcpy(tok, raw + start, tlen);",
        "            tok[tlen] = '\\0';",
        "            if (count >= cap) { cap *= 2; toks = (_MemeJsonTok*)realloc(toks, sizeof(_MemeJsonTok) * cap); }",
        "            if (strcmp(tok, \"true\") == 0) {",
        "                toks[count].kind = _MEME_JSON_BOOL; toks[count].s = tok; toks[count].b = true; count++;",
        "            } else if (strcmp(tok, \"false\") == 0) {",
        "                toks[count].kind = _MEME_JSON_BOOL; toks[count].s = tok; toks[count].b = false; count++;",
        "            } else if (strcmp(tok, \"null\") == 0) {",
        "                _meme_json_fail(\"JSON null is not allowed\");",
        "            } else {",
        "                toks[count].kind = _MEME_JSON_NUM; toks[count].s = tok; toks[count].b = false; count++;",
        "            }",
        "        }",
        "        while (i < n && isspace((unsigned char)raw[i])) i++;",
        "        if (i < n && raw[i] == ',') { i++; continue; }",
        "        else if (i < n && raw[i] == ']') { i++; break; }",
        "        else { _meme_json_fail(\"expected `,` or `]`\"); }",
        "    }",
        "    while (i < n && isspace((unsigned char)raw[i])) i++;",
        "    if (i != n) _meme_json_fail(\"trailing data after JSON array\");",
        "    *out_tokens = toks;",
        "    return count;",
        "}",
        "",
    ]

    # Primitive list types
    primitive_lists: list[str] = []
    for el_t in list_elem_types:
        if el_t not in gen.records:
            primitive_lists.extend(_emit_list_type(el_t, gen))
            primitive_lists.append("")

    # Specialized JSON readers for primitive element types
    json_readers = [
        "static inline meme_list_Int _meme_read_json_list_int(const char* path) {",
        "    _MemeJsonTok* toks = NULL;",
        "    size_t n = _meme_parse_json_tokens(path, &toks);",
        "    meme_list_Int out = _meme_list_Int_new();",
        "    for (size_t i = 0; i < n; ++i) {",
        "        if (toks[i].kind != _MEME_JSON_NUM) _meme_json_fail(\"expected Int element\");",
        "        char* end = NULL;",
        "        int64_t v = strtoll(toks[i].s, &end, 10);",
        "        if (!end || *end != '\\0') {",
        "            char buf[256]; snprintf(buf, sizeof(buf), \"expected Int, got `%s`\", toks[i].s);",
        "            _meme_json_fail(buf);",
        "        }",
        "        _meme_list_Int_append(&out, v);",
        "    }",
        "    return out;",
        "}",
        "static inline meme_list_Float _meme_read_json_list_float(const char* path) {",
        "    _MemeJsonTok* toks = NULL;",
        "    size_t n = _meme_parse_json_tokens(path, &toks);",
        "    meme_list_Float out = _meme_list_Float_new();",
        "    for (size_t i = 0; i < n; ++i) {",
        "        if (toks[i].kind != _MEME_JSON_NUM) _meme_json_fail(\"expected Float element\");",
        "        char* end = NULL;",
        "        double v = strtod(toks[i].s, &end);",
        "        if (!end || *end != '\\0' || !isfinite(v)) {",
        "            char buf[256]; snprintf(buf, sizeof(buf), \"expected Float, got `%s`\", toks[i].s);",
        "            _meme_json_fail(buf);",
        "        }",
        "        _meme_list_Float_append(&out, v);",
        "    }",
        "    return out;",
        "}",
        "static inline meme_list_String _meme_read_json_list_string(const char* path) {",
        "    _MemeJsonTok* toks = NULL;",
        "    size_t n = _meme_parse_json_tokens(path, &toks);",
        "    meme_list_String out = _meme_list_String_new();",
        "    for (size_t i = 0; i < n; ++i) {",
        "        if (toks[i].kind != _MEME_JSON_STR) _meme_json_fail(\"expected String element\");",
        "        _meme_list_String_append(&out, toks[i].s);",
        "    }",
        "    return out;",
        "}",
        "static inline meme_list_Bool _meme_read_json_list_bool(const char* path) {",
        "    _MemeJsonTok* toks = NULL;",
        "    size_t n = _meme_parse_json_tokens(path, &toks);",
        "    meme_list_Bool out = _meme_list_Bool_new();",
        "    for (size_t i = 0; i < n; ++i) {",
        "        if (toks[i].kind != _MEME_JSON_BOOL) _meme_json_fail(\"expected Bool element\");",
        "        _meme_list_Bool_append(&out, toks[i].b);",
        "    }",
        "    return out;",
        "}",
        "static inline meme_list_Int _meme_rand_list(int64_t count, int64_t lo, int64_t hi) {",
        "    meme_list_Int out = _meme_list_Int_new();",
        "    if (count > 0) {",
        "        for (int64_t i = 0; i < count; ++i) _meme_list_Int_append(&out, _meme_rand_int(lo, hi));",
        "    }",
        "    return out;",
        "}",
        "",
    ]

    # String verbs that return/take meme_list_String
    str_container_helpers = [
        "static inline meme_list_String _meme_str_split(const char* s, const char* sep) {",
        "    if (!sep || strlen(sep) == 0) {",
        "        printf(\"Error: empty separator in split\\n\");",
        "        exit(1);",
        "    }",
        "    meme_list_String out = _meme_list_String_new();",
        "    if (!s) s = \"\";",
        "    size_t sep_len = strlen(sep);",
        "    const char* p = s;",
        "    while (1) {",
        "        const char* found = strstr(p, sep);",
        "        if (!found) {",
        "            size_t tail_len = strlen(p);",
        "            char* part = (char*)malloc(tail_len + 1);",
        "            memcpy(part, p, tail_len);",
        "            part[tail_len] = '\\0';",
        "            _meme_list_String_append(&out, part);",
        "            break;",
        "        }",
        "        size_t part_len = found - p;",
        "        char* part = (char*)malloc(part_len + 1);",
        "        memcpy(part, p, part_len);",
        "        part[part_len] = '\\0';",
        "        _meme_list_String_append(&out, part);",
        "        p = found + sep_len;",
        "    }",
        "    return out;",
        "}",
        "static inline const char* _meme_str_join(meme_list_String items, const char* sep) {",
        "    if (!sep) sep = \"\";",
        "    _MemeSB sb = _meme_sb_new();",
        "    for (int64_t i = 0; i < items.len; ++i) {",
        "        if (i > 0) _meme_sb_append(&sb, sep);",
        "        _meme_sb_append(&sb, items.data[i]);",
        "    }",
        "    return sb.data;",
        "}",
        "",
    ]

    # Primitive maps
    primitive_maps: list[str] = []
    for k_t, v_t in map_types:
        if v_t not in gen.records:
            primitive_maps.extend(_emit_map_type(k_t, v_t, gen))
            primitive_maps.append("")

    # Primitive optionals
    primitive_opts: list[str] = []
    for inner in opt_types:
        if inner not in gen.records:
            primitive_opts.extend(_emit_opt_type(inner, gen))
            primitive_opts.append("")

    # Record definitions, eq, and formatters
    record_blocks: list[str] = []
    for r in records:
        record_blocks.extend(_emit_record(r, gen))
        record_blocks.append("")

    # Record lists
    record_lists: list[str] = []
    for el_t in list_elem_types:
        if el_t in gen.records:
            record_lists.extend(_emit_list_type(el_t, gen))
            record_lists.append("")

    # Record maps
    record_maps: list[str] = []
    for k_t, v_t in map_types:
        if v_t in gen.records:
            record_maps.extend(_emit_map_type(k_t, v_t, gen))
            record_maps.append("")

    # Record optionals
    record_opts: list[str] = []
    for inner in opt_types:
        if inner in gen.records:
            record_opts.extend(_emit_opt_type(inner, gen))
            record_opts.append("")

    # Function declarations and definitions
    fn_fwd_decls: list[str] = []
    for fn in funcs:
        params = ", ".join(f"{_c_type(p.param_type)} {_c_ident(p.name)}" for p in fn.params)
        fn_fwd_decls.append(f"{_c_type(fn.return_type)} {_c_ident(fn.name)}({params});")
    if fn_fwd_decls:
        fn_fwd_decls.append("")

    fn_blocks: list[str] = []
    for fn in funcs:
        fn_blocks.extend(gen.gen_func(fn))
        fn_blocks.append("")

    # Main function
    main_scope: dict[str, MemeType] = {}
    main_lines: list[str] = [
        "int main(int argc, char** argv) {",
        "    _meme_argc = argc;",
        "    _meme_argv = argv;",
    ]
    for stmt in main_stmts:
        main_lines.extend(gen.gen_stmt(stmt, main_scope, indent=1))
    main_lines.append("    return 0;")
    main_lines.append("}")
    main_lines.append("")

    out = (
        headers
        + record_fwd_decls
        + runtime_helpers
        + str_helpers
        + file_helpers
        + input_helpers
        + argv_helpers
        + random_helpers
        + json_helpers
        + primitive_lists
        + json_readers
        + str_container_helpers
        + primitive_maps
        + primitive_opts
        + record_blocks
        + record_lists
        + record_maps
        + record_opts
        + fn_fwd_decls
        + fn_blocks
        + main_lines
    )
    return "\n".join(out)

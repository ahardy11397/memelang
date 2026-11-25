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

import json
import math
import re
from typing import Any

from memelang.codegen.base import (
    BaseGen,
    _get_transitive_json_records,
    _map_types_of,
    _set_types_of,
    escape_str,
)
from memelang.ir.canonical import format_expr
from memelang.ir.schema import (
    AppendFileStmt,
    ArgAtExpr,
    ArgCountExpr,
    AssertStmt,
    AssignStmt,
    BinaryOpExpr,
    BreakStmt,
    CallExpr,
    CallStmt,
    CharacterOfExpr,
    ClampCollectionStmt,
    CompoundAssignStmt,
    ContinueStmt,
    CopyFileStmt,
    CreateDirectoryStmt,
    CurrentEpochExpr,
    DeleteFileStmt,
    EnvVarExpr,
    ExitStmt,
    FailStmt,
    FileExistsExpr,
    FilterCollectionStmt,
    ForEachStmt,
    FormatIntExpr,
    FormatFloatExpr,
    FloatOfExpr,
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
    EmptySetExpr,
    SetAddStmt,
    SetContainsExpr,
    SetLengthExpr,
    SetRemoveStmt,
    MapEntry,
    MapGetExpr,
    MapHasKeyExpr,
    MapLiteralExpr,
    MapSetStmt,
    MemeType,
    MoveFileStmt,
    NumberOfExpr,
    OptionalIsNothingExpr,
    OptionalNoneExpr,
    OptionalUnwrapExpr,
    OptionalUnwrapOrDefaultExpr,
    OptionalWrapExpr,
    ParseIntExpr,
    ParseIntOrDefaultExpr,
    PrintErrorStmt,
    PrintStmt,
    ProgramIR,
    RandomIntExpr,
    RandomListExpr,
    ReadFileStringExpr,
    ReadFileLinesExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    ReadJsonRecordExpr,
    ReadJsonRecordsExpr,
    RecordDefStmt,
    RecordFieldDef,
    RecordFieldExpr,
    RecordFieldInit,
    RecordLiteralExpr,
    RecordSetFieldStmt,
    RenameFileStmt,
    ReturnStmt,
    Sha256Expr,
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
    TestBlockStmt,
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
    WriteFileStmt,
    WriteJsonStmt,
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
    return escape_str(val, "c")


def _c_ident(name: str) -> str:
    cleaned = name.replace("-", "_")
    if cleaned in _C_KEYWORDS or cleaned.startswith("_meme_"):
        return f"meme_{cleaned}"
    return cleaned


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
    set_t = _set_types_of(meme_type)
    if set_t is not None:
        return f"meme_set_{_mangle_type(set_t)}"
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
    elif isinstance(expr, EmptySetExpr):
        out.add(f"Set<{expr.element_type}>")
        out.add(expr.element_type)
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
        if expr.default_val is not None:
            out.add(f"Optional<List<{expr.element_type}>>")
            _collect_types_from_expr(expr.default_val, out)
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
    elif isinstance(expr, (OptionalUnwrapOrDefaultExpr, ParseIntOrDefaultExpr)):
        _collect_types_from_expr(expr.target, out)
        _collect_types_from_expr(expr.default_val, out)
    elif isinstance(expr, ListFilesExpr):
        out.add("List<String>")
        _collect_types_from_expr(expr.path, out)
    elif isinstance(expr, ReadJsonRecordExpr):
        out.add(f"Optional<{expr.record_name}>")
        out.add(expr.record_name)
        _collect_types_from_expr(expr.filepath, out)
        if expr.default_val is not None:
            _collect_types_from_expr(expr.default_val, out)
    elif isinstance(expr, ReadJsonRecordsExpr):
        out.add(f"List<{expr.record_name}>")
        out.add(f"Optional<List<{expr.record_name}>>")
        out.add(f"Optional<{expr.record_name}>")
        out.add(expr.record_name)
        _collect_types_from_expr(expr.filepath, out)
        if expr.default_val is not None:
            _collect_types_from_expr(expr.default_val, out)
    elif isinstance(expr, CurrentEpochExpr):
        out.add("Int")
    elif isinstance(expr, EnvVarExpr):
        out.add("String")
        out.add("Optional<String>")
        _collect_types_from_expr(expr.var_name, out)
        if expr.default_val is not None:
            _collect_types_from_expr(expr.default_val, out)
    elif isinstance(expr, ReadFileLinesExpr):
        out.add("List<String>")
        out.add("String")
        if expr.default_val is not None:
            out.add("Optional<List<String>>")
            _collect_types_from_expr(expr.default_val, out)
        _collect_types_from_expr(expr.filepath, out)
    elif isinstance(expr, ReadFileStringExpr):
        out.add("String")
        if expr.default_val is not None:
            out.add("Optional<String>")
            _collect_types_from_expr(expr.default_val, out)
        _collect_types_from_expr(expr.filepath, out)
    elif isinstance(expr, (StringLengthExpr, StringSliceExpr, StringReplaceExpr,
                           StringUpperExpr, StringLowerExpr, StringTrimExpr,
                           StringJoinExpr, StringIndexOfExpr, StringCharAtExpr,
                           StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr,
                           FileExistsExpr, ParseIntExpr, FormatIntExpr,
                           FormatFloatExpr,
                           IsDigitExpr, IsLetterExpr, IsUpperExpr, IsLowerExpr, Sha256Expr)):
        for attr in ("target", "substring", "prefix", "suffix", "old", "new",
                     "start", "end", "filepath", "index", "separator", "items", "decimals"):
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
        if stmt.collection_expr is not None:
            _collect_types_from_expr(stmt.collection_expr, out)
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
    elif isinstance(stmt, (PrintStmt, PrintErrorStmt)):
        for e in stmt.expressions:
            _collect_types_from_expr(e, out)
    elif isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _collect_types_from_expr(stmt.value, out)
    elif isinstance(stmt, FailStmt):
        _collect_types_from_expr(stmt.message, out)
    elif isinstance(stmt, ExitStmt):
        _collect_types_from_expr(stmt.code, out)
    elif isinstance(stmt, AssertStmt):
        _collect_types_from_expr(stmt.condition, out)
    elif isinstance(stmt, TestBlockStmt):
        for s in stmt.body:
            _collect_types_from_stmt(s, out)
    elif isinstance(stmt, (ListAppendStmt, ListInsertStmt, ListSetIndexStmt)):
        _collect_types_from_expr(stmt.value, out)
        if hasattr(stmt, "index"):
            _collect_types_from_expr(stmt.index, out)
    elif isinstance(stmt, ListRemoveStmt):
        if stmt.index is not None:
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
    elif isinstance(stmt, WriteJsonStmt):
        _collect_types_from_expr(stmt.target, out)
        _collect_types_from_expr(stmt.filepath, out)
    elif isinstance(stmt, (CopyFileStmt, MoveFileStmt)):
        _collect_types_from_expr(stmt.src, out)
        _collect_types_from_expr(stmt.dst, out)
    elif isinstance(stmt, RenameFileStmt):
        _collect_types_from_expr(stmt.path, out)
        _collect_types_from_expr(stmt.new_name, out)
    elif isinstance(stmt, (DeleteFileStmt, CreateDirectoryStmt)):
        _collect_types_from_expr(stmt.path, out)
    elif isinstance(stmt, CallStmt):
        for a in stmt.args:
            _collect_types_from_expr(a, out)


class _CGen(BaseGen):
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_input = False
        self.uses_str_helpers = False
        self.uses_json_io = False
        self.uses_file_io = False
        self.uses_file_io_opt = False
        self.uses_read_file_string_opt = False
        self.uses_read_file_lines_opt = False
        self.uses_json_list_opt = False
        self.json_list_opt_types: set[str] = set()
        self.uses_list_files = False
        self.uses_argv = False
        self.uses_int_div = False
        self.uses_int_mod = False
        self._match_counter = 0
        self.func_returns: dict[str, MemeType] = {}
        self.func_params: dict[str, list[FuncParam]] = {}
        self.records: dict[str, dict[str, MemeType]] = {}
        self.current_func_return: str | None = None
        self.uses_env = False
        self.uses_env_or = False
        self.uses_json_records = False
        self.uses_json_write = False
        self.json_records_read: set[str] = set()
        self.json_record_lists_read: set[str] = set()
        self.json_records_write: set[str] = set()

    def _maybe_copy_val(self, val: str, t: str) -> str:
        if t.startswith("List<") and t.endswith(">"):
            el_t = t[5:-1]
            return f"_meme_list_{_mangle_type(el_t)}_copy({val})"
        if t.startswith("Map<") and t.endswith(">"):
            mt = _map_types_of(t)
            if mt:
                return f"_meme_map_{_mangle_type(mt[0])}_{_mangle_type(mt[1])}_copy({val})"
        if t.startswith("Set<") and t.endswith(">"):
            st = _set_types_of(t)
            if st:
                return f"_meme_set_{_mangle_type(st)}_copy({val})"
        if t in self.records:
            return f"{_c_ident(t)}_copy({val})"
        if t.startswith("Optional<") and t.endswith(">"):
            inner = t[9:-1]
            return f"_meme_opt_{_mangle_type(inner)}_copy({val})"
        return val

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

            cmp_t = left_t if left_t not in ("Int", "Optional<Void>") else self.infer_type(expr.right, scope)
            if cmp_t in self.records:
                rec_name = _c_ident(cmp_t)
                if expr.op == "==":
                    return f"{rec_name}_eq({left}, {right})"
                if expr.op == "!=":
                    return f"(!{rec_name}_eq({left}, {right}))"

            if cmp_t.startswith("Optional<") and cmp_t.endswith(">"):
                inner = cmp_t[9:-1]
                m_type = _mangle_type(inner)
                if expr.op == "==":
                    return f"_meme_opt_{m_type}_eq({left}, {right})"
                if expr.op == "!=":
                    return f"(!_meme_opt_{m_type}_eq({left}, {right}))"

            if cmp_t.startswith("List<") and cmp_t.endswith(">"):
                el_t = cmp_t[5:-1]
                m_type = _mangle_type(el_t)
                if expr.op == "==":
                    return f"_meme_list_{m_type}_eq({left}, {right})"
                if expr.op == "!=":
                    return f"(!_meme_list_{m_type}_eq({left}, {right}))"

            if cmp_t.startswith("Map<") and cmp_t.endswith(">"):
                map_t = _map_types_of(cmp_t)
                m_k = _mangle_type(map_t[0]) if map_t else "Int"
                m_v = _mangle_type(map_t[1]) if map_t else "String"
                if expr.op == "==":
                    return f"_meme_map_{m_k}_{m_v}_eq({left}, {right})"
                if expr.op == "!=":
                    return f"(!_meme_map_{m_k}_{m_v}_eq({left}, {right}))"

            if cmp_t.startswith("Set<") and cmp_t.endswith(">"):
                el_t = cmp_t[4:-1]
                m_type = _mangle_type(el_t)
                if expr.op == "==":
                    return f"_meme_set_{m_type}_eq({left}, {right})"
                if expr.op == "!=":
                    return f"(!_meme_set_{m_type}_eq({left}, {right}))"

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

        if isinstance(expr, ParseIntOrDefaultExpr):
            self.uses_str_helpers = True
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"__extension__ ({{ int64_t _val; _meme_try_parse_int({tgt}, &_val) ? _val : ({dflt}); }})"

        if isinstance(expr, IsDigitExpr):
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_digit({tgt})"

        if isinstance(expr, IsLetterExpr):
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_letter({tgt})"

        if isinstance(expr, IsUpperExpr):
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_upper({tgt})"

        if isinstance(expr, IsLowerExpr):
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_lower({tgt})"

        if isinstance(expr, FormatIntExpr):
            return f"_meme_fmt_int({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, FormatFloatExpr):
            tgt = self.gen_expr(expr.target, scope)
            dec = self.gen_expr(expr.decimals, scope)
            return f"_meme_format_float({tgt}, {dec})"

        if isinstance(expr, FloatOfExpr):
            return f"((double)({self.gen_expr(expr.target, scope, 'Int')}))"

        if isinstance(expr, NumberOfExpr):
            self.uses_str_helpers = True
            tgt = self.gen_expr(expr.target, scope, "String")
            return f"_meme_number_of({tgt})"

        if isinstance(expr, CharacterOfExpr):
            self.uses_str_helpers = True
            tgt = self.gen_expr(expr.target, scope, "Int")
            return f"_meme_character_of({tgt})"

        if isinstance(expr, Sha256Expr):
            self.uses_str_helpers = True
            tgt = self.gen_expr(expr.target, scope, "String")
            return f"_meme_sha256({tgt})"

        if isinstance(expr, CurrentEpochExpr):
            return "(int64_t)time(NULL)"

        if isinstance(expr, EnvVarExpr):
            v = self.gen_expr(expr.var_name, scope, "String")
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                d = self.gen_expr(expr.default_val, scope, "String")
                self.uses_env_or = True
                return f"_meme_env_var_or({v}, {d})"
            self.uses_env = True
            return f"_meme_env_var({v})"

        if isinstance(expr, ReadJsonListExpr):
            self.uses_str_helpers = True
            self.uses_json_io = True
            el_t = expr.element_type
            el_lower = el_t.lower()
            p = self.gen_expr(expr.filepath, scope)
            if expr.default_val is not None:
                self.uses_json_list_opt = True
                self.json_list_opt_types.add(el_lower)
                if not isinstance(expr.default_val, OptionalNoneExpr):
                    d = self.gen_expr(expr.default_val, scope, f"List<{el_t}>")
                    return f"_meme_read_json_list_{el_lower}_or({p}, {d})"
                return f"_meme_read_json_list_{el_lower}_opt({p})"
            return f"_meme_read_json_list_{el_lower}({p})"

        if isinstance(expr, ReadJsonRecordExpr):
            self.uses_json_records = True
            self.uses_str_helpers = True
            self.json_records_read.add(expr.record_name)
            p = self.gen_expr(expr.filepath, scope)
            call = f"_meme_read_json_record_{_c_ident(expr.record_name)}({p})"
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                d = self.gen_expr(expr.default_val, scope, expr.record_name)
                return f"_meme_read_json_record_{_c_ident(expr.record_name)}_or({p}, {d})"
            return call

        if isinstance(expr, ReadJsonRecordsExpr):
            self.uses_json_records = True
            self.uses_str_helpers = True
            self.json_record_lists_read.add(expr.record_name)
            p = self.gen_expr(expr.filepath, scope)
            call = f"_meme_read_json_records_{_c_ident(expr.record_name)}({p})"
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                d = self.gen_expr(expr.default_val, scope, f"List<{expr.record_name}>")
                return f"_meme_read_json_records_{_c_ident(expr.record_name)}_or({p}, {d})"
            return call

        if isinstance(expr, FileExistsExpr):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return f"_meme_file_exists({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ReadFileStringExpr):
            self.uses_str_helpers = True
            self.uses_file_io = True
            p = self.gen_expr(expr.filepath, scope)
            if expr.default_val is not None:
                self.uses_file_io_opt = True
                self.uses_read_file_string_opt = True
                if not isinstance(expr.default_val, OptionalNoneExpr):
                    d = self.gen_expr(expr.default_val, scope, "String")
                    return f"_meme_read_file_string_or({p}, {d})"
                return f"_meme_read_file_string_opt({p})"
            return f"_meme_read_file_string({p})"

        if isinstance(expr, ReadFileLinesExpr):
            self.uses_str_helpers = True
            self.uses_file_io = True
            p = self.gen_expr(expr.filepath, scope)
            if expr.default_val is not None:
                self.uses_file_io_opt = True
                self.uses_read_file_lines_opt = True
                self.uses_read_file_string_opt = True
                if not isinstance(expr.default_val, OptionalNoneExpr):
                    d = self.gen_expr(expr.default_val, scope, "List<String>")
                    return f"_meme_read_file_lines_or({p}, {d})"
                return f"_meme_read_file_lines_opt({p})"
            return f"_meme_read_file_lines({p})"

        if isinstance(expr, ListFilesExpr):
            self.uses_str_helpers = True
            self.uses_file_io = True
            self.uses_list_files = True
            return f"_meme_list_files({self.gen_expr(expr.path, scope)})"

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
            field_inits: list[str] = []
            for fname, fval in ordered_fields:
                f_t = rec_def.get(fname) if rec_def else None
                f_ident = _c_ident(fname)
                val_str = self.gen_expr(fval, scope, f_t)
                if f_t and isinstance(fval, VarRefExpr):
                    val_str = self._maybe_copy_val(val_str, f_t)
                field_inits.append(f".{f_ident} = {val_str}")
            return f"({_c_ident(expr.record_name)}){{ {', '.join(field_inits)} }}"

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

        if isinstance(expr, EmptySetExpr):
            return f"_meme_set_{_mangle_type(expr.element_type)}_new()"

        if isinstance(expr, SetContainsExpr):
            tgt = self.gen_expr(expr.target, scope)
            v = self.gen_expr(expr.value, scope)
            tgt_t = self.infer_type(expr.target, scope)
            el_t = _set_types_of(tgt_t) if _set_types_of(tgt_t) else "String"
            return f"_meme_set_{_mangle_type(el_t)}_contains({tgt}, {v})"

        if isinstance(expr, SetLengthExpr):
            return f"((int64_t)({self.gen_expr(expr.target, scope)}).len)"

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
            if inner_t in self.records:
                if isinstance(expr.default_val, VarRefExpr):
                    def_val = self._maybe_copy_val(def_val, inner_t)
                return f"(({tgt}).present ? *({tgt}).value : ({def_val}))"
            return f"(({tgt}).present ? ({tgt}).value : ({def_val}))"

        raise NotImplementedError(f"Unsupported expression: {type(expr).__name__}")

    def gen_stmt(self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 1) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            scope[stmt.name] = stmt.var_type
            ident = _c_ident(stmt.name)
            c_t = _c_type(stmt.var_type)
            val = self.gen_expr(stmt.value, scope, stmt.var_type)
            if isinstance(stmt.value, VarRefExpr):
                val = self._maybe_copy_val(val, stmt.var_type)
            return [
                f"{pad}{c_t} {ident} = {val};",
                f"{pad}(void){ident};",
            ]

        if isinstance(stmt, AssignStmt):
            ident = _c_ident(stmt.name)
            tgt_t = scope.get(stmt.name)
            val = self.gen_expr(stmt.value, scope, tgt_t)
            if isinstance(stmt.value, VarRefExpr) and tgt_t:
                val = self._maybe_copy_val(val, tgt_t)
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
            if stmt.nested_index is not None:
                nidx = self.gen_expr(stmt.nested_index, scope, el_t)
                inner_elem_t = (
                    el_t[5:-1] if el_t.startswith("List<") else el_t
                )
                val = self.gen_expr(stmt.value, scope, inner_elem_t)
                return [
                    f"{pad}_meme_list_{_mangle_type(inner_elem_t)}_set(&{tgt}.data[{idx}], {nidx}, {val});"
                ]
            return [f"{pad}_meme_list_{m_type}_set(&{tgt}, {idx}, {val});"]

        if isinstance(stmt, ListRemoveStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            el_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            m_type = _mangle_type(el_t)
            if stmt.index is not None:
                idx = self.gen_expr(stmt.index, scope)
                return [f"{pad}_meme_list_{m_type}_remove(&{tgt}, {idx});"]
            return [f"{pad}_meme_list_{m_type}_remove_last(&{tgt});"]

        if isinstance(stmt, FailStmt):
            msg = self.gen_expr(stmt.message, scope)
            return [
                f"{pad}printf(\"%s\\n\", _meme_fmt_string({msg}));",
                f"{pad}exit(1);",
            ]

        if isinstance(stmt, ExitStmt):
            code = self.gen_expr(stmt.code, scope)
            return [f"{pad}exit((int)(({code}) & 0xFF));"]

        if isinstance(stmt, AssertStmt):
            cond = self.gen_expr(stmt.condition, scope)
            line = stmt.source_line if stmt.source_line is not None else 1
            src_text = stmt.source_text if getattr(stmt, "source_text", None) else format_expr(stmt.condition)
            escaped_src = json.dumps(src_text)
            return [
                f"{pad}if (!({cond})) {{",
                f"{pad}    fprintf(stderr, \"ASSERT FAILED line %d: %s\\n\", {line}, {escaped_src});",
                f"{pad}    exit(1);",
                f"{pad}}}",
            ]

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

        if isinstance(stmt, PrintErrorStmt):
            if not stmt.expressions:
                return [f'{pad}fprintf(stderr, "\\n");']
            fmts: list[str] = []
            for e in stmt.expressions:
                t = self.infer_type(e, scope)
                fmt_fn = self._fmt_function_name(t)
                fmts.append(f"{fmt_fn}({self.gen_expr(e, scope)})")
            fmt_str = " ".join(["%s"] * len(stmt.expressions)) + "\\n"
            return [f'{pad}fprintf(stderr, "{fmt_str}", {", ".join(fmts)});']

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
            col_expr = (
                stmt.collection_expr
                if stmt.collection_expr is not None
                else VarRefExpr(name=stmt.collection)
            )
            sub = dict(scope)
            col_t = self.infer_type(col_expr, scope)
            col_ident = (
                _c_ident(stmt.collection)
                if isinstance(col_expr, VarRefExpr)
                else f"({self.gen_expr(col_expr, scope)})"
            )
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
            elif _set_types_of(col_t) is not None:
                el_t = _set_types_of(col_t)
                sub[stmt.item_var] = el_t  # type: ignore[assignment]
                c_el_t = _c_type(el_t)
                m_type = _mangle_type(el_t)
                lines = [
                    f"{pad}{{",
                    f"{pad}    meme_set_{m_type} _meme_col = _meme_set_{m_type}_copy({col_ident});",
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
            if expected_f_t and isinstance(stmt.value, VarRefExpr):
                val = self._maybe_copy_val(val, expected_f_t)
            return [f"{pad}{tgt}.{fld} = {val};"]

        if isinstance(stmt, MapSetStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "")
            k_t, v_t = _map_types_of(col_t) if _map_types_of(col_t) else ("String", "Int")
            m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
            k = self.gen_expr(stmt.key, scope, k_t)
            val = self.gen_expr(stmt.value, scope, v_t)
            return [f"{pad}_meme_map_{m_type}_set(&{tgt}, {k}, {val});"]

        if isinstance(stmt, SetAddStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "")
            el_t = _set_types_of(col_t) if _set_types_of(col_t) else "String"
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}_meme_set_{_mangle_type(el_t)}_add(&{tgt}, {val});"]

        if isinstance(stmt, SetRemoveStmt):
            tgt = _c_ident(stmt.target)
            col_t = scope.get(stmt.target, "")
            el_t = _set_types_of(col_t) if _set_types_of(col_t) else "String"
            val = self.gen_expr(stmt.value, scope, el_t)
            return [f"{pad}_meme_set_{_mangle_type(el_t)}_remove(&{tgt}, {val});"]

        if isinstance(stmt, WriteFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            path = self.gen_expr(stmt.filepath, scope)
            content = self.gen_expr(stmt.content, scope)
            return [f"{pad}_meme_write_file({path}, {content});"]

        if isinstance(stmt, WriteJsonStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            self.uses_json_write = True
            tgt_t = self.infer_type(stmt.target, scope)
            path = self.gen_expr(stmt.filepath, scope)
            tgt = self.gen_expr(stmt.target, scope)
            if tgt_t in self.records:
                self.json_records_write.add(tgt_t)
                r_ident = _c_ident(tgt_t)
                return [
                    f"{pad}{{",
                    f"{pad}    char* _jstr = _meme_serialize_json_record_{r_ident}({tgt});",
                    f"{pad}    _meme_write_file({path}, _jstr);",
                    f"{pad}    free(_jstr);",
                    f"{pad}}}",
                ]
            elif tgt_t.startswith("List<") and tgt_t.endswith(">"):
                r_name = tgt_t[5:-1]
                self.json_records_write.add(r_name)
                r_ident = _c_ident(r_name)
                return [
                    f"{pad}{{",
                    f"{pad}    char* _jstr = _meme_serialize_json_records_{r_ident}({tgt});",
                    f"{pad}    _meme_write_file({path}, _jstr);",
                    f"{pad}    free(_jstr);",
                    f"{pad}}}",
                ]

        if isinstance(stmt, AppendFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            path = self.gen_expr(stmt.filepath, scope)
            content = self.gen_expr(stmt.content, scope)
            return [f"{pad}_meme_append_file({path}, {content});"]

        if isinstance(stmt, CopyFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            src = self.gen_expr(stmt.src, scope)
            dst = self.gen_expr(stmt.dst, scope)
            return [f"{pad}_meme_copy_file({src}, {dst});"]

        if isinstance(stmt, MoveFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            src = self.gen_expr(stmt.src, scope)
            dst = self.gen_expr(stmt.dst, scope)
            return [f"{pad}_meme_move_file({src}, {dst});"]

        if isinstance(stmt, RenameFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            path = self.gen_expr(stmt.path, scope)
            new_name = self.gen_expr(stmt.new_name, scope)
            return [f"{pad}_meme_rename_file({path}, {new_name});"]

        if isinstance(stmt, DeleteFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            path = self.gen_expr(stmt.path, scope)
            return [f"{pad}_meme_delete_file({path});"]

        if isinstance(stmt, CreateDirectoryStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            path = self.gen_expr(stmt.path, scope)
            return [f"{pad}_meme_create_directory({path});"]

        if isinstance(stmt, CallStmt):
            param_types = [p.param_type for p in self.func_params.get(stmt.func_name, [])]
            args: list[str] = []
            for i, a in enumerate(stmt.args):
                expected = param_types[i] if i < len(param_types) else None
                args.append(self.gen_expr(a, scope, expected))
            return [f"{pad}{_c_ident(stmt.func_name)}({', '.join(args)});"]

        if isinstance(stmt, (ImportStmt, TestBlockStmt)):
            return []

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
        set_t = _set_types_of(meme_type)
        if set_t is not None:
            return f"_meme_fmt_set_{_mangle_type(set_t)}"
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
            p_ident = _c_ident(p.name)
            lines.append(f"    (void){p_ident};")
            if (
                p.param_type.startswith("List<")
                or p.param_type.startswith("Map<")
                or p.param_type.startswith("Set<")
                or p.param_type in self.records
            ):
                lines.append(f"    {p_ident} = {self._maybe_copy_val(p_ident, p.param_type)};")
        for ch in fn.body:
            lines.extend(self.gen_stmt(ch, fn_scope, indent=1))
        if fn.return_type != "Void" and not (fn.body and isinstance(fn.body[-1], ReturnStmt)):
            lines.append(f"    return ({c_ret}){{0}};")
        lines.append("}")
        self.current_func_return = None
        return lines

def _c_copy_expr(t: str, val: str, gen: _CGen) -> str:
    if t.startswith("List<") and t.endswith(">"):
        el_t = t[5:-1]
        return f"_meme_list_{_mangle_type(el_t)}_copy({val})"
    if t.startswith("Map<") and t.endswith(">"):
        mt = _map_types_of(t)
        if mt:
            return f"_meme_map_{_mangle_type(mt[0])}_{_mangle_type(mt[1])}_copy({val})"
    if t.startswith("Set<") and t.endswith(">"):
        st = _set_types_of(t)
        if st:
            return f"_meme_set_{_mangle_type(st)}_copy({val})"
    if t in gen.records:
        return f"{_c_ident(t)}_copy({val})"
    if t.startswith("Optional<") and t.endswith(">"):
        inner = t[9:-1]
        return f"_meme_opt_{_mangle_type(inner)}_copy({val})"
    return val


def _sort_records_by_deps(records: list[RecordDefStmt]) -> list[RecordDefStmt]:
    rec_by_name = {r.name: r for r in records}
    deps: dict[str, set[str]] = {r.name: set() for r in records}
    for r in records:
        for f in r.fields:
            if f.field_type in rec_by_name:
                deps[r.name].add(f.field_type)
            elif f.field_type.startswith("Map<") and f.field_type.endswith(">"):
                mt = _map_types_of(f.field_type)
                if mt:
                    if mt[0] in rec_by_name:
                        deps[r.name].add(mt[0])
                    if mt[1] in rec_by_name:
                        deps[r.name].add(mt[1])
    sorted_recs: list[RecordDefStmt] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            return
        visiting.add(name)
        for dep in sorted(deps.get(name, set())):
            if dep in rec_by_name:
                visit(dep)
        visiting.remove(name)
        visited.add(name)
        sorted_recs.append(rec_by_name[name])

    for r in records:
        if r.name not in visited:
            visit(r.name)
    return sorted_recs


def _emit_list_struct(el_t: str) -> list[str]:
    m_type = _mangle_type(el_t)
    c_elem = _c_type(el_t)
    return [
        f"// List<{el_t}>",
        "typedef struct {",
        f"    {c_elem}* data;",
        "    int64_t len;",
        "    int64_t cap;",
        f"}} meme_list_{m_type};",
    ]


def _emit_list_proto(el_t: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(el_t)
    c_elem = _c_type(el_t)
    is_sortable = el_t in ("Int", "Float", "String", "Bool")
    sort_proto: list[str] = []
    if is_sortable:
        sort_proto.extend([
            f"static void _meme_merge_sort_{m_type}({c_elem}* arr, {c_elem}* temp, int64_t left, int64_t right, bool desc);",
            f"static inline void _meme_list_{m_type}_sort(meme_list_{m_type}* l, bool desc);",
        ])
    return [
        f"static inline meme_list_{m_type} _meme_list_{m_type}_new(void);",
        f"static inline meme_list_{m_type} _meme_list_{m_type}_create(int64_t count, {c_elem} const* items);",
        f"static inline meme_list_{m_type} _meme_list_{m_type}_copy(meme_list_{m_type} l);",
        f"static inline void _meme_list_{m_type}_append(meme_list_{m_type}* l, {c_elem} val);",
        f"static inline void _meme_list_{m_type}_insert(meme_list_{m_type}* l, int64_t idx, {c_elem} val);",
        f"static inline {c_elem} _meme_list_{m_type}_get(meme_list_{m_type} l, int64_t idx);",
        f"static inline void _meme_list_{m_type}_set(meme_list_{m_type}* l, int64_t idx, {c_elem} val);",
        f"static inline void _meme_list_{m_type}_remove(meme_list_{m_type}* l, int64_t idx);",
        f"static inline void _meme_list_{m_type}_remove_last(meme_list_{m_type}* l);",
        f"static inline const char* _meme_fmt_list_{m_type}(meme_list_{m_type} l);",
        f"static inline bool _meme_list_{m_type}_eq(meme_list_{m_type} a, meme_list_{m_type} b);",
        *sort_proto,
    ]


def _emit_list_body(el_t: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(el_t)
    c_elem = _c_type(el_t)
    is_sortable = el_t in ("Int", "Float", "String", "Bool")
    elem_fmt_call = gen._fmt_function_name(el_t)

    if el_t == "String":
        elem_eq = '(strcmp(a.data[i] ? a.data[i] : "", b.data[i] ? b.data[i] : "") == 0)'
    elif el_t in gen.records:
        elem_eq = f"{_c_ident(el_t)}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("List<") and el_t.endswith(">"):
        inner_m = _mangle_type(el_t[5:-1])
        elem_eq = f"_meme_list_{inner_m}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Map<") and el_t.endswith(">"):
        inner_map = _map_types_of(el_t)
        inner_m = f"{_mangle_type(inner_map[0])}_{_mangle_type(inner_map[1])}" if inner_map else "unknown"
        elem_eq = f"_meme_map_{inner_m}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Set<") and el_t.endswith(">"):
        st = _set_types_of(el_t)
        elem_eq = f"_meme_set_{_mangle_type(st)}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Optional<") and el_t.endswith(">"):
        inner_m = _mangle_type(el_t[9:-1])
        elem_eq = f"_meme_opt_{inner_m}_eq(a.data[i], b.data[i])"
    else:
        elem_eq = "(a.data[i] == b.data[i])"

    copy_expr = _c_copy_expr(el_t, "l.data[i]", gen)
    if copy_expr == "l.data[i]":
        copy_block = [f"    if (l.len > 0 && l.data) {{ memcpy(res.data, l.data, sizeof({c_elem}) * l.len); }}"]
    else:
        copy_block = [
            "    if (l.len > 0 && l.data) {",
            f"        for (int64_t i = 0; i < l.len; ++i) {{ res.data[i] = {copy_expr}; }}",
            "    }",
        ]

    list_lines = [
        f"static inline meme_list_{m_type} _meme_list_{m_type}_new(void) {{",
        f"    meme_list_{m_type} l;",
        "    l.data = NULL; l.len = 0; l.cap = 0;",
        "    return l;",
        "}",
        f"static inline meme_list_{m_type} _meme_list_{m_type}_create(int64_t count, {c_elem} const* items) {{",
        f"    meme_list_{m_type} l;",
        "    l.len = count;",
        "    l.cap = count > 0 ? count : 4;",
        f"    l.data = ({c_elem}*)malloc(sizeof({c_elem}) * l.cap);",
        f"    if (count > 0 && items) {{ memcpy(l.data, items, sizeof({c_elem}) * count); }}",
        "    return l;",
        "}",
        f"static inline meme_list_{m_type} _meme_list_{m_type}_copy(meme_list_{m_type} l) {{",
        f"    meme_list_{m_type} res;",
        "    res.len = l.len;",
        "    res.cap = l.len > 0 ? l.len : 4;",
        f"    res.data = ({c_elem}*)malloc(sizeof({c_elem}) * res.cap);",
        *copy_block,
        "    return res;",
        "}",
        f"static inline void _meme_list_{m_type}_append(meme_list_{m_type}* l, {c_elem} val) {{",
        "    if (l->len >= l->cap) {",
        "        l->cap = l->cap == 0 ? 4 : l->cap * 2;",
        f"        l->data = ({c_elem}*)realloc(l->data, sizeof({c_elem}) * l->cap);",
        "    }",
        "    l->data[l->len++] = val;",
        "}",
        f"static inline void _meme_list_{m_type}_insert(meme_list_{m_type}* l, int64_t idx, {c_elem} val) {{",
        "    if (idx < 0) idx = 0;",
        "    if (idx > l->len) idx = l->len;",
        "    if (l->len >= l->cap) {",
        "        l->cap = l->cap == 0 ? 4 : l->cap * 2;",
        f"        l->data = ({c_elem}*)realloc(l->data, sizeof({c_elem}) * l->cap);",
        "    }",
        "    for (int64_t i = l->len; i > idx; --i) l->data[i] = l->data[i - 1];",
        "    l->data[idx] = val;",
        "    l->len++;",
        "}",
        f"static inline {c_elem} _meme_list_{m_type}_get(meme_list_{m_type} l, int64_t idx) {{",
        "    if (idx < 0 || idx >= l.len) {",
        '        printf("Error: list index out of range\\n");',
        "        exit(1);",
        "    }",
        "    return l.data[idx];",
        "}",
        f"static inline void _meme_list_{m_type}_set(meme_list_{m_type}* l, int64_t idx, {c_elem} val) {{",
        "    if (idx < 0 || idx >= l->len) {",
        '        printf("Error: list index out of range\\n");',
        "        exit(1);",
        "    }",
        "    l->data[idx] = val;",
        "}",
        f"static inline void _meme_list_{m_type}_remove(meme_list_{m_type}* l, int64_t idx) {{",
        "    if (idx < 0 || idx >= l->len) {",
        '        printf("Error: list index out of range\\n");',
        "        exit(1);",
        "    }",
        "    for (int64_t i = idx; i < l->len - 1; ++i) l->data[i] = l->data[i + 1];",
        "    l->len--;",
        "}",
        f"static inline void _meme_list_{m_type}_remove_last(meme_list_{m_type}* l) {{",
        "    if (l->len <= 0) {",
        '        printf("Error: list index out of range\\n");',
        "        exit(1);",
        "    }",
        "    l->len--;",
        "}",
        f"static inline const char* _meme_fmt_list_{m_type}(meme_list_{m_type} l) {{",
        "    _MemeSB sb = _meme_sb_new();",
        "    _meme_sb_append_char(&sb, '[');",
        "    for (int64_t i = 0; i < l.len; ++i) {",
        '        if (i > 0) _meme_sb_append(&sb, ", ");',
        f"        _meme_sb_append(&sb, {elem_fmt_call}(l.data[i]));",
        "    }",
        "    _meme_sb_append_char(&sb, ']');",
        "    return sb.data;",
        "}",
        f"static inline bool _meme_list_{m_type}_eq(meme_list_{m_type} a, meme_list_{m_type} b) {{",
        "    if (a.len != b.len) return false;",
        "    for (int64_t i = 0; i < a.len; ++i) {",
        f"        if (!{elem_eq}) return false;",
        "    }",
        "    return true;",
        "}",
    ]

    if is_sortable:
        cmp_fn = f"_cmp_{el_t}"
        list_lines.extend([
            f"static void _meme_merge_sort_{m_type}({c_elem}* arr, {c_elem}* temp, int64_t left, int64_t right, bool desc) {{",
            "    if (left >= right) return;",
            "    int64_t mid = left + (right - left) / 2;",
            f"    _meme_merge_sort_{m_type}(arr, temp, left, mid, desc);",
            f"    _meme_merge_sort_{m_type}(arr, temp, mid + 1, right, desc);",
            "    int64_t i = left, j = mid + 1, k = left;",
            "    while (i <= mid && j <= right) {",
            f"        bool take_left = !desc ? ({cmp_fn}(arr[i], arr[j]) <= 0) : ({cmp_fn}(arr[i], arr[j]) >= 0);",
            "        if (take_left) temp[k++] = arr[i++];",
            "        else temp[k++] = arr[j++];",
            "    }",
            "    while (i <= mid) temp[k++] = arr[i++];",
            "    while (j <= right) temp[k++] = arr[j++];",
            "    for (i = left; i <= right; i++) arr[i] = temp[i];",
            "}",
            f"static inline void _meme_list_{m_type}_sort(meme_list_{m_type}* l, bool desc) {{",
            "    if (l->len <= 1) return;",
            f"    {c_elem}* temp = ({c_elem}*)malloc(sizeof({c_elem}) * l->len);",
            f"    _meme_merge_sort_{m_type}(l->data, temp, 0, l->len - 1, desc);",
            "    free(temp);",
            "}",
        ])
    return list_lines


def _emit_list_type(el_t: str, gen: _CGen) -> list[str]:
    return _emit_list_struct(el_t) + _emit_list_proto(el_t, gen) + _emit_list_body(el_t, gen)


def _emit_map_struct(k_t: str, v_t: str) -> list[str]:
    m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
    c_k_t = _c_type(k_t)
    c_v_t = _c_type(v_t)
    return [
        f"// Map<{k_t}, {v_t}>",
        "typedef struct {",
        f"    {c_k_t} key;",
        f"    {c_v_t} value;",
        f"}} meme_entry_{m_type};",
        "typedef struct {",
        f"    meme_entry_{m_type}* data;",
        "    int64_t len;",
        "    int64_t cap;",
        f"}} meme_map_{m_type};",
    ]


def _emit_map_proto(k_t: str, v_t: str, gen: _CGen) -> list[str]:
    m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
    c_k_t = _c_type(k_t)
    c_v_t = _c_type(v_t)
    return [
        f"static inline meme_map_{m_type} _meme_map_{m_type}_new(void);",
        f"static inline meme_map_{m_type} _meme_map_{m_type}_copy(meme_map_{m_type} m);",
        f"static inline int64_t _meme_map_{m_type}_find(const meme_map_{m_type}* m, {c_k_t} key);",
        f"static inline void _meme_map_{m_type}_set(meme_map_{m_type}* m, {c_k_t} key, {c_v_t} value);",
        f"static inline bool _meme_map_{m_type}_has_key(meme_map_{m_type} m, {c_k_t} key);",
        f"static inline {c_v_t} _meme_map_{m_type}_get(meme_map_{m_type} m, {c_k_t} key);",
        f"static inline {c_v_t} _meme_map_{m_type}_get_default(meme_map_{m_type} m, {c_k_t} key, {c_v_t} default_val);",
        f"static inline meme_map_{m_type} _meme_map_{m_type}_literal(int64_t count, const meme_entry_{m_type}* entries);",
        f"static inline const char* _meme_fmt_map_{m_type}(meme_map_{m_type} m);",
        f"static inline bool _meme_map_{m_type}_eq(meme_map_{m_type} a, meme_map_{m_type} b);",
    ]


def _emit_map_body(k_t: str, v_t: str, gen: _CGen) -> list[str]:
    m_type = f"{_mangle_type(k_t)}_{_mangle_type(v_t)}"
    c_k_t = _c_type(k_t)
    c_v_t = _c_type(v_t)
    cmp_fn = f"_cmp_{k_t}"
    k_fmt_call = gen._fmt_function_name(k_t)
    v_fmt_call = gen._fmt_function_name(v_t)

    if v_t == "String":
        val_eq = '(strcmp(a.data[i].value ? a.data[i].value : "", b.data[i].value ? b.data[i].value : "") == 0)'
    elif v_t in gen.records:
        val_eq = f"{_c_ident(v_t)}_eq(a.data[i].value, b.data[i].value)"
    elif v_t.startswith("List<") and v_t.endswith(">"):
        el_t = v_t[5:-1]
        val_eq = f"_meme_list_{_mangle_type(el_t)}_eq(a.data[i].value, b.data[i].value)"
    elif v_t.startswith("Map<") and v_t.endswith(">"):
        mt = _map_types_of(v_t)
        m_k = _mangle_type(mt[0]) if mt else "Int"
        m_v = _mangle_type(mt[1]) if mt else "String"
        val_eq = f"_meme_map_{m_k}_{m_v}_eq(a.data[i].value, b.data[i].value)"
    elif v_t.startswith("Set<") and v_t.endswith(">"):
        st = _set_types_of(v_t)
        val_eq = f"_meme_set_{_mangle_type(st)}_eq(a.data[i].value, b.data[i].value)"
    elif v_t.startswith("Optional<") and v_t.endswith(">"):
        inner = v_t[9:-1]
        val_eq = f"_meme_opt_{_mangle_type(inner)}_eq(a.data[i].value, b.data[i].value)"
    else:
        val_eq = "(a.data[i].value == b.data[i].value)"

    k_copy = _c_copy_expr(k_t, "m.data[i].key", gen)
    v_copy = _c_copy_expr(v_t, "m.data[i].value", gen)
    if k_copy == "m.data[i].key" and v_copy == "m.data[i].value":
        copy_block = [f"    if (m.len > 0 && m.data) {{ memcpy(res.data, m.data, sizeof(meme_entry_{m_type}) * m.len); }}"]
    else:
        copy_block = [
            "    if (m.len > 0 && m.data) {",
            "        for (int64_t i = 0; i < m.len; ++i) {",
            f"            res.data[i].key = {k_copy};",
            f"            res.data[i].value = {v_copy};",
            "        }",
            "    }",
        ]

    return [
        f"static inline meme_map_{m_type} _meme_map_{m_type}_new(void) {{",
        f"    meme_map_{m_type} m;",
        "    m.data = NULL; m.len = 0; m.cap = 0;",
        "    return m;",
        "}",
        f"static inline meme_map_{m_type} _meme_map_{m_type}_copy(meme_map_{m_type} m) {{",
        f"    meme_map_{m_type} res;",
        "    res.len = m.len;",
        "    res.cap = m.len > 0 ? m.len : 4;",
        f"    res.data = (meme_entry_{m_type}*)malloc(sizeof(meme_entry_{m_type}) * res.cap);",
        *copy_block,
        "    return res;",
        "}",
        f"static inline int64_t _meme_map_{m_type}_find(const meme_map_{m_type}* m, {c_k_t} key) {{",
        "    int64_t lo = 0, hi = m->len - 1;",
        "    while (lo <= hi) {",
        "        int64_t mid = lo + (hi - lo) / 2;",
        f"        int cmp = {cmp_fn}(m->data[mid].key, key);",
        "        if (cmp == 0) return mid;",
        "        if (cmp < 0) lo = mid + 1;",
        "        else hi = mid - 1;",
        "    }",
        "    return -1 - lo;",
        "}",
        f"static inline void _meme_map_{m_type}_set(meme_map_{m_type}* m, {c_k_t} key, {c_v_t} value) {{",
        f"    int64_t idx = _meme_map_{m_type}_find(m, key);",
        "    if (idx >= 0) {",
        "        m->data[idx].value = value;",
        "    } else {",
        "        int64_t ins = -1 - idx;",
        "        if (m->len >= m->cap) {",
        "            m->cap = m->cap == 0 ? 4 : m->cap * 2;",
        f"            m->data = (meme_entry_{m_type}*)realloc(m->data, sizeof(meme_entry_{m_type}) * m->cap);",
        "        }",
        "        for (int64_t i = m->len; i > ins; --i) m->data[i] = m->data[i - 1];",
        "        m->data[ins].key = key;",
        "        m->data[ins].value = value;",
        "        m->len++;",
        "    }",
        "}",
        f"static inline bool _meme_map_{m_type}_has_key(meme_map_{m_type} m, {c_k_t} key) {{",
        f"    return _meme_map_{m_type}_find(&m, key) >= 0;",
        "}",
        f"static inline {c_v_t} _meme_map_{m_type}_get(meme_map_{m_type} m, {c_k_t} key) {{",
        f"    int64_t idx = _meme_map_{m_type}_find(&m, key);",
        "    if (idx < 0) {",
        '        printf("Error: key not found in map\\n");',
        "        exit(1);",
        "    }",
        "    return m.data[idx].value;",
        "}",
        f"static inline {c_v_t} _meme_map_{m_type}_get_default(meme_map_{m_type} m, {c_k_t} key, {c_v_t} default_val) {{",
        f"    int64_t idx = _meme_map_{m_type}_find(&m, key);",
        "    if (idx >= 0) return m.data[idx].value;",
        "    return default_val;",
        "}",
        f"static inline meme_map_{m_type} _meme_map_{m_type}_literal(int64_t count, const meme_entry_{m_type}* entries) {{",
        f"    meme_map_{m_type} res = _meme_map_{m_type}_new();",
        "    for (int64_t i = 0; i < count; ++i) {",
        f"        _meme_map_{m_type}_set(&res, entries[i].key, entries[i].value);",
        "    }",
        "    return res;",
        "}",
        f"static inline const char* _meme_fmt_map_{m_type}(meme_map_{m_type} m) {{",
        "    _MemeSB sb = _meme_sb_new();",
        "    _meme_sb_append_char(&sb, '{');",
        "    for (int64_t i = 0; i < m.len; ++i) {",
        '        if (i > 0) _meme_sb_append(&sb, ", ");',
        f"        _meme_sb_append(&sb, {k_fmt_call}(m.data[i].key));",
        '        _meme_sb_append(&sb, ": ");',
        f"        _meme_sb_append(&sb, {v_fmt_call}(m.data[i].value));",
        "    }",
        "    _meme_sb_append_char(&sb, '}');",
        "    return sb.data;",
        "}",
        f"static inline bool _meme_map_{m_type}_eq(meme_map_{m_type} a, meme_map_{m_type} b) {{",
        "    if (a.len != b.len) return false;",
        "    for (int64_t i = 0; i < a.len; ++i) {",
        f"        if ({cmp_fn}(a.data[i].key, b.data[i].key) != 0) return false;",
        f"        if (!{val_eq}) return false;",
        "    }",
        "    return true;",
        "}",
    ]


def _emit_map_type(k_t: str, v_t: str, gen: _CGen) -> list[str]:
    return _emit_map_struct(k_t, v_t) + _emit_map_proto(k_t, v_t, gen) + _emit_map_body(k_t, v_t, gen)


def _emit_set_struct(el_t: str) -> list[str]:
    m_type = _mangle_type(el_t)
    c_el = _c_type(el_t)
    return [
        f"// Set<{el_t}>",
        "typedef struct {",
        f"    {c_el}* data;",
        "    int64_t len;",
        "    int64_t cap;",
        f"}} meme_set_{m_type};",
    ]


def _emit_set_proto(el_t: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(el_t)
    c_el = _c_type(el_t)
    cmp_proto: list[str] = []
    if el_t in gen.records:
        cmp_proto.append(f"static inline int _meme_set_cmp_{m_type}({_c_ident(el_t)} a, {_c_ident(el_t)} b);")
    return [
        *cmp_proto,
        f"static inline meme_set_{m_type} _meme_set_{m_type}_new(void);",
        f"static inline int64_t _meme_set_{m_type}_find(const meme_set_{m_type}* s, {c_el} val);",
        f"static inline void _meme_set_{m_type}_add(meme_set_{m_type}* s, {c_el} val);",
        f"static inline void _meme_set_{m_type}_remove(meme_set_{m_type}* s, {c_el} val);",
        f"static inline bool _meme_set_{m_type}_contains(meme_set_{m_type} s, {c_el} val);",
        f"static inline meme_set_{m_type} _meme_set_{m_type}_copy(meme_set_{m_type} s);",
        f"static inline const char* _meme_set_{m_type}_fmt(meme_set_{m_type} s);",
        f"static inline const char* _meme_fmt_set_{m_type}(meme_set_{m_type} s);",
        f"static inline bool _meme_set_{m_type}_eq(meme_set_{m_type} a, meme_set_{m_type} b);",
    ]


def _emit_set_body(el_t: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(el_t)
    c_el = _c_type(el_t)
    fmt_call = gen._fmt_function_name(el_t)
    if el_t == "String":
        elem_eq = '(strcmp(a.data[i] ? a.data[i] : "", b.data[i] ? b.data[i] : "") == 0)'
    elif el_t in gen.records:
        elem_eq = f"{_c_ident(el_t)}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("List<") and el_t.endswith(">"):
        inner = el_t[5:-1]
        elem_eq = f"_meme_list_{_mangle_type(inner)}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Map<") and el_t.endswith(">"):
        mt = _map_types_of(el_t)
        m_k = _mangle_type(mt[0]) if mt else "Int"
        m_v = _mangle_type(mt[1]) if mt else "String"
        elem_eq = f"_meme_map_{m_k}_{m_v}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Set<") and el_t.endswith(">"):
        inner = _set_types_of(el_t)
        elem_eq = f"_meme_set_{_mangle_type(inner)}_eq(a.data[i], b.data[i])"
    elif el_t.startswith("Optional<") and el_t.endswith(">"):
        inner = el_t[9:-1]
        elem_eq = f"_meme_opt_{_mangle_type(inner)}_eq(a.data[i], b.data[i])"
    else:
        elem_eq = "(a.data[i] == b.data[i])"

    if el_t in gen.records:
        cmp_fn = f"_meme_set_cmp_{m_type}"
        field_cmps: list[str] = []
        for f_name, f_type in gen.records[el_t].items():
            f_ident = _c_ident(f_name)
            if f_type == "String":
                field_cmps.append(
                    f'    {{ int _c = strcmp((a.{f_ident} ? a.{f_ident} : ""), (b.{f_ident} ? b.{f_ident} : "")); if (_c != 0) return _c; }}'
                )
            elif f_type in ("Int", "Float", "Bool"):
                field_cmps.append(
                    f'    {{ if (a.{f_ident} != b.{f_ident}) return (a.{f_ident} > b.{f_ident}) - (a.{f_ident} < b.{f_ident}); }}'
                )
            elif f_type.startswith("Optional<"):
                field_cmps.append(
                    f'    {{ if (a.{f_ident}.present != b.{f_ident}.present) return a.{f_ident}.present ? 1 : -1; }}'
                )
                if f_type.startswith("Optional<List<"):
                    continue
                inner_v_t = f_type[9:-1]
                if inner_v_t == "String":
                    field_cmps.append(
                        f'    {{ if (a.{f_ident}.present) {{ int _c = strcmp(a.{f_ident}.value, b.{f_ident}.value); if (_c != 0) return _c; }} }}'
                    )
                elif inner_v_t in ("Int", "Float", "Bool"):
                    field_cmps.append(
                        f'    {{ if (a.{f_ident}.present && a.{f_ident}.value != b.{f_ident}.value) return (a.{f_ident}.value > b.{f_ident}.value) - (a.{f_ident}.value < b.{f_ident}.value); }}'
                    )
        cmp_lines = [
            f"static inline int _meme_set_cmp_{m_type}({_c_ident(el_t)} a, {_c_ident(el_t)} b) {{",
            *field_cmps,
            "    return 0;",
            "}",
        ]
    else:
        cmp_fn = f"_cmp_{el_t}"
        cmp_lines = []

    copy_expr = _c_copy_expr(el_t, "s.data[i]", gen)
    if copy_expr == "s.data[i]":
        copy_block = [f"    if (s.len > 0 && s.data) {{ memcpy(res.data, s.data, sizeof({c_el}) * s.len); }}"]
    else:
        copy_block = [
            "    if (s.len > 0 && s.data) {",
            f"        for (int64_t i = 0; i < s.len; ++i) {{ res.data[i] = {copy_expr}; }}",
            "    }",
        ]

    return [
        *cmp_lines,
        f"static inline meme_set_{m_type} _meme_set_{m_type}_new(void) {{",
        f"    meme_set_{m_type} s = {{ .data = NULL, .len = 0, .cap = 0 }};",
        "    return s;",
        "}",
        f"static inline int64_t _meme_set_{m_type}_find(const meme_set_{m_type}* s, {c_el} val) {{",
        "    int64_t lo = 0, hi = s->len - 1;",
        "    while (lo <= hi) {",
        "        int64_t mid = lo + (hi - lo) / 2;",
        f"        int cmp = {cmp_fn}(s->data[mid], val);",
        "        if (cmp == 0) return mid;",
        "        if (cmp < 0) lo = mid + 1;",
        "        else hi = mid - 1;",
        "    }",
        "    return -1 - lo;",
        "}",
        f"static inline void _meme_set_{m_type}_add(meme_set_{m_type}* s, {c_el} val) {{",
        f"    int64_t idx = _meme_set_{m_type}_find(s, val);",
        "    if (idx >= 0) return;",
        "    int64_t ins = -1 - idx;",
        "    if (s->len >= s->cap) {",
        "        s->cap = s->cap == 0 ? 4 : s->cap * 2;",
        f"        s->data = ({c_el}*)realloc(s->data, sizeof({c_el}) * s->cap);",
        "    }",
        "    for (int64_t i = s->len; i > ins; --i) s->data[i] = s->data[i - 1];",
        "    s->data[ins] = val;",
        "    s->len++;",
        "}",
        f"static inline void _meme_set_{m_type}_remove(meme_set_{m_type}* s, {c_el} val) {{",
        f"    int64_t idx = _meme_set_{m_type}_find(s, val);",
        "    if (idx < 0) return;",
        "    for (int64_t i = idx; i < s->len - 1; ++i) s->data[i] = s->data[i + 1];",
        "    s->len--;",
        "}",
        f"static inline bool _meme_set_{m_type}_contains(meme_set_{m_type} s, {c_el} val) {{",
        f"    return _meme_set_{m_type}_find(&s, val) >= 0;",
        "}",
        f"static inline meme_set_{m_type} _meme_set_{m_type}_copy(meme_set_{m_type} s) {{",
        f"    meme_set_{m_type} res;",
        "    res.len = s.len;",
        "    res.cap = s.len > 0 ? s.len : 4;",
        f"    res.data = ({c_el}*)malloc(sizeof({c_el}) * res.cap);",
        *copy_block,
        "    return res;",
        "}",
        f"static inline const char* _meme_set_{m_type}_fmt(meme_set_{m_type} s) {{",
        "    _MemeSB sb = _meme_sb_new();",
        '    _meme_sb_append(&sb, "{");',
        "    for (int64_t i = 0; i < s.len; ++i) {",
        '        if (i > 0) _meme_sb_append(&sb, ", ");',
        f"        _meme_sb_append(&sb, {fmt_call}(s.data[i]));",
        "    }",
        '    _meme_sb_append(&sb, "}");',
        "    return sb.data;",
        "}",
        f"static inline const char* _meme_fmt_set_{m_type}(meme_set_{m_type} s) {{",
        f"    return _meme_set_{m_type}_fmt(s);",
        "}",
        f"static inline bool _meme_set_{m_type}_eq(meme_set_{m_type} a, meme_set_{m_type} b) {{",
        "    if (a.len != b.len) return false;",
        "    for (int64_t i = 0; i < a.len; ++i) {",
        f"        if (!{elem_eq}) return false;",
        "    }",
        "    return true;",
        "}",
    ]


def _emit_set_type(el_t: str, gen: _CGen) -> list[str]:
    return _emit_set_struct(el_t) + _emit_set_proto(el_t, gen) + _emit_set_body(el_t, gen)


def _emit_opt_struct(inner: str, gen: _CGen | None = None) -> list[str]:
    m_type = _mangle_type(inner)
    if gen and inner in gen.records:
        c_inner = f"{_c_ident(inner)}*"
    else:
        c_inner = _c_type(inner)
    return [
        f"// Optional<{inner}>",
        "typedef struct {",
        "    bool present;",
        f"    {c_inner} value;",
        f"}} meme_opt_{m_type};",
    ]


def _emit_opt_proto(inner: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(inner)
    c_inner = _c_type(inner)
    return [
        f"static inline meme_opt_{m_type} _meme_opt_{m_type}_some({c_inner} val);",
        f"static inline {c_inner} _meme_opt_{m_type}_unwrap(meme_opt_{m_type} opt);",
        f"static inline meme_opt_{m_type} _meme_opt_{m_type}_copy(meme_opt_{m_type} opt);",
        f"static inline const char* _meme_fmt_opt_{m_type}(meme_opt_{m_type} opt);",
        f"static inline bool _meme_opt_{m_type}_eq(meme_opt_{m_type} a, meme_opt_{m_type} b);",
    ]


def _emit_opt_body(inner: str, gen: _CGen) -> list[str]:
    m_type = _mangle_type(inner)
    c_inner = _c_type(inner)
    inner_fmt_call = gen._fmt_function_name(inner)

    if inner in gen.records:
        r_id = _c_ident(inner)
        return [
            f"static inline meme_opt_{m_type} _meme_opt_{m_type}_some({c_inner} val) {{",
            f"    meme_opt_{m_type} o;",
            "    o.present = true;",
            f"    o.value = ({c_inner}*)malloc(sizeof({c_inner}));",
            f"    *o.value = {r_id}_copy(val);",
            "    return o;",
            "}",
            f"static inline {c_inner} _meme_opt_{m_type}_unwrap(meme_opt_{m_type} opt) {{",
            "    if (!opt.present || opt.value == NULL) {",
            '        printf("Unwrap failed: Optional value is nothing\\n");',
            "        exit(1);",
            "    }",
            f"    return {r_id}_copy(*opt.value);",
            "}",
            f"static inline meme_opt_{m_type} _meme_opt_{m_type}_copy(meme_opt_{m_type} opt) {{",
            "    if (!opt.present || opt.value == NULL) {",
            f"        meme_opt_{m_type} r = {{0}};",
            "        return r;",
            "    }",
            f"    meme_opt_{m_type} res;",
            "    res.present = true;",
            f"    res.value = ({c_inner}*)malloc(sizeof({c_inner}));",
            f"    *res.value = {r_id}_copy(*opt.value);",
            "    return res;",
            "}",
            f"static inline const char* _meme_fmt_opt_{m_type}(meme_opt_{m_type} opt) {{",
            f"    if (opt.present && opt.value != NULL) return {inner_fmt_call}(*opt.value);",
            '    return "None";',
            "}",
            f"static inline bool _meme_opt_{m_type}_eq(meme_opt_{m_type} a, meme_opt_{m_type} b) {{",
            "    if (a.present != b.present) return false;",
            "    if (!a.present) return true;",
            "    if (a.value == NULL || b.value == NULL) return a.value == b.value;",
            f"    return {r_id}_eq(*a.value, *b.value);",
            "}",
        ]
    elif inner.startswith("List<") and inner.endswith(">"):
        el_t = inner[5:-1]
        val_eq = f"_meme_list_{_mangle_type(el_t)}_eq(a.value, b.value)"
    elif inner.startswith("Map<") and inner.endswith(">"):
        mt = _map_types_of(inner)
        m_k = _mangle_type(mt[0]) if mt else "Int"
        m_v = _mangle_type(mt[1]) if mt else "String"
        val_eq = f"_meme_map_{m_k}_{m_v}_eq(a.value, b.value)"
    elif inner.startswith("Set<") and inner.endswith(">"):
        st = _set_types_of(inner)
        val_eq = f"_meme_set_{_mangle_type(st)}_eq(a.value, b.value)"
    elif inner.startswith("Optional<") and inner.endswith(">"):
        inner_sub = inner[9:-1]
        val_eq = f"_meme_opt_{_mangle_type(inner_sub)}_eq(a.value, b.value)"
    else:
        val_eq = "(a.value == b.value)"

    copy_call = _c_copy_expr(inner, "opt.value", gen)

    return [
        f"static inline meme_opt_{m_type} _meme_opt_{m_type}_some({c_inner} val) {{",
        f"    meme_opt_{m_type} o;",
        "    o.present = true; o.value = val;",
        "    return o;",
        "}",
        f"static inline {c_inner} _meme_opt_{m_type}_unwrap(meme_opt_{m_type} opt) {{",
        "    if (!opt.present) {",
        '        printf("Unwrap failed: Optional value is nothing\\n");',
        "        exit(1);",
        "    }",
        "    return opt.value;",
        "}",
        f"static inline meme_opt_{m_type} _meme_opt_{m_type}_copy(meme_opt_{m_type} opt) {{",
        "    if (!opt.present) return opt;",
        f"    meme_opt_{m_type} res;",
        "    res.present = true;",
        f"    res.value = {copy_call};",
        "    return res;",
        "}",
        f"static inline const char* _meme_fmt_opt_{m_type}(meme_opt_{m_type} opt) {{",
        f"    if (opt.present) return {inner_fmt_call}(opt.value);",
        '    return "None";',
        "}",
        f"static inline bool _meme_opt_{m_type}_eq(meme_opt_{m_type} a, meme_opt_{m_type} b) {{",
        "    if (a.present != b.present) return false;",
        "    if (!a.present) return true;",
        f"    return {val_eq};",
        "}",
    ]


def _emit_opt_type(inner: str, gen: _CGen) -> list[str]:
    return _emit_opt_struct(inner) + _emit_opt_proto(inner, gen) + _emit_opt_body(inner, gen)


def _emit_record_decl(r: RecordDefStmt, gen: _CGen) -> list[str]:
    r_ident = _c_ident(r.name)
    lines = [f"struct {r_ident} {{"]
    for f in r.fields:
        lines.append(f"    {_c_type(f.field_type)} {_c_ident(f.name)};")
    lines.append("};")
    return lines


def _emit_record_proto(r: RecordDefStmt, gen: _CGen) -> list[str]:
    r_ident = _c_ident(r.name)
    return [
        f"static inline bool {r_ident}_eq({r_ident} a, {r_ident} b);",
        f"static inline {r_ident} {r_ident}_copy({r_ident} r);",
        f"static inline const char* _meme_fmt_{r_ident}({r_ident} r);",
    ]


def _emit_record_body(r: RecordDefStmt, gen: _CGen) -> list[str]:
    r_ident = _c_ident(r.name)
    lines: list[str] = []

    # Record equality
    lines.append(f"static inline bool {r_ident}_eq({r_ident} a, {r_ident} b) {{")
    if not r.fields:
        lines.append("    (void)a; (void)b; return true;")
    else:
        conds: list[str] = []
        for f in r.fields:
            f_ident = _c_ident(f.name)
            if f.field_type == "String":
                conds.append(f'(strcmp(a.{f_ident} ? a.{f_ident} : "", b.{f_ident} ? b.{f_ident} : "") == 0)')
            elif f.field_type in gen.records:
                conds.append(f"{_c_ident(f.field_type)}_eq(a.{f_ident}, b.{f_ident})")
            elif f.field_type.startswith("List<") and f.field_type.endswith(">"):
                el_t = f.field_type[5:-1]
                conds.append(f"_meme_list_{_mangle_type(el_t)}_eq(a.{f_ident}, b.{f_ident})")
            elif f.field_type.startswith("Map<") and f.field_type.endswith(">"):
                mt = _map_types_of(f.field_type)
                m_k = _mangle_type(mt[0]) if mt else "Int"
                m_v = _mangle_type(mt[1]) if mt else "String"
                conds.append(f"_meme_map_{m_k}_{m_v}_eq(a.{f_ident}, b.{f_ident})")
            elif f.field_type.startswith("Set<") and f.field_type.endswith(">"):
                st = _set_types_of(f.field_type)
                conds.append(f"_meme_set_{_mangle_type(st)}_eq(a.{f_ident}, b.{f_ident})")
            elif f.field_type.startswith("Optional<") and f.field_type.endswith(">"):
                inner = f.field_type[9:-1]
                conds.append(f"_meme_opt_{_mangle_type(inner)}_eq(a.{f_ident}, b.{f_ident})")
            else:
                conds.append(f"(a.{f_ident} == b.{f_ident})")
        lines.append(f"    return {' && '.join(conds)};")
    lines.append("}")

    # Record copy
    lines.append(f"static inline {r_ident} {r_ident}_copy({r_ident} r) {{")
    lines.append(f"    {r_ident} res = r;")
    for f in r.fields:
        f_ident = _c_ident(f.name)
        copy_expr = _c_copy_expr(f.field_type, f"r.{f_ident}", gen)
        if copy_expr != f"r.{f_ident}":
            lines.append(f"    res.{f_ident} = {copy_expr};")
    lines.append("    return res;")
    lines.append("}")

    # Record formatting
    lines.append(f"static inline const char* _meme_fmt_{r_ident}({r_ident} r) {{")
    if not r.fields:
        lines.append(f'    (void)r; return "{r.name}()";')
    else:
        lines.append("    _MemeSB sb = _meme_sb_new();")
        lines.append(f'    _meme_sb_append(&sb, "{r.name}(");')
        for idx, f in enumerate(r.fields):
            f_ident = _c_ident(f.name)
            fmt_fn = gen._fmt_function_name(f.field_type)
            if idx > 0:
                lines.append('    _meme_sb_append(&sb, ", ");')
            lines.append(f'    _meme_sb_append(&sb, "{f.name}=");')
            lines.append(f"    _meme_sb_append(&sb, {fmt_fn}(r.{f_ident}));")
        lines.append("    _meme_sb_append_char(&sb, ')');")
        lines.append("    return sb.data;")
    lines.append("}")
    return lines


def _emit_record(r: RecordDefStmt, gen: _CGen) -> list[str]:
    return _emit_record_decl(r, gen) + _emit_record_proto(r, gen) + _emit_record_body(r, gen)


_C_JSON_PARSER_HELPERS = [
    "typedef enum { _MEME_J_NULL, _MEME_J_BOOL, _MEME_J_NUM, _MEME_J_STR, _MEME_J_ARR, _MEME_J_OBJ } _MemeJK;",
    "typedef struct _MemeJV _MemeJV;",
    "typedef struct { char* key; _MemeJV* val; } _MemeJField;",
    "struct _MemeJV {",
    "    _MemeJK kind;",
    "    bool b;",
    "    double num;",
    "    bool is_int;",
    "    int64_t i_val;",
    "    char* str;",
    "    _MemeJV** arr;",
    "    size_t arr_len;",
    "    _MemeJField* obj;",
    "    size_t obj_len;",
    "};",
    "",
    "static void _meme_free_jv(_MemeJV* v) {",
    "    if (!v) return;",
    "    if (v->kind == _MEME_J_STR) free(v->str);",
    "    else if (v->kind == _MEME_J_ARR) {",
    "        for (size_t i = 0; i < v->arr_len; ++i) _meme_free_jv(v->arr[i]);",
    "        free(v->arr);",
    "    } else if (v->kind == _MEME_J_OBJ) {",
    "        for (size_t i = 0; i < v->obj_len; ++i) {",
    "            free(v->obj[i].key);",
    "            _meme_free_jv(v->obj[i].val);",
    "        }",
    "        free(v->obj);",
    "    }",
    "    free(v);",
    "}",
    "",
    "static inline void _meme_skip_ws(const char* s, size_t* i) {",
    "    while (s[*i] && isspace((unsigned char)s[*i])) (*i)++;",
    "}",
    "",
    "static bool _meme_parse_jv(const char* s, size_t* i, _MemeJV** out);",
    "",
    "static bool _meme_parse_jv_str(const char* s, size_t* i, char** out) {",
    "    if (s[*i] != '\"') return false;",
    "    (*i)++;",
    "    _MemeSB sb = _meme_sb_new();",
    "    while (s[*i] && s[*i] != '\"') {",
    "        if (s[*i] == '\\\\') {",
    "            (*i)++;",
    "            if (!s[*i]) { free(sb.data); return false; }",
    "            char c = s[(*i)++];",
    "            if (c == '\"') _meme_sb_append_char(&sb, '\"');",
    "            else if (c == '\\\\') _meme_sb_append_char(&sb, '\\\\');",
    "            else if (c == '/') _meme_sb_append_char(&sb, '/');",
    "            else if (c == 'b') _meme_sb_append_char(&sb, '\\b');",
    "            else if (c == 'f') _meme_sb_append_char(&sb, '\\f');",
    "            else if (c == 'n') _meme_sb_append_char(&sb, '\\n');",
    "            else if (c == 'r') _meme_sb_append_char(&sb, '\\r');",
    "            else if (c == 't') _meme_sb_append_char(&sb, '\\t');",
    "            else if (c == 'u') {",
    "                unsigned int cp = 0;",
    "                for (int k = 0; k < 4; ++k) {",
    "                    char h = s[(*i)++];",
    "                    if (!h) { free(sb.data); return false; }",
    "                    cp <<= 4;",
    "                    if (h >= '0' && h <= '9') cp |= (h - '0');",
    "                    else if (h >= 'a' && h <= 'f') cp |= (h - 'a' + 10);",
    "                    else if (h >= 'A' && h <= 'F') cp |= (h - 'A' + 10);",
    "                    else { free(sb.data); return false; }",
    "                }",
    "                char ubuf[5] = {0};",
    "                if (cp <= 0x7F) { ubuf[0] = (char)cp; }",
    "                else if (cp <= 0x7FF) {",
    "                    ubuf[0] = (char)(0xC0 | (cp >> 6));",
    "                    ubuf[1] = (char)(0x80 | (cp & 0x3F));",
    "                } else {",
    "                    ubuf[0] = (char)(0xE0 | (cp >> 12));",
    "                    ubuf[1] = (char)(0x80 | ((cp >> 6) & 0x3F));",
    "                    ubuf[2] = (char)(0x80 | (cp & 0x3F));",
    "                }",
    "                _meme_sb_append(&sb, ubuf);",
    "            } else { free(sb.data); return false; }",
    "        } else {",
    "            _meme_sb_append_char(&sb, s[(*i)++]);",
    "        }",
    "    }",
    "    if (s[*i] != '\"') { free(sb.data); return false; }",
    "    (*i)++;",
    "    *out = sb.data;",
    "    return true;",
    "}",
    "",
    "static bool _meme_parse_jv(const char* s, size_t* i, _MemeJV** out) {",
    "    _meme_skip_ws(s, i);",
    "    if (!s[*i]) return false;",
    "    _MemeJV* v = (_MemeJV*)calloc(1, sizeof(_MemeJV));",
    "    if (strncmp(s + *i, \"null\", 4) == 0) {",
    "        *i += 4; v->kind = _MEME_J_NULL; *out = v; return true;",
    "    }",
    "    if (strncmp(s + *i, \"true\", 4) == 0) {",
    "        *i += 4; v->kind = _MEME_J_BOOL; v->b = true; *out = v; return true;",
    "    }",
    "    if (strncmp(s + *i, \"false\", 5) == 0) {",
    "        *i += 5; v->kind = _MEME_J_BOOL; v->b = false; *out = v; return true;",
    "    }",
    "    if (s[*i] == '\"') {",
    "        v->kind = _MEME_J_STR;",
    "        if (!_meme_parse_jv_str(s, i, &v->str)) { free(v); return false; }",
    "        *out = v; return true;",
    "    }",
    "    if (s[*i] == '-' || (s[*i] >= '0' && s[*i] <= '9')) {",
    "        size_t start = *i;",
    "        bool has_dot_or_exp = false;",
    "        if (s[*i] == '-') (*i)++;",
    "        while (s[*i] >= '0' && s[*i] <= '9') (*i)++;",
    "        if (s[*i] == '.') {",
    "            has_dot_or_exp = true; (*i)++;",
    "            while (s[*i] >= '0' && s[*i] <= '9') (*i)++;",
    "        }",
    "        if (s[*i] == 'e' || s[*i] == 'E') {",
    "            has_dot_or_exp = true; (*i)++;",
    "            if (s[*i] == '+' || s[*i] == '-') (*i)++;",
    "            while (s[*i] >= '0' && s[*i] <= '9') (*i)++;",
    "        }",
    "        size_t nlen = *i - start;",
    "        char nbuf[64];",
    "        if (nlen >= sizeof(nbuf)) { free(v); return false; }",
    "        memcpy(nbuf, s + start, nlen);",
    "        nbuf[nlen] = '\\0';",
    "        char* end = NULL;",
    "        v->num = strtod(nbuf, &end);",
    "        if (!end || *end != '\\0') { free(v); return false; }",
    "        v->kind = _MEME_J_NUM;",
    "        if (!has_dot_or_exp) {",
    "            v->is_int = true;",
    "            v->i_val = strtoll(nbuf, NULL, 10);",
    "        } else if (v->num == (double)((int64_t)v->num)) {",
    "            v->is_int = true;",
    "            v->i_val = (int64_t)v->num;",
    "        } else {",
    "            v->is_int = false;",
    "        }",
    "        *out = v; return true;",
    "    }",
    "    if (s[*i] == '[') {",
    "        (*i)++;",
    "        v->kind = _MEME_J_ARR;",
    "        size_t cap = 8;",
    "        v->arr = (_MemeJV**)malloc(sizeof(_MemeJV*) * cap);",
    "        v->arr_len = 0;",
    "        _meme_skip_ws(s, i);",
    "        if (s[*i] == ']') { (*i)++; *out = v; return true; }",
    "        while (s[*i]) {",
    "            _MemeJV* elem = NULL;",
    "            if (!_meme_parse_jv(s, i, &elem)) { _meme_free_jv(v); return false; }",
    "            if (v->arr_len >= cap) {",
    "                cap *= 2;",
    "                v->arr = (_MemeJV**)realloc(v->arr, sizeof(_MemeJV*) * cap);",
    "            }",
    "            v->arr[v->arr_len++] = elem;",
    "            _meme_skip_ws(s, i);",
    "            if (s[*i] == ',') { (*i)++; continue; }",
    "            if (s[*i] == ']') { (*i)++; *out = v; return true; }",
    "            _meme_free_jv(v); return false;",
    "        }",
    "        _meme_free_jv(v); return false;",
    "    }",
    "    if (s[*i] == '{') {",
    "        (*i)++;",
    "        v->kind = _MEME_J_OBJ;",
    "        size_t cap = 8;",
    "        v->obj = (_MemeJField*)malloc(sizeof(_MemeJField) * cap);",
    "        v->obj_len = 0;",
    "        _meme_skip_ws(s, i);",
    "        if (s[*i] == '}') { (*i)++; *out = v; return true; }",
    "        while (s[*i]) {",
    "            _meme_skip_ws(s, i);",
    "            char* key = NULL;",
    "            if (!_meme_parse_jv_str(s, i, &key)) { _meme_free_jv(v); return false; }",
    "            _meme_skip_ws(s, i);",
    "            if (s[*i] != ':') { free(key); _meme_free_jv(v); return false; }",
    "            (*i)++;",
    "            _MemeJV* val = NULL;",
    "            if (!_meme_parse_jv(s, i, &val)) { free(key); _meme_free_jv(v); return false; }",
    "            if (v->obj_len >= cap) {",
    "                cap *= 2;",
    "                v->obj = (_MemeJField*)realloc(v->obj, sizeof(_MemeJField) * cap);",
    "            }",
    "            v->obj[v->obj_len].key = key;",
    "            v->obj[v->obj_len].val = val;",
    "            v->obj_len++;",
    "            _meme_skip_ws(s, i);",
    "            if (s[*i] == ',') { (*i)++; continue; }",
    "            if (s[*i] == '}') { (*i)++; *out = v; return true; }",
    "            _meme_free_jv(v); return false;",
    "        }",
    "        _meme_free_jv(v); return false;",
    "    }",
    "    free(v);",
    "    return false;",
    "}",
    "",
    "static const _MemeJV* _meme_jv_find_field(const _MemeJV* obj, const char* key) {",
    "    if (!obj || obj->kind != _MEME_J_OBJ) return NULL;",
    "    for (size_t i = 0; i < obj->obj_len; ++i) {",
    "        if (strcmp(obj->obj[i].key, key) == 0) return obj->obj[i].val;",
    "    }",
    "    return NULL;",
    "}",
    "",
    "static _MemeJV* _meme_read_json_file(const char* path) {",
    "    const char* rp = _meme_resolve_path(path);",
    "    FILE* fp = fopen(rp, \"rb\");",
    "    if (!fp) return NULL;",
    "    fseek(fp, 0, SEEK_END);",
    "    long sz = ftell(fp);",
    "    fseek(fp, 0, SEEK_SET);",
    "    if (sz < 0) { fclose(fp); return NULL; }",
    "    char* buf = (char*)malloc(sz + 1);",
    "    if (fread(buf, 1, sz, fp) != (size_t)sz) { free(buf); fclose(fp); return NULL; }",
    "    fclose(fp);",
    "    buf[sz] = '\\0';",
    "    size_t i = 0;",
    "    _MemeJV* root = NULL;",
    "    if (!_meme_parse_jv(buf, &i, &root)) { free(buf); return NULL; }",
    "    _meme_skip_ws(buf, &i);",
    "    if (buf[i] != '\\0') { _meme_free_jv(root); free(buf); return NULL; }",
    "    free(buf);",
    "    return root;",
    "}",
    "",
]


def _c_json_decode_val(jv_ptr: str, ftype: str, indent: str, records: set[str] | None = None) -> tuple[str, list[str]]:
    if ftype == "Int":
        temp_val = f"_v_{abs(hash(ftype + jv_ptr)) % 1000000}"
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_NUM || !{jv_ptr}->is_int) return false;",
            f"{indent}int64_t {temp_val} = {jv_ptr}->i_val;",
        ]
        return temp_val, code
    if ftype == "Float":
        temp_val = f"_v_{abs(hash(ftype + jv_ptr)) % 1000000}"
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_NUM) return false;",
            f"{indent}double {temp_val} = {jv_ptr}->num;",
        ]
        return temp_val, code
    if ftype == "String":
        temp_val = f"_v_{abs(hash(ftype + jv_ptr)) % 1000000}"
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_STR) return false;",
            f"{indent}char* {temp_val} = (char*)malloc(strlen({jv_ptr}->str) + 1);",
            f"{indent}strcpy({temp_val}, {jv_ptr}->str);",
        ]
        return temp_val, code
    if ftype == "Bool":
        temp_val = f"_v_{abs(hash(ftype + jv_ptr)) % 1000000}"
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_BOOL) return false;",
            f"{indent}bool {temp_val} = {jv_ptr}->b;",
        ]
        return temp_val, code
    if ftype.startswith("Optional<") and ftype.endswith(">"):
        inner = ftype[9:-1]
        m_inner = _mangle_type(inner)
        temp_opt = f"_opt_{abs(hash(ftype + jv_ptr)) % 1000000}"
        inner_val, inner_code = _c_json_decode_val(jv_ptr, inner, indent + "    ", records)
        code = [
            f"{indent}meme_opt_{m_inner} {temp_opt} = (meme_opt_{m_inner}){{0}};",
            f"{indent}if ({jv_ptr} && {jv_ptr}->kind != _MEME_J_NULL) {{",
            *inner_code,
            f"{indent}    {temp_opt} = _meme_opt_{m_inner}_some({inner_val});",
            f"{indent}}}",
        ]
        return temp_opt, code
    if ftype.startswith("List<") and ftype.endswith(">"):
        el_t = ftype[5:-1]
        m_el = _mangle_type(el_t)
        temp_list = f"_l_{abs(hash(ftype + jv_ptr)) % 1000000}"
        temp_i = f"_i_{abs(hash(ftype + jv_ptr)) % 1000000}"
        el_val, el_code = _c_json_decode_val(f"{jv_ptr}->arr[{temp_i}]", el_t, indent + "    ", records)
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_ARR) return false;",
            f"{indent}meme_list_{m_el} {temp_list} = _meme_list_{m_el}_new();",
            f"{indent}for (size_t {temp_i} = 0; {temp_i} < {jv_ptr}->arr_len; ++{temp_i}) {{",
            *el_code,
            f"{indent}    _meme_list_{m_el}_append(&{temp_list}, {el_val});",
            f"{indent}}}",
        ]
        return temp_list, code
    if ftype.startswith("Set<") and ftype.endswith(">"):
        el_t = ftype[4:-1]
        m_el = _mangle_type(el_t)
        temp_set = f"_s_{abs(hash(ftype + jv_ptr)) % 1000000}"
        temp_i = f"_i_{abs(hash(ftype + jv_ptr)) % 1000000}"
        el_val, el_code = _c_json_decode_val(f"{jv_ptr}->arr[{temp_i}]", el_t, indent + "    ", records)
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_ARR) return false;",
            f"{indent}meme_set_{m_el} {temp_set} = _meme_set_{m_el}_new();",
            f"{indent}for (size_t {temp_i} = 0; {temp_i} < {jv_ptr}->arr_len; ++{temp_i}) {{",
            *el_code,
            f"{indent}    _meme_set_{m_el}_add(&{temp_set}, {el_val});",
            f"{indent}}}",
        ]
        return temp_set, code
    if ftype.startswith("Map<") and ftype.endswith(">"):
        mt = _map_types_of(ftype)
        assert mt is not None
        k_t, v_t = mt
        m_k = _mangle_type(k_t)
        m_v = _mangle_type(v_t)
        temp_map = f"_m_{abs(hash(ftype + jv_ptr)) % 1000000}"
        temp_i = f"_i_{abs(hash(ftype + jv_ptr)) % 1000000}"
        v_val, v_code = _c_json_decode_val(f"{jv_ptr}->obj[{temp_i}].val", v_t, indent + "    ", records)
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_OBJ) return false;",
            f"{indent}meme_map_{m_k}_{m_v} {temp_map} = _meme_map_{m_k}_{m_v}_new();",
            f"{indent}for (size_t {temp_i} = 0; {temp_i} < {jv_ptr}->obj_len; ++{temp_i}) {{",
            f"{indent}    const char* _k_str = {jv_ptr}->obj[{temp_i}].key;",
        ]
        if k_t == "Int":
            code.extend([
                f"{indent}    char* _endptr = NULL;",
                f"{indent}    errno = 0;",
                f"{indent}    int64_t _k_val = strtoll(_k_str, &_endptr, 10);",
                f"{indent}    if (errno != 0 || _endptr == _k_str || *_endptr != '\\0') return false;",
            ])
            key_access = "_k_val"
        else:
            code.extend([
                f"{indent}    char* _k_val = (char*)malloc(strlen(_k_str) + 1);",
                f"{indent}    strcpy(_k_val, _k_str);",
            ])
            key_access = "_k_val"
        code.extend(v_code)
        code.append(f"{indent}    _meme_map_{m_k}_{m_v}_set(&{temp_map}, {key_access}, {v_val});")
        code.append(f"{indent}}}")
        return temp_map, code
    if records is not None and ftype in records:
        r_ident = _c_ident(ftype)
        temp_val = f"_rec_{abs(hash(ftype + jv_ptr)) % 1000000}"
        code = [
            f"{indent}if (!{jv_ptr} || {jv_ptr}->kind != _MEME_J_OBJ) return false;",
            f"{indent}{r_ident} {temp_val};",
            f"{indent}if (!_meme_parse_record_{r_ident}({jv_ptr}, &{temp_val})) return false;",
        ]
        return temp_val, code
    return jv_ptr, []


def _c_json_serialize_val(val_expr: str, ftype: str, indent: str, records: set[str] | None = None) -> list[str]:
    if ftype == "Int":
        return [
            f"{indent}{{",
            f"{indent}    char buf[32];",
            f"{indent}    snprintf(buf, sizeof(buf), \"%lld\", (long long)({val_expr}));",
            f"{indent}    _meme_sb_append(&sb, buf);",
            f"{indent}}}",
        ]
    if ftype == "Float":
        return [
            f"{indent}{{",
            f"{indent}    char* f_str = _meme_format_json_float({val_expr});",
            f"{indent}    _meme_sb_append(&sb, f_str);",
            f"{indent}    free(f_str);",
            f"{indent}}}",
        ]
    if ftype == "String":
        return [
            f"{indent}{{",
            f"{indent}    char* s_str = _meme_escape_json_str({val_expr});",
            f"{indent}    _meme_sb_append(&sb, s_str);",
            f"{indent}    free(s_str);",
            f"{indent}}}",
        ]
    if ftype == "Bool":
        return [
            f"{indent}_meme_sb_append(&sb, ({val_expr}) ? \"true\" : \"false\");",
        ]
    if ftype.startswith("Optional<") and ftype.endswith(">"):
        inner = ftype[9:-1]
        inner_val = f"*({val_expr}).value" if (records and inner in records) else f"({val_expr}).value"
        inner_code = _c_json_serialize_val(inner_val, inner, indent + "    ", records)
        return [
            f"{indent}if (!({val_expr}).present) {{",
            f"{indent}    _meme_sb_append(&sb, \"null\");",
            f"{indent}}} else {{",
            *inner_code,
            f"{indent}}}",
        ]
    if ftype.startswith("List<") and ftype.endswith(">"):
        el_t = ftype[5:-1]
        temp_i = f"_i_{abs(hash(ftype + val_expr)) % 1000000}"
        el_code = _c_json_serialize_val(f"({val_expr}).data[{temp_i}]", el_t, indent + "        ", records)
        return [
            f"{indent}{{",
            f"{indent}    _meme_sb_append_char(&sb, '[');",
            f"{indent}    for (int64_t {temp_i} = 0; {temp_i} < ({val_expr}).len; ++{temp_i}) {{",
            f"{indent}        if ({temp_i} > 0) _meme_sb_append_char(&sb, ',');",
            *el_code,
            f"{indent}    }}",
            f"{indent}    _meme_sb_append_char(&sb, ']');",
            f"{indent}}}",
        ]
    if ftype.startswith("Set<") and ftype.endswith(">"):
        el_t = ftype[4:-1]
        temp_i = f"_i_{abs(hash(ftype + val_expr)) % 1000000}"
        el_code = _c_json_serialize_val(f"({val_expr}).data[{temp_i}]", el_t, indent + "        ", records)
        return [
            f"{indent}{{",
            f"{indent}    _meme_sb_append_char(&sb, '[');",
            f"{indent}    for (int64_t {temp_i} = 0; {temp_i} < ({val_expr}).len; ++{temp_i}) {{",
            f"{indent}        if ({temp_i} > 0) _meme_sb_append_char(&sb, ',');",
            *el_code,
            f"{indent}    }}",
            f"{indent}    _meme_sb_append_char(&sb, ']');",
            f"{indent}}}",
        ]
    if ftype.startswith("Map<") and ftype.endswith(">"):
        mt = _map_types_of(ftype)
        assert mt is not None
        k_t, v_t = mt
        temp_i = f"_i_{abs(hash(ftype + val_expr)) % 1000000}"
        v_code = _c_json_serialize_val(f"({val_expr}).data[{temp_i}].value", v_t, indent + "        ", records)
        lines = [
            f"{indent}{{",
            f"{indent}    _meme_sb_append_char(&sb, '{{');",
            f"{indent}    for (int64_t {temp_i} = 0; {temp_i} < ({val_expr}).len; ++{temp_i}) {{",
            f"{indent}        if ({temp_i} > 0) _meme_sb_append_char(&sb, ',');",
        ]
        if k_t == "Int":
            lines.extend([
                f"{indent}        char _kbuf[32];",
                f"{indent}        snprintf(_kbuf, sizeof(_kbuf), \"\\\"%lld\\\"\", (long long)({val_expr}).data[{temp_i}].key);",
                f"{indent}        _meme_sb_append(&sb, _kbuf);",
            ])
        else:
            lines.extend([
                f"{indent}        char* _k_esc = _meme_escape_json_str(({val_expr}).data[{temp_i}].key);",
                f"{indent}        _meme_sb_append(&sb, _k_esc);",
                f"{indent}        free(_k_esc);",
            ])
        lines.extend([
            f"{indent}        _meme_sb_append_char(&sb, ':');",
            *v_code,
            f"{indent}    }}",
            f"{indent}    _meme_sb_append_char(&sb, '}}');",
            f"{indent}}}",
        ])
        return lines
    if records is not None and ftype in records:
        r_ident = _c_ident(ftype)
        temp_s = f"_s_{abs(hash(ftype + val_expr)) % 1000000}"
        return [
            f"{indent}char* {temp_s} = _meme_serialize_json_record_{r_ident}({val_expr});",
            f"{indent}_meme_sb_append(&sb, {temp_s});",
            f"{indent}free({temp_s});",
        ]
    return [f"{indent}_meme_sb_append(&sb, \"null\");"]


def _emit_c_json_record_reader(r_name: str, fields: dict[str, MemeType], records: set[str] | None = None) -> list[str]:
    ident = _c_ident(r_name)
    lines = [
        f"static inline bool _meme_parse_record_{ident}(const _MemeJV* _jv, {ident}* _out) {{",
        "    if (!_jv || _jv->kind != _MEME_J_OBJ) return false;",
    ]
    for fname, ftype in fields.items():
        fn_str = json.dumps(fname)
        f_ident = _c_ident(fname)
        lines.append(f"    const _MemeJV* _f_{fname} = _meme_jv_find_field(_jv, {fn_str});")
        if ftype.startswith("Optional<"):
            inner = ftype[9:-1]
            m_inner = _mangle_type(inner)
            dec_val, dec_code = _c_json_decode_val(f"_f_{fname}", inner, "        ", records)
            lines.extend([
                f"    if (!_f_{fname} || _f_{fname}->kind == _MEME_J_NULL) {{",
                f"        _out->{f_ident} = (meme_opt_{m_inner}){{0}};",
                "    } else {",
                *dec_code,
                f"        _out->{f_ident} = _meme_opt_{m_inner}_some({dec_val});",
                "    }",
            ])
        else:
            dec_val, dec_code = _c_json_decode_val(f"_f_{fname}", ftype, "    ", records)
            lines.extend(dec_code)
            lines.append(f"    _out->{f_ident} = {dec_val};")

    lines.append("    return true;")
    lines.append("}")
    lines.append("")
    lines.extend([
        f"static inline meme_opt_{ident} _meme_read_json_record_{ident}(const char* path) {{",
        "    _MemeJV* root = _meme_read_json_file(path);",
        f"    if (!root) return (meme_opt_{ident}){{0}};",
        f"    {ident} rec;",
        f"    bool ok = _meme_parse_record_{ident}(root, &rec);",
        "    _meme_free_jv(root);",
        f"    if (!ok) return (meme_opt_{ident}){{0}};",
        f"    return _meme_opt_{ident}_some(rec);",
        "}",
        "",
        f"static inline {ident} _meme_read_json_record_{ident}_or(const char* path, {ident} dflt) {{",
        f"    meme_opt_{ident} o = _meme_read_json_record_{ident}(path);",
        "    return o.present ? *o.value : dflt;",
        "}",
        "",
        f"static inline meme_opt_List_{ident} _meme_read_json_records_{ident}(const char* path) {{",
        "    _MemeJV* root = _meme_read_json_file(path);",
        f"    if (!root || root->kind != _MEME_J_ARR) {{",
        "        _meme_free_jv(root);",
        f"        return (meme_opt_List_{ident}){{0}};",
        "    }",
        f"    meme_list_{ident} list = _meme_list_{ident}_new();",
        "    for (size_t i = 0; i < root->arr_len; ++i) {",
        f"        {ident} rec;",
        f"        if (!_meme_parse_record_{ident}(root->arr[i], &rec)) {{",
        "            _meme_free_jv(root);",
        f"            return (meme_opt_List_{ident}){{0}};",
        "        }",
        f"        _meme_list_{ident}_append(&list, rec);",
        "    }",
        "    _meme_free_jv(root);",
        f"    return (meme_opt_List_{ident}){{ .present = true, .value = list }};",
        "}",
        "",
        f"static inline meme_list_{ident} _meme_read_json_records_{ident}_or(const char* path, meme_list_{ident} dflt) {{",
        f"    meme_opt_List_{ident} o = _meme_read_json_records_{ident}(path);",
        "    return o.present ? o.value : dflt;",
        "}",
        "",
    ])
    return lines


def _emit_c_json_record_writer(r_name: str, fields: dict[str, MemeType], records: set[str] | None = None) -> list[str]:
    ident = _c_ident(r_name)
    lines = [
        f"static inline char* _meme_serialize_json_record_{ident}({ident} rec) {{",
        "    _MemeSB sb = _meme_sb_new();",
        "    _meme_sb_append_char(&sb, '{');",
    ]
    for idx, (fname, ftype) in enumerate(fields.items()):
        fn_str = json.dumps(fname) + ":"
        f_ident = _c_ident(fname)
        if idx > 0:
            lines.append("    _meme_sb_append_char(&sb, ',');")
        lines.append(f"    _meme_sb_append(&sb, {json.dumps(fn_str)});")
        lines.extend(_c_json_serialize_val(f"rec.{f_ident}", ftype, "    ", records))
    lines.extend([
        "    _meme_sb_append_char(&sb, '}');",
        "    return sb.data;",
        "}",
        "",
        f"static inline char* _meme_serialize_json_records_{ident}(meme_list_{ident} recs) {{",
        "    _MemeSB sb = _meme_sb_new();",
        "    _meme_sb_append_char(&sb, '[');",
        "    for (int64_t i = 0; i < recs.len; ++i) {",
        "        if (i > 0) _meme_sb_append_char(&sb, ',');",
        f"        char* s = _meme_serialize_json_record_{ident}(recs.data[i]);",
        "        _meme_sb_append(&sb, s);",
        "        free(s);",
        "    }",
        "    _meme_sb_append_char(&sb, ']');",
        "    return sb.data;",
        "}",
        "",
    ])
    return lines


def generate_c(ir: ProgramIR) -> str:
    gen = _CGen()
    records: list[RecordDefStmt] = []
    funcs: list[FuncDefStmt] = []
    test_blocks: list[TestBlockStmt] = []
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
        elif isinstance(stmt, TestBlockStmt):
            test_blocks.append(stmt)
        else:
            main_stmts.append(stmt)

    # Collect all types used across the entire IR
    used_types: set[str] = set()
    for stmt in all_stmts:
        _collect_types_from_stmt(stmt, used_types)

    for r_name in gen.records:
        used_types.add(r_name)
        used_types.add(f"Optional<{r_name}>")
        used_types.add(f"List<{r_name}>")
        used_types.add(f"Optional<List<{r_name}>>")

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
            set_t = _set_types_of(t)
            if set_t is not None:
                used_types.add(set_t)
            if t in gen.records:
                for f_type in gen.records[t].values():
                    used_types.add(f_type)
        expanded = len(used_types) > prev_len

    # Identify distinct lists, maps, optionals
    list_elem_types: list[str] = ["Int", "Float", "String", "Bool"]
    map_types: list[tuple[str, str]] = []
    opt_types: list[str] = []
    set_elem_types: list[str] = []

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
        set_t = _set_types_of(t)
        if set_t is not None and set_t not in set_elem_types:
            set_elem_types.append(set_t)

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
        "#include <dirent.h>",
        "#include <unistd.h>",
        "#include <time.h>",
        "",
    ]

    # Forward typedefs for records so containers can reference them
    sorted_records = _sort_records_by_deps(records)
    record_fwd_decls: list[str] = []
    for r in sorted_records:
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
        "static inline char* _meme_format_float(double v, int64_t n) {",
        "    bool neg = (v < 0.0);",
        "    double mag = fabs(v);",
        "    if (n == 0) {",
        "        double r = floor(mag + 0.5);",
        "        if (r == 0.0) neg = false;",
        "        char* buf = (char*)malloc(64);",
        "        if (neg) snprintf(buf, 64, \"-%.0f\", r);",
        "        else snprintf(buf, 64, \"%.0f\", r);",
        "        return buf;",
        "    }",
        "    double factor = pow(10.0, (double)n);",
        "    double rounded_total = floor(mag * factor + 0.5);",
        "    double int_part = floor(rounded_total / factor);",
        "    uint64_t frac_part = (uint64_t)(rounded_total - int_part * factor + 0.5);",
        "    if (int_part == 0.0 && frac_part == 0) neg = false;",
        "    char* buf = (char*)malloc(128);",
        "    if (neg) snprintf(buf, 128, \"-%.0f.%0*llu\", int_part, (int)n, (unsigned long long)frac_part);",
        "    else snprintf(buf, 128, \"%.0f.%0*llu\", int_part, (int)n, (unsigned long long)frac_part);",
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
        "static inline int64_t _meme_number_of(const char* s) {",
        "    if (s == NULL || s[0] == '\\0') {",
        "        printf(\"Error: empty string in number of\\n\");",
        "        exit(1);",
        "    }",
        "    const unsigned char* p = (const unsigned char*)s;",
        "    unsigned char c = p[0];",
        "    if (c < 0x80) return (int64_t)c;",
        "    if ((c & 0xE0) == 0xC0 && p[1] != '\\0') {",
        "        return (int64_t)(((c & 0x1F) << 6) | (p[1] & 0x3F));",
        "    }",
        "    if ((c & 0xF0) == 0xE0 && p[1] != '\\0' && p[2] != '\\0') {",
        "        return (int64_t)(((c & 0x0F) << 12) | ((p[1] & 0x3F) << 6) | (p[2] & 0x3F));",
        "    }",
        "    if ((c & 0xF8) == 0xF0 && p[1] != '\\0' && p[2] != '\\0' && p[3] != '\\0') {",
        "        return (int64_t)(((c & 0x07) << 18) | ((p[1] & 0x3F) << 12) | ((p[2] & 0x3F) << 6) | (p[3] & 0x3F));",
        "    }",
        "    return (int64_t)c;",
        "}",
        "static inline const char* _meme_character_of(int64_t cp) {",
        "    if (cp < 0 || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {",
        "        printf(\"Error: invalid codepoint %lld\\n\", (long long)cp);",
        "        exit(1);",
        "    }",
        "    char* buf = (char*)malloc(5);",
        "    if (buf == NULL) { exit(1); }",
        "    if (cp <= 0x7F) {",
        "        buf[0] = (char)cp;",
        "        buf[1] = '\\0';",
        "    } else if (cp <= 0x7FF) {",
        "        buf[0] = (char)(0xC0 | (cp >> 6));",
        "        buf[1] = (char)(0x80 | (cp & 0x3F));",
        "        buf[2] = '\\0';",
        "    } else if (cp <= 0xFFFF) {",
        "        buf[0] = (char)(0xE0 | (cp >> 12));",
        "        buf[1] = (char)(0x80 | ((cp >> 6) & 0x3F));",
        "        buf[2] = (char)(0x80 | (cp & 0x3F));",
        "        buf[3] = '\\0';",
        "    } else {",
        "        buf[0] = (char)(0xF0 | (cp >> 18));",
        "        buf[1] = (char)(0x80 | ((cp >> 12) & 0x3F));",
        "        buf[2] = (char)(0x80 | ((cp >> 6) & 0x3F));",
        "        buf[3] = (char)(0x80 | (cp & 0x3F));",
        "        buf[4] = '\\0';",
        "    }",
        "    return buf;",
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
        "static inline uint32_t _meme_ror32(uint32_t x, uint32_t n) {",
        "    return (x >> n) | (x << (32 - n));",
        "}",
        "static inline const char* _meme_sha256(const char* s) {",
        "    if (!s) s = \"\";",
        "    size_t s_len = strlen(s);",
        "    uint64_t bit_len = (uint64_t)s_len * 8;",
        "    size_t padded_len = s_len + 1;",
        "    while ((padded_len % 64) != 56) padded_len++;",
        "    padded_len += 8;",
        "    uint8_t* data = (uint8_t*)calloc(padded_len, 1);",
        "    if (!data) exit(1);",
        "    memcpy(data, s, s_len);",
        "    data[s_len] = 0x80;",
        "    for (int i = 7; i >= 0; --i) {",
        "        data[padded_len - 8 + (7 - i)] = (uint8_t)((bit_len >> (i * 8)) & 0xff);",
        "    }",
        "    uint64_t primes[64];",
        "    size_t p_count = 0;",
        "    uint64_t cand = 2;",
        "    while (p_count < 64) {",
        "        int is_p = 1;",
        "        for (size_t i = 0; i < p_count; ++i) {",
        "            if (cand % primes[i] == 0) { is_p = 0; break; }",
        "            if (primes[i] * primes[i] > cand) break;",
        "        }",
        "        if (is_p) primes[p_count++] = cand;",
        "        cand++;",
        "    }",
        "    uint32_t h[8];",
        "    for (int i = 0; i < 8; ++i) {",
        "        double f = sqrt((double)primes[i]);",
        "        h[i] = (uint32_t)((f - floor(f)) * 4294967296.0);",
        "    }",
        "    uint32_t k[64];",
        "    for (int i = 0; i < 64; ++i) {",
        "        double f = cbrt((double)primes[i]);",
        "        k[i] = (uint32_t)((f - floor(f)) * 4294967296.0);",
        "    }",
        "    uint32_t w[64];",
        "    for (size_t offset = 0; offset < padded_len; offset += 64) {",
        "        const uint8_t* chunk = &data[offset];",
        "        for (int i = 0; i < 16; ++i) {",
        "            w[i] = ((uint32_t)chunk[4*i] << 24) | ((uint32_t)chunk[4*i+1] << 16) | ((uint32_t)chunk[4*i+2] << 8) | (uint32_t)chunk[4*i+3];",
        "        }",
        "        for (int i = 16; i < 64; ++i) {",
        "            uint32_t s0 = _meme_ror32(w[i - 15], 7) ^ _meme_ror32(w[i - 15], 18) ^ (w[i - 15] >> 3);",
        "            uint32_t s1 = _meme_ror32(w[i - 2], 17) ^ _meme_ror32(w[i - 2], 19) ^ (w[i - 2] >> 10);",
        "            w[i] = w[i - 16] + s0 + w[i - 7] + s1;",
        "        }",
        "        uint32_t a = h[0], b = h[1], c = h[2], d = h[3];",
        "        uint32_t e = h[4], f = h[5], g = h[6], hh = h[7];",
        "        for (int i = 0; i < 64; ++i) {",
        "            uint32_t s1 = _meme_ror32(e, 6) ^ _meme_ror32(e, 11) ^ _meme_ror32(e, 25);",
        "            uint32_t ch = (e & f) ^ ((~e) & g);",
        "            uint32_t t1 = hh + s1 + ch + k[i] + w[i];",
        "            uint32_t s0 = _meme_ror32(a, 2) ^ _meme_ror32(a, 13) ^ _meme_ror32(a, 22);",
        "            uint32_t maj = (a & b) ^ (a & c) ^ (b & c);",
        "            uint32_t t2 = s0 + maj;",
        "            hh = g; g = f; f = e; e = d + t1;",
        "            d = c; c = b; b = a; a = t1 + t2;",
        "        }",
        "        h[0] += a; h[1] += b; h[2] += c; h[3] += d;",
        "        h[4] += e; h[5] += f; h[6] += g; h[7] += hh;",
        "    }",
        "    free(data);",
        "    char* res = (char*)malloc(65);",
        "    if (!res) exit(1);",
        "    for (int i = 0; i < 8; ++i) {",
        "        snprintf(res + (i * 8), 9, \"%08x\", h[i]);",
        "    }",
        "    res[64] = '\\0';",
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
        "static inline void _meme_copy_file(const char* src, const char* dst) {",
        "    const char* rsrc = _meme_resolve_path(src);",
        "    struct stat st;",
        "    if (stat(rsrc, &st) != 0 || !S_ISREG(st.st_mode)) {",
        "        printf(\"Error copying file: %s\\n\", src);",
        "        exit(1);",
        "    }",
        "    FILE* fin = fopen(rsrc, \"rb\");",
        "    if (!fin) {",
        "        printf(\"Error copying file: %s\\n\", src);",
        "        exit(1);",
        "    }",
        "    FILE* fout = fopen(_meme_trim(dst), \"wb\");",
        "    if (!fout) {",
        "        fclose(fin);",
        "        printf(\"Error copying file: %s\\n\", src);",
        "        exit(1);",
        "    }",
        "    char buf[8192];",
        "    size_t n;",
        "    while ((n = fread(buf, 1, sizeof(buf), fin)) > 0) {",
        "        if (fwrite(buf, 1, n, fout) != n) {",
        "            fclose(fin);",
        "            fclose(fout);",
        "            printf(\"Error copying file: %s\\n\", src);",
        "            exit(1);",
        "        }",
        "    }",
        "    fclose(fin);",
        "    fclose(fout);",
        "}",
        "static inline void _meme_move_file(const char* src, const char* dst) {",
        "    const char* rsrc = _meme_resolve_path(src);",
        "    struct stat st;",
        "    if (stat(rsrc, &st) != 0 || !S_ISREG(st.st_mode)) {",
        "        printf(\"Error moving file: %s\\n\", src);",
        "        exit(1);",
        "    }",
        "    const char* target = _meme_trim(dst);",
        "    if (rename(rsrc, target) != 0) {",
        "        _meme_copy_file(src, dst);",
        "        unlink(rsrc);",
        "    }",
        "}",
        "static inline void _meme_rename_file(const char* path, const char* new_name) {",
        "    const char* rsrc = _meme_resolve_path(path);",
        "    struct stat st;",
        "    if (stat(rsrc, &st) != 0 || !S_ISREG(st.st_mode)) {",
        "        printf(\"Error renaming file: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    const char* p = _meme_trim(path);",
        "    const char* nn = _meme_trim(new_name);",
        "    const char* last_slash_nn = strrchr(nn, '/');",
        "    if (last_slash_nn) nn = last_slash_nn + 1;",
        "    const char* last_slash_p = strrchr(p, '/');",
        "    char target[4096];",
        "    if (last_slash_p) {",
        "        size_t dir_len = (size_t)(last_slash_p - p);",
        "        snprintf(target, sizeof(target), \"%.*s/%s\", (int)dir_len, p, nn);",
        "    } else {",
        "        snprintf(target, sizeof(target), \"%s\", nn);",
        "    }",
        "    if (rename(rsrc, target) != 0) {",
        "        _meme_copy_file(path, target);",
        "        unlink(rsrc);",
        "    }",
        "}",
        "static inline void _meme_delete_file(const char* path) {",
        "    const char* rsrc = _meme_resolve_path(path);",
        "    struct stat st;",
        "    if (stat(rsrc, &st) != 0 || !S_ISREG(st.st_mode)) {",
        "        printf(\"Error deleting file: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    if (unlink(rsrc) != 0) {",
        "        printf(\"Error deleting file: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "}",
        "static inline void _meme_create_directory(const char* path) {",
        "    const char* p = _meme_trim(path);",
        "    char tmp[4096];",
        "    snprintf(tmp, sizeof(tmp), \"%s\", p);",
        "    size_t len = strlen(tmp);",
        "    if (len == 0) return;",
        "    if (tmp[len - 1] == '/') tmp[len - 1] = '\\0';",
        "    for (char* s = tmp + 1; *s; s++) {",
        "        if (*s == '/') {",
        "            *s = '\\0';",
        "            mkdir(tmp, 0777);",
        "            *s = '/';",
        "        }",
        "    }",
        "    if (mkdir(tmp, 0777) != 0 && errno != EEXIST) {",
        "        struct stat st;",
        "        if (stat(tmp, &st) != 0 || !S_ISDIR(st.st_mode)) {",
        "            printf(\"Error creating directory: %s\\n\", path);",
        "            exit(1);",
        "        }",
        "    }",
        "}",
        "",
    ]

    # File container helpers
    file_container_helpers = [
        "static inline int _meme_strcmp_qsort(const void* a, const void* b) {",
        "    const char* const* sa = (const char* const*)a;",
        "    const char* const* sb = (const char* const*)b;",
        "    return strcmp(*sa, *sb);",
        "}",
        "static inline meme_list_String _meme_list_files(const char* path) {",
        "    const char* rpath = _meme_resolve_path(path);",
        "    struct stat st;",
        "    if (stat(rpath, &st) != 0 || !S_ISDIR(st.st_mode)) {",
        "        printf(\"Error listing directory: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    DIR* d = opendir(rpath);",
        "    if (!d) {",
        "        printf(\"Error listing directory: %s\\n\", path);",
        "        exit(1);",
        "    }",
        "    meme_list_String res = _meme_list_String_new();",
        "    struct dirent* ent;",
        "    while ((ent = readdir(d)) != NULL) {",
        "        if (strcmp(ent->d_name, \".\") == 0 || strcmp(ent->d_name, \"..\") == 0) continue;",
        "        size_t elen = strlen(ent->d_name);",
        "        char* item = (char*)malloc(elen + 1);",
        "        memcpy(item, ent->d_name, elen + 1);",
        "        _meme_list_String_append(&res, item);",
        "    }",
        "    closedir(d);",
        "    if (res.len > 1) {",
        "        qsort(res.data, (size_t)res.len, sizeof(const char*), _meme_strcmp_qsort);",
        "    }",
        "    return res;",
        "}",
        "static inline meme_list_String _meme_read_file_lines(const char* path) {",
        "    const char* raw = _meme_read_file_string(path);",
        "    meme_list_String res = _meme_list_String_new();",
        "    if (!raw || strlen(raw) == 0) {",
        "        return res;",
        "    }",
        "    size_t len = strlen(raw);",
        "    if (len > 0 && raw[len - 1] == '\\n') {",
        "        len--;",
        "    }",
        "    const char* p = raw;",
        "    const char* end = raw + len;",
        "    while (p <= end) {",
        "        const char* next_nl = (const char*)memchr(p, '\\n', (size_t)(end - p));",
        "        size_t part_len = next_nl ? (size_t)(next_nl - p) : (size_t)(end - p);",
        "        char* part = (char*)malloc(part_len + 1);",
        "        memcpy(part, p, part_len);",
        "        part[part_len] = '\\0';",
        "        _meme_list_String_append(&res, part);",
        "        if (!next_nl) break;",
        "        p = next_nl + 1;",
        "    }",
        "    return res;",
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
        "static inline bool _meme_try_parse_int(const char* s, int64_t* out) {",
        "    if (!s) return false;",
        "    const char* ts = _meme_trim(s);",
        "    if (!ts || !*ts) return false;",
        "    char* end = NULL;",
        "    errno = 0;",
        "    long long v = strtoll(ts, &end, 10);",
        "    if (errno != 0 || end == ts || *end != '\\0') return false;",
        "    *out = (int64_t)v;",
        "    return true;",
        "}",
        "static inline bool _meme_is_digit(const char* s) {",
        "    return (s != NULL && strlen(s) == 1 && s[0] >= '0' && s[0] <= '9');",
        "}",
        "static inline bool _meme_is_letter(const char* s) {",
        "    return (s != NULL && strlen(s) == 1 && ((s[0] >= 'A' && s[0] <= 'Z') || (s[0] >= 'a' && s[0] <= 'z')));",
        "}",
        "static inline bool _meme_is_upper(const char* s) {",
        "    return (s != NULL && strlen(s) == 1 && s[0] >= 'A' && s[0] <= 'Z');",
        "}",
        "static inline bool _meme_is_lower(const char* s) {",
        "    return (s != NULL && strlen(s) == 1 && s[0] >= 'a' && s[0] <= 'z');",
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

        # Struct declarations in dependency order
    struct_decls: list[str] = []

    # Forward declarations for all records
    for r in records:
        r_ident = _c_ident(r.name)
        struct_decls.append(f"typedef struct {r_ident} {r_ident};")
    if records:
        struct_decls.append("")

    for el_t in list_elem_types:
        struct_decls.extend(_emit_list_struct(el_t))
    struct_decls.append("")

    for el_t in set_elem_types:
        struct_decls.extend(_emit_set_struct(el_t))
    struct_decls.append("")

    emitted_maps: set[tuple[str, str]] = set()
    for k_t, v_t in map_types:
        if k_t not in gen.records and v_t not in gen.records:
            struct_decls.extend(_emit_map_struct(k_t, v_t))
            emitted_maps.add((k_t, v_t))
    struct_decls.append("")

    # All optionals (primitives, records, lists, sets, non-record maps)
    emitted_opts: set[str] = set()
    for inner in opt_types:
        if not (inner.startswith("Map<") and any(r in inner for r in gen.records)):
            struct_decls.extend(_emit_opt_struct(inner, gen))
            emitted_opts.add(inner)
    struct_decls.append("")

    # Records in dependency order, emitting map and opt types as dependencies are satisfied
    emitted_records: set[str] = set()
    for r in sorted_records:
        struct_decls.extend(_emit_record_decl(r, gen))
        struct_decls.append("")
        emitted_records.add(r.name)
        for k_t, v_t in map_types:
            if (k_t, v_t) not in emitted_maps:
                k_ok = k_t not in gen.records or k_t in emitted_records
                v_ok = v_t not in gen.records or v_t in emitted_records
                if k_ok and v_ok:
                    struct_decls.extend(_emit_map_struct(k_t, v_t))
                    struct_decls.append("")
                    emitted_maps.add((k_t, v_t))
        for inner in opt_types:
            if inner not in emitted_opts:
                mt = _map_types_of(inner)
                if mt and mt in emitted_maps:
                    struct_decls.extend(_emit_opt_struct(inner, gen))
                    struct_decls.append("")
                    emitted_opts.add(inner)

    # Any remaining maps
    for k_t, v_t in map_types:
        if (k_t, v_t) not in emitted_maps:
            struct_decls.extend(_emit_map_struct(k_t, v_t))
            struct_decls.append("")
            emitted_maps.add((k_t, v_t))

    # Any remaining optionals
    for inner in opt_types:
        if inner not in emitted_opts:
            struct_decls.extend(_emit_opt_struct(inner, gen))
            struct_decls.append("")
            emitted_opts.add(inner)

    # Prototypes for all container & record helpers
    all_protos: list[str] = []
    for el_t in list_elem_types:
        all_protos.extend(_emit_list_proto(el_t, gen))
    for el_t in set_elem_types:
        all_protos.extend(_emit_set_proto(el_t, gen))
    for k_t, v_t in map_types:
        all_protos.extend(_emit_map_proto(k_t, v_t, gen))
    for inner in opt_types:
        all_protos.extend(_emit_opt_proto(inner, gen))
    for r in sorted_records:
        all_protos.extend(_emit_record_proto(r, gen))
    if all_protos:
        all_protos.append("")

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

    # Helper function bodies
    helper_bodies: list[str] = []
    for el_t in list_elem_types:
        helper_bodies.extend(_emit_list_body(el_t, gen))
        helper_bodies.append("")
    for el_t in set_elem_types:
        helper_bodies.extend(_emit_set_body(el_t, gen))
        helper_bodies.append("")
    for k_t, v_t in map_types:
        helper_bodies.extend(_emit_map_body(k_t, v_t, gen))
        helper_bodies.append("")
    for inner in opt_types:
        helper_bodies.extend(_emit_opt_body(inner, gen))
        helper_bodies.append("")
    for r in sorted_records:
        helper_bodies.extend(_emit_record_body(r, gen))
        helper_bodies.append("")

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
        "int main(int meme_argc, char** meme_argv) {",
        "    _meme_argc = meme_argc;",
        "    _meme_argv = meme_argv;",
    ]
    if test_blocks:
        main_lines.append("    if (meme_argc > 2 && strcmp(meme_argv[1], \"--meme-test\") == 0) {")
        for idx, tb in enumerate(test_blocks):
            pfx = "if" if idx == 0 else "else if"
            main_lines.append(f"        {pfx} (strcmp(meme_argv[2], {json.dumps(tb.name)}) == 0) {{")
            tb_scope = dict(main_scope)
            for s in tb.body:
                main_lines.extend(gen.gen_stmt(s, tb_scope, indent=3))
            main_lines.append("            return 0;")
            main_lines.append("        }")
        main_lines.append("        else {")
        main_lines.append("            fprintf(stderr, \"Unknown test block: %s\\n\", meme_argv[2]);")
        main_lines.append("            exit(1);")
        main_lines.append("        }")
        main_lines.append("    }")
    for stmt in main_stmts:
        main_lines.extend(gen.gen_stmt(stmt, main_scope, indent=1))
    main_lines.append("    return 0;")
    main_lines.append("}")
    main_lines.append("")

    json_record_helpers: list[str] = []
    record_readers: list[str] = []
    all_read_records = _get_transitive_json_records(
        gen.json_records_read | gen.json_record_lists_read,
        gen.records,
    )
    if gen.uses_json_records or gen.uses_json_list_opt or all_read_records:
        json_record_helpers.extend(_C_JSON_PARSER_HELPERS)
    if all_read_records:
        for r_name in sorted(all_read_records):
            r_ident = _c_ident(r_name)
            record_readers.append(f"static inline bool _meme_parse_record_{r_ident}(const _MemeJV* _jv, {r_ident}* _out);")
        record_readers.append("")
        for r_name in sorted(all_read_records):
            r_fields = gen.records.get(r_name, {})
            record_readers.extend(_emit_c_json_record_reader(r_name, r_fields, set(gen.records.keys())))
            record_readers.append("")

    record_writers: list[str] = []
    all_write_records = _get_transitive_json_records(
        gen.json_records_write,
        gen.records,
    )
    if gen.uses_json_write or all_write_records:
        record_writers.extend([
            "static inline char* _meme_format_json_float(double v) {",
            "    char* s = _meme_format_float(v, 6);",
            "    char* dot = strchr(s, '.');",
            "    if (dot) {",
            "        size_t len = strlen(s);",
            "        while (len > 0 && s[len - 1] == '0') {",
            "            s[len - 1] = '\\0';",
            "            len--;",
            "        }",
            "        if (len > 0 && s[len - 1] == '.') {",
            "            s[len] = '0';",
            "            s[len + 1] = '\\0';",
            "        }",
            "    }",
            "    return s;",
            "}",
            "",
            "static inline char* _meme_escape_json_str(const char* s) {",
            "    if (!s) s = \"\";",
            "    size_t len = strlen(s);",
            "    char* buf = (char*)malloc(len * 6 + 3);",
            "    char* p = buf;",
            "    *p++ = '\"';",
            "    for (size_t i = 0; i < len; i++) {",
            "        unsigned char c = (unsigned char)s[i];",
            "        if (c == '\"') { *p++ = '\\\\'; *p++ = '\"'; }",
            "        else if (c == '\\\\') { *p++ = '\\\\'; *p++ = '\\\\'; }",
            "        else if (c == '\\n') { *p++ = '\\\\'; *p++ = 'n'; }",
            "        else if (c == '\\r') { *p++ = '\\\\'; *p++ = 'r'; }",
            "        else if (c == '\\t') { *p++ = '\\\\'; *p++ = 't'; }",
            "        else if (c < 0x20) {",
            "            p += sprintf(p, \"\\\\u%04x\", c);",
            "        } else {",
            "            *p++ = c;",
            "        }",
            "    }",
            "    *p++ = '\"';",
            "    *p = '\\0';",
            "    return buf;",
            "}",
            "",
        ])
        for r_name in sorted(all_write_records):
            r_ident = _c_ident(r_name)
            record_writers.append(f"static inline char* _meme_serialize_json_record_{r_ident}({r_ident} rec);")
        record_writers.append("")
        for r_name in sorted(all_write_records):
            r_fields = gen.records.get(r_name, {})
            record_writers.extend(_emit_c_json_record_writer(r_name, r_fields, set(gen.records.keys())))
            record_writers.append("")

    env_helpers: list[str] = []
    if gen.uses_env:
        env_helpers.extend([
            "static inline meme_opt_String _meme_env_var(const char* name) {",
            "    const char* val = getenv(name);",
            "    if (val != NULL) {",
            "        return (meme_opt_String){ .present = true, .value = val };",
            "    }",
            "    return (meme_opt_String){0};",
            "}",
            "",
        ])
    if gen.uses_env_or:
        env_helpers.extend([
            "static inline const char* _meme_env_var_or(const char* name, const char* fallback) {",
            "    const char* val = getenv(name);",
            "    return val != NULL ? val : fallback;",
            "}",
            "",
        ])

    opt_file_helpers: list[str] = []
    if gen.uses_read_file_string_opt:
        opt_file_helpers.extend([
            "static inline meme_opt_String _meme_read_file_string_opt(const char* path) {",
            "    const char* rp = _meme_resolve_path(path);",
            "    struct stat st;",
            "    if (stat(rp, &st) != 0 || !S_ISREG(st.st_mode)) return (meme_opt_String){0};",
            "    FILE* f = fopen(rp, \"rb\");",
            "    if (!f) return (meme_opt_String){0};",
            "    size_t sz = (size_t)st.st_size;",
            "    char* buf = (char*)malloc(sz + 1);",
            "    size_t n = fread(buf, 1, sz, f);",
            "    fclose(f);",
            "    buf[n] = '\\0';",
            "    return (meme_opt_String){ .present = true, .value = buf };",
            "}",
            "",
            "static inline const char* _meme_read_file_string_or(const char* path, const char* dflt) {",
            "    meme_opt_String o = _meme_read_file_string_opt(path);",
            "    return o.present ? o.value : dflt;",
            "}",
            "",
        ])

    if gen.uses_read_file_lines_opt:
        opt_file_helpers.extend([
            "static inline meme_opt_List_String _meme_read_file_lines_opt(const char* path) {",
            "    meme_opt_String o = _meme_read_file_string_opt(path);",
            "    if (!o.present) return (meme_opt_List_String){0};",
            "    const char* raw = o.value;",
            "    meme_list_String res = _meme_list_String_new();",
            "    if (!raw || strlen(raw) == 0) return (meme_opt_List_String){ .present = true, .value = res };",
            "    size_t len = strlen(raw);",
            "    if (len > 0 && raw[len - 1] == '\\n') len--;",
            "    const char* p = raw;",
            "    const char* end = raw + len;",
            "    while (p <= end) {",
            "        const char* next_nl = (const char*)memchr(p, '\\n', (size_t)(end - p));",
            "        size_t part_len = next_nl ? (size_t)(next_nl - p) : (size_t)(end - p);",
            "        char* part = (char*)malloc(part_len + 1);",
            "        memcpy(part, p, part_len);",
            "        part[part_len] = '\\0';",
            "        _meme_list_String_append(&res, part);",
            "        if (!next_nl) break;",
            "        p = next_nl + 1;",
            "    }",
            "    return (meme_opt_List_String){ .present = true, .value = res };",
            "}",
            "",
            "static inline meme_list_String _meme_read_file_lines_or(const char* path, meme_list_String dflt) {",
            "    meme_opt_List_String o = _meme_read_file_lines_opt(path);",
            "    return o.present ? o.value : dflt;",
            "}",
            "",
        ])

    for el in sorted(gen.json_list_opt_types):
        if el == "int":
            opt_file_helpers.extend([
                "static inline meme_opt_List_Int _meme_read_json_list_int_opt(const char* path) {",
                "    _MemeJV* root = _meme_read_json_file(path);",
                "    if (!root || root->kind != _MEME_J_ARR) {",
                "        _meme_free_jv(root);",
                "        return (meme_opt_List_Int){0};",
                "    }",
                "    meme_list_Int list = _meme_list_Int_new();",
                "    for (size_t i = 0; i < root->arr_len; ++i) {",
                "        _MemeJV* it = root->arr[i];",
                "        if (!it || it->kind != _MEME_J_NUM || !it->is_int) {",
                "            _meme_free_jv(root);",
                "            return (meme_opt_List_Int){0};",
                "        }",
                "        _meme_list_Int_append(&list, it->i_val);",
                "    }",
                "    _meme_free_jv(root);",
                "    return (meme_opt_List_Int){ .present = true, .value = list };",
                "}",
                "",
                "static inline meme_list_Int _meme_read_json_list_int_or(const char* path, meme_list_Int dflt) {",
                "    meme_opt_List_Int o = _meme_read_json_list_int_opt(path);",
                "    return o.present ? o.value : dflt;",
                "}",
                "",
            ])
        elif el == "float":
            opt_file_helpers.extend([
                "static inline meme_opt_List_Float _meme_read_json_list_float_opt(const char* path) {",
                "    _MemeJV* root = _meme_read_json_file(path);",
                "    if (!root || root->kind != _MEME_J_ARR) {",
                "        _meme_free_jv(root);",
                "        return (meme_opt_List_Float){0};",
                "    }",
                "    meme_list_Float list = _meme_list_Float_new();",
                "    for (size_t i = 0; i < root->arr_len; ++i) {",
                "        _MemeJV* it = root->arr[i];",
                "        if (!it || it->kind != _MEME_J_NUM) {",
                "            _meme_free_jv(root);",
                "            return (meme_opt_List_Float){0};",
                "        }",
                "        _meme_list_Float_append(&list, it->num);",
                "    }",
                "    _meme_free_jv(root);",
                "    return (meme_opt_List_Float){ .present = true, .value = list };",
                "}",
                "",
                "static inline meme_list_Float _meme_read_json_list_float_or(const char* path, meme_list_Float dflt) {",
                "    meme_opt_List_Float o = _meme_read_json_list_float_opt(path);",
                "    return o.present ? o.value : dflt;",
                "}",
                "",
            ])
        elif el == "string":
            opt_file_helpers.extend([
                "static inline meme_opt_List_String _meme_read_json_list_string_opt(const char* path) {",
                "    _MemeJV* root = _meme_read_json_file(path);",
                "    if (!root || root->kind != _MEME_J_ARR) {",
                "        _meme_free_jv(root);",
                "        return (meme_opt_List_String){0};",
                "    }",
                "    meme_list_String list = _meme_list_String_new();",
                "    for (size_t i = 0; i < root->arr_len; ++i) {",
                "        _MemeJV* it = root->arr[i];",
                "        if (!it || it->kind != _MEME_J_STR) {",
                "            _meme_free_jv(root);",
                "            return (meme_opt_List_String){0};",
                "        }",
                "        char* s = (char*)malloc(strlen(it->str) + 1);",
                "        strcpy(s, it->str);",
                "        _meme_list_String_append(&list, s);",
                "    }",
                "    _meme_free_jv(root);",
                "    return (meme_opt_List_String){ .present = true, .value = list };",
                "}",
                "",
                "static inline meme_list_String _meme_read_json_list_string_or(const char* path, meme_list_String dflt) {",
                "    meme_opt_List_String o = _meme_read_json_list_string_opt(path);",
                "    return o.present ? o.value : dflt;",
                "}",
                "",
            ])
        elif el == "bool":
            opt_file_helpers.extend([
                "static inline meme_opt_List_Bool _meme_read_json_list_bool_opt(const char* path) {",
                "    _MemeJV* root = _meme_read_json_file(path);",
                "    if (!root || root->kind != _MEME_J_ARR) {",
                "        _meme_free_jv(root);",
                "        return (meme_opt_List_Bool){0};",
                "    }",
                "    meme_list_Bool list = _meme_list_Bool_new();",
                "    for (size_t i = 0; i < root->arr_len; ++i) {",
                "        _MemeJV* it = root->arr[i];",
                "        if (!it || it->kind != _MEME_J_BOOL) {",
                "            _meme_free_jv(root);",
                "            return (meme_opt_List_Bool){0};",
                "        }",
                "        _meme_list_Bool_append(&list, it->b);",
                "    }",
                "    _meme_free_jv(root);",
                "    return (meme_opt_List_Bool){ .present = true, .value = list };",
                "}",
                "",
                "static inline meme_list_Bool _meme_read_json_list_bool_or(const char* path, meme_list_Bool dflt) {",
                "    meme_opt_List_Bool o = _meme_read_json_list_bool_opt(path);",
                "    return o.present ? o.value : dflt;",
                "}",
                "",
            ])

    out = (
        headers
        + record_fwd_decls
        + runtime_helpers
        + str_helpers
        + file_helpers
        + json_record_helpers
        + input_helpers
        + argv_helpers
        + random_helpers
        + json_helpers
        + struct_decls
        + all_protos
        + json_readers
        + str_container_helpers
        + file_container_helpers
        + env_helpers
        + helper_bodies
        + record_readers
        + record_writers
        + opt_file_helpers
        + fn_fwd_decls
        + fn_blocks
        + main_lines
    )
    return "\n".join(out)

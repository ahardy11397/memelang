"""Deterministic standalone Rust (`rustc`) code generator for Memelang ProgramIR."""

from __future__ import annotations

import json

from memelang.codegen.base import BaseGen, _get_transitive_json_records, _map_types_of, _set_type_of, escape_str
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
    EmptySetExpr,
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
    RenameFileStmt,
    RecordDefStmt,
    RecordFieldDef,
    RecordFieldExpr,
    RecordFieldInit,
    RecordLiteralExpr,
    RecordSetFieldStmt,
    ReturnStmt,
    SetAddStmt,
    SetContainsExpr,
    SetLengthExpr,
    SetRemoveStmt,
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


_RUST_KEYWORDS = {
    "as", "async", "await", "break", "const", "continue", "crate", "dyn", "else",
    "enum", "extern", "false", "fn", "for", "if", "impl", "in", "let", "loop",
    "match", "mod", "move", "mut", "pub", "ref", "return", "self", "Self",
    "static", "struct", "super", "trait", "true", "type", "unsafe", "use",
    "where", "while", "abstract", "become", "box", "do", "final", "gen", "macro",
    "override", "priv", "try", "typeof", "unsized", "virtual", "yield", "main",
}


def _escape_rust_str(val: str) -> str:
    return escape_str(val, "rust")


def _rust_ident(name: str) -> str:
    return f"meme_{name}" if name in _RUST_KEYWORDS or name.startswith("_meme_") else name


def _is_record_name(name: str, records: set[str] | None = None) -> bool:
    if records is not None:
        return name in records
    return name not in ("Int", "Float", "Bool", "String", "Void") and not any(
        name.startswith(p) for p in ("List<", "Map<", "Set<", "Optional<")
    )


def _rust_type(meme_type: MemeType | str, records: set[str] | None = None) -> str:
    if meme_type.startswith("List<") and meme_type.endswith(">"):
        inner = meme_type[5:-1]
        return f"std::rc::Rc<Vec<{_rust_type(inner, records)}>>"
    if meme_type.startswith("Optional<") and meme_type.endswith(">"):
        inner = meme_type[9:-1]
        return f"Option<{_rust_type(inner, records)}>"
    map_t = _map_types_of(meme_type)
    if map_t is not None:
        return f"std::rc::Rc<_MemeMap<{_rust_type(map_t[0], records)}, {_rust_type(map_t[1], records)}>>"
    set_t = _set_type_of(meme_type)
    if set_t is not None:
        return f"std::rc::Rc<_MemeSet<{_rust_type(set_t, records)}>>"
    mapping = {
        "Int": "i64",
        "Float": "f64",
        "Bool": "bool",
        "String": "String",
        "Void": "()",
    }
    if meme_type in mapping:
        return mapping[meme_type]
    return _rust_ident(meme_type)


class _RustGen(BaseGen):
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_input = False
        self.uses_json_io = False
        self.uses_file_io = False
        self.uses_list_remove = False
        self.uses_argv = False
        self.uses_str_split = False
        self.uses_char_at = False
        self.uses_parse_int = False
        self.uses_parse_int_or_else = False
        self.uses_is_digit = False
        self.uses_is_letter = False
        self.uses_is_upper = False
        self.uses_is_lower = False
        self.uses_format_float = False
        self.uses_number_of = False
        self.uses_character_of = False
        self.uses_sha256 = False
        self.uses_file_io_opt = False
        self.uses_json_list_opt = False
        self.uses_optional_helpers = False
        self.uses_json_records = False
        self.uses_json_write = False
        self.json_records_read: set[str] = set()
        self.json_record_lists_read: set[str] = set()
        self.json_records_write: set[str] = set()
        self._match_counter = 0
        self.func_returns: dict[str, MemeType] = {}
        self.records: dict[str, dict[str, MemeType]] = {}

    def gen_expr(self, expr: IRExpr, scope: dict[str, MemeType]) -> str:
        if isinstance(expr, LiteralExpr):
            if expr.data_type == "Bool":
                return "true" if expr.value else "false"
            if expr.data_type == "Int":
                return f"{expr.value}_i64"
            if expr.data_type == "Float":
                s = repr(float(expr.value))  # type: ignore[arg-type]
                if "." not in s and "e" not in s and "E" not in s:
                    s += ".0"
                return f"{s}_f64"
            if expr.data_type == "String":
                return f"String::from({_escape_rust_str(str(expr.value))})"

        if isinstance(expr, ListLiteralExpr):
            el_rust = _rust_type(expr.element_type)
            if not expr.elements:
                return f"std::rc::Rc::new(Vec::<{el_rust}>::new())"
            inner = ", ".join(self.gen_expr(e, scope) for e in expr.elements)
            return f"std::rc::Rc::new(vec![{inner}])"

        if isinstance(expr, VarRefExpr):
            ident = _rust_ident(expr.name)
            t = scope.get(expr.name, "Int")
            if t == "String" or t.startswith("List<") or t.startswith("Map<") or t.startswith("Set<") or t.startswith("Optional<") or t in self.records:
                return f"{ident}.clone()"
            return ident

        if isinstance(expr, RandomIntExpr):
            self.uses_random = True
            return f"_meme_rand_int({self.gen_expr(expr.min_val, scope)}, {self.gen_expr(expr.max_val, scope)})"

        if isinstance(expr, RandomListExpr):
            self.uses_random = True
            return (
                f"_meme_rand_list({self.gen_expr(expr.count, scope)}, "
                f"{self.gen_expr(expr.min_val, scope)}, {self.gen_expr(expr.max_val, scope)})"
            )

        if isinstance(expr, UnaryOpExpr):
            if expr.op == "not":
                return f"(!{self.gen_expr(expr.operand, scope)})"
            return f"(-{self.gen_expr(expr.operand, scope)})"

        if isinstance(expr, BinaryOpExpr):
            left = self.gen_expr(expr.left, scope)
            right = self.gen_expr(expr.right, scope)
            if expr.op == "+" and self.infer_type(expr.left, scope) == "String":
                return f"format!(\"{{}}{{}}\", {left}, {right})"
            op_map = {"and": "&&", "or": "||"}
            rust_op = op_map.get(expr.op, expr.op)
            return f"({left} {rust_op} {right})"

        if isinstance(expr, ListLengthExpr):
            return f"({self.gen_expr(expr.target, scope)}.len() as i64)"

        if isinstance(expr, ListIndexExpr):
            tgt_t = self.infer_type(expr.target, scope)
            if tgt_t.startswith("Map<"):
                tgt = self.gen_expr(expr.target, scope)
                k = self.gen_expr(expr.index, scope)
                return f"{tgt}.get(&({k})).unwrap().clone()"
            t = self.infer_type(expr, scope)
            base = f"({self.gen_expr(expr.target, scope)})[({self.gen_expr(expr.index, scope)}) as usize]"
            if t == "String" or t.startswith("List<") or t in self.records or t.startswith("Map<") or t.startswith("Set<") or t.startswith("Optional<"):
                return f"{base}.clone()"
            return base

        if isinstance(expr, CallExpr):
            args = ", ".join(self.gen_expr(a, scope) for a in expr.args)
            return f"{_rust_ident(expr.func_name)}({args})"

        if isinstance(expr, ReadInputExpr):
            self.uses_input = True
            raw = f"_meme_read_line({_escape_rust_str(expr.prompt)})"
            if expr.target_type == "Int":
                return f"{raw}.trim().parse::<i64>().unwrap_or(0)"
            if expr.target_type == "Float":
                return f"{raw}.trim().parse::<f64>().unwrap_or(0.0)"
            if expr.target_type == "Bool":
                return f"matches!({raw}.trim().to_lowercase().as_str(), \"true\" | \"1\" | \"yes\")"
            return raw

        if isinstance(expr, StrEndsWithExpr):
            tgt = self.gen_expr(expr.target, scope)
            suf = self.gen_expr(expr.suffix, scope)
            return f"({tgt}.trim().to_lowercase().ends_with(&({suf}.to_lowercase())))"

        if isinstance(expr, StrStartsWithExpr):
            tgt = self.gen_expr(expr.target, scope)
            pre = self.gen_expr(expr.prefix, scope)
            return f"({tgt}.starts_with(&({pre})))"

        if isinstance(expr, StrContainsExpr):
            tgt = self.gen_expr(expr.target, scope)
            sub = self.gen_expr(expr.substring, scope)
            return f"({tgt}.contains(&({sub})))"

        if isinstance(expr, StringReplaceExpr):
            tgt = self.gen_expr(expr.target, scope)
            old_s = self.gen_expr(expr.old, scope)
            new_s = self.gen_expr(expr.new, scope)
            return f"({tgt}.replace(&({old_s}), &({new_s})))"

        if isinstance(expr, StringUpperExpr):
            return f"({self.gen_expr(expr.target, scope)}.to_uppercase())"

        if isinstance(expr, StringLowerExpr):
            return f"({self.gen_expr(expr.target, scope)}.to_lowercase())"

        if isinstance(expr, StringTrimExpr):
            return f"({self.gen_expr(expr.target, scope)}.trim().to_string())"

        if isinstance(expr, StringSplitExpr):
            self.uses_str_split = True
            return f"_meme_str_split(&({self.gen_expr(expr.target, scope)}), &({self.gen_expr(expr.separator, scope)}))"

        if isinstance(expr, StringJoinExpr):
            return f"(({self.gen_expr(expr.items, scope)}).join(&({self.gen_expr(expr.separator, scope)})))"

        if isinstance(expr, StringIndexOfExpr):
            tgt = self.gen_expr(expr.target, scope)
            sub = self.gen_expr(expr.substring, scope)
            return f"(match ({tgt}).find(&({sub})) {{ Some(_i) => _i as i64, None => -1_i64 }})"

        if isinstance(expr, StringCharAtExpr):
            self.uses_char_at = True
            return f"_meme_char_at(&({self.gen_expr(expr.target, scope)}), {self.gen_expr(expr.index, scope)})"

        if isinstance(expr, StringLengthExpr):
            tgt = self.gen_expr(expr.target, scope)
            return f"(({tgt}).chars().count() as i64)"

        if isinstance(expr, StringSliceExpr):
            tgt = self.gen_expr(expr.target, scope)
            start = self.gen_expr(expr.start, scope)
            end = self.gen_expr(expr.end, scope)
            return f"(({tgt}).chars().skip(({start}) as usize).take((({end}).saturating_sub({start})).max(0) as usize).collect::<String>())"

        if isinstance(expr, ParseIntExpr):
            self.uses_parse_int = True
            return f"_meme_parse_int(&({self.gen_expr(expr.target, scope)}))"

        if isinstance(expr, ParseIntOrDefaultExpr):
            self.uses_parse_int_or_else = True
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_parse_int_or_else(&({tgt}), || {dflt})"

        if isinstance(expr, IsDigitExpr):
            self.uses_is_digit = True
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_digit(&({tgt}))"

        if isinstance(expr, IsLetterExpr):
            self.uses_is_letter = True
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_letter(&({tgt}))"

        if isinstance(expr, IsUpperExpr):
            self.uses_is_upper = True
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_upper(&({tgt}))"

        if isinstance(expr, IsLowerExpr):
            self.uses_is_lower = True
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_is_lower(&({tgt}))"

        if isinstance(expr, FormatIntExpr):
            return f"({self.gen_expr(expr.target, scope)}).to_string()"

        if isinstance(expr, FormatFloatExpr):
            self.uses_format_float = True
            tgt = self.gen_expr(expr.target, scope)
            dec = self.gen_expr(expr.decimals, scope)
            return f"_meme_format_float({tgt}, {dec})"

        if isinstance(expr, FloatOfExpr):
            return f"({self.gen_expr(expr.target, scope)} as f64)"

        if isinstance(expr, NumberOfExpr):
            self.uses_number_of = True
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_number_of(&({tgt}))"

        if isinstance(expr, CharacterOfExpr):
            self.uses_character_of = True
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_character_of({tgt})"

        if isinstance(expr, Sha256Expr):
            self.uses_sha256 = True
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_sha256(&({tgt}))"

        if isinstance(expr, CurrentEpochExpr):
            return "std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)"

        if isinstance(expr, EnvVarExpr):
            v = self.gen_expr(expr.var_name, scope)
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                d = self.gen_expr(expr.default_val, scope)
                return f"std::env::var(&({v})).unwrap_or_else(|_| {d})"
            return f"std::env::var(&({v})).ok()"

        if isinstance(expr, ReadJsonListExpr):
            self.uses_json_io = True
            if expr.default_val is not None:
                self.uses_json_list_opt = True
                call = f"_meme_read_json_list_{expr.element_type.lower()}_opt(&({self.gen_expr(expr.filepath, scope)}))"
                if not isinstance(expr.default_val, OptionalNoneExpr):
                    d = self.gen_expr(expr.default_val, scope)
                    return f"{call}.unwrap_or_else(|| {d})"
                return call
            return f"_meme_read_json_list_{expr.element_type.lower()}(&({self.gen_expr(expr.filepath, scope)}))"

        if isinstance(expr, ReadJsonRecordExpr):
            self.uses_json_records = True
            self.json_records_read.add(expr.record_name)
            p = self.gen_expr(expr.filepath, scope)
            call = f"_meme_read_json_record_{_rust_ident(expr.record_name)}(&({p}))"
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                d = self.gen_expr(expr.default_val, scope)
                return f"{call}.unwrap_or_else(|| {d})"
            return call

        if isinstance(expr, ReadJsonRecordsExpr):
            self.uses_json_records = True
            self.json_record_lists_read.add(expr.record_name)
            p = self.gen_expr(expr.filepath, scope)
            call = f"_meme_read_json_records_{_rust_ident(expr.record_name)}(&({p}))"
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                d = self.gen_expr(expr.default_val, scope)
                return f"{call}.unwrap_or_else(|| {d})"
            return call

        if isinstance(expr, FileExistsExpr):
            self.uses_file_io = True
            return f"_meme_file_exists(&({self.gen_expr(expr.filepath, scope)}))"

        if isinstance(expr, ReadFileStringExpr):
            self.uses_file_io = True
            if expr.default_val is not None:
                self.uses_file_io_opt = True
                call = f"_meme_read_file_string_opt(&({self.gen_expr(expr.filepath, scope)}))"
                if not isinstance(expr.default_val, OptionalNoneExpr):
                    d = self.gen_expr(expr.default_val, scope)
                    return f"{call}.unwrap_or_else(|| {d})"
                return call
            return f"_meme_read_file_string(&({self.gen_expr(expr.filepath, scope)}))"

        if isinstance(expr, ReadFileLinesExpr):
            self.uses_file_io = True
            if expr.default_val is not None:
                self.uses_file_io_opt = True
                call = f"_meme_read_file_lines_opt(&({self.gen_expr(expr.filepath, scope)}))"
                if not isinstance(expr.default_val, OptionalNoneExpr):
                    d = self.gen_expr(expr.default_val, scope)
                    return f"{call}.unwrap_or_else(|| {d})"
                return call
            return f"_meme_read_file_lines(&({self.gen_expr(expr.filepath, scope)}))"

        if isinstance(expr, ListFilesExpr):
            self.uses_file_io = True
            return f"_meme_list_files(&({self.gen_expr(expr.path, scope)}))"

        if isinstance(expr, ArgCountExpr):
            self.uses_argv = True
            return "(std::env::args().count() as i64)"

        if isinstance(expr, ArgAtExpr):
            self.uses_argv = True
            return f"_meme_arg_at({self.gen_expr(expr.index, scope)})"

        if isinstance(expr, RecordLiteralExpr):
            rec_def = self.records.get(expr.record_name, {})
            fields = []
            for f in expr.fields:
                f_t = rec_def.get(f.name, "")
                f_id = _rust_ident(f.name)
                if f_t.startswith("Optional<") and f_t.endswith(">") and _is_record_name(f_t[9:-1], set(self.records.keys())):
                    if isinstance(f.value, OptionalNoneExpr):
                        val_code = "None"
                    elif isinstance(f.value, OptionalWrapExpr):
                        val_code = f"Some(Box::new({self.gen_expr(f.value.value, scope)}))"
                    else:
                        val_code = f"({self.gen_expr(f.value, scope)}).map(Box::new)"
                else:
                    val_code = self.gen_expr(f.value, scope)
                fields.append(f"{f_id}: {val_code}")
            return f"{_rust_ident(expr.record_name)} {{ {', '.join(fields)} }}"

        if isinstance(expr, RecordFieldExpr):
            rec_t = self.infer_type(expr.target, scope)
            f_t = self.records.get(rec_t, {}).get(expr.field_name, "")
            tgt_expr = self.gen_expr(expr.target, scope)
            fld_id = _rust_ident(expr.field_name)
            if f_t.startswith("Optional<") and f_t.endswith(">") and _is_record_name(f_t[9:-1], set(self.records.keys())):
                return f"{tgt_expr}.{fld_id}.clone().map(|b| *b)"
            return f"{tgt_expr}.{fld_id}.clone()"

        if isinstance(expr, MapLiteralExpr):
            if not expr.entries:
                return f"std::rc::Rc::new(std::collections::HashMap::<{_rust_type(expr.key_type)}, {_rust_type(expr.value_type)}>::new())"
            inits = "; ".join(
                f"_m.insert({self.gen_expr(e.key, scope)}, {self.gen_expr(e.value, scope)})"
                for e in expr.entries
            )
            return f"std::rc::Rc::new({{ let mut _m = std::collections::HashMap::new(); {inits}; _m }})"

        if isinstance(expr, MapGetExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            if expr.default_val is not None:
                def_val = self.gen_expr(expr.default_val, scope)
                return f"{tgt}.get(&({k})).cloned().unwrap_or({def_val})"
            return f"{tgt}.get(&({k})).unwrap().clone()"

        if isinstance(expr, MapHasKeyExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            return f"{tgt}.contains_key(&({k}))"

        if isinstance(expr, OptionalNoneExpr):
            return "None"

        if isinstance(expr, OptionalWrapExpr):
            return f"Some({self.gen_expr(expr.value, scope)})"

        if isinstance(expr, OptionalIsNothingExpr):
            tgt = self.gen_expr(expr.target, scope)
            if expr.negated:
                return f"({tgt}.is_some())"
            return f"({tgt}.is_none())"

        if isinstance(expr, OptionalUnwrapExpr):
            self.uses_optional_helpers = True
            return f"_meme_unwrap({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, OptionalUnwrapOrDefaultExpr):
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"{tgt}.unwrap_or_else(|| {dflt})"

        if isinstance(expr, EmptySetExpr):
            return f"std::rc::Rc::new(_MemeSet::<{_rust_type(expr.element_type)}>::new())"

        if isinstance(expr, SetContainsExpr):
            return f"{self.gen_expr(expr.target, scope)}.contains(&({self.gen_expr(expr.value, scope)}))"

        if isinstance(expr, SetLengthExpr):
            return f"{self.gen_expr(expr.target, scope)}.len()"

        raise TypeError(f"Unsupported IRExpr: {type(expr)!r}")

    def _fmt_expr_for_print(self, expr: IRExpr, scope: dict[str, MemeType]) -> str:
        t = self.infer_type(expr, scope)
        code = self.gen_expr(expr, scope)
        if t.startswith("List<"):
            return f"_meme_fmt_slice(&({code}))"
        return f"({code}).meme_fmt()"

    def gen_stmt(
        self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 1
    ) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            val_code = self.gen_expr(stmt.value, scope)
            scope[stmt.name] = stmt.var_type
            return [f"{pad}let mut {_rust_ident(stmt.name)}: {_rust_type(stmt.var_type)} = {val_code};"]

        if isinstance(stmt, AssignStmt):
            return [f"{pad}{_rust_ident(stmt.name)} = {self.gen_expr(stmt.value, scope)};"]

        if isinstance(stmt, CompoundAssignStmt):
            return [
                f"{pad}{_rust_ident(stmt.target)} {stmt.operator}= {self.gen_expr(stmt.value, scope)};"
            ]

        if isinstance(stmt, SortCollectionStmt):
            tgt = _rust_ident(stmt.target)
            if stmt.direction == "ascending":
                return [
                    f"{pad}std::rc::Rc::make_mut(&mut {tgt}).sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));"
                ]
            return [
                f"{pad}std::rc::Rc::make_mut(&mut {tgt}).sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));"
            ]

        if isinstance(stmt, ClampCollectionStmt):
            tgt = _rust_ident(stmt.target)
            lo = self.gen_expr(stmt.min_val, scope)
            hi = self.gen_expr(stmt.max_val, scope)
            return [
                f"{pad}let (_lo, _hi) = ({lo}, {hi});",
                f"{pad}for _x in std::rc::Rc::make_mut(&mut {tgt}).iter_mut() {{",
                f"{pad}    if *_x < _lo {{ *_x = _lo; }} else if *_x > _hi {{ *_x = _hi; }}",
                f"{pad}}}",
            ]

        if isinstance(stmt, FilterCollectionStmt):
            tgt = _rust_ident(stmt.target)
            iv = _rust_ident(stmt.item_var)
            sub = dict(scope)
            col_t = scope.get(stmt.target, "List<Int>")
            sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
            pred = self.gen_expr(stmt.predicate, sub)
            return [
                f"{pad}{tgt} = std::rc::Rc::new({tgt}.iter().filter(|_item_ref| {{",
                f"{pad}    let {iv} = (*_item_ref).clone();",
                f"{pad}    {pred}",
                f"{pad}}}).cloned().collect());",
            ]

        if isinstance(stmt, ListAppendStmt):
            return [f"{pad}std::rc::Rc::make_mut(&mut {_rust_ident(stmt.target)}).push({self.gen_expr(stmt.value, scope)});"]

        if isinstance(stmt, ListInsertStmt):
            return [
                f"{pad}std::rc::Rc::make_mut(&mut {_rust_ident(stmt.target)}).insert(({self.gen_expr(stmt.index, scope)}) as usize, {self.gen_expr(stmt.value, scope)});"
            ]

        if isinstance(stmt, ListSetIndexStmt):
            tgt = _rust_ident(stmt.target)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope)
            if stmt.nested_index is not None:
                nidx = self.gen_expr(stmt.nested_index, scope)
                return [f"{pad}std::rc::Rc::make_mut(&mut std::rc::Rc::make_mut(&mut {tgt})[({idx}) as usize])[({nidx}) as usize] = {val};"]
            return [f"{pad}std::rc::Rc::make_mut(&mut {tgt})[({idx}) as usize] = {val};"]

        if isinstance(stmt, ListRemoveStmt):
            self.uses_list_remove = True
            tgt = _rust_ident(stmt.target)
            if stmt.index is not None:
                idx = self.gen_expr(stmt.index, scope)
                return [f"{pad}_meme_list_remove(std::rc::Rc::make_mut(&mut {tgt}), {idx});"]
            return [f"{pad}_meme_list_remove_last(std::rc::Rc::make_mut(&mut {tgt}));"]

        if isinstance(stmt, FailStmt):
            return [
                f"{pad}println!(\"{{}}\", {self._fmt_expr_for_print(stmt.message, scope)});",
                f"{pad}std::process::exit(1);",
            ]

        if isinstance(stmt, ExitStmt):
            return [
                f"{pad}std::process::exit((({self.gen_expr(stmt.code, scope)}) & 0xFF) as i32);"
            ]

        if isinstance(stmt, AssertStmt):
            cond = self.gen_expr(stmt.condition, scope)
            line = stmt.source_line if stmt.source_line is not None else 1
            src_text = stmt.source_text if getattr(stmt, "source_text", None) else format_expr(stmt.condition)
            escaped_src = json.dumps(src_text)
            return [
                f"{pad}if !({cond}) {{",
                f"{pad}    eprintln!(\"ASSERT FAILED line {line}: {{}}\", {escaped_src});",
                f"{pad}    std::process::exit(1);",
                f"{pad}}}",
            ]

        if isinstance(stmt, PrintStmt):
            if len(stmt.expressions) == 1:
                return [f"{pad}println!(\"{{}}\", {self._fmt_expr_for_print(stmt.expressions[0], scope)});"]
            fmt_str = " ".join("{}" for _ in stmt.expressions)
            args = ", ".join(self._fmt_expr_for_print(e, scope) for e in stmt.expressions)
            return [f'{pad}println!("{fmt_str}", {args});']

        if isinstance(stmt, PrintErrorStmt):
            if len(stmt.expressions) == 1:
                return [f"{pad}eprintln!(\"{{}}\", {self._fmt_expr_for_print(stmt.expressions[0], scope)});"]
            fmt_str = " ".join("{}" for _ in stmt.expressions)
            args = ", ".join(self._fmt_expr_for_print(e, scope) for e in stmt.expressions)
            return [f'{pad}eprintln!("{fmt_str}", {args});']

        if isinstance(stmt, IfStmt):
            lines = [f"{pad}if {self.gen_expr(stmt.condition, scope)} {{"]
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
            lines = [f"{pad}{{"]
            if stmt.cases:
                lines.append(f"{pad}    let {m_var} = {self.gen_expr(stmt.target, scope)};")
                for i, case in enumerate(stmt.cases):
                    kw = "if" if i == 0 else "} else if"
                    lines.append(f"{pad}    {kw} {m_var} == {self.gen_expr(case.value, scope)} {{")
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
                lines.append(f"{pad}    let _ = {self.gen_expr(stmt.target, scope)};")
                def_scope = dict(scope)
                for ch in stmt.default_body:
                    lines.extend(self.gen_stmt(ch, def_scope, indent + 1))
            else:
                lines.append(f"{pad}    let _ = {self.gen_expr(stmt.target, scope)};")
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
            map_t = _map_types_of(col_t)
            col_ident = (
                _rust_ident(stmt.collection)
                if isinstance(col_expr, VarRefExpr)
                else f"({self.gen_expr(col_expr, scope)})"
            )
            item_ident = _rust_ident(stmt.item_var)
            set_t = _set_type_of(col_t)
            if map_t is not None:
                sub[stmt.item_var] = map_t[0]  # type: ignore[assignment]
                lines = [
                    f"{pad}{{",
                    f"{pad}    let _meme_col = {col_ident}.clone();",
                    f"{pad}    let mut _meme_keys: Vec<_> = _meme_col.keys().cloned().collect();",
                    f"{pad}    _meme_keys.sort();",
                ]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _rust_ident(stmt.index_var)
                    lines.append(
                        f"{pad}    for (_meme_idx, mut {item_ident}) in _meme_keys.into_iter().enumerate() {{"
                    )
                    lines.append(f"{pad}        let mut {idx_ident}: i64 = _meme_idx as i64;")
                else:
                    lines.append(f"{pad}    for mut {item_ident} in _meme_keys.into_iter() {{")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines
            elif set_t is not None:
                sub[stmt.item_var] = set_t  # type: ignore[assignment]
                lines = [
                    f"{pad}{{",
                    f"{pad}    let _meme_col = {col_ident}.clone();",
                ]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _rust_ident(stmt.index_var)
                    lines.append(
                        f"{pad}    for (_meme_idx, mut {item_ident}) in _meme_col.data.iter().cloned().enumerate() {{"
                    )
                    lines.append(f"{pad}        let mut {idx_ident}: i64 = _meme_idx as i64;")
                else:
                    lines.append(f"{pad}    for mut {item_ident} in _meme_col.data.iter().cloned() {{")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines
            else:
                sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
                lines = [
                    f"{pad}{{",
                    f"{pad}    let _meme_col = {col_ident}.clone();",
                ]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _rust_ident(stmt.index_var)
                    lines.append(
                        f"{pad}    for (_meme_idx, mut {item_ident}) in _meme_col.iter().cloned().enumerate() {{"
                    )
                    lines.append(f"{pad}        let mut {idx_ident}: i64 = _meme_idx as i64;")
                else:
                    lines.append(f"{pad}    for mut {item_ident} in _meme_col.iter().cloned() {{")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines

        if isinstance(stmt, ForRangeStmt):
            sub = dict(scope)
            sub[stmt.loop_var] = "Int"
            s = self.gen_expr(stmt.start, scope)
            e = self.gen_expr(stmt.end, scope)
            lines = [f"{pad}for {_rust_ident(stmt.loop_var)} in ({s})..=({e}) {{"]
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, sub, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, WhileStmt):
            lines = [f"{pad}while {self.gen_expr(stmt.condition, scope)} {{"]
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
            return [f"{pad}return {self.gen_expr(stmt.value, scope)};"]

        if isinstance(stmt, RecordDefStmt):
            return []

        if isinstance(stmt, RecordSetFieldStmt):
            rec_t = scope.get(stmt.target, "")
            f_t = self.records.get(rec_t, {}).get(stmt.field_name, "")
            tgt = _rust_ident(stmt.target)
            fld = _rust_ident(stmt.field_name)
            if f_t.startswith("Optional<") and f_t.endswith(">") and _is_record_name(f_t[9:-1], set(self.records.keys())):
                if isinstance(stmt.value, OptionalNoneExpr):
                    val_code = "None"
                elif isinstance(stmt.value, OptionalWrapExpr):
                    val_code = f"Some(Box::new({self.gen_expr(stmt.value.value, scope)}))"
                else:
                    val_code = f"({self.gen_expr(stmt.value, scope)}).map(Box::new)"
            else:
                val_code = self.gen_expr(stmt.value, scope)
            return [
                f"{pad}{tgt}.{fld} = {val_code};"
            ]

        if isinstance(stmt, MapSetStmt):
            return [
                f"{pad}std::rc::Rc::make_mut(&mut {_rust_ident(stmt.target)}).insert({self.gen_expr(stmt.key, scope)}, {self.gen_expr(stmt.value, scope)});"
            ]

        if isinstance(stmt, SetAddStmt):
            tgt = _rust_ident(stmt.target)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}std::rc::Rc::make_mut(&mut {tgt}).insert({val});"]

        if isinstance(stmt, SetRemoveStmt):
            tgt = _rust_ident(stmt.target)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}std::rc::Rc::make_mut(&mut {tgt}).remove(&({val}));"]

        if isinstance(stmt, WriteFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_write_file(&({self.gen_expr(stmt.filepath, scope)}), &({self.gen_expr(stmt.content, scope)}));"
            ]

        if isinstance(stmt, WriteJsonStmt):
            self.uses_file_io = True
            self.uses_json_write = True
            self.uses_format_float = True
            tgt_t = self.infer_type(stmt.target, scope)
            fp = self.gen_expr(stmt.filepath, scope)
            tgt = self.gen_expr(stmt.target, scope)
            if tgt_t in self.records:
                self.json_records_write.add(tgt_t)
                return [f"{pad}_meme_write_file(&({fp}), &(_meme_serialize_json_record_{_rust_ident(tgt_t)}(&({tgt}))));"]
            elif tgt_t.startswith("List<") and tgt_t.endswith(">"):
                r_name = tgt_t[5:-1]
                self.json_records_write.add(r_name)
                return [f"{pad}_meme_write_file(&({fp}), &(_meme_serialize_json_records_{_rust_ident(r_name)}(&({tgt}))));"]

        if isinstance(stmt, AppendFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_append_file(&({self.gen_expr(stmt.filepath, scope)}), &({self.gen_expr(stmt.content, scope)}));"
            ]

        if isinstance(stmt, CopyFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_copy_file(&({self.gen_expr(stmt.src, scope)}), &({self.gen_expr(stmt.dst, scope)}));"
            ]

        if isinstance(stmt, MoveFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_move_file(&({self.gen_expr(stmt.src, scope)}), &({self.gen_expr(stmt.dst, scope)}));"
            ]

        if isinstance(stmt, RenameFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_rename_file(&({self.gen_expr(stmt.path, scope)}), &({self.gen_expr(stmt.new_name, scope)}));"
            ]

        if isinstance(stmt, DeleteFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_delete_file(&({self.gen_expr(stmt.path, scope)}));"
            ]

        if isinstance(stmt, CreateDirectoryStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_create_directory(&({self.gen_expr(stmt.path, scope)}));"
            ]

        if isinstance(stmt, ImportStmt):
            return []

        if isinstance(stmt, TestBlockStmt):
            return []

        if isinstance(stmt, CallStmt):
            args = ", ".join(self.gen_expr(a, scope) for a in stmt.args)
            return [f"{pad}{_rust_ident(stmt.func_name)}({args});"]

        raise TypeError(f"Unsupported statement inside block: {type(stmt)!r}")

    def gen_func(self, fn: FuncDefStmt) -> list[str]:
        self.func_returns[fn.name] = fn.return_type
        params = ", ".join(f"mut {_rust_ident(p.name)}: {_rust_type(p.param_type)}" for p in fn.params)
        ret = f" -> {_rust_type(fn.return_type)}" if fn.return_type != "Void" else ""
        fn_scope = {p.name: p.param_type for p in fn.params}
        lines = [f"fn {_rust_ident(fn.name)}({params}){ret} {{"]
        for ch in fn.body:
            lines.extend(self.gen_stmt(ch, fn_scope, indent=1))
        lines.append("}")
        return lines


_RUST_JSON_PARSER_HELPERS = [
    "#[derive(Clone, Debug, PartialEq)]",
    "enum _MemeJV {",
    "    Null,",
    "    Bool(bool),",
    "    Num(f64, bool, i64),",
    "    Str(String),",
    "    Arr(Vec<_MemeJV>),",
    "    Obj(Vec<(String, _MemeJV)>),",
    "}",
    "",
    "fn _meme_skip_ws(chars: &[char], idx: &mut usize) {",
    "    while *idx < chars.len() && chars[*idx].is_whitespace() {",
    "        *idx += 1;",
    "    }",
    "}",
    "",
    "fn _meme_parse_jv_str(chars: &[char], idx: &mut usize) -> Option<String> {",
    "    if *idx >= chars.len() || chars[*idx] != '\"' { return None; }",
    "    *idx += 1;",
    "    let mut out = String::new();",
    "    while *idx < chars.len() && chars[*idx] != '\"' {",
    "        if chars[*idx] == '\\\\' {",
    "            *idx += 1;",
    "            if *idx >= chars.len() { return None; }",
    "            let c = chars[*idx];",
    "            *idx += 1;",
    "            match c {",
    "                '\"' => out.push('\"'),",
    "                '\\\\' => out.push('\\\\'),",
    "                '/' => out.push('/'),",
    "                'b' => out.push('\\x08'),",
    "                'f' => out.push('\\x0c'),",
    "                'n' => out.push('\\n'),",
    "                'r' => out.push('\\r'),",
    "                't' => out.push('\\t'),",
    "                'u' => {",
    "                    if *idx + 4 > chars.len() { return None; }",
    "                    let hex_str: String = chars[*idx..*idx + 4].iter().collect();",
    "                    *idx += 4;",
    "                    let cp = u32::from_str_radix(&hex_str, 16).ok()?;",
    "                    let ch = char::from_u32(cp)?;",
    "                    out.push(ch);",
    "                }",
    "                _ => return None,",
    "            }",
    "        } else {",
    "            out.push(chars[*idx]);",
    "            *idx += 1;",
    "        }",
    "    }",
    "    if *idx >= chars.len() || chars[*idx] != '\"' { return None; }",
    "    *idx += 1;",
    "    Some(out)",
    "}",
    "",
    "fn _meme_parse_jv(chars: &[char], idx: &mut usize) -> Option<_MemeJV> {",
    "    _meme_skip_ws(chars, idx);",
    "    if *idx >= chars.len() { return None; }",
    "    let rem: String = chars[*idx..].iter().collect();",
    "    if rem.starts_with(\"null\") {",
    "        *idx += 4; return Some(_MemeJV::Null);",
    "    }",
    "    if rem.starts_with(\"true\") {",
    "        *idx += 4; return Some(_MemeJV::Bool(true));",
    "    }",
    "    if rem.starts_with(\"false\") {",
    "        *idx += 5; return Some(_MemeJV::Bool(false));",
    "    }",
    "    if chars[*idx] == '\"' {",
    "        let s = _meme_parse_jv_str(chars, idx)?;",
    "        return Some(_MemeJV::Str(s));",
    "    }",
    "    if chars[*idx] == '-' || chars[*idx].is_ascii_digit() {",
    "        let start = *idx;",
    "        let mut has_dot_or_exp = false;",
    "        if chars[*idx] == '-' { *idx += 1; }",
    "        while *idx < chars.len() && chars[*idx].is_ascii_digit() { *idx += 1; }",
    "        if *idx < chars.len() && chars[*idx] == '.' {",
    "            has_dot_or_exp = true; *idx += 1;",
    "            while *idx < chars.len() && chars[*idx].is_ascii_digit() { *idx += 1; }",
    "        }",
    "        if *idx < chars.len() && (chars[*idx] == 'e' || chars[*idx] == 'E') {",
    "            has_dot_or_exp = true; *idx += 1;",
    "            if *idx < chars.len() && (chars[*idx] == '+' || chars[*idx] == '-') { *idx += 1; }",
    "            while *idx < chars.len() && chars[*idx].is_ascii_digit() { *idx += 1; }",
    "        }",
    "        let num_str: String = chars[start..*idx].iter().collect();",
    "        let num: f64 = num_str.parse().ok()?;",
    "        let (is_int, ival) = if !has_dot_or_exp {",
    "            let iv: i64 = num_str.parse().ok()?;",
    "            (true, iv)",
    "        } else if num == (num as i64 as f64) {",
    "            (true, num as i64)",
    "        } else {",
    "            (false, 0)",
    "        };",
    "        return Some(_MemeJV::Num(num, is_int, ival));",
    "    }",
    "    if chars[*idx] == '[' {",
    "        *idx += 1;",
    "        let mut arr = Vec::new();",
    "        _meme_skip_ws(chars, idx);",
    "        if *idx < chars.len() && chars[*idx] == ']' {",
    "            *idx += 1;",
    "            return Some(_MemeJV::Arr(arr));",
    "        }",
    "        while *idx < chars.len() {",
    "            let el = _meme_parse_jv(chars, idx)?;",
    "            arr.push(el);",
    "            _meme_skip_ws(chars, idx);",
    "            if *idx < chars.len() && chars[*idx] == ',' {",
    "                *idx += 1;",
    "                continue;",
    "            }",
    "            if *idx < chars.len() && chars[*idx] == ']' {",
    "                *idx += 1;",
    "                return Some(_MemeJV::Arr(arr));",
    "            }",
    "            return None;",
    "        }",
    "        return None;",
    "    }",
    "    if chars[*idx] == '{' {",
    "        *idx += 1;",
    "        let mut obj = Vec::new();",
    "        _meme_skip_ws(chars, idx);",
    "        if *idx < chars.len() && chars[*idx] == '}' {",
    "            *idx += 1;",
    "            return Some(_MemeJV::Obj(obj));",
    "        }",
    "        while *idx < chars.len() {",
    "            _meme_skip_ws(chars, idx);",
    "            let key = _meme_parse_jv_str(chars, idx)?;",
    "            _meme_skip_ws(chars, idx);",
    "            if *idx >= chars.len() || chars[*idx] != ':' { return None; }",
    "            *idx += 1;",
    "            let val = _meme_parse_jv(chars, idx)?;",
    "            obj.push((key, val));",
    "            _meme_skip_ws(chars, idx);",
    "            if *idx < chars.len() && chars[*idx] == ',' {",
    "                *idx += 1;",
    "                continue;",
    "            }",
    "            if *idx < chars.len() && chars[*idx] == '}' {",
    "                *idx += 1;",
    "                return Some(_MemeJV::Obj(obj));",
    "            }",
    "            return None;",
    "        }",
    "        return None;",
    "    }",
    "    None",
    "}",
    "",
    "fn _meme_find_field<'a>(obj: &'a _MemeJV, key: &str) -> Option<&'a _MemeJV> {",
    "    if let _MemeJV::Obj(fields) = obj {",
    "        for (k, v) in fields {",
    "            if k == key { return Some(v); }",
    "        }",
    "    }",
    "    None",
    "}",
    "",
    "fn _meme_read_json_file(path: &str) -> Option<_MemeJV> {",
    "    let resolved = _meme_resolve_path(path);",
    "    let raw = std::fs::read_to_string(resolved).ok()?;",
    "    let chars: Vec<char> = raw.chars().collect();",
    "    let mut idx = 0;",
    "    let jv = _meme_parse_jv(&chars, &mut idx)?;",
    "    _meme_skip_ws(&chars, &mut idx);",
    "    if idx < chars.len() { return None; }",
    "    Some(jv)",
    "}",
    "",
]


def _rust_json_decode_val(jv_expr: str, ftype: str, records: set[str] | None = None) -> str:
    if ftype == "Int":
        return f"match {jv_expr} {{ _MemeJV::Num(_, is_int, ival) if *is_int => *ival, _ => return None }}"
    if ftype == "Float":
        return f"match {jv_expr} {{ _MemeJV::Num(num, _, _) => *num, _ => return None }}"
    if ftype == "String":
        return f"match {jv_expr} {{ _MemeJV::Str(s) => s.clone(), _ => return None }}"
    if ftype == "Bool":
        return f"match {jv_expr} {{ _MemeJV::Bool(b) => *b, _ => return None }}"
    if ftype.startswith("Optional<") and ftype.endswith(">"):
        inner = ftype[9:-1]
        inner_dec = _rust_json_decode_val("other", inner, records)
        if records and inner in records:
            wrap = f"Some(Box::new({inner_dec}))"
        else:
            wrap = f"Some({inner_dec})"
        return f"match {jv_expr} {{ _MemeJV::Null => None, other => {wrap} }}"
    if ftype.startswith("List<") and ftype.endswith(">"):
        el_t = ftype[5:-1]
        el_dec = _rust_json_decode_val("it", el_t, records)
        return f"if let _MemeJV::Arr(items) = {jv_expr} {{ let mut out = Vec::new(); for it in items {{ out.push({el_dec}); }} std::rc::Rc::new(out) }} else {{ return None; }}"
    if ftype.startswith("Set<") and ftype.endswith(">"):
        el_t = ftype[4:-1]
        el_dec = _rust_json_decode_val("it", el_t, records)
        return f"if let _MemeJV::Arr(items) = {jv_expr} {{ let mut out = _MemeSet::new(); for it in items {{ out.insert({el_dec}); }} std::rc::Rc::new(out) }} else {{ return None; }}"
    if ftype.startswith("Map<") and ftype.endswith(">"):
        mt = _map_types_of(ftype)
        assert mt is not None
        k_t, v_t = mt
        v_dec = _rust_json_decode_val("v_jv", v_t, records)
        if k_t == "Int":
            k_parse = "let k_val: i64 = k_str.parse().ok()?;"
        else:
            k_parse = "let k_val = k_str.clone();"
        return f"if let _MemeJV::Obj(pairs) = {jv_expr} {{ let mut out = std::collections::HashMap::new(); for (k_str, v_jv) in pairs {{ {k_parse} let v_val = {v_dec}; out.insert(k_val, v_val); }} std::rc::Rc::new(out) }} else {{ return None; }}"
    r_ident = _rust_ident(ftype)
    return f"_meme_parse_record_{r_ident}(&({jv_expr}))?"


def _rust_json_serialize_val(val_expr: str, ftype: str, is_ref: bool = False, records: set[str] | None = None) -> str:
    if ftype == "Int":
        return f"{val_expr}.to_string()"
    if ftype == "Float":
        deref = f"*{val_expr}" if is_ref else val_expr
        return f"_meme_format_json_float({deref})"
    if ftype == "String":
        ref = val_expr if is_ref else f"&{val_expr}"
        return f"_meme_escape_json_str({ref})"
    if ftype == "Bool":
        deref = f"*{val_expr}" if is_ref else val_expr
        return f'(if {deref} {{ "true" }} else {{ "false" }}).to_string()'
    if ftype.startswith("Optional<") and ftype.endswith(">"):
        inner = ftype[9:-1]
        inner_code = _rust_json_serialize_val("v", inner, is_ref=True, records=records)
        return f'(match &{val_expr} {{ None => "null".to_string(), Some(v) => {inner_code} }})'
    if ftype.startswith("List<") and ftype.endswith(">"):
        el_t = ftype[5:-1]
        el_code = _rust_json_serialize_val("_x", el_t, is_ref=True, records=records)
        return f'format!("[{{}}]", {val_expr}.iter().map(|_x| {el_code}).collect::<Vec<_>>().join(","))'
    if ftype.startswith("Set<") and ftype.endswith(">"):
        el_t = ftype[4:-1]
        el_code = _rust_json_serialize_val("_x", el_t, is_ref=True, records=records)
        return f'format!("[{{}}]", {val_expr}.data.iter().map(|_x| {el_code}).collect::<Vec<_>>().join(","))'
    if ftype.startswith("Map<") and ftype.endswith(">"):
        mt = _map_types_of(ftype)
        assert mt is not None
        k_t, v_t = mt
        v_code = _rust_json_serialize_val(f"{val_expr}.get(k).unwrap()", v_t, is_ref=True, records=records)
        return (
            f"{{ let mut keys: Vec<_> = {val_expr}.keys().cloned().collect();"
            f" keys.sort_by(|a, b| a.meme_cmp(b));"
            f' let parts: Vec<String> = keys.iter().map(|k| format!("{{}}:{{}}", _meme_escape_json_str(&k.to_string()), {v_code})).collect();'
            ' format!("{{{}}}", parts.join(",")) }'
        )
    r_ident = _rust_ident(ftype)
    ref = val_expr if is_ref else f"&{val_expr}"
    return f"_meme_serialize_json_record_{r_ident}({ref})"


def _emit_rust_json_record_reader(r_name: str, fields: dict[str, MemeType], records: set[str] | None = None) -> list[str]:
    ident = _rust_ident(r_name)
    lines = [
        f"fn _meme_parse_record_{ident}(jv: &_MemeJV) -> Option<{ident}> {{",
        "    if let _MemeJV::Obj(_) = jv {",
        f"        Some({ident} {{",
    ]
    for fname, ftype in fields.items():
        fn_str = json.dumps(fname)
        f_ident = _rust_ident(fname)
        lines.append(f"            {f_ident}: {{")
        lines.append(f"                let f_val = _meme_find_field(jv, {fn_str});")
        if ftype.startswith("Optional<"):
            inner = ftype[9:-1]
            inner_dec = _rust_json_decode_val("val", inner, records)
            if records and inner in records:
                wrap = f"Some(Box::new({inner_dec}))"
            else:
                wrap = f"Some({inner_dec})"
            lines.extend([
                "                match f_val {",
                "                    None | Some(_MemeJV::Null) => None,",
                f"                    Some(val) => {wrap},",
                "                }",
            ])
        else:
            lines.append("                let f_val = f_val?;")
            lines.append(f"                {_rust_json_decode_val('f_val', ftype, records)}")
        lines.append("            },")

    lines.extend([
        "        })",
        "    } else {",
        "        None",
        "    }",
        "}",
        "",
        f"fn _meme_read_json_record_{ident}(path: &str) -> Option<{ident}> {{",
        "    let jv = _meme_read_json_file(path)?;",
        f"    _meme_parse_record_{ident}(&jv)",
        "}",
        "",
        f"fn _meme_read_json_records_{ident}(path: &str) -> Option<std::rc::Rc<Vec<{ident}>>> {{",
        "    let jv = _meme_read_json_file(path)?;",
        "    if let _MemeJV::Arr(items) = jv {",
        "        let mut out = Vec::new();",
        "        for item in items {",
        f"            out.push(_meme_parse_record_{ident}(&item)?);",
        "        }",
        "        Some(std::rc::Rc::new(out))",
        "    } else {",
        "        None",
        "    }",
        "}",
        "",
    ])
    return lines


def _emit_rust_json_record_writer(r_name: str, fields: dict[str, MemeType], records: set[str] | None = None) -> list[str]:
    ident = _rust_ident(r_name)
    lines = [
        f"fn _meme_serialize_json_record_{ident}(rec: &{ident}) -> String {{",
        "    let mut parts: Vec<String> = Vec::new();",
    ]
    for fname, ftype in fields.items():
        k_str = json.dumps(fname) + ":"
        f_ident = _rust_ident(fname)
        val_code = _rust_json_serialize_val(f"rec.{f_ident}", ftype, records=records)
        lines.append(f"    parts.push(format!(\"{{}}{{}}\", {json.dumps(k_str)}, {val_code}));")
    lines.extend([
        "    format!(\"{{{}}}\", parts.join(\",\"))",
        "}",
        "",
        f"fn _meme_serialize_json_records_{ident}(recs: &[{ident}]) -> String {{",
        f"    let parts: Vec<String> = recs.iter().map(_meme_serialize_json_record_{ident}).collect();",
        "    format!(\"[{}]\", parts.join(\",\"))",
        "}",
        "",
    ])
    return lines


def generate_rust(ir: ProgramIR) -> str:
    gen = _RustGen()
    records: list[RecordDefStmt] = []
    funcs: list[FuncDefStmt] = []
    test_blocks: list[TestBlockStmt] = []
    main_stmts: list[IRStatement] = []
    for stmt in [*ir.imported_definitions, *ir.statements]:
        if isinstance(stmt, RecordDefStmt):
            gen.records[stmt.name] = {f.name: f.field_type for f in stmt.fields}
            records.append(stmt)
        elif isinstance(stmt, FuncDefStmt):
            gen.func_returns[stmt.name] = stmt.return_type
            funcs.append(stmt)
        elif isinstance(stmt, ImportStmt):
            continue
        elif isinstance(stmt, TestBlockStmt):
            test_blocks.append(stmt)
        else:
            main_stmts.append(stmt)

    record_blocks: list[str] = []
    for r in records:
        r_name = _rust_ident(r.name)
        record_blocks.append("#[derive(Clone, Debug, PartialEq)]")
        record_blocks.append(f"struct {r_name} {{")
        for f in r.fields:
            if f.field_type.startswith("Optional<") and f.field_type.endswith(">"):
                inner = f.field_type[9:-1]
                if _is_record_name(inner, set(gen.records.keys())):
                    record_blocks.append(f"    {_rust_ident(f.name)}: Option<Box<{_rust_ident(inner)}>>,")
                else:
                    record_blocks.append(f"    {_rust_ident(f.name)}: {_rust_type(f.field_type)},")
            else:
                record_blocks.append(f"    {_rust_ident(f.name)}: {_rust_type(f.field_type)},")
        record_blocks.append("}")
        record_blocks.append(f"impl _MemeFmt for {r_name} {{")
        record_blocks.append("    fn meme_fmt(&self) -> String {")
        if not r.fields:
            record_blocks.append(f'        format!("{r.name}()")')
        else:
            f_fmts = ", ".join(
                f'format!("{f.name}={{}}", self.{_rust_ident(f.name)}.meme_fmt())' for f in r.fields
            )
            record_blocks.append(f"        let _parts = vec![{f_fmts}];")
            record_blocks.append(f'        format!("{r.name}({{}})", _parts.join(", "))')
        record_blocks.append("    }")
        record_blocks.append("}")
        record_blocks.append(f"impl _MemeOrd for {r_name} {{")
        record_blocks.append("    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering {")
        if not r.fields:
            record_blocks.append("        std::cmp::Ordering::Equal")
        else:
            for f in r.fields:
                f_id = _rust_ident(f.name)
                record_blocks.append(f"        match self.{f_id}.meme_cmp(&other.{f_id}) {{")
                record_blocks.append("            std::cmp::Ordering::Equal => {},")
                record_blocks.append("            ord => return ord,")
                record_blocks.append("        }")
            record_blocks.append("        std::cmp::Ordering::Equal")
        record_blocks.append("    }")
        record_blocks.append("}")
        record_blocks.append("")

    fn_blocks: list[str] = []
    for fn in funcs:
        fn_blocks.extend(gen.gen_func(fn))
        fn_blocks.append("")

    main_scope: dict[str, MemeType] = {}
    main_lines: list[str] = []
    if test_blocks:
        main_lines.append("    let _meme_args: Vec<String> = std::env::args().collect();")
        main_lines.append("    if _meme_args.len() > 2 && _meme_args[1] == \"--meme-test\" {")
        main_lines.append("        match _meme_args[2].as_str() {")
        for tb in test_blocks:
            main_lines.append(f"            {json.dumps(tb.name)} => {{")
            tb_scope = dict(main_scope)
            for s in tb.body:
                main_lines.extend(gen.gen_stmt(s, tb_scope, indent=4))
            main_lines.append("                return;")
            main_lines.append("            }")
        main_lines.append("            unknown => {")
        main_lines.append("                eprintln!(\"Unknown test block: {}\", unknown);")
        main_lines.append("                std::process::exit(1);")
        main_lines.append("            }")
        main_lines.append("        }")
        main_lines.append("    }")
    for stmt in main_stmts:
        main_lines.extend(gen.gen_stmt(stmt, main_scope, indent=1))

    preamble: list[str] = [
        "#![allow(dead_code, unused_mut, unused_parens, unused_variables)]",
        "",
        "type _MemeMap<K, V> = std::collections::HashMap<K, V>;",
        "",
        "trait _MemeFmt {",
        "    fn meme_fmt(&self) -> String;",
        "}",
        "impl _MemeFmt for i64 { fn meme_fmt(&self) -> String { format!(\"{}\", self) } }",
        "impl _MemeFmt for f64 {",
        "    fn meme_fmt(&self) -> String {",
        "        if self.is_finite() && self.trunc() == *self && *self >= -9007199254740992.0 && *self <= 9007199254740992.0 {",
        "            format!(\"{}\", *self as i64)",
        "        } else {",
        "            format!(\"{}\", self)",
        "        }",
        "    }",
        "}",
        "impl _MemeFmt for bool { fn meme_fmt(&self) -> String { format!(\"{}\", self) } }",
        "impl _MemeFmt for String { fn meme_fmt(&self) -> String { self.clone() } }",
        "impl<T: _MemeFmt> _MemeFmt for Vec<T> {",
        "    fn meme_fmt(&self) -> String {",
        "        let parts: Vec<String> = self.iter().map(|x| x.meme_fmt()).collect();",
        "        format!(\"[{}]\", parts.join(\", \"))",
        "    }",
        "}",
        "impl<K: _MemeFmt + std::cmp::Eq + std::hash::Hash, V: _MemeFmt> _MemeFmt for std::collections::HashMap<K, V> {",
        "    fn meme_fmt(&self) -> String {",
        "        let mut items: Vec<(String, String)> = self.iter().map(|(k, v)| (k.meme_fmt(), v.meme_fmt())).collect();",
        "        items.sort();",
        "        let parts: Vec<String> = items.into_iter().map(|(k, v)| format!(\"{}: {}\", k, v)).collect();",
        "        format!(\"{{{}}}\", parts.join(\", \"))",
        "    }",
        "}",
        "impl<T: _MemeFmt> _MemeFmt for Option<T> {",
        "    fn meme_fmt(&self) -> String {",
        "        match self {",
        "            Some(v) => v.meme_fmt(),",
        "            None => \"None\".to_string(),",
        "        }",
        "    }",
        "}",
        "impl<T: _MemeFmt> _MemeFmt for Box<T> {",
        "    fn meme_fmt(&self) -> String {",
        "        (**self).meme_fmt()",
        "    }",
        "}",
        "impl<T: _MemeFmt> _MemeFmt for std::rc::Rc<T> {",
        "    fn meme_fmt(&self) -> String {",
        "        (**self).meme_fmt()",
        "    }",
        "}",
        "fn _meme_fmt_slice<T: _MemeFmt>(items: &[T]) -> String {",
        "    let parts: Vec<String> = items.iter().map(|x| x.meme_fmt()).collect();",
        "    format!(\"[{}]\", parts.join(\", \"))",
        "}",
        "trait _MemeOrd {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering;",
        "}",
        "impl _MemeOrd for i64 {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering { self.cmp(other) }",
        "}",
        "impl _MemeOrd for f64 {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering { self.total_cmp(other) }",
        "}",
        "impl _MemeOrd for bool {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering { self.cmp(other) }",
        "}",
        "impl _MemeOrd for String {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering { self.cmp(other) }",
        "}",
        "impl<T: _MemeOrd> _MemeOrd for Option<T> {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering {",
        "        match (self, other) {",
        "            (None, None) => std::cmp::Ordering::Equal,",
        "            (None, Some(_)) => std::cmp::Ordering::Less,",
        "            (Some(_), None) => std::cmp::Ordering::Greater,",
        "            (Some(a), Some(b)) => a.meme_cmp(b),",
        "        }",
        "    }",
        "}",
        "impl<T: _MemeOrd> _MemeOrd for Box<T> {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering {",
        "        (**self).meme_cmp(&**other)",
        "    }",
        "}",
        "impl<T: _MemeOrd> _MemeOrd for std::rc::Rc<T> {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering {",
        "        (**self).meme_cmp(&**other)",
        "    }",
        "}",
        "impl<T: _MemeOrd> _MemeOrd for Vec<T> {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering {",
        "        for (a, b) in self.iter().zip(other.iter()) {",
        "            let ord = a.meme_cmp(b);",
        "            if ord != std::cmp::Ordering::Equal { return ord; }",
        "        }",
        "        self.len().cmp(&other.len())",
        "    }",
        "}",
        "#[derive(Clone, Debug, PartialEq)]",
        "struct _MemeSet<T> {",
        "    data: Vec<T>,",
        "}",
        "impl<T: _MemeOrd + Clone> _MemeSet<T> {",
        "    fn new() -> Self { Self { data: Vec::new() } }",
        "    fn insert(&mut self, val: T) {",
        "        match self.data.binary_search_by(|x| x.meme_cmp(&val)) {",
        "            Ok(_) => {},",
        "            Err(idx) => self.data.insert(idx, val),",
        "        }",
        "    }",
        "    fn remove(&mut self, val: &T) {",
        "        if let Ok(idx) = self.data.binary_search_by(|x| x.meme_cmp(val)) {",
        "            self.data.remove(idx);",
        "        }",
        "    }",
        "    fn contains(&self, val: &T) -> bool {",
        "        self.data.binary_search_by(|x| x.meme_cmp(val)).is_ok()",
        "    }",
        "    fn len(&self) -> i64 { self.data.len() as i64 }",
        "}",
        "impl<T: _MemeFmt> _MemeFmt for _MemeSet<T> {",
        "    fn meme_fmt(&self) -> String {",
        "        let parts: Vec<String> = self.data.iter().map(|x| x.meme_fmt()).collect();",
        "        format!(\"{{{}}}\", parts.join(\", \"))",
        "    }",
        "}",
        "impl<T: _MemeOrd> _MemeOrd for _MemeSet<T> {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering {",
        "        for (a, b) in self.data.iter().zip(other.data.iter()) {",
        "            let ord = a.meme_cmp(b);",
        "            if ord != std::cmp::Ordering::Equal { return ord; }",
        "        }",
        "        self.data.len().cmp(&other.data.len())",
        "    }",
        "}",
        "impl<K: _MemeOrd + Clone + std::cmp::Eq + std::hash::Hash, V: _MemeOrd> _MemeOrd for std::collections::HashMap<K, V> {",
        "    fn meme_cmp(&self, other: &Self) -> std::cmp::Ordering {",
        "        let mut keys_a: Vec<&K> = self.keys().collect();",
        "        keys_a.sort_by(|a, b| a.meme_cmp(b));",
        "        let mut keys_b: Vec<&K> = other.keys().collect();",
        "        keys_b.sort_by(|a, b| a.meme_cmp(b));",
        "        for (ka, kb) in keys_a.iter().zip(keys_b.iter()) {",
        "            let k_ord = ka.meme_cmp(kb);",
        "            if k_ord != std::cmp::Ordering::Equal { return k_ord; }",
        "            let va = &self[*ka];",
        "            let vb = &other[*kb];",
        "            let v_ord = va.meme_cmp(vb);",
        "            if v_ord != std::cmp::Ordering::Equal { return v_ord; }",
        "        }",
        "        self.len().cmp(&other.len())",
        "    }",
        "}",
        "",
    ]

    if gen.uses_random:
        preamble.extend(
            [
                "fn _meme_next_u64() -> u64 {",
                "    use std::sync::atomic::{AtomicU64, Ordering};",
                "    use std::time::{SystemTime, UNIX_EPOCH};",
                "    static STATE: AtomicU64 = AtomicU64::new(0);",
                "    let mut cur = STATE.load(Ordering::Relaxed);",
                "    if cur == 0 {",
                "        let nanos = SystemTime::now()",
                "            .duration_since(UNIX_EPOCH)",
                "            .map(|d| d.as_nanos() as u64)",
                "            .unwrap_or(0x9E3779B97F4A7C15);",
                "        cur = nanos ^ 0xBF58476D1CE4E5B9;",
                "    }",
                "    let mut z = cur.wrapping_add(0x9E3779B97F4A7C15);",
                "    STATE.store(z, Ordering::Relaxed);",
                "    z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);",
                "    z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);",
                "    z ^ (z >> 31)",
                "}",
                "",
                "fn _meme_rand_int(lo: i64, hi: i64) -> i64 {",
                "    if hi <= lo { return lo; }",
                "    let span = (hi as i128 - lo as i128 + 1) as u64;",
                "    lo + (_meme_next_u64() % span) as i64",
                "}",
                "",
                "fn _meme_rand_list(count: i64, lo: i64, hi: i64) -> std::rc::Rc<Vec<i64>> {",
                "    let n = if count < 0 { 0 } else { count as usize };",
                "    std::rc::Rc::new((0..n).map(|_| _meme_rand_int(lo, hi)).collect())",
                "}",
                "",
            ]
        )

    if gen.uses_argv:
        preamble.extend(
            [
                "fn _meme_arg_at(idx: i64) -> String {",
                "    if idx < 0 {",
                "        println!(\"Error: argument index {} out of range\", idx);",
                "        std::process::exit(1);",
                "    }",
                "    match std::env::args().nth(idx as usize) {",
                "        Some(s) => s,",
                "        None => {",
                "            println!(\"Error: argument index {} out of range\", idx);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_list_remove:
        preamble.extend(
            [
                "fn _meme_list_remove<T>(vec: &mut Vec<T>, idx: i64) {",
                "    if idx < 0 || (idx as usize) >= vec.len() {",
                "        println!(\"Error: list index out of range\");",
                "        std::process::exit(1);",
                "    }",
                "    vec.remove(idx as usize);",
                "}",
                "fn _meme_list_remove_last<T>(vec: &mut Vec<T>) {",
                "    if vec.is_empty() {",
                "        println!(\"Error: list index out of range\");",
                "        std::process::exit(1);",
                "    }",
                "    vec.pop();",
                "}",
                "",
            ]
        )

    if gen.uses_str_split:
        preamble.extend(
            [
                "fn _meme_str_split(s: &str, sep: &str) -> std::rc::Rc<Vec<String>> {",
                "    if sep.is_empty() {",
                "        println!(\"Error: empty separator in split\");",
                "        std::process::exit(1);",
                "    }",
                "    std::rc::Rc::new(s.split(sep).map(|p| p.to_string()).collect())",
                "}",
                "",
            ]
        )

    if gen.uses_char_at:
        preamble.extend(
            [
                "fn _meme_char_at(s: &str, idx: i64) -> String {",
                "    let bytes = s.as_bytes();",
                "    if idx < 0 || (idx as usize) >= bytes.len() {",
                "        println!(\"Error: string index {} out of range\", idx);",
                "        std::process::exit(1);",
                "    }",
                "    (bytes[idx as usize] as char).to_string()",
                "}",
                "",
            ]
        )

    if gen.uses_number_of:
        preamble.extend(
            [
                "fn _meme_number_of(s: &str) -> i64 {",
                "    if s.is_empty() {",
                "        println!(\"Error: empty string in number of\");",
                "        std::process::exit(1);",
                "    }",
                "    s.chars().next().unwrap() as u32 as i64",
                "}",
                "",
            ]
        )

    if gen.uses_character_of:
        preamble.extend(
            [
                "fn _meme_character_of(cp: i64) -> String {",
                "    if cp < 0 || cp > 0x10FFFF || (0xD800..=0xDFFF).contains(&cp) {",
                "        println!(\"Error: invalid codepoint {}\", cp);",
                "        std::process::exit(1);",
                "    }",
                "    match char::from_u32(cp as u32) {",
                "        Some(c) => c.to_string(),",
                "        None => {",
                "            println!(\"Error: invalid codepoint {}\", cp);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_sha256:
        preamble.extend(
            [
                "fn _meme_sha256(s: &str) -> String {",
                "    let bytes = s.as_bytes();",
                "    let bit_len = (bytes.len() as u64) * 8;",
                "    let mut data = Vec::with_capacity(bytes.len() + 72);",
                "    data.extend_from_slice(bytes);",
                "    data.push(0x80);",
                "    while (data.len() % 64) != 56 {",
                "        data.push(0);",
                "    }",
                "    data.extend_from_slice(&bit_len.to_be_bytes());",
                "    let mut primes = Vec::new();",
                "    let mut cand = 2u64;",
                "    while primes.len() < 64 {",
                "        let mut is_p = true;",
                "        for &p in &primes {",
                "            if cand % p == 0 { is_p = false; break; }",
                "            if p * p > cand { break; }",
                "        }",
                "        if is_p { primes.push(cand); }",
                "        cand += 1;",
                "    }",
                "    let mut h = [0u32; 8];",
                "    for i in 0..8 {",
                "        let f = (primes[i] as f64).sqrt();",
                "        h[i] = ((f - f.floor()) * 4294967296.0) as u32;",
                "    }",
                "    let mut k = [0u32; 64];",
                "    for i in 0..64 {",
                "        let f = (primes[i] as f64).cbrt();",
                "        k[i] = ((f - f.floor()) * 4294967296.0) as u32;",
                "    }",
                "    let mut w = [0u32; 64];",
                "    for chunk in data.chunks_exact(64) {",
                "        for i in 0..16 {",
                "            w[i] = u32::from_be_bytes([chunk[4*i], chunk[4*i+1], chunk[4*i+2], chunk[4*i+3]]);",
                "        }",
                "        for i in 16..64 {",
                "            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);",
                "            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);",
                "            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);",
                "        }",
                "        let mut a = h[0]; let mut b = h[1]; let mut c = h[2]; let mut d = h[3];",
                "        let mut e = h[4]; let mut f = h[5]; let mut g = h[6]; let mut hh = h[7];",
                "        for i in 0..64 {",
                "            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);",
                "            let ch = (e & f) ^ ((!e) & g);",
                "            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(k[i]).wrapping_add(w[i]);",
                "            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);",
                "            let maj = (a & b) ^ (a & c) ^ (b & c);",
                "            let t2 = s0.wrapping_add(maj);",
                "            hh = g; g = f; f = e; e = d.wrapping_add(t1);",
                "            d = c; c = b; b = a; a = t1.wrapping_add(t2);",
                "        }",
                "        h[0] = h[0].wrapping_add(a); h[1] = h[1].wrapping_add(b);",
                "        h[2] = h[2].wrapping_add(c); h[3] = h[3].wrapping_add(d);",
                "        h[4] = h[4].wrapping_add(e); h[5] = h[5].wrapping_add(f);",
                "        h[6] = h[6].wrapping_add(g); h[7] = h[7].wrapping_add(hh);",
                "    }",
                "    let mut res = String::with_capacity(64);",
                "    for val in h {",
                "        use std::fmt::Write;",
                "        write!(&mut res, \"{:08x}\", val).unwrap();",
                "    }",
                "    res",
                "}",
                "",
            ]
        )

    if gen.uses_parse_int:
        preamble.extend(
            [
                "fn _meme_parse_int(s: &str) -> i64 {",
                "    let ts = s.trim();",
                "    match ts.parse::<i64>() {",
                "        Ok(v) => v,",
                "        Err(_) => {",
                "            println!(\"Error parsing integer: {}\", s);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_parse_int_or_else:
        preamble.extend(
            [
                "fn _meme_parse_int_or_else<F: FnOnce() -> i64>(s: &str, default_fn: F) -> i64 {",
                "    let ts = s.trim();",
                "    match ts.parse::<i64>() {",
                "        Ok(v) => v,",
                "        Err(_) => default_fn(),",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_is_digit:
        preamble.extend(
            [
                "fn _meme_is_digit(s: &str) -> bool {",
                "    s.len() == 1 && s.as_bytes()[0] >= b'0' && s.as_bytes()[0] <= b'9'",
                "}",
                "",
            ]
        )

    if gen.uses_is_letter:
        preamble.extend(
            [
                "fn _meme_is_letter(s: &str) -> bool {",
                "    s.len() == 1 && ((s.as_bytes()[0] >= b'A' && s.as_bytes()[0] <= b'Z') || (s.as_bytes()[0] >= b'a' && s.as_bytes()[0] <= b'z'))",
                "}",
                "",
            ]
        )

    if gen.uses_is_upper:
        preamble.extend(
            [
                "fn _meme_is_upper(s: &str) -> bool {",
                "    s.len() == 1 && s.as_bytes()[0] >= b'A' && s.as_bytes()[0] <= b'Z'",
                "}",
                "",
            ]
        )

    if gen.uses_is_lower:
        preamble.extend(
            [
                "fn _meme_is_lower(s: &str) -> bool {",
                "    s.len() == 1 && s.as_bytes()[0] >= b'a' && s.as_bytes()[0] <= b'z'",
                "}",
                "",
            ]
        )

    if gen.uses_format_float:
        preamble.extend(
            [
                "fn _meme_format_float(v: f64, n: i64) -> String {",
                "    let mut neg = v < 0.0;",
                "    let mag = v.abs();",
                "    if n == 0 {",
                "        let r = (mag + 0.5).floor();",
                "        if r == 0.0 { neg = false; }",
                "        return if neg { format!(\"-{:.0}\", r) } else { format!(\"{:.0}\", r) };",
                "    }",
                "    let factor = 10.0_f64.powi(n as i32);",
                "    let rounded_total = (mag * factor + 0.5).floor();",
                "    let int_part = (rounded_total / factor).floor();",
                "    let frac_part = (rounded_total - int_part * factor + 0.5) as u64;",
                "    if int_part == 0.0 && frac_part == 0 { neg = false; }",
                "    let s = format!(\"{:.0}.{:0>width$}\", int_part, frac_part, width = n as usize);",
                "    if neg { format!(\"-{}\", s) } else { s }",
                "}",
                "",
            ]
        )

    if gen.uses_input:
        preamble.extend(
            [
                "fn _meme_read_line(prompt: &str) -> String {",
                "    use std::io::{self, Write};",
                "    let quiet = std::env::var(\"MEME_QUIET_PROMPTS\")",
                "        .map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), \"1\" | \"true\" | \"yes\"))",
                "        .unwrap_or(false);",
                "    if !prompt.is_empty() && !quiet {",
                "        print!(\"{}\", prompt);",
                "        let _ = io::stdout().flush();",
                "    }",
                "    let mut buf = String::new();",
                "    let _ = io::stdin().read_line(&mut buf);",
                "    buf.trim_end_matches(&['\\r', '\\n'][..]).to_string()",
                "}",
                "",
            ]
        )

    if gen.uses_json_io or gen.uses_file_io or gen.uses_json_records:
        preamble.extend(
            [
                "fn _meme_resolve_path(path: &str) -> std::path::PathBuf {",
                "    let p = std::path::Path::new(path.trim());",
                "    if p.exists() || p.is_absolute() {",
                "        return p.to_path_buf();",
                "    }",
                "    if let Ok(sd) = std::env::var(\"MEME_SOURCE_DIR\") {",
                "        let sdt = sd.trim();",
                "        if !sdt.is_empty() {",
                "            let cand = std::path::Path::new(sdt).join(p);",
                "            if cand.exists() {",
                "                return cand;",
                "            }",
                "        }",
                "    }",
                "    p.to_path_buf()",
                "}",
                "",
            ]
        )

    if gen.uses_json_records or gen.uses_json_list_opt:
        preamble.extend(_RUST_JSON_PARSER_HELPERS)

    if gen.uses_file_io:
        preamble.extend(
            [
                "fn _meme_file_exists(path: &str) -> bool {",
                "    _meme_resolve_path(path).is_file()",
                "}",
                "",
                "fn _meme_read_file_string(path: &str) -> String {",
                "    let resolved = _meme_resolve_path(path);",
                "    if !resolved.is_file() {",
                "        println!(\"Error reading file: {}\", path);",
                "        std::process::exit(1);",
                "    }",
                "    match std::fs::read_to_string(&resolved) {",
                "        Ok(s) => s,",
                "        Err(_) => {",
                "            println!(\"Error reading file: {}\", path);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
                "fn _meme_read_file_lines(path: &str) -> std::rc::Rc<Vec<String>> {",
                "    let raw = _meme_read_file_string(path);",
                "    if raw.is_empty() {",
                "        return std::rc::Rc::new(Vec::new());",
                "    }",
                "    let s = if raw.ends_with('\\n') {",
                "        &raw[..raw.len() - 1]",
                "    } else {",
                "        &raw[..]",
                "    };",
                "    std::rc::Rc::new(s.split('\\n').map(|line| line.to_string()).collect())",
                "}",
                "",
                "fn _meme_read_file_string_opt(path: &str) -> Option<String> {",
                "    let resolved = _meme_resolve_path(path);",
                "    if !resolved.is_file() {",
                "        return None;",
                "    }",
                "    std::fs::read_to_string(&resolved).ok()",
                "}",
                "",
                "fn _meme_read_file_lines_opt(path: &str) -> Option<std::rc::Rc<Vec<String>>> {",
                "    let raw = _meme_read_file_string_opt(path)?;",
                "    if raw.is_empty() {",
                "        return Some(std::rc::Rc::new(Vec::new()));",
                "    }",
                "    let s = if raw.ends_with('\\n') {",
                "        &raw[..raw.len() - 1]",
                "    } else {",
                "        &raw[..]",
                "    };",
                "    Some(std::rc::Rc::new(s.split('\\n').map(|line| line.to_string()).collect()))",
                "}",
                "",
                "fn _meme_write_file(path: &str, content: &str) {",
                "    if std::fs::write(path.trim(), content).is_err() {",
                "        println!(\"Error writing file: {}\", path);",
                "        std::process::exit(1);",
                "    }",
                "}",
                "",
                "fn _meme_append_file(path: &str, content: &str) {",
                "    use std::io::Write;",
                "    match std::fs::OpenOptions::new().create(true).append(true).open(path.trim()) {",
                "        Ok(mut f) => {",
                "            if f.write_all(content.as_bytes()).is_err() {",
                "                println!(\"Error writing file: {}\", path);",
                "                std::process::exit(1);",
                "            }",
                "        }",
                "        Err(_) => {",
                "            println!(\"Error writing file: {}\", path);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
                "fn _meme_copy_file(src: &str, dst: &str) {",
                "    let rsrc = _meme_resolve_path(src);",
                "    if !rsrc.is_file() {",
                "        println!(\"Error copying file: {}\", src);",
                "        std::process::exit(1);",
                "    }",
                "    if std::fs::copy(&rsrc, dst.trim()).is_err() {",
                "        println!(\"Error copying file: {}\", src);",
                "        std::process::exit(1);",
                "    }",
                "}",
                "",
                "fn _meme_move_file(src: &str, dst: &str) {",
                "    let rsrc = _meme_resolve_path(src);",
                "    if !rsrc.is_file() {",
                "        println!(\"Error moving file: {}\", src);",
                "        std::process::exit(1);",
                "    }",
                "    let target = dst.trim();",
                "    if std::fs::rename(&rsrc, target).is_err() {",
                "        if std::fs::copy(&rsrc, target).is_err() || std::fs::remove_file(&rsrc).is_err() {",
                "            println!(\"Error moving file: {}\", src);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
                "fn _meme_rename_file(path: &str, new_name: &str) {",
                "    let rsrc = _meme_resolve_path(path);",
                "    if !rsrc.is_file() {",
                "        println!(\"Error renaming file: {}\", path);",
                "        std::process::exit(1);",
                "    }",
                "    let p = std::path::Path::new(path.trim());",
                "    let parent = p.parent().unwrap_or(std::path::Path::new(\"\"));",
                "    let nn = std::path::Path::new(new_name.trim()).file_name().unwrap_or(std::ffi::OsStr::new(new_name.trim()));",
                "    let target = if parent.as_os_str().is_empty() {",
                "        std::path::PathBuf::from(nn)",
                "    } else {",
                "        parent.join(nn)",
                "    };",
                "    if std::fs::rename(&rsrc, &target).is_err() {",
                "        if std::fs::copy(&rsrc, &target).is_err() || std::fs::remove_file(&rsrc).is_err() {",
                "            println!(\"Error renaming file: {}\", path);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
                "fn _meme_delete_file(path: &str) {",
                "    let rsrc = _meme_resolve_path(path);",
                "    if !rsrc.is_file() {",
                "        println!(\"Error deleting file: {}\", path);",
                "        std::process::exit(1);",
                "    }",
                "    if std::fs::remove_file(&rsrc).is_err() {",
                "        println!(\"Error deleting file: {}\", path);",
                "        std::process::exit(1);",
                "    }",
                "}",
                "",
                "fn _meme_create_directory(path: &str) {",
                "    if std::fs::create_dir_all(path.trim()).is_err() {",
                "        println!(\"Error creating directory: {}\", path);",
                "        std::process::exit(1);",
                "    }",
                "}",
                "",
                "fn _meme_list_files(path: &str) -> std::rc::Rc<Vec<String>> {",
                "    let rpath = _meme_resolve_path(path);",
                "    if !rpath.is_dir() {",
                "        println!(\"Error listing directory: {}\", path);",
                "        std::process::exit(1);",
                "    }",
                "    match std::fs::read_dir(&rpath) {",
                "        Ok(entries) => {",
                "            let mut res: Vec<String> = entries",
                "                .filter_map(|e| e.ok())",
                "                .map(|e| e.file_name().to_string_lossy().into_owned())",
                "                .collect();",
                "            res.sort();",
                "            std::rc::Rc::new(res)",
                "        }",
                "        Err(_) => {",
                "            println!(\"Error listing directory: {}\", path);",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_json_io:
        preamble.extend(
            [
                "#[derive(Debug)]",
                "enum _MemeJsonTok {",
                "    Str(String),",
                "    Bool(bool),",
                "    Num(String),",
                "}",
                "",
                "fn _meme_json_fail(msg: &str) -> ! {",
                "    eprintln!(\"Error reading JSON file: {}\", msg);",
                "    std::process::exit(1);",
                "}",
                "",
                "fn _meme_parse_json_tokens(path: &str) -> Vec<_MemeJsonTok> {",
                "    let resolved = _meme_resolve_path(path);",
                "    let raw = match std::fs::read_to_string(&resolved) {",
                "        Ok(s) => s,",
                "        Err(e) => _meme_json_fail(&e.to_string()),",
                "    };",
                "    let chars: Vec<char> = raw.chars().collect();",
                "    let n = chars.len();",
                "    let mut i = 0;",
                "    while i < n && chars[i].is_whitespace() { i += 1; }",
                "    if i >= n || chars[i] != '[' {",
                "        _meme_json_fail(\"expected JSON array\");",
                "    }",
                "    i += 1;",
                "    while i < n && chars[i].is_whitespace() { i += 1; }",
                "    let mut out = Vec::new();",
                "    if i < n && chars[i] == ']' {",
                "        i += 1;",
                "        while i < n && chars[i].is_whitespace() { i += 1; }",
                "        if i != n { _meme_json_fail(\"trailing data after JSON array\"); }",
                "        return out;",
                "    }",
                "    loop {",
                "        while i < n && chars[i].is_whitespace() { i += 1; }",
                "        if i >= n { _meme_json_fail(\"unterminated JSON array\"); }",
                "        let ch = chars[i];",
                "        if ch == '\"' {",
                "            i += 1;",
                "            let mut s = String::new();",
                "            while i < n && chars[i] != '\"' {",
                "                if chars[i] == '\\\\' {",
                "                    i += 1;",
                "                    if i >= n { _meme_json_fail(\"unterminated string escape\"); }",
                "                    match chars[i] {",
                "                        '\"' => s.push('\"'),",
                "                        '\\\\' => s.push('\\\\'),",
                "                        '/' => s.push('/'),",
                "                        'b' => s.push('\\u{0008}'),",
                "                        'f' => s.push('\\u{000C}'),",
                "                        'n' => s.push('\\n'),",
                "                        'r' => s.push('\\r'),",
                "                        't' => s.push('\\t'),",
                "                        'u' => {",
                "                            if i + 4 >= n { _meme_json_fail(\"invalid unicode escape\"); }",
                "                            let hex: String = chars[i + 1..=i + 4].iter().collect();",
                "                            let code = u32::from_str_radix(&hex, 16).unwrap_or_else(|_| _meme_json_fail(\"invalid unicode escape\"));",
                "                            let c = std::char::from_u32(code).unwrap_or_else(|| _meme_json_fail(\"invalid unicode scalar\"));",
                "                            s.push(c);",
                "                            i += 4;",
                "                        }",
                "                        _ => _meme_json_fail(\"invalid escape sequence\"),",
                "                    }",
                "                } else {",
                "                    s.push(chars[i]);",
                "                }",
                "                i += 1;",
                "            }",
                "            if i >= n || chars[i] != '\"' { _meme_json_fail(\"unterminated string literal\"); }",
                "            i += 1;",
                "            out.push(_MemeJsonTok::Str(s));",
                "        } else {",
                "            let start = i;",
                "            while i < n && !chars[i].is_whitespace() && chars[i] != ',' && chars[i] != ']' {",
                "                if chars[i] == '[' || chars[i] == '{' || chars[i] == '}' || chars[i] == '\"' {",
                "                    _meme_json_fail(\"unexpected nested or malformed token\");",
                "                }",
                "                i += 1;",
                "            }",
                "            if i == start { _meme_json_fail(\"expected element\"); }",
                "            let tok: String = chars[start..i].iter().collect();",
                "            if tok == \"true\" {",
                "                out.push(_MemeJsonTok::Bool(true));",
                "            } else if tok == \"false\" {",
                "                out.push(_MemeJsonTok::Bool(false));",
                "            } else if tok == \"null\" {",
                "                _meme_json_fail(\"JSON null is not allowed\");",
                "            } else {",
                "                out.push(_MemeJsonTok::Num(tok));",
                "            }",
                "        }",
                "        while i < n && chars[i].is_whitespace() { i += 1; }",
                "        if i < n && chars[i] == ',' {",
                "            i += 1;",
                "            continue;",
                "        } else if i < n && chars[i] == ']' {",
                "            i += 1;",
                "            break;",
                "        } else {",
                "            _meme_json_fail(\"expected `,` or `]`\");",
                "        }",
                "    }",
                "    while i < n && chars[i].is_whitespace() { i += 1; }",
                "    if i != n { _meme_json_fail(\"trailing data after JSON array\"); }",
                "    out",
                "}",
                "",
                "fn _meme_read_json_list_int(path: &str) -> std::rc::Rc<Vec<i64>> {",
                "    let mut out = Vec::new();",
                "    for tok in _meme_parse_json_tokens(path) {",
                "        match tok {",
                "            _MemeJsonTok::Num(s) => match s.parse::<i64>() {",
                "                Ok(v) => out.push(v),",
                "                Err(_) => _meme_json_fail(&format!(\"expected Int, got `{}`\", s)),",
                "            },",
                "            _ => _meme_json_fail(\"expected Int element\"),",
                "        }",
                "    }",
                "    std::rc::Rc::new(out)",
                "}",
                "",
                "fn _meme_read_json_list_float(path: &str) -> std::rc::Rc<Vec<f64>> {",
                "    let mut out = Vec::new();",
                "    for tok in _meme_parse_json_tokens(path) {",
                "        match tok {",
                "            _MemeJsonTok::Num(s) => match s.parse::<f64>() {",
                "                Ok(v) if v.is_finite() => out.push(v),",
                "                _ => _meme_json_fail(&format!(\"expected Float, got `{}`\", s)),",
                "            },",
                "            _ => _meme_json_fail(\"expected Float element\"),",
                "        }",
                "    }",
                "    std::rc::Rc::new(out)",
                "}",
                "",
                "fn _meme_read_json_list_string(path: &str) -> std::rc::Rc<Vec<String>> {",
                "    let mut out = Vec::new();",
                "    for tok in _meme_parse_json_tokens(path) {",
                "        match tok {",
                "            _MemeJsonTok::Str(s) => out.push(s),",
                "            _ => _meme_json_fail(\"expected String element\"),",
                "        }",
                "    }",
                "    std::rc::Rc::new(out)",
                "}",
                "",
                "fn _meme_read_json_list_bool(path: &str) -> std::rc::Rc<Vec<bool>> {",
                "    let mut out = Vec::new();",
                "    for tok in _meme_parse_json_tokens(path) {",
                "        match tok {",
                "            _MemeJsonTok::Bool(b) => out.push(b),",
                "            _ => _meme_json_fail(\"expected Bool element\"),",
                "        }",
                "    }",
                "    std::rc::Rc::new(out)",
                "}",
                "",
            ]
        )

    if gen.uses_optional_helpers:
        preamble.extend(
            [
                "fn _meme_unwrap<T>(opt: Option<T>) -> T {",
                "    match opt {",
                "        Some(v) => v,",
                "        None => {",
                "            println!(\"Unwrap failed: Optional value is nothing\");",
                "            std::process::exit(1);",
                "        }",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_json_list_opt:
        preamble.extend(
            [
                "fn _meme_read_json_list_int_opt(path: &str) -> Option<std::rc::Rc<Vec<i64>>> {",
                "    let jv = _meme_read_json_file(path)?;",
                "    if let _MemeJV::Arr(items) = jv {",
                "        let mut out = Vec::new();",
                "        for item in items {",
                "            if let _MemeJV::Num(_, true, i) = item {",
                "                out.push(i);",
                "            } else {",
                "                return None;",
                "            }",
                "        }",
                "        Some(std::rc::Rc::new(out))",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
                "fn _meme_read_json_list_float_opt(path: &str) -> Option<std::rc::Rc<Vec<f64>>> {",
                "    let jv = _meme_read_json_file(path)?;",
                "    if let _MemeJV::Arr(items) = jv {",
                "        let mut out = Vec::new();",
                "        for item in items {",
                "            if let _MemeJV::Num(f, _, _) = item {",
                "                out.push(f);",
                "            } else {",
                "                return None;",
                "            }",
                "        }",
                "        Some(std::rc::Rc::new(out))",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
                "fn _meme_read_json_list_string_opt(path: &str) -> Option<std::rc::Rc<Vec<String>>> {",
                "    let jv = _meme_read_json_file(path)?;",
                "    if let _MemeJV::Arr(items) = jv {",
                "        let mut out = Vec::new();",
                "        for item in items {",
                "            if let _MemeJV::Str(s) = item {",
                "                out.push(s);",
                "            } else {",
                "                return None;",
                "            }",
                "        }",
                "        Some(std::rc::Rc::new(out))",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
                "fn _meme_read_json_list_bool_opt(path: &str) -> Option<std::rc::Rc<Vec<bool>>> {",
                "    let jv = _meme_read_json_file(path)?;",
                "    if let _MemeJV::Arr(items) = jv {",
                "        let mut out = Vec::new();",
                "        for item in items {",
                "            if let _MemeJV::Bool(b) = item {",
                "                out.push(b);",
                "            } else {",
                "                return None;",
                "            }",
                "        }",
                "        Some(std::rc::Rc::new(out))",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_json_records:
        all_read = _get_transitive_json_records(gen.json_records_read | gen.json_record_lists_read, gen.records)
        for r_name in sorted(all_read):
            r_fields = gen.records.get(r_name, {})
            record_blocks.extend(_emit_rust_json_record_reader(r_name, r_fields, set(gen.records.keys())))

    if gen.uses_json_write:
        gen.uses_format_float = True
        preamble.extend([
            "fn _meme_format_json_float(v: f64) -> String {",
            "    let mut s = _meme_format_float(v, 6);",
            "    if s.contains('.') {",
            "        while s.ends_with('0') {",
            "            s.pop();",
            "        }",
            "        if s.ends_with('.') {",
            "            s.push('0');",
            "        }",
            "    }",
            "    s",
            "}",
            "",
            "fn _meme_escape_json_str(s: &str) -> String {",
            "    let mut out = String::from(\"\\\"\");",
            "    for b in s.bytes() {",
            "        match b {",
            "            b'\"' => out.push_str(\"\\\\\\\"\"),",
            "            b'\\\\' => out.push_str(\"\\\\\\\\\"),",
            "            b'\\n' => out.push_str(\"\\\\n\"),",
            "            b'\\r' => out.push_str(\"\\\\r\"),",
            "            b'\\t' => out.push_str(\"\\\\t\"),",
            "            0..=0x1f => {",
            "                out.push_str(&format!(\"\\\\u{:04x}\", b));",
            "            }",
            "            _ => out.push(b as char),",
            "        }",
            "    }",
            "    out.push('\"');",
            "    out",
            "}",
            "",
        ])
        all_write = _get_transitive_json_records(gen.json_records_write, gen.records)
        for r_name in sorted(all_write):
            r_fields = gen.records.get(r_name, {})
            record_blocks.extend(_emit_rust_json_record_writer(r_name, r_fields, set(gen.records.keys())))

    out = preamble + record_blocks + fn_blocks + ["fn main() {"] + main_lines + ["}", ""]
    return "\n".join(out)

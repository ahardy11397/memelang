"""Deterministic standalone Rust (`rustc`) code generator for Memelang ProgramIR."""

from __future__ import annotations

import json

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


def _escape_rust_str(val: str) -> str:
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
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


_RUST_KEYWORDS = {
    "as", "async", "await", "break", "const", "continue", "crate", "dyn", "else",
    "enum", "extern", "false", "fn", "for", "if", "impl", "in", "let", "loop",
    "match", "mod", "move", "mut", "pub", "ref", "return", "self", "Self",
    "static", "struct", "super", "trait", "true", "type", "unsafe", "use",
    "where", "while", "abstract", "become", "box", "do", "final", "gen", "macro",
    "override", "priv", "try", "typeof", "unsized", "virtual", "yield", "main",
}


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


def _set_type_of(set_type: str) -> str | None:
    if set_type.startswith("Set<") and set_type.endswith(">"):
        return set_type[4:-1].strip()
    return None


def _rust_ident(name: str) -> str:
    return f"meme_{name}" if name in _RUST_KEYWORDS or name.startswith("_meme_") else name


def _rust_type(meme_type: MemeType | str) -> str:
    if meme_type.startswith("List<") and meme_type.endswith(">"):
        inner = meme_type[5:-1]
        return f"Vec<{_rust_type(inner)}>"
    if meme_type.startswith("Optional<") and meme_type.endswith(">"):
        inner = meme_type[9:-1]
        return f"Option<{_rust_type(inner)}>"
    map_t = _map_types_of(meme_type)
    if map_t is not None:
        return f"std::collections::HashMap<{_rust_type(map_t[0])}, {_rust_type(map_t[1])}>"
    set_t = _set_type_of(meme_type)
    if set_t is not None:
        return f"_MemeSet<{_rust_type(set_t)}>"
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


class _RustGen:
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

    def infer_type(self, expr: IRExpr, scope: dict[str, MemeType]) -> MemeType:
        if isinstance(expr, FloatOfExpr):
            return "Float"
        if isinstance(expr, NumberOfExpr):
            return "Int"
        if isinstance(expr, CharacterOfExpr):
            return "String"
        if isinstance(expr, LiteralExpr):
            return expr.data_type
        if isinstance(expr, ListLiteralExpr):
            return f"List<{expr.element_type}>"  # type: ignore[return-value]
        if isinstance(expr, VarRefExpr):
            return scope.get(expr.name, "Int")
        if isinstance(expr, RandomListExpr):
            return "List<Int>"
        if isinstance(expr, ReadJsonListExpr):
            t = f"List<{expr.element_type}>"
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return t  # type: ignore[return-value]
            if expr.default_val is not None:
                return f"Optional<{t}>"  # type: ignore[return-value]
            return t  # type: ignore[return-value]
        if isinstance(expr, ReadJsonRecordExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return expr.record_name  # type: ignore[return-value]
            return f"Optional<{expr.record_name}>"  # type: ignore[return-value]
        if isinstance(expr, ReadJsonRecordsExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return f"List<{expr.record_name}>"  # type: ignore[return-value]
            return f"Optional<List<{expr.record_name}>>"  # type: ignore[return-value]
        if isinstance(expr, CurrentEpochExpr):
            return "Int"
        if isinstance(expr, EnvVarExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return "String"
            return "Optional<String>"
        if isinstance(expr, StringSplitExpr):
            return "List<String>"
        if isinstance(expr, ListFilesExpr):
            return "List<String>"
        if isinstance(expr, (StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr, FileExistsExpr, IsDigitExpr, IsLetterExpr, IsUpperExpr, IsLowerExpr)):
            return "Bool"
        if isinstance(
            expr,
            (RandomIntExpr, ListLengthExpr, StringLengthExpr, StringIndexOfExpr, ArgCountExpr, ParseIntExpr, ParseIntOrDefaultExpr),
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
                ArgAtExpr,
                FormatIntExpr,
                FormatFloatExpr,
            ),
        ):
            return "String"
        if isinstance(expr, ReadFileStringExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return "String"
            if expr.default_val is not None:
                return "Optional<String>"
            return "String"
        if isinstance(expr, ReadFileLinesExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return "List<String>"
            if expr.default_val is not None:
                return "Optional<List<String>>"
            return "List<String>"
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
        if isinstance(expr, EmptySetExpr):
            return f"Set<{expr.element_type}>"
        if isinstance(expr, SetContainsExpr):
            return "Bool"
        if isinstance(expr, SetLengthExpr):
            return "Int"
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
                return f"Vec::<{el_rust}>::new()"
            inner = ", ".join(self.gen_expr(e, scope) for e in expr.elements)
            return f"vec![{inner}]"

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
            base = f"{self.gen_expr(expr.target, scope)}[({self.gen_expr(expr.index, scope)}) as usize]"
            if t == "String" or t.startswith("List<") or t in self.records or t.startswith("Map<"):
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
            fields = ", ".join(
                f"{_rust_ident(f.name)}: {self.gen_expr(f.value, scope)}" for f in expr.fields
            )
            return f"{_rust_ident(expr.record_name)} {{ {fields} }}"

        if isinstance(expr, RecordFieldExpr):
            return f"{self.gen_expr(expr.target, scope)}.{_rust_ident(expr.field_name)}.clone()"

        if isinstance(expr, MapLiteralExpr):
            if not expr.entries:
                return f"std::collections::HashMap::<{_rust_type(expr.key_type)}, {_rust_type(expr.value_type)}>::new()"
            inits = "; ".join(
                f"_m.insert({self.gen_expr(e.key, scope)}, {self.gen_expr(e.value, scope)})"
                for e in expr.entries
            )
            return f"{{ let mut _m = std::collections::HashMap::new(); {inits}; _m }}"

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
            return f"_MemeSet::<{_rust_type(expr.element_type)}>::new()"

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
                    f"{pad}{tgt}.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));"
                ]
            return [
                f"{pad}{tgt}.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));"
            ]

        if isinstance(stmt, ClampCollectionStmt):
            tgt = _rust_ident(stmt.target)
            lo = self.gen_expr(stmt.min_val, scope)
            hi = self.gen_expr(stmt.max_val, scope)
            return [
                f"{pad}let (_lo, _hi) = ({lo}, {hi});",
                f"{pad}for _x in {tgt}.iter_mut() {{",
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
                f"{pad}{tgt} = {tgt}.into_iter().filter(|_item_ref| {{",
                f"{pad}    let {iv} = _item_ref.clone();",
                f"{pad}    {pred}",
                f"{pad}}}).collect();",
            ]

        if isinstance(stmt, ListAppendStmt):
            return [f"{pad}{_rust_ident(stmt.target)}.push({self.gen_expr(stmt.value, scope)});"]

        if isinstance(stmt, ListInsertStmt):
            return [
                f"{pad}{_rust_ident(stmt.target)}.insert(({self.gen_expr(stmt.index, scope)}) as usize, {self.gen_expr(stmt.value, scope)});"
            ]

        if isinstance(stmt, ListSetIndexStmt):
            tgt = _rust_ident(stmt.target)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope)
            if stmt.nested_index is not None:
                nidx = self.gen_expr(stmt.nested_index, scope)
                return [f"{pad}{tgt}[({idx}) as usize][({nidx}) as usize] = {val};"]
            return [f"{pad}{tgt}[({idx}) as usize] = {val};"]

        if isinstance(stmt, ListRemoveStmt):
            self.uses_list_remove = True
            tgt = _rust_ident(stmt.target)
            if stmt.index is not None:
                idx = self.gen_expr(stmt.index, scope)
                return [f"{pad}_meme_list_remove(&mut {tgt}, {idx});"]
            return [f"{pad}_meme_list_remove_last(&mut {tgt});"]

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
                    f"{pad}    let mut _meme_keys: Vec<_> = {col_ident}.keys().cloned().collect();",
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
                    f"{pad}    let mut _meme_items: Vec<_> = {col_ident}.data.clone();",
                ]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _rust_ident(stmt.index_var)
                    lines.append(
                        f"{pad}    for (_meme_idx, mut {item_ident}) in _meme_items.into_iter().enumerate() {{"
                    )
                    lines.append(f"{pad}        let mut {idx_ident}: i64 = _meme_idx as i64;")
                else:
                    lines.append(f"{pad}    for mut {item_ident} in _meme_items.into_iter() {{")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines
            else:
                sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _rust_ident(stmt.index_var)
                    lines = [
                        f"{pad}for (_meme_idx, mut {item_ident}) in {col_ident}.clone().into_iter().enumerate() {{",
                        f"{pad}    let mut {idx_ident}: i64 = _meme_idx as i64;",
                    ]
                else:
                    lines = [
                        f"{pad}for mut {item_ident} in {col_ident}.clone().into_iter() {{"
                    ]
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 1))
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
            return [
                f"{pad}{_rust_ident(stmt.target)}.{_rust_ident(stmt.field_name)} = {self.gen_expr(stmt.value, scope)};"
            ]

        if isinstance(stmt, MapSetStmt):
            return [
                f"{pad}{_rust_ident(stmt.target)}.insert({self.gen_expr(stmt.key, scope)}, {self.gen_expr(stmt.value, scope)});"
            ]

        if isinstance(stmt, SetAddStmt):
            tgt = _rust_ident(stmt.target)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt}.insert({val});"]

        if isinstance(stmt, SetRemoveStmt):
            tgt = _rust_ident(stmt.target)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt}.remove(&({val}));"]

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


def _emit_rust_json_record_reader(r_name: str, fields: dict[str, MemeType]) -> list[str]:
    ident = _rust_ident(r_name)
    lines = [
        f"fn _meme_parse_record_{ident}(jv: &_MemeJV) -> Option<{ident}> {{",
        "    if let _MemeJV::Obj(_) = jv {",
        f"        Some({ident} {{",
    ]
    for fname, ftype in fields.items():
        fn_str = json.dumps(fname)
        f_ident = _rust_ident(fname)
        if ftype == "Int":
            lines.extend([
                f"            {f_ident}: {{",
                f"                let f_val = _meme_find_field(jv, {fn_str})?;",
                "                if let _MemeJV::Num(_, is_int, ival) = f_val {",
                "                    if !*is_int { return None; }",
                "                    *ival",
                "                } else {",
                "                    return None;",
                "                }",
                "            },",
            ])
        elif ftype == "Float":
            lines.extend([
                f"            {f_ident}: {{",
                f"                let f_val = _meme_find_field(jv, {fn_str})?;",
                "                if let _MemeJV::Num(num, _, _) = f_val {",
                "                    *num",
                "                } else {",
                "                    return None;",
                "                }",
                "            },",
            ])
        elif ftype == "String":
            lines.extend([
                f"            {f_ident}: {{",
                f"                let f_val = _meme_find_field(jv, {fn_str})?;",
                "                if let _MemeJV::Str(s) = f_val {",
                "                    s.clone()",
                "                } else {",
                "                    return None;",
                "                }",
                "            },",
            ])
        elif ftype == "Bool":
            lines.extend([
                f"            {f_ident}: {{",
                f"                let f_val = _meme_find_field(jv, {fn_str})?;",
                "                if let _MemeJV::Bool(b) = f_val {",
                "                    *b",
                "                } else {",
                "                    return None;",
                "                }",
                "            },",
            ])
        elif ftype.startswith("Optional<"):
            inner = ftype[9:-1]
            lines.extend([
                f"            {f_ident}: {{",
                f"                match _meme_find_field(jv, {fn_str}) {{",
                "                    None | Some(_MemeJV::Null) => None,",
            ])
            if inner == "Int":
                lines.extend([
                    "                    Some(_MemeJV::Num(_, is_int, ival)) if *is_int => Some(*ival),",
                    "                    _ => return None,",
                ])
            elif inner == "Float":
                lines.extend([
                    "                    Some(_MemeJV::Num(num, _, _)) => Some(*num),",
                    "                    _ => return None,",
                ])
            elif inner == "String":
                lines.extend([
                    "                    Some(_MemeJV::Str(s)) => Some(s.clone()),",
                    "                    _ => return None,",
                ])
            elif inner == "Bool":
                lines.extend([
                    "                    Some(_MemeJV::Bool(b)) => Some(*b),",
                    "                    _ => return None,",
                ])
            lines.extend([
                "                }",
                "            },",
            ])
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
        f"fn _meme_read_json_records_{ident}(path: &str) -> Option<Vec<{ident}>> {{",
        "    let jv = _meme_read_json_file(path)?;",
        "    if let _MemeJV::Arr(items) = jv {",
        "        let mut out = Vec::new();",
        "        for item in items {",
        f"            out.push(_meme_parse_record_{ident}(&item)?);",
        "        }",
        "        Some(out)",
        "    } else {",
        "        None",
        "    }",
        "}",
        "",
    ])
    return lines


def _emit_rust_json_record_writer(r_name: str, fields: dict[str, MemeType]) -> list[str]:
    ident = _rust_ident(r_name)
    lines = [
        f"fn _meme_serialize_json_record_{ident}(rec: &{ident}) -> String {{",
        "    let mut parts: Vec<String> = Vec::new();",
    ]
    for fname, ftype in fields.items():
        k_str = json.dumps(fname) + ":"
        f_ident = _rust_ident(fname)
        if ftype == "Int":
            val_code = f"rec.{f_ident}.to_string()"
        elif ftype == "Float":
            val_code = f"_meme_format_json_float(rec.{f_ident})"
        elif ftype == "String":
            val_code = f"_meme_escape_json_str(&rec.{f_ident})"
        elif ftype == "Bool":
            val_code = f"(if rec.{f_ident} {{ \"true\" }} else {{ \"false\" }}).to_string()"
        elif ftype.startswith("Optional<"):
            inner = ftype[9:-1]
            if inner == "Int":
                inner_code = "v.to_string()"
            elif inner == "Float":
                inner_code = "_meme_format_json_float(*v)"
            elif inner == "String":
                inner_code = "_meme_escape_json_str(v)"
            elif inner == "Bool":
                inner_code = "(if *v { \"true\" } else { \"false\" }).to_string()"
            else:
                inner_code = "v.to_string()"
            val_code = f"(match &rec.{f_ident} {{ None => \"null\".to_string(), Some(v) => {inner_code} }})"
        else:
            val_code = f"rec.{f_ident}.to_string()"
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
                "fn _meme_rand_list(count: i64, lo: i64, hi: i64) -> Vec<i64> {",
                "    let n = if count < 0 { 0 } else { count as usize };",
                "    (0..n).map(|_| _meme_rand_int(lo, hi)).collect()",
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
                "fn _meme_str_split(s: &str, sep: &str) -> Vec<String> {",
                "    if sep.is_empty() {",
                "        println!(\"Error: empty separator in split\");",
                "        std::process::exit(1);",
                "    }",
                "    s.split(sep).map(|p| p.to_string()).collect()",
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
                "fn _meme_read_file_lines(path: &str) -> Vec<String> {",
                "    let raw = _meme_read_file_string(path);",
                "    if raw.is_empty() {",
                "        return Vec::new();",
                "    }",
                "    let s = if raw.ends_with('\\n') {",
                "        &raw[..raw.len() - 1]",
                "    } else {",
                "        &raw[..]",
                "    };",
                "    s.split('\\n').map(|line| line.to_string()).collect()",
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
                "fn _meme_read_file_lines_opt(path: &str) -> Option<Vec<String>> {",
                "    let raw = _meme_read_file_string_opt(path)?;",
                "    if raw.is_empty() {",
                "        return Some(Vec::new());",
                "    }",
                "    let s = if raw.ends_with('\\n') {",
                "        &raw[..raw.len() - 1]",
                "    } else {",
                "        &raw[..]",
                "    };",
                "    Some(s.split('\\n').map(|line| line.to_string()).collect())",
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
                "fn _meme_list_files(path: &str) -> Vec<String> {",
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
                "            res",
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
                "fn _meme_read_json_list_int(path: &str) -> Vec<i64> {",
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
                "    out",
                "}",
                "",
                "fn _meme_read_json_list_float(path: &str) -> Vec<f64> {",
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
                "    out",
                "}",
                "",
                "fn _meme_read_json_list_string(path: &str) -> Vec<String> {",
                "    let mut out = Vec::new();",
                "    for tok in _meme_parse_json_tokens(path) {",
                "        match tok {",
                "            _MemeJsonTok::Str(s) => out.push(s),",
                "            _ => _meme_json_fail(\"expected String element\"),",
                "        }",
                "    }",
                "    out",
                "}",
                "",
                "fn _meme_read_json_list_bool(path: &str) -> Vec<bool> {",
                "    let mut out = Vec::new();",
                "    for tok in _meme_parse_json_tokens(path) {",
                "        match tok {",
                "            _MemeJsonTok::Bool(b) => out.push(b),",
                "            _ => _meme_json_fail(\"expected Bool element\"),",
                "        }",
                "    }",
                "    out",
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
                "fn _meme_read_json_list_int_opt(path: &str) -> Option<Vec<i64>> {",
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
                "        Some(out)",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
                "fn _meme_read_json_list_float_opt(path: &str) -> Option<Vec<f64>> {",
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
                "        Some(out)",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
                "fn _meme_read_json_list_string_opt(path: &str) -> Option<Vec<String>> {",
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
                "        Some(out)",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
                "fn _meme_read_json_list_bool_opt(path: &str) -> Option<Vec<bool>> {",
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
                "        Some(out)",
                "    } else {",
                "        None",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_json_records:
        for r_name in sorted(gen.json_records_read | gen.json_record_lists_read):
            r_fields = gen.records.get(r_name, {})
            record_blocks.extend(_emit_rust_json_record_reader(r_name, r_fields))

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
        for r_name in sorted(gen.json_records_write):
            r_fields = gen.records.get(r_name, {})
            record_blocks.extend(_emit_rust_json_record_writer(r_name, r_fields))

    out = preamble + record_blocks + fn_blocks + ["fn main() {"] + main_lines + ["}", ""]
    return "\n".join(out)

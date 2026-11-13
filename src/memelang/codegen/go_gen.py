"""Deterministic standalone Go (`go build`) code generator for Memelang ProgramIR."""

from __future__ import annotations

import subprocess
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

_GO_KEYWORDS = {
    "break", "default", "func", "interface", "select",
    "case", "defer", "go", "map", "struct",
    "chan", "else", "goto", "package", "switch",
    "const", "fallthrough", "if", "range", "type",
    "continue", "for", "import", "return", "var",
    "nil", "true", "false", "iota",
    "append", "cap", "close", "complex", "copy", "delete", "imag", "len", "make", "new", "panic", "print", "println", "real", "recover",
    "bool", "byte", "complex64", "complex128", "error", "float32", "float64", "int", "int8", "int16", "int32", "int64", "rune", "string", "uint", "uint8", "uint16", "uint32", "uint64", "uintptr",
    "main",
}


def _go_ident(name: str) -> str:
    cleaned = name.replace("-", "_")
    if cleaned in _GO_KEYWORDS or cleaned.startswith("_meme_"):
        return f"m_{cleaned}"
    return cleaned


def _escape_go_str(val: str) -> str:
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


def _go_type(meme_type: str) -> str:
    mapping = {
        "Int": "int64",
        "Float": "float64",
        "Bool": "bool",
        "String": "string",
        "Void": "",
    }
    if meme_type in mapping:
        return mapping[meme_type]
    if meme_type.startswith("List<") and meme_type.endswith(">"):
        inner = meme_type[5:-1]
        return f"[]{_go_type(inner)}"
    if meme_type.startswith("Map<") and meme_type.endswith(">"):
        mt = _map_types_of(meme_type)
        if mt is not None:
            return f"map[{_go_type(mt[0])}]{_go_type(mt[1])}"
    if meme_type.startswith("Optional<") and meme_type.endswith(">"):
        inner = meme_type[9:-1]
        return f"*{_go_type(inner)}"
    return _go_ident(meme_type)


class _GoGen:
    def __init__(self) -> None:
        self.uses_fmt = False
        self.uses_math = False
        self.uses_os = False
        self.uses_filepath = False
        self.uses_reflect = False
        self.uses_sort = False
        self.uses_strconv = False
        self.uses_strings = False
        self.uses_bufio = False
        self.uses_bytes = False
        self.uses_json = False
        self.uses_rand = False
        self.uses_slices = False
        self.uses_list_remove = False
        self.uses_parse_int_or_else = False
        self.uses_is_digit = False

        self.uses_meme_fmt = False
        self.uses_int_div = False
        self.uses_int_mod = False
        self.uses_random_helpers = False
        self.uses_argv_helpers = False
        self.uses_input_helpers = False
        self.uses_path_helpers = False
        self.uses_file_io = False
        self.uses_json_io = False
        self.uses_str_split = False
        self.uses_char_at = False
        self.uses_str_slice = False
        self.uses_optional_helpers = False
        self.uses_map_helpers = False

        self.func_returns: dict[str, MemeType] = {}
        self.records: dict[str, dict[str, MemeType]] = {}

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
        if isinstance(expr, ListFilesExpr):
            return "List<String>"
        if isinstance(expr, (StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr, FileExistsExpr, IsDigitExpr)):
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

    def gen_expr(self, expr: IRExpr, scope: dict[str, MemeType]) -> str:
        if isinstance(expr, LiteralExpr):
            if expr.data_type == "Bool":
                return "true" if expr.value else "false"
            if expr.data_type == "Int":
                return f"int64({expr.value})"
            if expr.data_type == "Float":
                s = repr(float(expr.value))  # type: ignore[arg-type]
                if "." not in s and "e" not in s and "E" not in s:
                    s += ".0"
                return f"float64({s})"
            if expr.data_type == "String":
                return _escape_go_str(str(expr.value))

        if isinstance(expr, ListLiteralExpr):
            el_go = _go_type(expr.element_type)
            if not expr.elements:
                return f"[]{el_go}{{}}"
            inner = ", ".join(self.gen_expr(e, scope) for e in expr.elements)
            return f"[]{el_go}{{{inner}}}"

        if isinstance(expr, VarRefExpr):
            return _go_ident(expr.name)

        if isinstance(expr, RandomIntExpr):
            self.uses_rand = True
            self.uses_random_helpers = True
            return f"_meme_rand_int({self.gen_expr(expr.min_val, scope)}, {self.gen_expr(expr.max_val, scope)})"

        if isinstance(expr, RandomListExpr):
            self.uses_rand = True
            self.uses_random_helpers = True
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
            left_t = self.infer_type(expr.left, scope)
            if expr.op == "+" and left_t == "String":
                return f"({left} + {right})"
            if expr.op == "/":
                if left_t == "Int":
                    self.uses_int_div = True
                    return f"_meme_int_div({left}, {right})"
                return f"({left} / {right})"
            if expr.op == "%":
                if left_t == "Int":
                    self.uses_int_mod = True
                    return f"_meme_int_mod({left}, {right})"
                self.uses_math = True
                return f"math.Mod({left}, {right})"
            if expr.op in ("==", "!="):
                if left_t.startswith("List<") or left_t.startswith("Map<"):
                    self.uses_reflect = True
                    if expr.op == "==":
                        return f"reflect.DeepEqual({left}, {right})"
                    return f"(!reflect.DeepEqual({left}, {right}))"
            op_map = {"and": "&&", "or": "||"}
            go_op = op_map.get(expr.op, expr.op)
            return f"({left} {go_op} {right})"

        if isinstance(expr, ListLengthExpr):
            return f"int64(len({self.gen_expr(expr.target, scope)}))"

        if isinstance(expr, ListIndexExpr):
            tgt = self.gen_expr(expr.target, scope)
            idx = self.gen_expr(expr.index, scope)
            return f"{tgt}[{idx}]"

        if isinstance(expr, CallExpr):
            args = ", ".join(self.gen_expr(a, scope) for a in expr.args)
            return f"{_go_ident(expr.func_name)}({args})"

        if isinstance(expr, ReadInputExpr):
            self.uses_input_helpers = True
            raw = f"_meme_read_line({_escape_go_str(expr.prompt)})"
            if expr.target_type == "Int":
                return f"_meme_parse_int({raw})"
            if expr.target_type == "Float":
                return f"_meme_parse_float({raw})"
            if expr.target_type == "Bool":
                self.uses_strings = True
                return f"func(s string) bool {{ s = strings.TrimSpace(strings.ToLower(s)); return s == \"true\" || s == \"1\" || s == \"yes\" }}({raw})"
            return raw

        if isinstance(expr, StrEndsWithExpr):
            self.uses_strings = True
            tgt = self.gen_expr(expr.target, scope)
            suf = self.gen_expr(expr.suffix, scope)
            return f"strings.HasSuffix(strings.ToLower(strings.TrimSpace({tgt})), strings.ToLower({suf}))"

        if isinstance(expr, StrStartsWithExpr):
            self.uses_strings = True
            tgt = self.gen_expr(expr.target, scope)
            pre = self.gen_expr(expr.prefix, scope)
            return f"strings.HasPrefix({tgt}, {pre})"

        if isinstance(expr, StrContainsExpr):
            self.uses_strings = True
            tgt = self.gen_expr(expr.target, scope)
            sub = self.gen_expr(expr.substring, scope)
            return f"strings.Contains({tgt}, {sub})"

        if isinstance(expr, StringReplaceExpr):
            self.uses_strings = True
            tgt = self.gen_expr(expr.target, scope)
            old_s = self.gen_expr(expr.old, scope)
            new_s = self.gen_expr(expr.new, scope)
            return f"strings.ReplaceAll({tgt}, {old_s}, {new_s})"

        if isinstance(expr, StringUpperExpr):
            self.uses_strings = True
            return f"strings.ToUpper({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringLowerExpr):
            self.uses_strings = True
            return f"strings.ToLower({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringTrimExpr):
            self.uses_strings = True
            return f"strings.TrimSpace({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringSplitExpr):
            self.uses_str_split = True
            return f"_meme_str_split({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.separator, scope)})"

        if isinstance(expr, StringJoinExpr):
            self.uses_strings = True
            return f"strings.Join({self.gen_expr(expr.items, scope)}, {self.gen_expr(expr.separator, scope)})"

        if isinstance(expr, StringIndexOfExpr):
            self.uses_strings = True
            tgt = self.gen_expr(expr.target, scope)
            sub = self.gen_expr(expr.substring, scope)
            return f"int64(strings.Index({tgt}, {sub}))"

        if isinstance(expr, StringCharAtExpr):
            self.uses_char_at = True
            return f"_meme_char_at({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.index, scope)})"

        if isinstance(expr, StringLengthExpr):
            tgt = self.gen_expr(expr.target, scope)
            return f"int64(len({tgt}))"

        if isinstance(expr, StringSliceExpr):
            self.uses_str_slice = True
            tgt = self.gen_expr(expr.target, scope)
            start = self.gen_expr(expr.start, scope)
            end = self.gen_expr(expr.end, scope)
            return f"_meme_str_slice({tgt}, {start}, {end})"

        if isinstance(expr, ParseIntExpr):
            self.uses_input_helpers = True
            self.uses_strconv = True
            self.uses_strings = True
            self.uses_os = True
            self.uses_fmt = True
            return f"_meme_parse_int({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ParseIntOrDefaultExpr):
            self.uses_parse_int_or_else = True
            self.uses_strconv = True
            self.uses_strings = True
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_parse_int_or_else({tgt}, func() int64 {{ return {dflt} }})"

        if isinstance(expr, IsDigitExpr):
            self.uses_is_digit = True
            return f"_meme_is_digit({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, FormatIntExpr):
            self.uses_strconv = True
            return f"strconv.FormatInt({self.gen_expr(expr.target, scope)}, 10)"

        if isinstance(expr, ReadJsonListExpr):
            self.uses_json_io = True
            el_lower = expr.element_type.lower()
            return f"_meme_read_json_list_{el_lower}({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, FileExistsExpr):
            self.uses_file_io = True
            return f"_meme_file_exists({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ReadFileStringExpr):
            self.uses_file_io = True
            return f"_meme_read_file_string({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ListFilesExpr):
            self.uses_file_io = True
            return f"_meme_list_files({self.gen_expr(expr.path, scope)})"

        if isinstance(expr, ArgCountExpr):
            self.uses_os = True
            return "int64(len(os.Args))"

        if isinstance(expr, ArgAtExpr):
            self.uses_argv_helpers = True
            return f"_meme_arg_at({self.gen_expr(expr.index, scope)})"

        if isinstance(expr, RecordLiteralExpr):
            fields = ", ".join(
                f"{_go_ident(f.name)}: {self.gen_expr(f.value, scope)}" for f in expr.fields
            )
            return f"{_go_ident(expr.record_name)}{{{fields}}}"

        if isinstance(expr, RecordFieldExpr):
            return f"{self.gen_expr(expr.target, scope)}.{_go_ident(expr.field_name)}"

        if isinstance(expr, MapLiteralExpr):
            k_go = _go_type(expr.key_type)
            v_go = _go_type(expr.value_type)
            if not expr.entries:
                return f"make(map[{k_go}]{v_go})"
            inits = ", ".join(
                f"{self.gen_expr(e.key, scope)}: {self.gen_expr(e.value, scope)}"
                for e in expr.entries
            )
            return f"map[{k_go}]{v_go}{{{inits}}}"

        if isinstance(expr, MapGetExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            if expr.default_val is not None:
                self.uses_map_helpers = True
                def_val = self.gen_expr(expr.default_val, scope)
                return f"_meme_map_get({tgt}, {k}, {def_val})"
            return f"{tgt}[{k}]"

        if isinstance(expr, MapHasKeyExpr):
            self.uses_map_helpers = True
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            return f"_meme_map_has_key({tgt}, {k})"

        if isinstance(expr, OptionalNoneExpr):
            return "nil"

        if isinstance(expr, OptionalWrapExpr):
            self.uses_optional_helpers = True
            return f"_meme_some({self.gen_expr(expr.value, scope)})"

        if isinstance(expr, OptionalIsNothingExpr):
            tgt = self.gen_expr(expr.target, scope)
            if expr.negated:
                return f"({tgt} != nil)"
            return f"({tgt} == nil)"

        if isinstance(expr, OptionalUnwrapExpr):
            self.uses_optional_helpers = True
            return f"_meme_unwrap({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, OptionalUnwrapOrDefaultExpr):
            self.uses_optional_helpers = True
            tgt = self.gen_expr(expr.target, scope)
            val_t = self.infer_type(expr, scope)
            dflt_t = _go_type(val_t)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_unwrap_or_else({tgt}, func() {dflt_t} {{ return {dflt} }})"

        raise TypeError(f"Unsupported IRExpr: {type(expr)!r}")

    def gen_stmt(
        self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 1
    ) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            val_code = self.gen_expr(stmt.value, scope)
            scope[stmt.name] = stmt.var_type
            ident = _go_ident(stmt.name)
            go_t = _go_type(stmt.var_type)
            return [
                f"{pad}var {ident} {go_t} = {val_code}",
                f"{pad}_ = {ident}",
            ]

        if isinstance(stmt, AssignStmt):
            return [f"{pad}{_go_ident(stmt.name)} = {self.gen_expr(stmt.value, scope)}"]

        if isinstance(stmt, CompoundAssignStmt):
            ident = _go_ident(stmt.target)
            val = self.gen_expr(stmt.value, scope)
            target_t = scope.get(stmt.target, "Int")
            if stmt.operator == "/" and target_t == "Int":
                self.uses_int_div = True
                return [f"{pad}{ident} = _meme_int_div({ident}, {val})"]
            return [f"{pad}{ident} {stmt.operator}= {val}"]

        if isinstance(stmt, SortCollectionStmt):
            self.uses_sort = True
            tgt = _go_ident(stmt.target)
            col_t = scope.get(stmt.target, "List<Int>")
            if col_t == "List<Bool>":
                if stmt.direction == "ascending":
                    return [f"{pad}sort.SliceStable({tgt}, func(i, j int) bool {{ return !{tgt}[i] && {tgt}[j] }})"]
                return [f"{pad}sort.SliceStable({tgt}, func(i, j int) bool {{ return {tgt}[i] && !{tgt}[j] }})"]
            cmp_op = "<" if stmt.direction == "ascending" else ">"
            return [
                f"{pad}sort.SliceStable({tgt}, func(i, j int) bool {{ return {tgt}[i] {cmp_op} {tgt}[j] }})"
            ]

        if isinstance(stmt, ClampCollectionStmt):
            tgt = _go_ident(stmt.target)
            lo = self.gen_expr(stmt.min_val, scope)
            hi = self.gen_expr(stmt.max_val, scope)
            return [
                f"{pad}{{",
                f"{pad}    _lo, _hi := {lo}, {hi}",
                f"{pad}    for _i := range {tgt} {{",
                f"{pad}        if {tgt}[_i] < _lo {{ {tgt}[_i] = _lo }} else if {tgt}[_i] > _hi {{ {tgt}[_i] = _hi }}",
                f"{pad}    }}",
                f"{pad}}}",
            ]

        if isinstance(stmt, FilterCollectionStmt):
            tgt = _go_ident(stmt.target)
            iv = _go_ident(stmt.item_var)
            sub = dict(scope)
            col_t = scope.get(stmt.target, "List<Int>")
            elem_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
            sub[stmt.item_var] = elem_t  # type: ignore[assignment]
            pred = self.gen_expr(stmt.predicate, sub)
            go_elem_t = _go_type(elem_t)
            return [
                f"{pad}{{",
                f"{pad}    _filtered := make([]{go_elem_t}, 0, len({tgt}))",
                f"{pad}    for _, {iv} := range {tgt} {{",
                f"{pad}        _ = {iv}",
                f"{pad}        if {pred} {{",
                f"{pad}            _filtered = append(_filtered, {iv})",
                f"{pad}        }}",
                f"{pad}    }}",
                f"{pad}    {tgt} = _filtered",
                f"{pad}}}",
            ]

        if isinstance(stmt, ListAppendStmt):
            tgt = _go_ident(stmt.target)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt} = append({tgt}, {val})"]

        if isinstance(stmt, ListInsertStmt):
            self.uses_slices = True
            tgt = _go_ident(stmt.target)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt} = slices.Insert({tgt}, int({idx}), {val})"]

        if isinstance(stmt, ListSetIndexStmt):
            tgt = _go_ident(stmt.target)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt}[{idx}] = {val}"]

        if isinstance(stmt, ListRemoveStmt):
            self.uses_slices = True
            self.uses_list_remove = True
            self.uses_fmt = True
            self.uses_os = True
            tgt = _go_ident(stmt.target)
            if stmt.index is not None:
                idx = self.gen_expr(stmt.index, scope)
                return [f"{pad}{tgt} = _meme_list_remove({tgt}, {idx})"]
            return [f"{pad}{tgt} = _meme_list_remove_last({tgt})"]

        if isinstance(stmt, FailStmt):
            self.uses_fmt = True
            self.uses_os = True
            self.uses_meme_fmt = True
            msg = self.gen_expr(stmt.message, scope)
            return [
                f"{pad}fmt.Println(_meme_fmt({msg}))",
                f"{pad}os.Exit(1)",
            ]

        if isinstance(stmt, ExitStmt):
            self.uses_os = True
            code = self.gen_expr(stmt.code, scope)
            return [f"{pad}os.Exit(int(({code}) & 0xFF))"]

        if isinstance(stmt, PrintStmt):
            self.uses_fmt = True
            self.uses_meme_fmt = True
            if len(stmt.expressions) == 1:
                return [f"{pad}fmt.Println(_meme_fmt({self.gen_expr(stmt.expressions[0], scope)}))"]
            self.uses_strings = True
            args = ", ".join(f"_meme_fmt({self.gen_expr(e, scope)})" for e in stmt.expressions)
            return [f"{pad}fmt.Println(strings.Join([]string{{{args}}}, \" \"))"]

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
            tgt = self.gen_expr(stmt.target, scope)
            lines = [f"{pad}switch {tgt} {{"]
            for case in stmt.cases:
                lines.append(f"{pad}case {self.gen_expr(case.value, scope)}:")
                case_scope = dict(scope)
                if not case.body:
                    lines.append(f"{pad}    // empty")
                else:
                    for ch in case.body:
                        lines.extend(self.gen_stmt(ch, case_scope, indent + 1))
            if stmt.default_body:
                lines.append(f"{pad}default:")
                def_scope = dict(scope)
                for ch in stmt.default_body:
                    lines.extend(self.gen_stmt(ch, def_scope, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, ForEachStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.collection, "List<Int>")
            map_t = _map_types_of(col_t)
            col_ident = _go_ident(stmt.collection)
            item_ident = _go_ident(stmt.item_var)
            if map_t is not None:
                self.uses_sort = True
                sub[stmt.item_var] = map_t[0]  # type: ignore[assignment]
                k_go = _go_type(map_t[0])
                lines = [
                    f"{pad}{{",
                    f"{pad}    _meme_keys := make([]{k_go}, 0, len({col_ident}))",
                    f"{pad}    for _k := range {col_ident} {{",
                    f"{pad}        _meme_keys = append(_meme_keys, _k)",
                    f"{pad}    }}",
                ]
                if map_t[0] == "Bool":
                    lines.append(
                        f"{pad}    sort.SliceStable(_meme_keys, func(i, j int) bool {{ return !_meme_keys[i] && _meme_keys[j] }})"
                    )
                else:
                    lines.append(
                        f"{pad}    sort.SliceStable(_meme_keys, func(i, j int) bool {{ return _meme_keys[i] < _meme_keys[j] }})"
                    )
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _go_ident(stmt.index_var)
                    lines.append(f"{pad}    for _meme_idx, {item_ident} := range _meme_keys {{")
                    lines.append(f"{pad}        _ = {item_ident}")
                    lines.append(f"{pad}        {idx_ident} := int64(_meme_idx)")
                    lines.append(f"{pad}        _ = {idx_ident}")
                else:
                    lines.append(f"{pad}    for _, {item_ident} := range _meme_keys {{")
                    lines.append(f"{pad}        _ = {item_ident}")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines
            else:
                elem_t = col_t[5:-1] if col_t.startswith("List<") else "Int"
                sub[stmt.item_var] = elem_t  # type: ignore[assignment]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _go_ident(stmt.index_var)
                    lines = [
                        f"{pad}for _meme_idx, {item_ident} := range {col_ident} {{",
                        f"{pad}    _ = {item_ident}",
                        f"{pad}    {idx_ident} := int64(_meme_idx)",
                        f"{pad}    _ = {idx_ident}",
                    ]
                else:
                    lines = [
                        f"{pad}for _, {item_ident} := range {col_ident} {{",
                        f"{pad}    _ = {item_ident}",
                    ]
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 1))
                lines.append(f"{pad}}}")
                return lines

        if isinstance(stmt, ForRangeStmt):
            sub = dict(scope)
            sub[stmt.loop_var] = "Int"
            loop_ident = _go_ident(stmt.loop_var)
            s = self.gen_expr(stmt.start, scope)
            e = self.gen_expr(stmt.end, scope)
            lines = [
                f"{pad}for {loop_ident}, _end := {s}, {e}; {loop_ident} <= _end; {loop_ident}++ {{",
                f"{pad}    _ = {loop_ident}",
            ]
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, sub, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, WhileStmt):
            lines = [f"{pad}for {self.gen_expr(stmt.condition, scope)} {{"]
            sub = dict(scope)
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, sub, indent + 1))
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, BreakStmt):
            return [f"{pad}break"]

        if isinstance(stmt, ContinueStmt):
            return [f"{pad}continue"]

        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                return [f"{pad}return"]
            return [f"{pad}return {self.gen_expr(stmt.value, scope)}"]

        if isinstance(stmt, RecordDefStmt):
            return []

        if isinstance(stmt, RecordSetFieldStmt):
            return [
                f"{pad}{_go_ident(stmt.target)}.{_go_ident(stmt.field_name)} = {self.gen_expr(stmt.value, scope)}"
            ]

        if isinstance(stmt, MapSetStmt):
            return [
                f"{pad}{_go_ident(stmt.target)}[{self.gen_expr(stmt.key, scope)}] = {self.gen_expr(stmt.value, scope)}"
            ]

        if isinstance(stmt, WriteFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_write_file({self.gen_expr(stmt.filepath, scope)}, {self.gen_expr(stmt.content, scope)})"
            ]

        if isinstance(stmt, AppendFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_append_file({self.gen_expr(stmt.filepath, scope)}, {self.gen_expr(stmt.content, scope)})"
            ]

        if isinstance(stmt, CopyFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_copy_file({self.gen_expr(stmt.src, scope)}, {self.gen_expr(stmt.dst, scope)})"
            ]

        if isinstance(stmt, MoveFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_move_file({self.gen_expr(stmt.src, scope)}, {self.gen_expr(stmt.dst, scope)})"
            ]

        if isinstance(stmt, RenameFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_rename_file({self.gen_expr(stmt.path, scope)}, {self.gen_expr(stmt.new_name, scope)})"
            ]

        if isinstance(stmt, DeleteFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_delete_file({self.gen_expr(stmt.path, scope)})"
            ]

        if isinstance(stmt, CreateDirectoryStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_create_directory({self.gen_expr(stmt.path, scope)})"
            ]

        if isinstance(stmt, ImportStmt):
            return []

        raise TypeError(f"Unsupported statement inside block: {type(stmt)!r}")

    def gen_func(self, fn: FuncDefStmt) -> list[str]:
        self.func_returns[fn.name] = fn.return_type
        params_str = ", ".join(f"{_go_ident(p.name)} {_go_type(p.param_type)}" for p in fn.params)
        ret_type_str = f" {_go_type(fn.return_type)}" if fn.return_type != "Void" else ""
        fn_scope = {p.name: p.param_type for p in fn.params}
        lines = [f"func {_go_ident(fn.name)}({params_str}){ret_type_str} {{"]
        for p in fn.params:
            lines.append(f"    _ = {_go_ident(p.name)}")
        for ch in fn.body:
            lines.extend(self.gen_stmt(ch, fn_scope, indent=1))
        if fn.return_type != "Void" and not (fn.body and isinstance(fn.body[-1], ReturnStmt)):
            lines.append('    panic("unreachable")')
        lines.append("}")
        return lines


def generate_go(ir: ProgramIR) -> str:
    gen = _GoGen()
    records: list[RecordDefStmt] = []
    funcs: list[FuncDefStmt] = []
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
        else:
            main_stmts.append(stmt)

    # Pre-scan records for types and fmt
    if records:
        gen.uses_meme_fmt = True

    record_blocks: list[str] = []
    for r in records:
        r_name = _go_ident(r.name)
        record_blocks.append(f"type {r_name} struct {{")
        for f in r.fields:
            record_blocks.append(f"    {_go_ident(f.name)} {_go_type(f.field_type)}")
        record_blocks.append("}")
        record_blocks.append(f"func (r {r_name}) memeFmt() string {{")
        if not r.fields:
            record_blocks.append(f'    return "{r.name}()"')
        else:
            gen.uses_fmt = True
            f_fmts = ", ".join(
                f'"{f.name}=" + _meme_fmt(r.{_go_ident(f.name)})' for f in r.fields
            )
            record_blocks.append(f'    _parts := []string{{{f_fmts}}}')
            record_blocks.append(f'    return "{r.name}(" + strings.Join(_parts, ", ") + ")"')
            gen.uses_strings = True
        record_blocks.append("}")
        record_blocks.append("")

    fn_blocks: list[str] = []
    for fn in funcs:
        fn_blocks.extend(gen.gen_func(fn))
        fn_blocks.append("")

    main_scope: dict[str, MemeType] = {}
    main_lines: list[str] = []
    for stmt in main_stmts:
        main_lines.extend(gen.gen_stmt(stmt, main_scope, indent=1))

    # Determine imports and helpers
    helpers: list[str] = []

    if gen.uses_meme_fmt:
        gen.uses_fmt = True
        gen.uses_math = True
        gen.uses_reflect = True
        gen.uses_sort = True
        gen.uses_strconv = True
        gen.uses_strings = True
        helpers.extend(
            [
                "func _meme_fmt(val any) string {",
                "    if val == nil {",
                '        return "None"',
                "    }",
                "    valVal := reflect.ValueOf(val)",
                "    if valVal.Kind() == reflect.Pointer {",
                "        if valVal.IsNil() {",
                '            return "None"',
                "        }",
                "        return _meme_fmt(valVal.Elem().Interface())",
                "    }",
                "    switch v := val.(type) {",
                "    case bool:",
                "        if v {",
                '            return "true"',
                "        }",
                '        return "false"',
                "    case int64:",
                "        return strconv.FormatInt(v, 10)",
                "    case int:",
                "        return strconv.Itoa(v)",
                "    case float64:",
                "        if math.IsNaN(v) {",
                '            return "NaN"',
                "        }",
                "        if math.IsInf(v, 1) {",
                '            return "inf"',
                "        }",
                "        if math.IsInf(v, -1) {",
                '            return "-inf"',
                "        }",
                "        if math.Trunc(v) == v && v >= -9007199254740992.0 && v <= 9007199254740992.0 {",
                "            return strconv.FormatInt(int64(v), 10)",
                "        }",
                "        return strconv.FormatFloat(v, 'g', -1, 64)",
                "    case string:",
                "        return v",
                "    case interface{ memeFmt() string }:",
                "        return v.memeFmt()",
                "    }",
                "    switch valVal.Kind() {",
                "    case reflect.Slice:",
                "        n := valVal.Len()",
                "        parts := make([]string, n)",
                "        for i := 0; i < n; i++ {",
                "            parts[i] = _meme_fmt(valVal.Index(i).Interface())",
                "        }",
                '        return "[" + strings.Join(parts, ", ") + "]"',
                "    case reflect.Map:",
                "        keys := valVal.MapKeys()",
                "        type entry struct{ kStr, vStr string }",
                "        entries := make([]entry, len(keys))",
                "        for i, k := range keys {",
                "            entries[i] = entry{_meme_fmt(k.Interface()), _meme_fmt(valVal.MapIndex(k).Interface())}",
                "        }",
                "        sort.SliceStable(entries, func(i, j int) bool {",
                "            return entries[i].kStr < entries[j].kStr",
                "        })",
                "        parts := make([]string, len(entries))",
                "        for i, e := range entries {",
                '            parts[i] = e.kStr + ": " + e.vStr',
                "        }",
                '        return "{" + strings.Join(parts, ", ") + "}"',
                "    default:",
                "        return fmt.Sprint(val)",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_int_div:
        helpers.extend(
            [
                "func _meme_int_div(a int64, b int64) int64 {",
                "    return a / b",
                "}",
                "",
            ]
        )

    if gen.uses_int_mod:
        helpers.extend(
            [
                "func _meme_int_mod(a int64, b int64) int64 {",
                "    return a % b",
                "}",
                "",
            ]
        )

    if gen.uses_random_helpers:
        gen.uses_rand = True
        helpers.extend(
            [
                "func _meme_rand_int(lo int64, hi int64) int64 {",
                "    if hi <= lo {",
                "        return lo",
                "    }",
                "    span := uint64(hi - lo + 1)",
                "    return lo + int64(rand.Uint64N(span))",
                "}",
                "",
                "func _meme_rand_list(count int64, lo int64, hi int64) []int64 {",
                "    if count <= 0 {",
                "        return []int64{}",
                "    }",
                "    out := make([]int64, count)",
                "    for i := int64(0); i < count; i++ {",
                "        out[i] = _meme_rand_int(lo, hi)",
                "    }",
                "    return out",
                "}",
                "",
            ]
        )

    if gen.uses_argv_helpers:
        gen.uses_fmt = True
        gen.uses_os = True
        helpers.extend(
            [
                "func _meme_arg_at(idx int64) string {",
                "    if idx < 0 || idx >= int64(len(os.Args)) {",
                '        fmt.Printf("Error: argument index %d out of range\\n", idx)',
                "        os.Exit(1)",
                "    }",
                "    return os.Args[idx]",
                "}",
                "",
            ]
        )

    if gen.uses_list_remove:
        gen.uses_fmt = True
        gen.uses_os = True
        gen.uses_slices = True
        helpers.extend(
            [
                "func _meme_list_remove[T any](s []T, idx int64) []T {",
                "    if idx < 0 || int(idx) >= len(s) {",
                '        fmt.Printf("Error: list index out of range\\n")',
                "        os.Exit(1)",
                "    }",
                "    return slices.Delete(s, int(idx), int(idx)+1)",
                "}",
                "",
                "func _meme_list_remove_last[T any](s []T) []T {",
                "    if len(s) == 0 {",
                '        fmt.Printf("Error: list index out of range\\n")',
                "        os.Exit(1)",
                "    }",
                "    return s[:len(s)-1]",
                "}",
                "",
            ]
        )

    if gen.uses_str_split:
        gen.uses_fmt = True
        gen.uses_os = True
        gen.uses_strings = True
        helpers.extend(
            [
                "func _meme_str_split(s string, sep string) []string {",
                '    if sep == "" {',
                '        fmt.Println("Error: empty separator in split")',
                "        os.Exit(1)",
                "    }",
                "    return strings.Split(s, sep)",
                "}",
                "",
            ]
        )

    if gen.uses_char_at:
        gen.uses_fmt = True
        gen.uses_os = True
        helpers.extend(
            [
                "func _meme_char_at(s string, idx int64) string {",
                "    if idx < 0 || idx >= int64(len(s)) {",
                '        fmt.Printf("Error: string index %d out of range\\n", idx)',
                "        os.Exit(1)",
                "    }",
                "    return string(s[idx])",
                "}",
                "",
            ]
        )

    if gen.uses_str_slice:
        helpers.extend(
            [
                "func _meme_str_slice(s string, start int64, end int64) string {",
                "    if start < 0 {",
                "        start = 0",
                "    }",
                "    n := int64(len(s))",
                "    if end <= start || start >= n {",
                '        return ""',
                "    }",
                "    if end > n {",
                "        end = n",
                "    }",
                "    return s[start:end]",
                "}",
                "",
            ]
        )

    if gen.uses_input_helpers:
        gen.uses_bufio = True
        gen.uses_fmt = True
        gen.uses_os = True
        gen.uses_strconv = True
        gen.uses_strings = True
        helpers.extend(
            [
                "var _meme_stdin_reader = bufio.NewReader(os.Stdin)",
                "",
                "func _meme_read_line(prompt string) string {",
                '    q := strings.TrimSpace(strings.ToLower(os.Getenv("MEME_QUIET_PROMPTS")))',
                '    quiet := q == "1" || q == "true" || q == "yes"',
                '    if prompt != "" && !quiet {',
                "        fmt.Print(prompt)",
                "    }",
                "    line, err := _meme_stdin_reader.ReadString('\\n')",
                "    if err != nil && len(line) == 0 {",
                '        return ""',
                "    }",
                '    return strings.TrimRight(line, "\\r\\n")',
                "}",
                "",
                "func _meme_parse_int(s string) int64 {",
                "    v, err := strconv.ParseInt(strings.TrimSpace(s), 10, 64)",
                "    if err != nil {",
                '        fmt.Printf("Error parsing integer: %s\\n", s)',
                "        os.Exit(1)",
                "    }",
                "    return v",
                "}",
                "",
                "func _meme_parse_float(s string) float64 {",
                "    v, err := strconv.ParseFloat(strings.TrimSpace(s), 64)",
                "    if err != nil {",
                "        return 0.0",
                "    }",
                "    return v",
                "}",
                "",
            ]
        )

    if gen.uses_parse_int_or_else:
        gen.uses_strconv = True
        gen.uses_strings = True
        helpers.extend(
            [
                "func _meme_parse_int_or_else(s string, default_fn func() int64) int64 {",
                "    v, err := strconv.ParseInt(strings.TrimSpace(s), 10, 64)",
                "    if err != nil {",
                "        return default_fn()",
                "    }",
                "    return v",
                "}",
                "",
            ]
        )

    if gen.uses_is_digit:
        helpers.extend(
            [
                "func _meme_is_digit(s string) bool {",
                "    return len(s) == 1 && s[0] >= '0' && s[0] <= '9'",
                "}",
                "",
            ]
        )

    if gen.uses_file_io or gen.uses_json_io:
        gen.uses_filepath = True
        gen.uses_os = True
        gen.uses_strings = True
        helpers.extend(
            [
                "func _meme_resolve_path(path string) string {",
                "    p := strings.TrimSpace(path)",
                "    if _, err := os.Stat(p); err == nil || filepath.IsAbs(p) {",
                "        return p",
                "    }",
                '    if sd := strings.TrimSpace(os.Getenv("MEME_SOURCE_DIR")); sd != "" {',
                "        cand := filepath.Join(sd, p)",
                "        if _, err := os.Stat(cand); err == nil {",
                "            return cand",
                "        }",
                "    }",
                "    return p",
                "}",
                "",
            ]
        )

    if gen.uses_file_io:
        gen.uses_fmt = True
        gen.uses_os = True
        gen.uses_sort = True
        gen.uses_filepath = True
        gen.uses_strings = True
        helpers.extend(
            [
                "func _meme_file_exists(path string) bool {",
                "    info, err := os.Stat(_meme_resolve_path(path))",
                "    return err == nil && !info.IsDir()",
                "}",
                "",
                "func _meme_read_file_string(path string) string {",
                "    rp := _meme_resolve_path(path)",
                "    info, err := os.Stat(rp)",
                "    if err != nil || info.IsDir() {",
                '        fmt.Printf("Error reading file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "    bytes, err := os.ReadFile(rp)",
                "    if err != nil {",
                '        fmt.Printf("Error reading file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "    return string(bytes)",
                "}",
                "",
                "func _meme_write_file(path string, content string) {",
                "    p := strings.TrimSpace(path)",
                "    if err := os.WriteFile(p, []byte(content), 0644); err != nil {",
                '        fmt.Printf("Error writing file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "}",
                "",
                "func _meme_append_file(path string, content string) {",
                "    p := strings.TrimSpace(path)",
                "    f, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)",
                "    if err != nil {",
                '        fmt.Printf("Error writing file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "    defer f.Close()",
                "    if _, err := f.WriteString(content); err != nil {",
                '        fmt.Printf("Error writing file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "}",
                "",
                "func _meme_copy_file(src string, dst string) {",
                "    rsrc := _meme_resolve_path(src)",
                "    info, err := os.Stat(rsrc)",
                "    if err != nil || info.IsDir() {",
                '        fmt.Printf("Error copying file: %s\\n", src)',
                "        os.Exit(1)",
                "    }",
                "    data, err := os.ReadFile(rsrc)",
                "    if err != nil {",
                '        fmt.Printf("Error copying file: %s\\n", src)',
                "        os.Exit(1)",
                "    }",
                "    err = os.WriteFile(strings.TrimSpace(dst), data, 0644)",
                "    if err != nil {",
                '        fmt.Printf("Error copying file: %s\\n", src)',
                "        os.Exit(1)",
                "    }",
                "}",
                "",
                "func _meme_move_file(src string, dst string) {",
                "    rsrc := _meme_resolve_path(src)",
                "    info, err := os.Stat(rsrc)",
                "    if err != nil || info.IsDir() {",
                '        fmt.Printf("Error moving file: %s\\n", src)',
                "        os.Exit(1)",
                "    }",
                "    target := strings.TrimSpace(dst)",
                "    err = os.Rename(rsrc, target)",
                "    if err != nil {",
                "        data, rerr := os.ReadFile(rsrc)",
                "        if rerr != nil {",
                '            fmt.Printf("Error moving file: %s\\n", src)',
                "            os.Exit(1)",
                "        }",
                "        werr := os.WriteFile(target, data, 0644)",
                "        if werr != nil {",
                '            fmt.Printf("Error moving file: %s\\n", src)',
                "            os.Exit(1)",
                "        }",
                "        _ = os.Remove(rsrc)",
                "    }",
                "}",
                "",
                "func _meme_rename_file(path string, newName string) {",
                "    rsrc := _meme_resolve_path(path)",
                "    info, err := os.Stat(rsrc)",
                "    if err != nil || info.IsDir() {",
                '        fmt.Printf("Error renaming file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "    p := strings.TrimSpace(path)",
                "    dir := filepath.Dir(p)",
                "    nn := filepath.Base(strings.TrimSpace(newName))",
                '    target := nn',
                '    if dir != "." && dir != "" {',
                "        target = filepath.Join(dir, nn)",
                "    }",
                "    err = os.Rename(rsrc, target)",
                "    if err != nil {",
                "        data, rerr := os.ReadFile(rsrc)",
                "        if rerr != nil {",
                '            fmt.Printf("Error renaming file: %s\\n", path)',
                "            os.Exit(1)",
                "        }",
                "        werr := os.WriteFile(target, data, 0644)",
                "        if werr != nil {",
                '            fmt.Printf("Error renaming file: %s\\n", path)',
                "            os.Exit(1)",
                "        }",
                "        _ = os.Remove(rsrc)",
                "    }",
                "}",
                "",
                "func _meme_delete_file(path string) {",
                "    rsrc := _meme_resolve_path(path)",
                "    info, err := os.Stat(rsrc)",
                "    if err != nil || info.IsDir() {",
                '        fmt.Printf("Error deleting file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "    err = os.Remove(rsrc)",
                "    if err != nil {",
                '        fmt.Printf("Error deleting file: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "}",
                "",
                "func _meme_create_directory(path string) {",
                "    err := os.MkdirAll(strings.TrimSpace(path), 0755)",
                "    if err != nil {",
                '        fmt.Printf("Error creating directory: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "}",
                "",
                "func _meme_list_files(path string) []string {",
                "    rpath := _meme_resolve_path(path)",
                "    info, err := os.Stat(rpath)",
                "    if err != nil || !info.IsDir() {",
                '        fmt.Printf("Error listing directory: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "    entries, err := os.ReadDir(rpath)",
                "    if err != nil {",
                '        fmt.Printf("Error listing directory: %s\\n", path)',
                "        os.Exit(1)",
                "    }",
                "    res := make([]string, 0, len(entries))",
                "    for _, e := range entries {",
                "        res = append(res, e.Name())",
                "    }",
                "    sort.Strings(res)",
                "    return res",
                "}",
                "",
            ]
        )

    if gen.uses_json_io:
        gen.uses_bytes = True
        gen.uses_fmt = True
        gen.uses_json = True
        gen.uses_os = True
        gen.uses_strconv = True
        gen.uses_strings = True
        helpers.extend(
            [
                "func _meme_parse_json_raw(path string) []json.RawMessage {",
                "    data, err := os.ReadFile(_meme_resolve_path(path))",
                "    if err != nil {",
                '        fmt.Fprintf(os.Stderr, "Error reading JSON file: %s\\n", err)',
                "        os.Exit(1)",
                "    }",
                "    d := json.NewDecoder(bytes.NewReader(data))",
                "    tok, err := d.Token()",
                "    if err != nil {",
                '        fmt.Fprintf(os.Stderr, "Error reading JSON file: %s\\n", err)',
                "        os.Exit(1)",
                "    }",
                "    if delim, ok := tok.(json.Delim); !ok || delim != '[' {",
                '        fmt.Fprintf(os.Stderr, "Error reading JSON file: expected array start [\\n")',
                "        os.Exit(1)",
                "    }",
                "    var out []json.RawMessage",
                "    for d.More() {",
                "        var raw json.RawMessage",
                "        if err := d.Decode(&raw); err != nil {",
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: %s\\n", err)',
                "            os.Exit(1)",
                "        }",
                "        rawStr := strings.TrimSpace(string(raw))",
                '        if rawStr == "null" {',
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: JSON null is not allowed\\n")',
                "            os.Exit(1)",
                "        }",
                "        out = append(out, raw)",
                "    }",
                "    tok, err = d.Token()",
                "    if err != nil || tok != json.Delim(']') {",
                '        fmt.Fprintf(os.Stderr, "Error reading JSON file: expected array end ]\\n")',
                "        os.Exit(1)",
                "    }",
                "    if d.More() {",
                '        fmt.Fprintf(os.Stderr, "Error reading JSON file: trailing data after JSON array\\n")',
                "        os.Exit(1)",
                "    }",
                "    return out",
                "}",
                "",
                "func _meme_read_json_list_int(path string) []int64 {",
                "    raws := _meme_parse_json_raw(path)",
                "    out := make([]int64, len(raws))",
                "    for i, r := range raws {",
                "        s := strings.TrimSpace(string(r))",
                '        if s == "true" || s == "false" {',
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: boolean in int array\\n")',
                "            os.Exit(1)",
                "        }",
                "        v, err := strconv.ParseInt(s, 10, 64)",
                "        if err != nil {",
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: %s\\n", err)',
                "            os.Exit(1)",
                "        }",
                "        out[i] = v",
                "    }",
                "    return out",
                "}",
                "",
                "func _meme_read_json_list_float(path string) []float64 {",
                "    raws := _meme_parse_json_raw(path)",
                "    out := make([]float64, len(raws))",
                "    for i, r := range raws {",
                "        s := strings.TrimSpace(string(r))",
                '        if s == "true" || s == "false" {',
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: boolean in float array\\n")',
                "            os.Exit(1)",
                "        }",
                "        v, err := strconv.ParseFloat(s, 64)",
                "        if err != nil {",
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: %s\\n", err)',
                "            os.Exit(1)",
                "        }",
                "        out[i] = v",
                "    }",
                "    return out",
                "}",
                "",
                "func _meme_read_json_list_string(path string) []string {",
                "    raws := _meme_parse_json_raw(path)",
                "    out := make([]string, len(raws))",
                "    for i, r := range raws {",
                "        var s string",
                "        if err := json.Unmarshal(r, &s); err != nil {",
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: %s\\n", err)',
                "            os.Exit(1)",
                "        }",
                "        out[i] = s",
                "    }",
                "    return out",
                "}",
                "",
                "func _meme_read_json_list_bool(path string) []bool {",
                "    raws := _meme_parse_json_raw(path)",
                "    out := make([]bool, len(raws))",
                "    for i, r := range raws {",
                "        s := strings.TrimSpace(string(r))",
                '        if s == "true" {',
                "            out[i] = true",
                '        } else if s == "false" {',
                "            out[i] = false",
                "        } else {",
                '            fmt.Fprintf(os.Stderr, "Error reading JSON file: invalid bool element\\n")',
                "            os.Exit(1)",
                "        }",
                "    }",
                "    return out",
                "}",
                "",
            ]
        )

    if gen.uses_optional_helpers:
        gen.uses_fmt = True
        gen.uses_os = True
        helpers.extend(
            [
                "// Optional representation: pointer *T where nil denotes nothing/None.",
                "func _meme_some[T any](v T) *T {",
                "    return &v",
                "}",
                "",
                "func _meme_unwrap[T any](opt *T) T {",
                "    if opt == nil {",
                '        fmt.Println("Unwrap failed: Optional value is nothing")',
                "        os.Exit(1)",
                "    }",
                "    return *opt",
                "}",
                "",
                "func _meme_unwrap_or_else[T any](opt *T, dflt func() T) T {",
                "    if opt != nil {",
                "        return *opt",
                "    }",
                "    return dflt()",
                "}",
                "",
            ]
        )

    if gen.uses_map_helpers:
        helpers.extend(
            [
                "func _meme_map_has_key[K comparable, V any](m map[K]V, k K) bool {",
                "    _, ok := m[k]",
                "    return ok",
                "}",
                "",
                "func _meme_map_get[K comparable, V any](m map[K]V, k K, dflt V) V {",
                "    if v, ok := m[k]; ok {",
                "        return v",
                "    }",
                "    return dflt",
                "}",
                "",
            ]
        )

    # Collect required imports in sorted order
    imports: list[str] = []
    if gen.uses_bufio:
        imports.append('"bufio"')
    if gen.uses_bytes:
        imports.append('"bytes"')
    if gen.uses_json:
        imports.append('"encoding/json"')
    if gen.uses_fmt:
        imports.append('"fmt"')
    if gen.uses_math:
        imports.append('"math"')
    if gen.uses_rand:
        imports.append('"math/rand/v2"')
    if gen.uses_os:
        imports.append('"os"')
    if gen.uses_filepath:
        imports.append('"path/filepath"')
    if gen.uses_reflect:
        imports.append('"reflect"')
    if gen.uses_slices:
        imports.append('"slices"')
    if gen.uses_sort:
        imports.append('"sort"')
    if gen.uses_strconv:
        imports.append('"strconv"')
    if gen.uses_strings:
        imports.append('"strings"')

    out: list[str] = ["package main", ""]
    if imports:
        out.append("import (")
        for imp in sorted(imports):
            out.append(f"    {imp}")
        out.append(")")
        out.append("")

    if record_blocks:
        out.extend(record_blocks)

    if helpers:
        out.extend(helpers)

    if fn_blocks:
        out.extend(fn_blocks)

    out.append("func main() {")
    if main_lines:
        out.extend(main_lines)
    out.append("}")
    out.append("")

    raw_code = "\n".join(out)
    try:
        proc = subprocess.run(
            ["gofmt"],
            input=raw_code,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    except Exception:
        pass
    return raw_code

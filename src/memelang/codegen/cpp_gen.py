"""Deterministic C++20 (`g++ -std=c++20`) code generator for Memelang ProgramIR."""

from __future__ import annotations

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


def _escape_cpp_str(val: str) -> str:
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
            out.append(f"\\x{ord(ch):02x}\" \"")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


_CPP_KEYWORDS = {
    "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor",
    "bool", "break", "case", "catch", "char", "char8_t", "char16_t", "char32_t",
    "class", "compl", "concept", "const", "consteval", "constexpr", "constinit",
    "const_cast", "continue", "co_await", "co_return", "co_yield", "decltype",
    "default", "delete", "do", "double", "dynamic_cast", "else", "enum", "explicit",
    "export", "extern", "false", "float", "for", "friend", "goto", "if", "inline",
    "int", "long", "mutable", "namespace", "new", "noexcept", "not", "not_eq",
    "nullptr", "operator", "or", "or_eq", "private", "protected", "public",
    "register", "reinterpret_cast", "requires", "return", "short", "signed",
    "sizeof", "static", "static_assert", "static_cast", "struct", "switch",
    "template", "this", "thread_local", "throw", "true", "try", "typedef",
    "typeid", "typename", "union", "unsigned", "using", "virtual", "void",
    "volatile", "wchar_t", "while", "xor", "xor_eq", "main",
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


def _cpp_ident(name: str) -> str:
    return f"meme_{name}" if name in _CPP_KEYWORDS or name.startswith("_meme_") else name


def _cpp_type(meme_type: MemeType | str) -> str:
    if meme_type.startswith("List<") and meme_type.endswith(">"):
        inner = meme_type[5:-1]
        return f"std::vector<{_cpp_type(inner)}>"
    if meme_type.startswith("Optional<") and meme_type.endswith(">"):
        inner = meme_type[9:-1]
        return f"std::optional<{_cpp_type(inner)}>"
    map_t = _map_types_of(meme_type)
    if map_t is not None:
        return f"std::unordered_map<{_cpp_type(map_t[0])}, {_cpp_type(map_t[1])}>"
    mapping = {
        "Int": "long long",
        "Float": "double",
        "Bool": "bool",
        "String": "std::string",
        "Void": "void",
    }
    if meme_type in mapping:
        return mapping[meme_type]
    return _cpp_ident(meme_type)


class _CppGen:
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_input = False
        self.uses_str_helpers = False
        self.uses_json_io = False
        self.uses_file_io = False
        self.uses_list_remove = False
        self.uses_parse_int_or_else = False
        self.uses_is_digit = False
        self.uses_argv = False
        self.uses_optional_helpers = False
        self._match_counter = 0
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
                return f"{expr.value}LL"
            if expr.data_type == "Float":
                s = repr(float(expr.value))  # type: ignore[arg-type]
                if "." not in s and "e" not in s and "E" not in s:
                    s += ".0"
                return s
            if expr.data_type == "String":
                return f"std::string({_escape_cpp_str(str(expr.value))})"

        if isinstance(expr, ListLiteralExpr):
            el_cpp = _cpp_type(expr.element_type)
            inner = ", ".join(self.gen_expr(e, scope) for e in expr.elements)
            return f"std::vector<{el_cpp}>{{{inner}}}"

        if isinstance(expr, VarRefExpr):
            return _cpp_ident(expr.name)

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
            if expr.op == "%" and self.infer_type(expr.left, scope) == "Float":
                return f"std::fmod({left}, {right})"
            op_map = {"and": "&&", "or": "||"}
            cpp_op = op_map.get(expr.op, expr.op)
            return f"({left} {cpp_op} {right})"

        if isinstance(expr, ListLengthExpr):
            return f"static_cast<long long>({self.gen_expr(expr.target, scope)}.size())"

        if isinstance(expr, ListIndexExpr):
            tgt_t = self.infer_type(expr.target, scope)
            if tgt_t.startswith("Map<"):
                return f"{self.gen_expr(expr.target, scope)}.at({self.gen_expr(expr.index, scope)})"
            indexed = f"{self.gen_expr(expr.target, scope)}.at(static_cast<std::size_t>({self.gen_expr(expr.index, scope)}))"
            if self.infer_type(expr, scope) == "Bool":
                return f"static_cast<bool>({indexed})"
            return indexed

        if isinstance(expr, CallExpr):
            args = ", ".join(self.gen_expr(a, scope) for a in expr.args)
            return f"{_cpp_ident(expr.func_name)}({args})"

        if isinstance(expr, ReadInputExpr):
            self.uses_input = True
            raw = f"_meme_read_line({_escape_cpp_str(expr.prompt)})"
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
            return f"({self.gen_expr(expr.target, scope)}.find({self.gen_expr(expr.substring, scope)}) != std::string::npos)"

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
            tgt = self.gen_expr(expr.target, scope)
            return f"_meme_str_len({tgt})"

        if isinstance(expr, StringSliceExpr):
            self.uses_str_helpers = True
            tgt = self.gen_expr(expr.target, scope)
            start = self.gen_expr(expr.start, scope)
            end = self.gen_expr(expr.end, scope)
            return f"_meme_str_slice({tgt}, {start}, {end})"

        if isinstance(expr, ParseIntExpr):
            self.uses_input = True
            return f"_meme_parse_int({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ParseIntOrDefaultExpr):
            self.uses_parse_int_or_else = True
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_parse_int_or_else({tgt}, [&]() -> long long {{ return {dflt}; }})"

        if isinstance(expr, IsDigitExpr):
            self.uses_is_digit = True
            return f"_meme_is_digit({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, FormatIntExpr):
            return f"std::to_string({self.gen_expr(expr.target, scope)})"

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

        if isinstance(expr, ListFilesExpr):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return f"_meme_list_files({self.gen_expr(expr.path, scope)})"

        if isinstance(expr, ArgCountExpr):
            self.uses_argv = True
            return "static_cast<long long>(_meme_argv().size())"

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
            fields = ", ".join(
                f".{_cpp_ident(fname)} = {self.gen_expr(fval, scope)}"
                for fname, fval in ordered_fields
            )
            return f"{_cpp_ident(expr.record_name)}{{ {fields} }}"

        if isinstance(expr, RecordFieldExpr):
            return f"{self.gen_expr(expr.target, scope)}.{_cpp_ident(expr.field_name)}"

        if isinstance(expr, MapLiteralExpr):
            map_t = _cpp_type(f"Map<{expr.key_type}, {expr.value_type}>")
            if not expr.entries:
                return f"{map_t}{{}}"
            entries_str = ", ".join(
                f"{{{self.gen_expr(e.key, scope)}, {self.gen_expr(e.value, scope)}}}"
                for e in expr.entries
            )
            return f"{map_t}{{{entries_str}}}"

        if isinstance(expr, MapGetExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            if expr.default_val is not None:
                def_val = self.gen_expr(expr.default_val, scope)
                return f"({tgt}.count({k}) ? {tgt}.at({k}) : {def_val})"
            return f"{tgt}.at({k})"

        if isinstance(expr, MapHasKeyExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            return f"({tgt}.count({k}) > 0)"

        if isinstance(expr, OptionalNoneExpr):
            return "std::nullopt"

        if isinstance(expr, OptionalWrapExpr):
            return f"std::make_optional({self.gen_expr(expr.value, scope)})"

        if isinstance(expr, OptionalIsNothingExpr):
            tgt = self.gen_expr(expr.target, scope)
            if expr.negated:
                return f"({tgt}.has_value())"
            return f"(!{tgt}.has_value())"

        if isinstance(expr, OptionalUnwrapExpr):
            self.uses_optional_helpers = True
            return f"_meme_unwrap({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, OptionalUnwrapOrDefaultExpr):
            self.uses_optional_helpers = True
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_unwrap_or_else({tgt}, [&]() {{ return {dflt}; }})"

        raise TypeError(f"Unsupported IRExpr: {type(expr)!r}")

    def gen_stmt(
        self, stmt: IRStatement, scope: dict[str, MemeType], indent: int = 1
    ) -> list[str]:
        pad = "    " * indent

        if isinstance(stmt, VarDeclStmt):
            val_code = self.gen_expr(stmt.value, scope)
            scope[stmt.name] = stmt.var_type
            return [f"{pad}{_cpp_type(stmt.var_type)} {_cpp_ident(stmt.name)} = {val_code};"]

        if isinstance(stmt, AssignStmt):
            return [f"{pad}{_cpp_ident(stmt.name)} = {self.gen_expr(stmt.value, scope)};"]

        if isinstance(stmt, CompoundAssignStmt):
            return [
                f"{pad}{_cpp_ident(stmt.target)} {stmt.operator}= {self.gen_expr(stmt.value, scope)};"
            ]

        if isinstance(stmt, SortCollectionStmt):
            tgt = _cpp_ident(stmt.target)
            if stmt.direction == "ascending":
                return [f"{pad}std::sort({tgt}.begin(), {tgt}.end());"]
            return [
                f"{pad}std::sort({tgt}.begin(), {tgt}.end(), std::greater<>{{}});"
            ]

        if isinstance(stmt, ClampCollectionStmt):
            tgt = _cpp_ident(stmt.target)
            lo = self.gen_expr(stmt.min_val, scope)
            hi = self.gen_expr(stmt.max_val, scope)
            return [
                f"{pad}{{",
                f"{pad}    auto _lo = {lo};",
                f"{pad}    auto _hi = {hi};",
                f"{pad}    if (_lo <= _hi) {{",
                f"{pad}        for (auto& _x : {tgt}) {{ _x = std::clamp(_x, _lo, _hi); }}",
                f"{pad}    }}",
                f"{pad}}}",
            ]

        if isinstance(stmt, FilterCollectionStmt):
            tgt = _cpp_ident(stmt.target)
            iv = _cpp_ident(stmt.item_var)
            sub = dict(scope)
            col_t = scope.get(stmt.target, "List<Int>")
            el_mtype = col_t[5:-1] if col_t.startswith("List<") else "Int"
            sub[stmt.item_var] = el_mtype  # type: ignore[assignment]
            pred = self.gen_expr(stmt.predicate, sub)
            return [
                f"{pad}std::erase_if({tgt}, [&](const {_cpp_type(el_mtype)}& {iv}) {{",  # type: ignore[arg-type]
                f"{pad}    return !({pred});",
                f"{pad}}});",
            ]

        if isinstance(stmt, ListAppendStmt):
            return [f"{pad}{_cpp_ident(stmt.target)}.push_back({self.gen_expr(stmt.value, scope)});"]

        if isinstance(stmt, ListInsertStmt):
            tgt = _cpp_ident(stmt.target)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt}.insert({tgt}.begin() + static_cast<std::ptrdiff_t>({idx}), {val});"]

        if isinstance(stmt, ListSetIndexStmt):
            tgt = _cpp_ident(stmt.target)
            idx = self.gen_expr(stmt.index, scope)
            val = self.gen_expr(stmt.value, scope)
            return [f"{pad}{tgt}.at(static_cast<std::size_t>({idx})) = {val};"]

        if isinstance(stmt, ListRemoveStmt):
            self.uses_list_remove = True
            tgt = _cpp_ident(stmt.target)
            if stmt.index is not None:
                idx = self.gen_expr(stmt.index, scope)
                return [f"{pad}_meme_list_remove({tgt}, {idx});"]
            return [f"{pad}_meme_list_remove_last({tgt});"]

        if isinstance(stmt, FailStmt):
            return [
                f"{pad}std::cout << _meme_fmt({self.gen_expr(stmt.message, scope)}) << \"\\n\";",
                f"{pad}std::exit(1);",
            ]

        if isinstance(stmt, ExitStmt):
            return [
                f"{pad}std::exit(static_cast<int>(({self.gen_expr(stmt.code, scope)}) & 0xFF));"
            ]

        if isinstance(stmt, PrintStmt):
            parts: list[str] = []
            for idx, e in enumerate(stmt.expressions):
                if idx > 0:
                    parts.append('" "')
                parts.append(f"_meme_fmt({self.gen_expr(e, scope)})")
            chain = " << ".join(parts)
            return [f"{pad}std::cout << {chain} << '\\n';"]

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
            lines = [f"{pad}{{"]
            if stmt.cases:
                lines.append(f"{pad}    auto {m_var} = {self.gen_expr(stmt.target, scope)};")
                for i, case in enumerate(stmt.cases):
                    kw = "if" if i == 0 else "} else if"
                    lines.append(f"{pad}    {kw} ({m_var} == {self.gen_expr(case.value, scope)}) {{")
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
                lines.append(f"{pad}    (void)({self.gen_expr(stmt.target, scope)});")
                def_scope = dict(scope)
                for ch in stmt.default_body:
                    lines.extend(self.gen_stmt(ch, def_scope, indent + 1))
            else:
                lines.append(f"{pad}    (void)({self.gen_expr(stmt.target, scope)});")
            lines.append(f"{pad}}}")
            return lines

        if isinstance(stmt, ForEachStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.collection, "List<Int>")
            map_t = _map_types_of(col_t)
            col_ident = _cpp_ident(stmt.collection)
            item_ident = _cpp_ident(stmt.item_var)
            if map_t is not None:
                el_mtype = map_t[0]
                sub[stmt.item_var] = el_mtype  # type: ignore[assignment]
                el_cpp = _cpp_type(el_mtype)  # type: ignore[arg-type]
                lines = [
                    f"{pad}{{",
                    f"{pad}    std::vector<{el_cpp}> _meme_keys;",
                    f"{pad}    _meme_keys.reserve({col_ident}.size());",
                    f"{pad}    for (const auto& _meme_kv : {col_ident}) {{ _meme_keys.push_back(_meme_kv.first); }}",
                    f"{pad}    std::sort(_meme_keys.begin(), _meme_keys.end());",
                ]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _cpp_ident(stmt.index_var)
                    lines.append(
                        f"{pad}    for (std::size_t _meme_idx = 0; _meme_idx < _meme_keys.size(); ++_meme_idx) {{"
                    )
                    lines.append(
                        f"{pad}        long long {idx_ident} = static_cast<long long>(_meme_idx);"
                    )
                    lines.append(f"{pad}        {el_cpp} {item_ident} = _meme_keys[_meme_idx];")
                else:
                    lines.append(f"{pad}    for ({el_cpp} {item_ident} : _meme_keys) {{")
                for ch in stmt.body:
                    lines.extend(self.gen_stmt(ch, sub, indent + 2))
                lines.append(f"{pad}    }}")
                lines.append(f"{pad}}}")
                return lines
            else:
                el_mtype = col_t[5:-1] if col_t.startswith("List<") else "Int"
                sub[stmt.item_var] = el_mtype  # type: ignore[assignment]
                el_cpp = _cpp_type(el_mtype)  # type: ignore[arg-type]
                if stmt.index_var is not None:
                    sub[stmt.index_var] = "Int"
                    idx_ident = _cpp_ident(stmt.index_var)
                    lines = [
                        f"{pad}{{",
                        f"{pad}    auto _meme_col = {col_ident};",
                        f"{pad}    for (std::size_t _meme_idx = 0; _meme_idx < _meme_col.size(); ++_meme_idx) {{",
                        f"{pad}        long long {idx_ident} = static_cast<long long>(_meme_idx);",
                        f"{pad}        {el_cpp} {item_ident} = _meme_col[_meme_idx];",
                    ]
                    for ch in stmt.body:
                        lines.extend(self.gen_stmt(ch, sub, indent + 2))
                    lines.append(f"{pad}    }}")
                    lines.append(f"{pad}}}")
                    return lines
                else:
                    lines = [
                        f"{pad}for ({el_cpp} {item_ident} : {col_ident}) {{"
                    ]
                    for ch in stmt.body:
                        lines.extend(self.gen_stmt(ch, sub, indent + 1))
                    lines.append(f"{pad}}}")
                    return lines

        if isinstance(stmt, ForRangeStmt):
            sub = dict(scope)
            sub[stmt.loop_var] = "Int"
            lv = _cpp_ident(stmt.loop_var)
            s = self.gen_expr(stmt.start, scope)
            e = self.gen_expr(stmt.end, scope)
            lines = [
                f"{pad}for (long long {lv} = ({s}); {lv} <= ({e}); ++{lv}) {{"
            ]
            for ch in stmt.body:
                lines.extend(self.gen_stmt(ch, sub, indent + 1))
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
            return [f"{pad}return {self.gen_expr(stmt.value, scope)};"]

        if isinstance(stmt, RecordDefStmt):
            return []

        if isinstance(stmt, RecordSetFieldStmt):
            return [
                f"{pad}{_cpp_ident(stmt.target)}.{_cpp_ident(stmt.field_name)} = {self.gen_expr(stmt.value, scope)};"
            ]

        if isinstance(stmt, MapSetStmt):
            return [
                f"{pad}{_cpp_ident(stmt.target)}[{self.gen_expr(stmt.key, scope)}] = {self.gen_expr(stmt.value, scope)};"
            ]

        if isinstance(stmt, WriteFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return [
                f"{pad}_meme_write_file({self.gen_expr(stmt.filepath, scope)}, {self.gen_expr(stmt.content, scope)});"
            ]

        if isinstance(stmt, AppendFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return [
                f"{pad}_meme_append_file({self.gen_expr(stmt.filepath, scope)}, {self.gen_expr(stmt.content, scope)});"
            ]

        if isinstance(stmt, CopyFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return [
                f"{pad}_meme_copy_file({self.gen_expr(stmt.src, scope)}, {self.gen_expr(stmt.dst, scope)});"
            ]

        if isinstance(stmt, MoveFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return [
                f"{pad}_meme_move_file({self.gen_expr(stmt.src, scope)}, {self.gen_expr(stmt.dst, scope)});"
            ]

        if isinstance(stmt, RenameFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return [
                f"{pad}_meme_rename_file({self.gen_expr(stmt.path, scope)}, {self.gen_expr(stmt.new_name, scope)});"
            ]

        if isinstance(stmt, DeleteFileStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return [
                f"{pad}_meme_delete_file({self.gen_expr(stmt.path, scope)});"
            ]

        if isinstance(stmt, CreateDirectoryStmt):
            self.uses_str_helpers = True
            self.uses_file_io = True
            return [
                f"{pad}_meme_create_directory({self.gen_expr(stmt.path, scope)});"
            ]

        if isinstance(stmt, ImportStmt):
            return []

        raise TypeError(f"Unsupported statement inside block: {type(stmt)!r}")

    def gen_func(self, fn: FuncDefStmt) -> list[str]:
        self.func_returns[fn.name] = fn.return_type
        params = ", ".join(f"{_cpp_type(p.param_type)} {_cpp_ident(p.name)}" for p in fn.params)
        fn_scope = {p.name: p.param_type for p in fn.params}
        lines = [f"{_cpp_type(fn.return_type)} {_cpp_ident(fn.name)}({params}) {{"]
        for ch in fn.body:
            lines.extend(self.gen_stmt(ch, fn_scope, indent=1))
        lines.append("}")
        return lines


def generate_cpp(ir: ProgramIR) -> str:
    gen = _CppGen()
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

    record_blocks: list[str] = []
    for r in records:
        r_name = _cpp_ident(r.name)
        record_blocks.append(f"struct {r_name} {{")
        for f in r.fields:
            record_blocks.append(f"    {_cpp_type(f.field_type)} {_cpp_ident(f.name)}{{}};")
        record_blocks.append(f"    bool operator==(const {r_name}&) const = default;")
        record_blocks.append("};")
        record_blocks.append(f"inline std::string _meme_fmt(const {r_name}& self) {{")
        if not r.fields:
            record_blocks.append(f'    return "{r.name}()";')
        else:
            parts = [
                f'oss << "{f.name}=" << _meme_fmt(self.{_cpp_ident(f.name)});'
                for f in r.fields
            ]
            record_blocks.append("    std::ostringstream oss;")
            record_blocks.append(f'    oss << "{r.name}(";')
            for idx, part in enumerate(parts):
                if idx > 0:
                    record_blocks.append('    oss << ", ";')
                record_blocks.append(f"    {part}")
            record_blocks.append('    oss << ")";')
            record_blocks.append("    return oss.str();")
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

    headers: list[str] = [
        "#include <algorithm>",
        "#include <cctype>",
        "#include <cmath>",
        "#include <cstdlib>",
        "#include <filesystem>",
        "#include <fstream>",
        "#include <iostream>",
        "#include <optional>",
        "#include <sstream>",
        "#include <string>",
        "#include <unordered_map>",
        "#include <utility>",
        "#include <vector>",
    ]
    if gen.uses_random:
        headers.append("#include <random>")
    headers.append("")

    helpers: list[str] = [
        "inline std::string _meme_fmt(bool v) { return v ? \"true\" : \"false\"; }",
        "inline std::string _meme_fmt(double v) {",
        "    if (std::isfinite(v) && std::trunc(v) == v && v >= -9007199254740992.0 && v <= 9007199254740992.0) {",
        "        return std::to_string(static_cast<long long>(v));",
        "    }",
        "    std::ostringstream oss;",
        "    oss << v;",
        "    return oss.str();",
        "}",
        "inline const std::string& _meme_fmt(const std::string& v) { return v; }",
        "template <typename T>",
        "std::string _meme_fmt(const T& v) {",
        "    std::ostringstream oss;",
        "    oss << v;",
        "    return oss.str();",
        "}",
        "template <typename T>",
        "std::string _meme_fmt(const std::vector<T>& vec) {",
        "    std::ostringstream oss;",
        "    oss << '[';",
        "    for (std::size_t i = 0; i < vec.size(); ++i) {",
        "        if (i > 0) oss << \", \";",
        "        oss << _meme_fmt(vec[i]);",
        "    }",
        "    oss << ']';",
        "    return oss.str();",
        "}",
        "template <typename K, typename V>",
        "std::string _meme_fmt(const std::unordered_map<K, V>& map) {",
        "    std::vector<std::pair<K, V>> items(map.begin(), map.end());",
        "    std::sort(items.begin(), items.end(), [](const auto& a, const auto& b) {",
        "        return _meme_fmt(a.first) < _meme_fmt(b.first);",
        "    });",
        "    std::ostringstream oss;",
        "    oss << '{';",
        "    for (std::size_t i = 0; i < items.size(); ++i) {",
        "        if (i > 0) oss << \", \";",
        "        oss << _meme_fmt(items[i].first) << \": \" << _meme_fmt(items[i].second);",
        "    }",
        "    oss << '}';",
        "    return oss.str();",
        "}",
        "template <typename T>",
        "std::string _meme_fmt(const std::optional<T>& opt) {",
        "    if (opt.has_value()) return _meme_fmt(*opt);",
        "    return \"None\";",
        "}",
        "",
    ]

    if gen.uses_argv:
        helpers.extend(
            [
                "inline std::vector<std::string>& _meme_argv() {",
                "    static std::vector<std::string> args;",
                "    return args;",
                "}",
                "inline std::string _meme_arg_at(long long idx) {",
                "    const auto& args = _meme_argv();",
                "    if (idx < 0 || static_cast<std::size_t>(idx) >= args.size()) {",
                "        std::cout << \"Error: argument index \" << idx << \" out of range\\n\";",
                "        std::exit(1);",
                "    }",
                "    return args[static_cast<std::size_t>(idx)];",
                "}",
                "",
            ]
        )

    if gen.uses_list_remove:
        helpers.extend(
            [
                "template <typename T>",
                "inline void _meme_list_remove(std::vector<T>& vec, int64_t idx) {",
                "    if (idx < 0 || static_cast<std::size_t>(idx) >= vec.size()) {",
                "        std::cout << \"Error: list index out of range\\n\";",
                "        std::exit(1);",
                "    }",
                "    vec.erase(vec.begin() + static_cast<std::ptrdiff_t>(idx));",
                "}",
                "template <typename T>",
                "inline void _meme_list_remove_last(std::vector<T>& vec) {",
                "    if (vec.empty()) {",
                "        std::cout << \"Error: list index out of range\\n\";",
                "        std::exit(1);",
                "    }",
                "    vec.pop_back();",
                "}",
                "",
            ]
        )

    if gen.uses_parse_int_or_else:
        helpers.extend(
            [
                "template <typename F>",
                "inline long long _meme_parse_int_or_else(const std::string& s, F default_fn) {",
                "    std::size_t a = 0;",
                "    while (a < s.size() && std::isspace(static_cast<unsigned char>(s[a]))) ++a;",
                "    std::size_t b = s.size();",
                "    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) --b;",
                "    std::string ts = s.substr(a, b - a);",
                "    if (ts.empty()) {",
                "        return default_fn();",
                "    }",
                "    try {",
                "        std::size_t idx = 0;",
                "        long long v = std::stoll(ts, &idx);",
                "        if (idx != ts.size()) {",
                "            return default_fn();",
                "        }",
                "        return v;",
                "    } catch (...) {",
                "        return default_fn();",
                "    }",
                "}",
                "",
            ]
        )

    if gen.uses_is_digit:
        helpers.extend(
            [
                "inline bool _meme_is_digit(const std::string& s) {",
                "    return s.size() == 1 && s[0] >= '0' && s[0] <= '9';",
                "}",
                "",
            ]
        )

    if gen.uses_optional_helpers:
        helpers.extend(
            [
                "template <typename T>",
                "T _meme_unwrap(const std::optional<T>& opt) {",
                "    if (!opt.has_value()) {",
                "        std::cout << \"Unwrap failed: Optional value is nothing\\n\";",
                "        std::exit(1);",
                "    }",
                "    return *opt;",
                "}",
                "",
                "template <typename T, typename F>",
                "T _meme_unwrap_or_else(const std::optional<T>& opt, F default_fn) {",
                "    if (opt.has_value()) return *opt;",
                "    return default_fn();",
                "}",
                "",
            ]
        )

    if gen.uses_random:
        helpers.extend(
            [
                "inline std::mt19937_64& _meme_rng() {",
                "    static std::mt19937_64 gen{std::random_device{}()};",
                "    return gen;",
                "}",
                "inline long long _meme_rand_int(long long lo, long long hi) {",
                "    if (hi <= lo) return lo;",
                "    std::uniform_int_distribution<long long> dist(lo, hi);",
                "    return dist(_meme_rng());",
                "}",
                "inline std::vector<long long> _meme_rand_list(long long count, long long lo, long long hi) {",
                "    std::vector<long long> out;",
                "    if (count > 0) {",
                "        out.reserve(static_cast<std::size_t>(count));",
                "        for (long long i = 0; i < count; ++i) out.push_back(_meme_rand_int(lo, hi));",
                "    }",
                "    return out;",
                "}",
                "",
            ]
        )

    if gen.uses_input:
        helpers.extend(
            [
                "inline std::string _meme_read_line(const std::string& prompt) {",
                "    const char* q = std::getenv(\"MEME_QUIET_PROMPTS\");",
                "    bool quiet = false;",
                "    if (q) {",
                "        std::string qs(q);",
                "        for (char& c : qs) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));",
                "        quiet = (qs == \"1\" || qs == \"true\" || qs == \"yes\");",
                "    }",
                "    if (!prompt.empty() && !quiet) { std::cout << prompt << std::flush; }",
                "    std::string line;",
                "    std::getline(std::cin, line);",
                "    if (!line.empty() && line.back() == '\\r') line.pop_back();",
                "    return line;",
                "}",
                "inline long long _meme_parse_int(const std::string& s) {",
                "    std::size_t a = 0;",
                "    while (a < s.size() && std::isspace(static_cast<unsigned char>(s[a]))) ++a;",
                "    std::size_t b = s.size();",
                "    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) --b;",
                "    std::string ts = s.substr(a, b - a);",
                "    if (ts.empty()) {",
                "        std::cout << \"Error parsing integer: \" << s << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    try {",
                "        std::size_t idx = 0;",
                "        long long v = std::stoll(ts, &idx);",
                "        if (idx != ts.size()) {",
                "            std::cout << \"Error parsing integer: \" << s << \"\\n\";",
                "            std::exit(1);",
                "        }",
                "        return v;",
                "    } catch (...) {",
                "        std::cout << \"Error parsing integer: \" << s << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "}",
                "inline double _meme_parse_float(const std::string& s) {",
                "    try {",
                "        std::size_t idx = 0;",
                "        return std::stod(s, &idx);",
                "    } catch (...) {",
                "        return 0.0;",
                "    }",
                "}",
                "inline bool _meme_parse_bool(const std::string& s) {",
                "    std::size_t a = 0;",
                "    while (a < s.size() && std::isspace(static_cast<unsigned char>(s[a]))) ++a;",
                "    std::size_t b = s.size();",
                "    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) --b;",
                "    std::string low;",
                "    low.reserve(b - a);",
                "    for (std::size_t i = a; i < b; ++i) {",
                "        low.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(s[i]))));",
                "    }",
                "    return low == \"true\" || low == \"1\" || low == \"yes\";",
                "}",
                "",
            ]
        )

    if gen.uses_str_helpers:
        helpers.extend(
            [
                "inline std::string _meme_trim(const std::string& s) {",
                "    std::size_t a = 0;",
                "    while (a < s.size() && std::isspace(static_cast<unsigned char>(s[a]))) ++a;",
                "    std::size_t b = s.size();",
                "    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) --b;",
                "    return s.substr(a, b - a);",
                "}",
                "inline long long _meme_str_len(const std::string& s) {",
                "    long long count = 0;",
                "    for (unsigned char c : s) {",
                "        if ((c & 0xC0) != 0x80) ++count;",
                "    }",
                "    return count;",
                "}",
                "inline std::string _meme_str_slice(const std::string& s, long long start, long long end) {",
                "    if (start < 0) start = 0;",
                "    if (end <= start) return std::string();",
                "    std::size_t byte_start = s.size();",
                "    std::size_t byte_end = s.size();",
                "    long long cp_idx = 0;",
                "    for (std::size_t i = 0; i < s.size(); ++i) {",
                "        unsigned char c = static_cast<unsigned char>(s[i]);",
                "        if ((c & 0xC0) != 0x80) {",
                "            if (cp_idx == start) byte_start = i;",
                "            if (cp_idx == end) { byte_end = i; break; }",
                "            ++cp_idx;",
                "        }",
                "    }",
                "    if (byte_start >= s.size() || byte_end <= byte_start) return std::string();",
                "    return s.substr(byte_start, byte_end - byte_start);",
                "}",
                "inline bool _meme_ends_with_ci(const std::string& s, const std::string& suf) {",
                "    std::string ts = _meme_trim(s);",
                "    if (ts.size() < suf.size()) return false;",
                "    std::size_t off = ts.size() - suf.size();",
                "    for (std::size_t i = 0; i < suf.size(); ++i) {",
                "        if (std::tolower(static_cast<unsigned char>(ts[off + i])) != std::tolower(static_cast<unsigned char>(suf[i]))) return false;",
                "    }",
                "    return true;",
                "}",
                "inline bool _meme_starts_with(const std::string& s, const std::string& pre) {",
                "    return s.size() >= pre.size() && s.compare(0, pre.size(), pre) == 0;",
                "}",
                "inline std::string _meme_str_upper(const std::string& s) {",
                "    std::string out;",
                "    out.reserve(s.size());",
                "    for (unsigned char c : s) out.push_back(static_cast<char>(std::toupper(c)));",
                "    return out;",
                "}",
                "inline std::string _meme_str_lower(const std::string& s) {",
                "    std::string out;",
                "    out.reserve(s.size());",
                "    for (unsigned char c : s) out.push_back(static_cast<char>(std::tolower(c)));",
                "    return out;",
                "}",
                "inline std::string _meme_str_replace(const std::string& s, const std::string& old_sub, const std::string& new_sub) {",
                "    if (old_sub.empty()) {",
                "        std::string out = new_sub;",
                "        for (char c : s) {",
                "            out.push_back(c);",
                "            out += new_sub;",
                "        }",
                "        return out;",
                "    }",
                "    std::string out;",
                "    std::size_t pos = 0;",
                "    while (true) {",
                "        std::size_t found = s.find(old_sub, pos);",
                "        if (found == std::string::npos) {",
                "            out.append(s, pos, std::string::npos);",
                "            break;",
                "        }",
                "        out.append(s, pos, found - pos);",
                "        out += new_sub;",
                "        pos = found + old_sub.size();",
                "    }",
                "    return out;",
                "}",
                "inline std::vector<std::string> _meme_str_split(const std::string& s, const std::string& sep) {",
                "    if (sep.empty()) {",
                "        std::cout << \"Error: empty separator in split\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::vector<std::string> out;",
                "    std::size_t pos = 0;",
                "    while (true) {",
                "        std::size_t found = s.find(sep, pos);",
                "        if (found == std::string::npos) {",
                "            out.push_back(s.substr(pos));",
                "            break;",
                "        }",
                "        out.push_back(s.substr(pos, found - pos));",
                "        pos = found + sep.size();",
                "    }",
                "    return out;",
                "}",
                "inline std::string _meme_str_join(const std::vector<std::string>& items, const std::string& sep) {",
                "    std::string out;",
                "    for (std::size_t i = 0; i < items.size(); ++i) {",
                "        if (i > 0) out += sep;",
                "        out += items[i];",
                "    }",
                "    return out;",
                "}",
                "inline long long _meme_str_index_of(const std::string& s, const std::string& sub) {",
                "    std::size_t pos = s.find(sub);",
                "    return pos == std::string::npos ? -1LL : static_cast<long long>(pos);",
                "}",
                "inline std::string _meme_char_at(const std::string& s, long long idx) {",
                "    if (idx < 0 || static_cast<std::size_t>(idx) >= s.size()) {",
                "        std::cout << \"Error: string index \" << idx << \" out of range\\n\";",
                "        std::exit(1);",
                "    }",
                "    return std::string(1, s[static_cast<std::size_t>(idx)]);",
                "}",
                "",
            ]
        )

    if gen.uses_json_io or gen.uses_file_io:
        helpers.extend(
            [
                "inline std::filesystem::path _meme_resolve_path(const std::string& path) {",
                "    std::filesystem::path p(_meme_trim(path));",
                "    if (std::filesystem::exists(p) || p.is_absolute()) return p;",
                "    if (const char* sd = std::getenv(\"MEME_SOURCE_DIR\")) {",
                "        std::string sds = _meme_trim(sd);",
                "        if (!sds.empty()) {",
                "            std::filesystem::path cand = std::filesystem::path(sds) / p;",
                "            if (std::filesystem::exists(cand)) return cand;",
                "        }",
                "    }",
                "    return p;",
                "}",
            ]
        )

    if gen.uses_file_io:
        helpers.extend(
            [
                "inline bool _meme_file_exists(const std::string& path) {",
                "    std::error_code ec;",
                "    return std::filesystem::is_regular_file(_meme_resolve_path(path), ec);",
                "}",
                "inline std::string _meme_read_file_string(const std::string& path) {",
                "    std::error_code ec;",
                "    std::filesystem::path rp = _meme_resolve_path(path);",
                "    if (!std::filesystem::is_regular_file(rp, ec)) {",
                "        std::cout << \"Error reading file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::ifstream ifs(rp, std::ios::binary);",
                "    if (!ifs) {",
                "        std::cout << \"Error reading file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::ostringstream ss;",
                "    ss << ifs.rdbuf();",
                "    return ss.str();",
                "}",
                "inline void _meme_write_file(const std::string& path, const std::string& content) {",
                "    std::ofstream ofs(_meme_trim(path), std::ios::out | std::ios::trunc | std::ios::binary);",
                "    if (!ofs) {",
                "        std::cout << \"Error writing file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    ofs.write(content.data(), static_cast<std::streamsize>(content.size()));",
                "    if (!ofs) {",
                "        std::cout << \"Error writing file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "}",
                "inline void _meme_append_file(const std::string& path, const std::string& content) {",
                "    std::ofstream ofs(_meme_trim(path), std::ios::out | std::ios::app | std::ios::binary);",
                "    if (!ofs) {",
                "        std::cout << \"Error writing file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    ofs.write(content.data(), static_cast<std::streamsize>(content.size()));",
                "    if (!ofs) {",
                "        std::cout << \"Error writing file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "}",
                "inline void _meme_copy_file(const std::string& src, const std::string& dst) {",
                "    std::string rsrc = _meme_resolve_path(src).string();",
                "    std::error_code ec;",
                "    if (!std::filesystem::is_regular_file(rsrc, ec)) {",
                "        std::cout << \"Error copying file: \" << src << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::filesystem::copy_file(rsrc, _meme_trim(dst), std::filesystem::copy_options::overwrite_existing, ec);",
                "    if (ec) {",
                "        std::cout << \"Error copying file: \" << src << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "}",
                "inline void _meme_move_file(const std::string& src, const std::string& dst) {",
                "    std::string rsrc = _meme_resolve_path(src).string();",
                "    std::error_code ec;",
                "    if (!std::filesystem::is_regular_file(rsrc, ec)) {",
                "        std::cout << \"Error moving file: \" << src << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::string target = _meme_trim(dst);",
                "    std::filesystem::rename(rsrc, target, ec);",
                "    if (ec) {",
                "        std::error_code ec2, ec3;",
                "        std::filesystem::copy_file(rsrc, target, std::filesystem::copy_options::overwrite_existing, ec2);",
                "        if (!ec2) {",
                "            std::filesystem::remove(rsrc, ec3);",
                "        }",
                "        if (ec2 || ec3) {",
                "            std::cout << \"Error moving file: \" << src << \"\\n\";",
                "            std::exit(1);",
                "        }",
                "    }",
                "}",
                "inline void _meme_rename_file(const std::string& path, const std::string& new_name) {",
                "    std::string rsrc = _meme_resolve_path(path).string();",
                "    std::error_code ec;",
                "    if (!std::filesystem::is_regular_file(rsrc, ec)) {",
                "        std::cout << \"Error renaming file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::filesystem::path p(_meme_trim(path));",
                "    std::filesystem::path parent = p.parent_path();",
                "    std::filesystem::path nn = std::filesystem::path(_meme_trim(new_name)).filename();",
                "    std::filesystem::path target = parent.empty() ? nn : (parent / nn);",
                "    std::filesystem::rename(rsrc, target, ec);",
                "    if (ec) {",
                "        std::error_code ec2, ec3;",
                "        std::filesystem::copy_file(rsrc, target, std::filesystem::copy_options::overwrite_existing, ec2);",
                "        if (!ec2) {",
                "            std::filesystem::remove(rsrc, ec3);",
                "        }",
                "        if (ec2 || ec3) {",
                "            std::cout << \"Error renaming file: \" << path << \"\\n\";",
                "            std::exit(1);",
                "        }",
                "    }",
                "}",
                "inline void _meme_delete_file(const std::string& path) {",
                "    std::string rsrc = _meme_resolve_path(path).string();",
                "    std::error_code ec;",
                "    if (!std::filesystem::is_regular_file(rsrc, ec)) {",
                "        std::cout << \"Error deleting file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    if (!std::filesystem::remove(rsrc, ec) || ec) {",
                "        std::cout << \"Error deleting file: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "}",
                "inline void _meme_create_directory(const std::string& path) {",
                "    std::error_code ec;",
                "    std::filesystem::create_directories(_meme_trim(path), ec);",
                "    if (ec) {",
                "        std::cout << \"Error creating directory: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "}",
                "inline std::vector<std::string> _meme_list_files(const std::string& path) {",
                "    std::string rpath = _meme_resolve_path(path).string();",
                "    std::error_code ec;",
                "    if (!std::filesystem::is_directory(rpath, ec)) {",
                "        std::cout << \"Error listing directory: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::vector<std::string> res;",
                "    for (const auto& entry : std::filesystem::directory_iterator(rpath, ec)) {",
                "        if (ec) break;",
                "        res.push_back(entry.path().filename().string());",
                "    }",
                "    if (ec) {",
                "        std::cout << \"Error listing directory: \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::sort(res.begin(), res.end());",
                "    return res;",
                "}",
                "",
            ]
        )

    if gen.uses_json_io:
        helpers.extend(
            [
                "struct _MemeJsonTok {",
                "    enum Kind { Str, Bool, Num } kind;",
                "    std::string s;",
                "    bool b = false;",
                "};",
                "[[noreturn]] inline void _meme_json_fail(const std::string& msg) {",
                "    std::cerr << \"Error reading JSON file: \" << msg << \"\\n\";",
                "    std::exit(1);",
                "}",
                "inline void _meme_append_utf8(std::string& out, unsigned int cp) {",
                "    if (cp <= 0x7F) {",
                "        out.push_back(static_cast<char>(cp));",
                "    } else if (cp <= 0x7FF) {",
                "        out.push_back(static_cast<char>(0xC0 | (cp >> 6)));",
                "        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));",
                "    } else if (cp <= 0xFFFF) {",
                "        out.push_back(static_cast<char>(0xE0 | (cp >> 12)));",
                "        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));",
                "        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));",
                "    } else if (cp <= 0x10FFFF) {",
                "        out.push_back(static_cast<char>(0xF0 | (cp >> 18)));",
                "        out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));",
                "        out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));",
                "        out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));",
                "    }",
                "}",
                "inline std::vector<_MemeJsonTok> _meme_parse_json_tokens(const std::string& path) {",
                "    std::ifstream ifs(_meme_resolve_path(path), std::ios::binary);",
                "    if (!ifs) _meme_json_fail(\"cannot open \" + path);",
                "    std::ostringstream ss;",
                "    ss << ifs.rdbuf();",
                "    std::string raw = ss.str();",
                "    std::size_t n = raw.size();",
                "    std::size_t i = 0;",
                "    auto is_ws = [&](std::size_t k) { return std::isspace(static_cast<unsigned char>(raw[k])) != 0; };",
                "    while (i < n && is_ws(i)) ++i;",
                "    if (i >= n || raw[i] != '[') _meme_json_fail(\"expected JSON array\");",
                "    ++i;",
                "    while (i < n && is_ws(i)) ++i;",
                "    std::vector<_MemeJsonTok> out;",
                "    if (i < n && raw[i] == ']') {",
                "        ++i;",
                "        while (i < n && is_ws(i)) ++i;",
                "        if (i != n) _meme_json_fail(\"trailing data after JSON array\");",
                "        return out;",
                "    }",
                "    while (true) {",
                "        while (i < n && is_ws(i)) ++i;",
                "        if (i >= n) _meme_json_fail(\"unterminated JSON array\");",
                "        if (raw[i] == '\"') {",
                "            ++i;",
                "            std::string s;",
                "            while (i < n && raw[i] != '\"') {",
                "                if (raw[i] == '\\\\') {",
                "                    ++i;",
                "                    if (i >= n) _meme_json_fail(\"unterminated string escape\");",
                "                    switch (raw[i]) {",
                "                        case '\"': s.push_back('\"'); break;",
                "                        case '\\\\': s.push_back('\\\\'); break;",
                "                        case '/': s.push_back('/'); break;",
                "                        case 'b': s.push_back('\\b'); break;",
                "                        case 'f': s.push_back('\\f'); break;",
                "                        case 'n': s.push_back('\\n'); break;",
                "                        case 'r': s.push_back('\\r'); break;",
                "                        case 't': s.push_back('\\t'); break;",
                "                        case 'u': {",
                "                            if (i + 4 >= n) _meme_json_fail(\"invalid unicode escape\");",
                "                            std::string hex = raw.substr(i + 1, 4);",
                "                            try {",
                "                                std::size_t hidx = 0;",
                "                                unsigned long cp = std::stoul(hex, &hidx, 16);",
                "                                if (hidx != 4) _meme_json_fail(\"invalid unicode escape\");",
                "                                _meme_append_utf8(s, static_cast<unsigned int>(cp));",
                "                            } catch (...) {",
                "                                _meme_json_fail(\"invalid unicode escape\");",
                "                            }",
                "                            i += 4;",
                "                            break;",
                "                        }",
                "                        default: _meme_json_fail(\"invalid escape sequence\");",
                "                    }",
                "                } else {",
                "                    s.push_back(raw[i]);",
                "                }",
                "                ++i;",
                "            }",
                "            if (i >= n || raw[i] != '\"') _meme_json_fail(\"unterminated string literal\");",
                "            ++i;",
                "            out.push_back({_MemeJsonTok::Str, s, false});",
                "        } else {",
                "            std::size_t start = i;",
                "            while (i < n && !is_ws(i) && raw[i] != ',' && raw[i] != ']') {",
                "                if (raw[i] == '[' || raw[i] == '{' || raw[i] == '}' || raw[i] == '\"') {",
                "                    _meme_json_fail(\"unexpected nested or malformed token\");",
                "                }",
                "                ++i;",
                "            }",
                "            if (i == start) _meme_json_fail(\"expected element\");",
                "            std::string tok = raw.substr(start, i - start);",
                "            if (tok == \"true\") {",
                "                out.push_back({_MemeJsonTok::Bool, \"\", true});",
                "            } else if (tok == \"false\") {",
                "                out.push_back({_MemeJsonTok::Bool, \"\", false});",
                "            } else if (tok == \"null\") {",
                "                _meme_json_fail(\"JSON null is not allowed\");",
                "            } else {",
                "                out.push_back({_MemeJsonTok::Num, tok, false});",
                "            }",
                "        }",
                "        while (i < n && is_ws(i)) ++i;",
                "        if (i < n && raw[i] == ',') {",
                "            ++i;",
                "            continue;",
                "        } else if (i < n && raw[i] == ']') {",
                "            ++i;",
                "            break;",
                "        } else {",
                "            _meme_json_fail(\"expected `,` or `]`\");",
                "        }",
                "    }",
                "    while (i < n && is_ws(i)) ++i;",
                "    if (i != n) _meme_json_fail(\"trailing data after JSON array\");",
                "    return out;",
                "}",
                "inline std::vector<long long> _meme_read_json_list_int(const std::string& path) {",
                "    std::vector<long long> out;",
                "    for (const auto& t : _meme_parse_json_tokens(path)) {",
                "        if (t.kind != _MemeJsonTok::Num) _meme_json_fail(\"expected Int element\");",
                "        try {",
                "            std::size_t idx = 0;",
                "            long long v = std::stoll(t.s, &idx, 10);",
                "            if (idx != t.s.size()) _meme_json_fail(\"expected Int, got `\" + t.s + \"`\");",
                "            out.push_back(v);",
                "        } catch (...) {",
                "            _meme_json_fail(\"expected Int, got `\" + t.s + \"`\");",
                "        }",
                "    }",
                "    return out;",
                "}",
                "inline std::vector<double> _meme_read_json_list_float(const std::string& path) {",
                "    std::vector<double> out;",
                "    for (const auto& t : _meme_parse_json_tokens(path)) {",
                "        if (t.kind != _MemeJsonTok::Num) _meme_json_fail(\"expected Float element\");",
                "        try {",
                "            std::size_t idx = 0;",
                "            double v = std::stod(t.s, &idx);",
                "            if (idx != t.s.size() || !std::isfinite(v)) _meme_json_fail(\"expected Float, got `\" + t.s + \"`\");",
                "            out.push_back(v);",
                "        } catch (...) {",
                "            _meme_json_fail(\"expected Float, got `\" + t.s + \"`\");",
                "        }",
                "    }",
                "    return out;",
                "}",
                "inline std::vector<std::string> _meme_read_json_list_string(const std::string& path) {",
                "    std::vector<std::string> out;",
                "    for (const auto& t : _meme_parse_json_tokens(path)) {",
                "        if (t.kind != _MemeJsonTok::Str) _meme_json_fail(\"expected String element\");",
                "        out.push_back(t.s);",
                "    }",
                "    return out;",
                "}",
                "inline std::vector<bool> _meme_read_json_list_bool(const std::string& path) {",
                "    std::vector<bool> out;",
                "    for (const auto& t : _meme_parse_json_tokens(path)) {",
                "        if (t.kind != _MemeJsonTok::Bool) _meme_json_fail(\"expected Bool element\");",
                "        out.push_back(t.b);",
                "    }",
                "    return out;",
                "}",
                "",
            ]
        )

    main_header = (
        ["int main(int argc, char** argv) {", "    _meme_argv().assign(argv, argv + argc);"]
        if gen.uses_argv
        else ["int main() {"]
    )
    out = (
        headers
        + helpers
        + record_blocks
        + fn_blocks
        + main_header
        + main_lines
        + ["    return 0;", "}", ""]
    )
    return "\n".join(out)

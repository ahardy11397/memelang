"""Deterministic Python 3 code generator for Memelang ProgramIR."""

from __future__ import annotations

import keyword

from memelang.ir.schema import (
    AppendFileStmt,
    ArgAtExpr,
    ArgCountExpr,
    AssignStmt,
    BinaryOpExpr,
    BreakStmt,
    CallExpr,
    CallStmt,
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
    ReadFileLinesExpr,
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


def _py_ident(name: str) -> str:
    return f"meme_{name}" if keyword.iskeyword(name) or name.startswith("_meme_") else name


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


class _PyGen:
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_math = False
        self.uses_json_io = False
        self.uses_file_io = False
        self.uses_list_remove = False
        self.uses_parse_int_or_else = False
        self.uses_is_digit = False
        self.uses_is_letter = False
        self.uses_is_upper = False
        self.uses_is_lower = False
        self.uses_argv = False
        self.uses_input = False
        self.uses_input_helpers = False
        self.uses_str_split = False
        self.uses_char_at = False
        self.uses_dataclass = False
        self.uses_optional_helpers = False
        self._match_counter = 0
        self.symbols: dict[str, MemeType] = {}
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
                ReadFileStringExpr,
                ArgAtExpr,
            ),
        ):
            return "String"
        if isinstance(expr, ReadFileLinesExpr):
            return "List<String>"
        if isinstance(expr, ListIndexExpr):
            col_t = self.infer_type(expr.target, scope)
            if col_t.startswith("List<"):
                return col_t[5:-1]  # type: ignore[return-value]
            mt = _map_types_of(col_t)
            if mt is not None:
                return mt[1]
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
            self.uses_input = True
            raw = f"_meme_read_line({repr(expr.prompt)})"
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

        if isinstance(expr, StrStartsWithExpr):
            tgt = self.gen_expr(expr.target, scope)
            pre = self.gen_expr(expr.prefix, scope)
            return f"({tgt}.startswith({pre}))"

        if isinstance(expr, StrContainsExpr):
            tgt = self.gen_expr(expr.target, scope)
            sub = self.gen_expr(expr.substring, scope)
            return f"({sub} in {tgt})"

        if isinstance(expr, StringReplaceExpr):
            tgt = self.gen_expr(expr.target, scope)
            old_s = self.gen_expr(expr.old, scope)
            new_s = self.gen_expr(expr.new, scope)
            return f"{tgt}.replace({old_s}, {new_s})"

        if isinstance(expr, StringUpperExpr):
            return f"{self.gen_expr(expr.target, scope)}.upper()"

        if isinstance(expr, StringLowerExpr):
            return f"{self.gen_expr(expr.target, scope)}.lower()"

        if isinstance(expr, StringTrimExpr):
            return f"{self.gen_expr(expr.target, scope)}.strip()"

        if isinstance(expr, StringSplitExpr):
            self.uses_str_split = True
            return f"_meme_str_split({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.separator, scope)})"

        if isinstance(expr, StringJoinExpr):
            return f"({self.gen_expr(expr.separator, scope)}).join({self.gen_expr(expr.items, scope)})"

        if isinstance(expr, StringIndexOfExpr):
            return f"{self.gen_expr(expr.target, scope)}.find({self.gen_expr(expr.substring, scope)})"

        if isinstance(expr, StringCharAtExpr):
            self.uses_char_at = True
            return f"_meme_char_at({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.index, scope)})"

        if isinstance(expr, StringLengthExpr):
            return f"_meme_builtins.len({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, StringSliceExpr):
            tgt = self.gen_expr(expr.target, scope)
            s = self.gen_expr(expr.start, scope)
            e = self.gen_expr(expr.end, scope)
            return f"{tgt}[_meme_builtins.int({s}):_meme_builtins.int({e})]"

        if isinstance(expr, ParseIntExpr):
            self.uses_input_helpers = True
            return f"_meme_parse_int({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ParseIntOrDefaultExpr):
            self.uses_parse_int_or_else = True
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_parse_int_or_else({tgt}, lambda: {dflt})"

        if isinstance(expr, IsDigitExpr):
            self.uses_is_digit = True
            return f"_meme_is_digit({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, IsLetterExpr):
            self.uses_is_letter = True
            return f"_meme_is_letter({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, IsUpperExpr):
            self.uses_is_upper = True
            return f"_meme_is_upper({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, IsLowerExpr):
            self.uses_is_lower = True
            return f"_meme_is_lower({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, FormatIntExpr):
            return f"_meme_builtins.str({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, ReadJsonListExpr):
            self.uses_json_io = True
            return f"_meme_read_json_list({self.gen_expr(expr.filepath, scope)}, {repr(expr.element_type)})"

        if isinstance(expr, FileExistsExpr):
            self.uses_file_io = True
            return f"_meme_file_exists({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ReadFileStringExpr):
            self.uses_file_io = True
            return f"_meme_read_file_string({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ReadFileLinesExpr):
            self.uses_file_io = True
            return f"_meme_read_file_lines({self.gen_expr(expr.filepath, scope)})"

        if isinstance(expr, ListFilesExpr):
            self.uses_file_io = True
            return f"_meme_list_files({self.gen_expr(expr.path, scope)})"

        if isinstance(expr, ArgCountExpr):
            self.uses_argv = True
            return "_meme_builtins.len(_meme_sys.argv)"

        if isinstance(expr, ArgAtExpr):
            self.uses_argv = True
            return f"_meme_arg_at({self.gen_expr(expr.index, scope)})"

        if isinstance(expr, RecordLiteralExpr):
            fields_code = ", ".join(
                f"{_py_ident(f.name)}={self.gen_expr(f.value, scope)}" for f in expr.fields
            )
            return f"{expr.record_name}({fields_code})"

        if isinstance(expr, RecordFieldExpr):
            return f"{self.gen_expr(expr.target, scope)}.{_py_ident(expr.field_name)}"

        if isinstance(expr, MapLiteralExpr):
            if not expr.entries:
                return "{}"
            entries_code = ", ".join(
                f"{self.gen_expr(e.key, scope)}: {self.gen_expr(e.value, scope)}"
                for e in expr.entries
            )
            return f"{{{entries_code}}}"

        if isinstance(expr, MapGetExpr):
            tgt = self.gen_expr(expr.target, scope)
            k = self.gen_expr(expr.key, scope)
            if expr.default_val is not None:
                def_val = self.gen_expr(expr.default_val, scope)
                return f"({tgt}.get({k}, {def_val}))"
            return f"{tgt}[{k}]"

        if isinstance(expr, MapHasKeyExpr):
            k = self.gen_expr(expr.key, scope)
            tgt = self.gen_expr(expr.target, scope)
            return f"({k} in {tgt})"

        if isinstance(expr, OptionalNoneExpr):
            return "None"

        if isinstance(expr, OptionalWrapExpr):
            return self.gen_expr(expr.value, scope)

        if isinstance(expr, OptionalIsNothingExpr):
            tgt = self.gen_expr(expr.target, scope)
            if expr.negated:
                return f"({tgt} is not None)"
            return f"({tgt} is None)"

        if isinstance(expr, OptionalUnwrapExpr):
            self.uses_optional_helpers = True
            return f"_meme_unwrap({self.gen_expr(expr.target, scope)})"

        if isinstance(expr, OptionalUnwrapOrDefaultExpr):
            self.uses_optional_helpers = True
            tgt = self.gen_expr(expr.target, scope)
            dflt = self.gen_expr(expr.default_val, scope)
            return f"_meme_unwrap_or_else({tgt}, lambda: {dflt})"

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

        if isinstance(stmt, CompoundAssignStmt):
            tgt = _py_ident(stmt.target)
            val_code = self.gen_expr(stmt.value, scope)
            if stmt.operator == "/" and scope.get(stmt.target, "Int") == "Int":
                self.uses_math = True
                return [f"{pad}{tgt} = _meme_int_div({tgt}, {val_code})"]
            return [f"{pad}{tgt} = ({tgt} {stmt.operator} {val_code})"]

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

        if isinstance(stmt, ListRemoveStmt):
            self.uses_list_remove = True
            tgt = _py_ident(stmt.target)
            if stmt.index is not None:
                idx = self.gen_expr(stmt.index, scope)
                return [f"{pad}_meme_list_remove({tgt}, {idx})"]
            return [f"{pad}_meme_list_remove_last({tgt})"]

        if isinstance(stmt, FailStmt):
            return [
                f"{pad}_meme_builtins.print(_meme_fmt({self.gen_expr(stmt.message, scope)}))",
                f"{pad}raise _meme_builtins.SystemExit(1)",
            ]

        if isinstance(stmt, ExitStmt):
            return [
                f"{pad}raise _meme_builtins.SystemExit(_meme_builtins.int({self.gen_expr(stmt.code, scope)}) & 0xFF)"
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

        if isinstance(stmt, SwitchStmt):
            self._match_counter += 1
            m_var = f"_meme_m{self._match_counter}"
            lines = [f"{pad}{m_var} = {self.gen_expr(stmt.target, scope)}"]
            if stmt.cases:
                for i, case in enumerate(stmt.cases):
                    kw = "if" if i == 0 else "elif"
                    lines.append(f"{pad}{kw} {m_var} == {self.gen_expr(case.value, scope)}:")
                    case_scope = dict(scope)
                    if case.body:
                        for ch in case.body:
                            lines.extend(self.gen_stmt(ch, case_scope, indent + 1))
                    else:
                        lines.append(f"{pad}    pass")
                if stmt.default_body:
                    lines.append(f"{pad}else:")
                    def_scope = dict(scope)
                    for ch in stmt.default_body:
                        lines.extend(self.gen_stmt(ch, def_scope, indent + 1))
            elif stmt.default_body:
                def_scope = dict(scope)
                for ch in stmt.default_body:
                    lines.extend(self.gen_stmt(ch, def_scope, indent))
            return lines

        if isinstance(stmt, ForEachStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.collection, "List<Int>")
            map_t = _map_types_of(col_t)
            if map_t is not None:
                sub[stmt.item_var] = map_t[0]  # type: ignore[assignment]
                iter_expr = f"_meme_builtins.sorted({_py_ident(stmt.collection)}.keys())"
            else:
                sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
                iter_expr = f"{_py_ident(stmt.collection)}[:]"
            if stmt.index_var is not None:
                sub[stmt.index_var] = "Int"
                lines = [
                    f"{pad}for {_py_ident(stmt.index_var)}, {_py_ident(stmt.item_var)} in _meme_builtins.enumerate({iter_expr}):"
                ]
            else:
                lines = [f"{pad}for {_py_ident(stmt.item_var)} in {iter_expr}:"]
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

        if isinstance(stmt, BreakStmt):
            return [f"{pad}break"]

        if isinstance(stmt, ContinueStmt):
            return [f"{pad}continue"]

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

        if isinstance(stmt, RecordDefStmt):
            self.uses_dataclass = True
            self.records[stmt.name] = {f.name: f.field_type for f in stmt.fields}
            lines = [f"{pad}@_dataclass", f"{pad}class {stmt.name}:"]
            if not stmt.fields:
                lines.append(f"{pad}    pass")
            else:
                for f in stmt.fields:
                    lines.append(f"{pad}    {_py_ident(f.name)}: object = None")
            return lines

        if isinstance(stmt, RecordSetFieldStmt):
            return [
                f"{pad}{_py_ident(stmt.target)}.{_py_ident(stmt.field_name)} = {self.gen_expr(stmt.value, scope)}"
            ]

        if isinstance(stmt, MapSetStmt):
            return [
                f"{pad}{_py_ident(stmt.target)}[{self.gen_expr(stmt.key, scope)}] = {self.gen_expr(stmt.value, scope)}"
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

        if isinstance(stmt, CallStmt):
            args = ", ".join(self.gen_expr(a, scope) for a in stmt.args)
            return [f"{pad}{_py_ident(stmt.func_name)}({args})"]

        raise TypeError(f"Unsupported IRStatement: {type(stmt)!r}")


def generate_python(ir: ProgramIR) -> str:
    gen = _PyGen()
    for stmt in [*ir.imported_definitions, *ir.statements]:
        if isinstance(stmt, RecordDefStmt):
            gen.records[stmt.name] = {f.name: f.field_type for f in stmt.fields}
            gen.uses_dataclass = True
        elif isinstance(stmt, FuncDefStmt):
            gen.func_returns[stmt.name] = stmt.return_type

    record_lines: list[str] = []
    body_lines: list[str] = []
    for stmt in [*ir.imported_definitions, *ir.statements]:
        if isinstance(stmt, RecordDefStmt):
            record_lines.extend(gen.gen_stmt(stmt, gen.symbols, indent=0))
            record_lines.append("")
        elif isinstance(stmt, ImportStmt):
            continue
        else:
            body_lines.extend(gen.gen_stmt(stmt, gen.symbols, indent=1))
    if not body_lines:
        body_lines.append("    pass")

    header: list[str] = ["import builtins as _meme_builtins"]
    if gen.uses_dataclass:
        header.append("from dataclasses import dataclass as _dataclass")
    if gen.uses_json_io:
        header.append("import json as _meme_json")
    if gen.uses_json_io or gen.uses_file_io or gen.uses_input:
        header.append("import os as _meme_os")
    if gen.uses_json_io or gen.uses_file_io or gen.uses_argv:
        header.append("import sys as _meme_sys")
    if gen.uses_file_io:
        header.append("import shutil as _shutil")
    if gen.uses_math:
        header.append("import math as _meme_math")
    if gen.uses_random:
        header.append("import random as _meme_random")
    header.append("")

    if gen.uses_argv:
        header.extend(
            [
                "def _meme_arg_at(idx: int) -> str:",
                "    _i = _meme_builtins.int(idx)",
                "    if _i < 0 or _i >= _meme_builtins.len(_meme_sys.argv):",
                "        _meme_builtins.print(f'Error: argument index {_i} out of range')",
                "        raise _meme_builtins.SystemExit(1)",
                "    return _meme_sys.argv[_i]",
                "",
            ]
        )

    if gen.uses_list_remove:
        header.extend(
            [
                "def _meme_list_remove(lst: list, idx: int) -> None:",
                "    _i = _meme_builtins.int(idx)",
                "    if _i < 0 or _i >= _meme_builtins.len(lst):",
                "        _meme_builtins.print('Error: list index out of range')",
                "        raise _meme_builtins.SystemExit(1)",
                "    lst.pop(_i)",
                "",
                "def _meme_list_remove_last(lst: list) -> None:",
                "    if not lst:",
                "        _meme_builtins.print('Error: list index out of range')",
                "        raise _meme_builtins.SystemExit(1)",
                "    lst.pop()",
                "",
            ]
        )

    if gen.uses_str_split:
        header.extend(
            [
                "def _meme_str_split(s: str, sep: str) -> list[str]:",
                "    if sep == '':",
                "        _meme_builtins.print('Error: empty separator in split')",
                "        raise _meme_builtins.SystemExit(1)",
                "    return s.split(sep)",
                "",
            ]
        )

    if gen.uses_char_at:
        header.extend(
            [
                "def _meme_char_at(s: str, idx: int) -> str:",
                "    _i = _meme_builtins.int(idx)",
                "    if _i < 0 or _i >= _meme_builtins.len(s):",
                "        _meme_builtins.print(f'Error: string index {_i} out of range')",
                "        raise _meme_builtins.SystemExit(1)",
                "    return s[_i]",
                "",
            ]
        )

    if gen.uses_input:
        header.extend(
            [
                "def _meme_read_line(prompt: str) -> str:",
                "    if prompt and _meme_os.environ.get('MEME_QUIET_PROMPTS', '').strip().lower() not in ('1', 'true', 'yes'):",
                "        return _meme_builtins.input(prompt)",
                "    return _meme_builtins.input()",
                "",
            ]
        )

    if gen.uses_json_io or gen.uses_file_io:
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
            ]
        )

    if gen.uses_file_io:
        header.extend(
            [
                "def _meme_file_exists(path: str) -> bool:",
                "    return _meme_os.path.isfile(_meme_resolve_path(path))",
                "",
                "def _meme_read_file_string(path: str) -> str:",
                "    _rp = _meme_resolve_path(path)",
                "    if not _meme_os.path.isfile(_rp):",
                "        _meme_builtins.print(f'Error reading file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "    try:",
                "        with _meme_builtins.open(_rp, 'r', encoding='utf-8', newline='') as _f:",
                "            return _f.read()",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error reading file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_read_file_lines(path: str) -> list[str]:",
                "    raw = _meme_read_file_string(path)",
                "    if not raw:",
                "        return []",
                "    if raw.endswith('\\n'):",
                "        raw = raw[:-1]",
                "    return raw.split('\\n')",
                "",
                "def _meme_write_file(path: str, content: str) -> None:",
                "    try:",
                "        with _meme_builtins.open(path.strip(), 'w', encoding='utf-8') as _f:",
                "            _f.write(content)",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error writing file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_append_file(path: str, content: str) -> None:",
                "    try:",
                "        with _meme_builtins.open(path.strip(), 'a', encoding='utf-8') as _f:",
                "            _f.write(content)",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error writing file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_copy_file(src: str, dst: str) -> None:",
                "    _sp = _meme_resolve_path(src)",
                "    if not _meme_os.path.isfile(_sp):",
                "        _meme_builtins.print(f'Error copying file: {src}')",
                "        raise _meme_builtins.SystemExit(1)",
                "    try:",
                "        _shutil.copyfile(_sp, dst.strip())",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error copying file: {src}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_move_file(src: str, dst: str) -> None:",
                "    _sp = _meme_resolve_path(src)",
                "    if not _meme_os.path.isfile(_sp):",
                "        _meme_builtins.print(f'Error moving file: {src}')",
                "        raise _meme_builtins.SystemExit(1)",
                "    try:",
                "        _target = dst.strip()",
                "        if _meme_os.path.exists(_target):",
                "            _meme_os.remove(_target)",
                "        _shutil.move(_sp, _target)",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error moving file: {src}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_rename_file(path: str, new_name: str) -> None:",
                "    _sp = _meme_resolve_path(path)",
                "    if not _meme_os.path.isfile(_sp):",
                "        _meme_builtins.print(f'Error renaming file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "    try:",
                "        _dir = _meme_os.path.dirname(path.strip())",
                "        _nn = _meme_os.path.basename(new_name.strip())",
                "        _target = _meme_os.path.join(_dir, _nn) if _dir else _nn",
                "        if _meme_os.path.exists(_target) and _meme_os.path.abspath(_sp) != _meme_os.path.abspath(_target):",
                "            _meme_os.remove(_target)",
                "        _shutil.move(_sp, _target)",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error renaming file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_delete_file(path: str) -> None:",
                "    _sp = _meme_resolve_path(path)",
                "    if not _meme_os.path.isfile(_sp):",
                "        _meme_builtins.print(f'Error deleting file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "    try:",
                "        _meme_os.remove(_sp)",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error deleting file: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_create_directory(path: str) -> None:",
                "    try:",
                "        _meme_os.makedirs(path.strip(), exist_ok=True)",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error creating directory: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
                "def _meme_list_files(path: str) -> list[str]:",
                "    _rp = _meme_resolve_path(path)",
                "    if not _meme_os.path.isdir(_rp):",
                "        _meme_builtins.print(f'Error listing directory: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "    try:",
                "        entries = _meme_os.listdir(_rp)",
                "        return _meme_builtins.sorted(entries)",
                "    except _meme_builtins.Exception:",
                "        _meme_builtins.print(f'Error listing directory: {path}')",
                "        raise _meme_builtins.SystemExit(1)",
                "",
            ]
        )

    if gen.uses_json_io:
        header.extend(
            [
                "def _meme_read_json_list(path: str, elem_type: str = 'Float'):",
                "    try:",
                "        with _meme_builtins.open(_meme_resolve_path(path), 'r', encoding='utf-8') as _f:",
                "            _data = _meme_json.load(_f)",
                "        if not _meme_builtins.isinstance(_data, _meme_builtins.list):",
                "            raise _meme_builtins.ValueError('Expected JSON list')",
                "        _out = []",
                "        for _x in _data:",
                "            if _x is None:",
                "                raise _meme_builtins.ValueError('JSON null is not allowed')",
                "            if elem_type == 'Int':",
                "                if _meme_builtins.isinstance(_x, _meme_builtins.bool) or not _meme_builtins.isinstance(_x, _meme_builtins.int):",
                "                    raise _meme_builtins.ValueError(f'Expected Int element, got {_x!r}')",
                "                _out.append(_meme_builtins.int(_x))",
                "            elif elem_type == 'Float':",
                "                if _meme_builtins.isinstance(_x, _meme_builtins.bool) or not _meme_builtins.isinstance(_x, (_meme_builtins.int, _meme_builtins.float)):",
                "                    raise _meme_builtins.ValueError(f'Expected Float element, got {_x!r}')",
                "                _out.append(_meme_builtins.float(_x))",
                "            elif elem_type == 'String':",
                "                if not _meme_builtins.isinstance(_x, _meme_builtins.str):",
                "                    raise _meme_builtins.ValueError(f'Expected String element, got {_x!r}')",
                "                _out.append(_x)",
                "            elif elem_type == 'Bool':",
                "                if not _meme_builtins.isinstance(_x, _meme_builtins.bool):",
                "                    raise _meme_builtins.ValueError(f'Expected Bool element, got {_x!r}')",
                "                _out.append(_x)",
                "            else:",
                "                raise _meme_builtins.ValueError(f'Unsupported element type: {elem_type}')",
                "        return _out",
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
                "    ts = s.strip()",
                "    try:",
                "        v = _meme_builtins.int(ts)",
                "        if v < -9223372036854775808 or v > 9223372036854775807:",
                "            raise _meme_builtins.ValueError",
                "        return v",
                "    except _meme_builtins.ValueError:",
                "        _meme_builtins.print(f'Error parsing integer: {s}')",
                "        raise _meme_builtins.SystemExit(1)",
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

    if gen.uses_optional_helpers:
        header.extend(
            [
                "def _meme_unwrap(opt):",
                "    if opt is None:",
                "        _meme_builtins.print('Unwrap failed: Optional value is nothing')",
                "        raise _meme_builtins.SystemExit(1)",
                "    return opt",
                "",
                "def _meme_unwrap_or_else(opt, default_fn):",
                "    if opt is None:",
                "        return default_fn()",
                "    return opt",
                "",
            ]
        )

    if gen.uses_parse_int_or_else:
        header.extend(
            [
                "def _meme_parse_int_or_else(s: str, default_fn) -> int:",
                "    ts = s.strip()",
                "    try:",
                "        v = _meme_builtins.int(ts)",
                "        if v < -9223372036854775808 or v > 9223372036854775807:",
                "            return default_fn()",
                "        return v",
                "    except _meme_builtins.ValueError:",
                "        return default_fn()",
                "",
            ]
        )

    if gen.uses_is_digit:
        header.extend(
            [
                "def _meme_is_digit(s: str) -> bool:",
                "    return _meme_builtins.len(s) == 1 and '0' <= s <= '9'",
                "",
            ]
        )

    if gen.uses_is_letter:
        header.extend(
            [
                "def _meme_is_letter(s: str) -> bool:",
                "    return _meme_builtins.len(s) == 1 and (('A' <= s <= 'Z') or ('a' <= s <= 'z'))",
                "",
            ]
        )

    if gen.uses_is_upper:
        header.extend(
            [
                "def _meme_is_upper(s: str) -> bool:",
                "    return _meme_builtins.len(s) == 1 and 'A' <= s <= 'Z'",
                "",
            ]
        )

    if gen.uses_is_lower:
        header.extend(
            [
                "def _meme_is_lower(s: str) -> bool:",
                "    return _meme_builtins.len(s) == 1 and 'a' <= s <= 'z'",
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
            "    if _meme_builtins.isinstance(val, _meme_builtins.dict):",
            "        _items = _meme_builtins.sorted((_meme_fmt(k), _meme_fmt(v)) for k, v in val.items())",
            "        return '{' + ', '.join(f'{k}: {v}' for k, v in _items) + '}'",
            "    if _meme_builtins.hasattr(val, '__dataclass_fields__'):",
            "        _fields = [f'{k}={_meme_fmt(_meme_builtins.getattr(val, k))}' for k in val.__dataclass_fields__]",
            "        return f'{val.__class__.__name__}({', '.join(_fields)})'",
            "    return _meme_builtins.str(val)",
            "",
        ]
    )
    if record_lines:
        header.extend(record_lines)
    header.append("def main() -> None:")
    header.extend(body_lines)
    header.extend(["", 'if __name__ == "__main__":', "    main()", ""])
    return "\n".join(header)

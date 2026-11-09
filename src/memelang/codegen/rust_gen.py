"""Deterministic standalone Rust (`rustc`) code generator for Memelang ProgramIR."""

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
    ContinueStmt,
    ExitStmt,
    FailStmt,
    FileExistsExpr,
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
    MapEntry,
    MapGetExpr,
    MapHasKeyExpr,
    MapLiteralExpr,
    MapSetStmt,
    MemeType,
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
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
    WriteFileStmt,
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


def _rust_ident(name: str) -> str:
    return f"meme_{name}" if name in _RUST_KEYWORDS or name.startswith("_meme_") else name


def _rust_type(meme_type: MemeType | str) -> str:
    if meme_type.startswith("List<") and meme_type.endswith(">"):
        inner = meme_type[5:-1]
        return f"Vec<{_rust_type(inner)}>"
    map_t = _map_types_of(meme_type)
    if map_t is not None:
        return f"std::collections::HashMap<{_rust_type(map_t[0])}, {_rust_type(map_t[1])}>"
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
        self.uses_argv = False
        self.uses_str_split = False
        self.uses_char_at = False
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
        if isinstance(expr, (StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr, FileExistsExpr)):
            return "Bool"
        if isinstance(
            expr,
            (RandomIntExpr, ListLengthExpr, StringLengthExpr, StringIndexOfExpr, ArgCountExpr),
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
            if t == "String" or t.startswith("List<") or t.startswith("Map<") or t in self.records:
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

        if isinstance(expr, ReadJsonListExpr):
            self.uses_json_io = True
            return f"_meme_read_json_list_{expr.element_type.lower()}(&({self.gen_expr(expr.filepath, scope)}))"

        if isinstance(expr, FileExistsExpr):
            self.uses_file_io = True
            return f"_meme_file_exists(&({self.gen_expr(expr.filepath, scope)}))"

        if isinstance(expr, ReadFileStringExpr):
            self.uses_file_io = True
            return f"_meme_read_file_string(&({self.gen_expr(expr.filepath, scope)}))"

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
            return [f"{pad}{tgt}[({idx}) as usize] = {val};"]

        if isinstance(stmt, FailStmt):
            return [
                f"{pad}println!(\"{{}}\", {self._fmt_expr_for_print(stmt.message, scope)});",
                f"{pad}std::process::exit(1);",
            ]

        if isinstance(stmt, ExitStmt):
            return [
                f"{pad}std::process::exit((({self.gen_expr(stmt.code, scope)}) & 0xFF) as i32);"
            ]

        if isinstance(stmt, PrintStmt):
            if len(stmt.expressions) == 1:
                return [f"{pad}println!(\"{{}}\", {self._fmt_expr_for_print(stmt.expressions[0], scope)});"]
            fmt_str = " ".join("{}" for _ in stmt.expressions)
            args = ", ".join(self._fmt_expr_for_print(e, scope) for e in stmt.expressions)
            return [f'{pad}println!("{fmt_str}", {args});']

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

        if isinstance(stmt, ForEachStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.collection, "List<Int>")
            map_t = _map_types_of(col_t)
            col_ident = _rust_ident(stmt.collection)
            item_ident = _rust_ident(stmt.item_var)
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

        if isinstance(stmt, WriteFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_write_file(&({self.gen_expr(stmt.filepath, scope)}), &({self.gen_expr(stmt.content, scope)}));"
            ]

        if isinstance(stmt, AppendFileStmt):
            self.uses_file_io = True
            return [
                f"{pad}_meme_append_file(&({self.gen_expr(stmt.filepath, scope)}), &({self.gen_expr(stmt.content, scope)}));"
            ]

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


def generate_rust(ir: ProgramIR) -> str:
    gen = _RustGen()
    records: list[RecordDefStmt] = []
    funcs: list[FuncDefStmt] = []
    main_stmts: list[IRStatement] = []
    for stmt in ir.statements:
        if isinstance(stmt, RecordDefStmt):
            gen.records[stmt.name] = {f.name: f.field_type for f in stmt.fields}
            records.append(stmt)
        elif isinstance(stmt, FuncDefStmt):
            gen.func_returns[stmt.name] = stmt.return_type
            funcs.append(stmt)
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
        record_blocks.append("")

    fn_blocks: list[str] = []
    for fn in funcs:
        fn_blocks.extend(gen.gen_func(fn))
        fn_blocks.append("")

    main_scope: dict[str, MemeType] = {}
    main_lines: list[str] = []
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
        "fn _meme_fmt_slice<T: _MemeFmt>(items: &[T]) -> String {",
        "    let parts: Vec<String> = items.iter().map(|x| x.meme_fmt()).collect();",
        "    format!(\"[{}]\", parts.join(\", \"))",
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

    if gen.uses_json_io or gen.uses_file_io:
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

    out = preamble + record_blocks + fn_blocks + ["fn main() {"] + main_lines + ["}", ""]
    return "\n".join(out)

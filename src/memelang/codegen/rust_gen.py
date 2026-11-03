"""Deterministic standalone Rust (`rustc`) code generator for Memelang ProgramIR."""

from __future__ import annotations

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
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
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


def _rust_ident(name: str) -> str:
    return f"meme_{name}" if name in _RUST_KEYWORDS or name.startswith("_meme_") else name


def _rust_type(meme_type: MemeType) -> str:
    mapping = {
        "Int": "i64",
        "Float": "f64",
        "Bool": "bool",
        "String": "String",
        "List<Int>": "Vec<i64>",
        "List<Float>": "Vec<f64>",
        "List<Bool>": "Vec<bool>",
        "List<String>": "Vec<String>",
        "Void": "()",
    }
    return mapping[meme_type]


class _RustGen:
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_input = False
        self.uses_json_io = False
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
        if isinstance(expr, (RandomIntExpr, ListLengthExpr)):
            return "Int"
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
            if t == "String" or t.startswith("List<"):
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
            t = self.infer_type(expr, scope)
            base = f"{self.gen_expr(expr.target, scope)}[({self.gen_expr(expr.index, scope)}) as usize]"
            if t == "String" or t.startswith("List<"):
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

        if isinstance(expr, ReadJsonListExpr):
            self.uses_json_io = True
            return f"_meme_read_json_list(&({self.gen_expr(expr.filepath, scope)}))"

        raise TypeError(f"Unsupported IRExpr: {type(expr)!r}")

    def _fmt_expr_for_print(self, expr: IRExpr, scope: dict[str, MemeType]) -> str:
        t = self.infer_type(expr, scope)
        code = self.gen_expr(expr, scope)
        if t.startswith("List<"):
            return f"_meme_fmt_slice(&({code}))"
        return f"format!(\"{{}}\", {code})"

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

        if isinstance(stmt, FailStmt):
            return [
                f"{pad}println!(\"{{}}\", {self._fmt_expr_for_print(stmt.message, scope)});",
                f"{pad}std::process::exit(0);",
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
            sub[stmt.item_var] = col_t[5:-1] if col_t.startswith("List<") else "Int"  # type: ignore[assignment]
            lines = [f"{pad}for {_rust_ident(stmt.item_var)} in {_rust_ident(stmt.collection)}.clone().into_iter() {{"]
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

        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                return [f"{pad}return;"]
            return [f"{pad}return {self.gen_expr(stmt.value, scope)};"]

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
    funcs: list[FuncDefStmt] = []
    main_stmts: list[IRStatement] = []
    for stmt in ir.statements:
        if isinstance(stmt, FuncDefStmt):
            gen.func_returns[stmt.name] = stmt.return_type
            funcs.append(stmt)
        else:
            main_stmts.append(stmt)

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
        "fn _meme_fmt_slice<T: std::fmt::Display>(items: &[T]) -> String {",
        "    let parts: Vec<String> = items.iter().map(|x| format!(\"{}\", x)).collect();",
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

    if gen.uses_input:
        preamble.extend(
            [
                "fn _meme_read_line(prompt: &str) -> String {",
                "    use std::io::{self, Write};",
                "    if !prompt.is_empty() {",
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

    if gen.uses_json_io:
        preamble.extend(
            [
                "fn _meme_read_json_list(path: &str) -> Vec<f64> {",
                "    let raw = match std::fs::read_to_string(path.trim()) {",
                "        Ok(s) => s,",
                "        Err(e) => {",
                "            eprintln!(\"Error reading JSON file: {}\", e);",
                "            std::process::exit(1);",
                "        }",
                "    };",
                "    let trimmed = raw.trim();",
                "    if !trimmed.starts_with('[') || !trimmed.ends_with(']') {",
                "        eprintln!(\"Error reading JSON file: expected JSON array\");",
                "        std::process::exit(1);",
                "    }",
                "    let inner = trimmed[1..trimmed.len() - 1].trim();",
                "    if inner.is_empty() {",
                "        return Vec::new();",
                "    }",
                "    let mut out = Vec::new();",
                "    for part in inner.split(',') {",
                "        let tok = part.trim();",
                "        match tok.parse::<f64>() {",
                "            Ok(v) if v.is_finite() => out.push(v),",
                "            _ => {",
                "                eprintln!(\"Error reading JSON file: invalid number `{}`\", tok);",
                "                std::process::exit(1);",
                "            }",
                "        }",
                "    }",
                "    out",
                "}",
                "",
            ]
        )

    out = preamble + fn_blocks + ["fn main() {"] + main_lines + ["}", ""]
    return "\n".join(out)

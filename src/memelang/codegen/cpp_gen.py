"""Deterministic C++20 (`g++ -std=c++20`) code generator for Memelang ProgramIR."""

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


def _cpp_ident(name: str) -> str:
    return f"meme_{name}" if name in _CPP_KEYWORDS or name.startswith("_meme_") else name
def _cpp_type(meme_type: MemeType) -> str:
    mapping = {
        "Int": "long long",
        "Float": "double",
        "Bool": "bool",
        "String": "std::string",
        "List<Int>": "std::vector<long long>",
        "List<Float>": "std::vector<double>",
        "List<Bool>": "std::vector<bool>",
        "List<String>": "std::vector<std::string>",
        "Void": "void",
    }
    return mapping[meme_type]


class _CppGen:
    def __init__(self) -> None:
        self.uses_random = False
        self.uses_input = False
        self.uses_str_helpers = False
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
                return f"std::stoll({raw})"
            if expr.target_type == "Float":
                return f"std::stod({raw})"
            if expr.target_type == "Bool":
                return f"_meme_parse_bool({raw})"
            return raw

        if isinstance(expr, StrEndsWithExpr):
            self.uses_str_helpers = True
            return f"_meme_ends_with_ci({self.gen_expr(expr.target, scope)}, {self.gen_expr(expr.suffix, scope)})"

        if isinstance(expr, ReadJsonListExpr):
            self.uses_str_helpers = True
            self.uses_json_io = True
            return f"_meme_read_json_list({self.gen_expr(expr.filepath, scope)})"

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

        if isinstance(stmt, FailStmt):
            return [
                f"{pad}std::cout << _meme_fmt({self.gen_expr(stmt.message, scope)}) << \"\\n\";",
                f"{pad}std::exit(0);",
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

        if isinstance(stmt, ForEachStmt):
            sub = dict(scope)
            col_t = scope.get(stmt.collection, "List<Int>")
            el_mtype = col_t[5:-1] if col_t.startswith("List<") else "Int"
            sub[stmt.item_var] = el_mtype  # type: ignore[assignment]
            lines = [
                f"{pad}for ({_cpp_type(el_mtype)} {_cpp_ident(stmt.item_var)} : {_cpp_ident(stmt.collection)}) {{"  # type: ignore[arg-type]
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

        if isinstance(stmt, ReturnStmt):
            if stmt.value is None:
                return [f"{pad}return;"]
            return [f"{pad}return {self.gen_expr(stmt.value, scope)};"]

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

    headers: list[str] = [
        "#include <algorithm>",
        "#include <cctype>",
        "#include <cmath>",
        "#include <cstdlib>",
        "#include <fstream>",
        "#include <iostream>",
        "#include <sstream>",
        "#include <string>",
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
        "",
    ]

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
                "    if (!prompt.empty()) { std::cout << prompt << std::flush; }",
                "    std::string line;",
                "    std::getline(std::cin, line);",
                "    if (!line.empty() && line.back() == '\\r') line.pop_back();",
                "    return line;",
                "}",
                "inline bool _meme_parse_bool(const std::string& s) {",
                "    return s == \"true\" || s == \"True\" || s == \"1\" || s == \"yes\";",
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
                "inline bool _meme_ends_with_ci(const std::string& s, const std::string& suf) {",
                "    std::string ts = _meme_trim(s);",
                "    if (ts.size() < suf.size()) return false;",
                "    std::size_t off = ts.size() - suf.size();",
                "    for (std::size_t i = 0; i < suf.size(); ++i) {",
                "        if (std::tolower(static_cast<unsigned char>(ts[off + i])) != std::tolower(static_cast<unsigned char>(suf[i]))) return false;",
                "    }",
                "    return true;",
                "}",
                "",
            ]
        )

    if gen.uses_json_io:
        helpers.extend(
            [
                "inline std::vector<double> _meme_read_json_list(const std::string& path) {",
                "    std::ifstream ifs(_meme_trim(path));",
                "    if (!ifs) {",
                "        std::cerr << \"Error reading JSON file: cannot open \" << path << \"\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::ostringstream ss;",
                "    ss << ifs.rdbuf();",
                "    std::string trimmed = _meme_trim(ss.str());",
                "    if (trimmed.size() < 2 || trimmed.front() != '[' || trimmed.back() != ']') {",
                "        std::cerr << \"Error reading JSON file: expected JSON array\\n\";",
                "        std::exit(1);",
                "    }",
                "    std::string inner = _meme_trim(trimmed.substr(1, trimmed.size() - 2));",
                "    std::vector<double> out;",
                "    if (inner.empty()) return out;",
                "    std::size_t start = 0;",
                "    while (start <= inner.size()) {",
                "        std::size_t comma = inner.find(',', start);",
                "        std::string tok = _meme_trim(comma == std::string::npos ? inner.substr(start) : inner.substr(start, comma - start));",
                "        try {",
                "            std::size_t idx = 0;",
                "            double v = std::stod(tok, &idx);",
                "            if (idx != tok.size() || !std::isfinite(v)) throw std::invalid_argument(\"bad\");",
                "            out.push_back(v);",
                "        } catch (...) {",
                "            std::cerr << \"Error reading JSON file: invalid number `\" << tok << \"`\\n\";",
                "            std::exit(1);",
                "        }",
                "        if (comma == std::string::npos) break;",
                "        start = comma + 1;",
                "    }",
                "    return out;",
                "}",
                "",
            ]
        )

    out = (
        headers
        + helpers
        + fn_blocks
        + ["int main() {"]
        + main_lines
        + ["    return 0;", "}", ""]
    )
    return "\n".join(out)

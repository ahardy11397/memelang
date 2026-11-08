"""Zero-dependency deterministic heuristic frontend for Structured & Hybrid English."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Literal, cast

from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    AmbiguityCandidate,
    AmbiguityDiagnostic,
    AssignStmt,
    BinaryOpExpr,
    BinaryOperator,
    CallExpr,
    ClampCollectionStmt,
    FailStmt,
    FilterCollectionStmt,
    ForEachStmt,
    ForRangeStmt,
    FuncDefStmt,
    FuncParam,
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
    SortDirection,
    StrEndsWithExpr,
    StringLengthExpr,
    StringSliceExpr,
    SynthesisItem,
    SynthesisResult,
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
)
from memelang.llm.base import LLMProviderError, has_executable_content

_VALID_TYPES: set[str] = {
    "Int",
    "Float",
    "Bool",
    "String",
    "List<Int>",
    "List<Float>",
    "List<Bool>",
    "List<String>",
    "List<List<Int>>",
    "List<List<Float>>",
    "List<List<Bool>>",
    "List<List<String>>",
    "Void",
}


def _is_valid_type(t: str, records: dict[str, dict[str, MemeType]] | None = None) -> bool:
    t = t.strip().replace(" ", "")
    if t in _VALID_TYPES:
        return True
    if records and t in records:
        return True
    if t.startswith("List<") and t.endswith(">"):
        return _is_valid_type(t[5:-1], records)
    if t.startswith("Map<") and t.endswith(">"):
        inner = t[4:-1]
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
            return _is_valid_type(inner[:comma], records) and _is_valid_type(
                inner[comma + 1 :], records
            )
    return False


def _normalize_type(t: str) -> str:
    t = t.strip()
    if t.startswith("List<") and t.endswith(">"):
        return f"List<{_normalize_type(t[5:-1])}>"
    if t.startswith("Map<") and t.endswith(">"):
        inner = t[4:-1]
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
            k = _normalize_type(inner[:comma])
            v = _normalize_type(inner[comma + 1 :])
            return f"Map<{k}, {v}>"
    return t.replace(" ", "")


@dataclass
class _SourceLine:
    lineno: int
    indent: int
    text: str


# --- Expression Tokenizer & Recursive-Descent Parser ---

_TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<STRING>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
      | (?P<FLOAT>\d+\.\d+)
      | (?P<INT>\d+)
      | (?P<OP>==|!=|<=|>=|[+\-*/%<>(),\[\]\{\}\.:=])
      | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    )
    """,
    re.VERBOSE,
)


@dataclass
class _Tok:
    kind: str
    val: str


def _tokenize_expr(text: str) -> list[_Tok]:
    pos = 0
    tokens: list[_Tok] = []
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(text, pos)
        if not m or m.group(0).strip() == "":
            raise LLMProviderError(f"Cannot parse expression near: {text[pos:]!r}")
        pos = m.end()
        if m.lastgroup == "STRING":
            raw = m.group("STRING")
            try:
                val = ast.literal_eval(raw)
                if not isinstance(val, str):
                    raise ValueError("Not a string literal")
            except (SyntaxError, ValueError) as exc:
                raise LLMProviderError(f"Invalid string literal {raw!r}: {exc}") from exc
            tokens.append(_Tok("STRING", val))
        elif m.lastgroup == "FLOAT":
            tokens.append(_Tok("FLOAT", m.group("FLOAT")))
        elif m.lastgroup == "INT":
            tokens.append(_Tok("INT", m.group("INT")))
        elif m.lastgroup == "OP":
            tokens.append(_Tok("OP", m.group("OP")))
        elif m.lastgroup == "IDENT":
            tokens.append(_Tok("IDENT", m.group("IDENT")))
    return tokens


class _ExprParser:
    def __init__(
        self,
        tokens: list[_Tok],
        symbols: dict[str, MemeType] | None = None,
        func_returns: dict[str, MemeType] | None = None,
        records: dict[str, dict[str, MemeType]] | None = None,
    ) -> None:
        self.tokens = tokens
        self.pos = 0
        self.symbols = symbols or {}
        self.func_returns = func_returns
        self.records = records

    def peek(self) -> _Tok | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, kind: str | None = None, val: str | None = None) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise LLMProviderError("Unexpected end of expression")
        if kind and tok.kind != kind:
            raise LLMProviderError(f"Expected {kind}, got {tok.val!r}")
        if val and tok.val != val:
            raise LLMProviderError(f"Expected {val!r}, got {tok.val!r}")
        self.pos += 1
        return tok

    def parse(self) -> IRExpr:
        expr = self.parse_or()
        rem = self.peek()
        if rem is not None:
            raise LLMProviderError(f"Unexpected trailing token in expression: {rem.val!r}")
        return expr

    def parse_or(self) -> IRExpr:
        left = self.parse_and()
        while (t := self.peek()) and t.kind == "IDENT" and t.val == "or":
            self.consume()
            right = self.parse_and()
            left = BinaryOpExpr(op="or", left=left, right=right)
        return left

    def parse_and(self) -> IRExpr:
        left = self.parse_not()
        while (t := self.peek()) and t.kind == "IDENT" and t.val == "and":
            self.consume()
            right = self.parse_not()
            left = BinaryOpExpr(op="and", left=left, right=right)
        return left

    def parse_not(self) -> IRExpr:
        t = self.peek()
        if t and t.kind == "IDENT" and t.val == "not":
            self.consume()
            return UnaryOpExpr(op="not", operand=self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> IRExpr:
        left = self.parse_add()
        t = self.peek()
        if t and t.kind == "IDENT" and t.val == "has":
            self.consume("IDENT", "has")
            if (nxt := self.peek()) and nxt.kind == "IDENT" and nxt.val == "key":
                self.consume("IDENT", "key")
            key_expr = self.parse_add()
            left = MapHasKeyExpr(target=left, key=key_expr)
            t = self.peek()
        if t and t.kind == "OP" and t.val in ("==", "!=", "<", "<=", ">", ">="):
            op = cast(BinaryOperator, self.consume().val)
            right = self.parse_add()
            return BinaryOpExpr(op=op, left=left, right=right)
        return left

    def parse_add(self) -> IRExpr:
        left = self.parse_mul()
        while (t := self.peek()) and t.kind == "OP" and t.val in ("+", "-"):
            op = cast(BinaryOperator, self.consume().val)
            right = self.parse_mul()
            left = BinaryOpExpr(op=op, left=left, right=right)
        return left

    def parse_mul(self) -> IRExpr:
        left = self.parse_unary()
        while (t := self.peek()) and t.kind == "OP" and t.val in ("*", "/", "%"):
            op = cast(BinaryOperator, self.consume().val)
            right = self.parse_unary()
            left = BinaryOpExpr(op=op, left=left, right=right)
        return left

    def parse_unary(self) -> IRExpr:
        t = self.peek()
        if t and t.kind == "OP" and t.val == "-":
            self.consume()
            operand = self.parse_unary()
            if isinstance(operand, LiteralExpr) and operand.data_type in ("Int", "Float"):
                return LiteralExpr(value=-operand.value, data_type=operand.data_type)  # type: ignore[operator]
            return UnaryOpExpr(op="-", operand=operand)
        return self.parse_postfix()

    def parse_postfix(self) -> IRExpr:
        node = self.parse_primary()
        while (t := self.peek()):
            if t.kind == "OP" and t.val == "[":
                self.consume("OP", "[")
                idx = self.parse_or()
                self.consume("OP", "]")
                if (nxt := self.peek()) and nxt.kind == "IDENT" and nxt.val == "default":
                    self.consume("IDENT", "default")
                    def_val = self.parse_unary()
                    node = MapGetExpr(target=node, key=idx, default_val=def_val)
                else:
                    tgt_t = _guess_expr_type(
                        node, self.symbols, self.func_returns, self.records
                    )
                    if tgt_t.startswith("Map<"):
                        node = MapGetExpr(target=node, key=idx, default_val=None)
                    else:
                        node = ListIndexExpr(target=node, index=idx)
            elif t.kind == "OP" and t.val == ".":
                self.consume("OP", ".")
                f_tok = self.consume("IDENT")
                node = RecordFieldExpr(target=node, field_name=f_tok.val)
            else:
                break
        return node

    def parse_primary(self) -> IRExpr:
        t = self.peek()
        if t is None:
            raise LLMProviderError("Unexpected end of expression")

        if t.kind == "INT":
            self.consume()
            return LiteralExpr(value=int(t.val), data_type="Int")
        if t.kind == "FLOAT":
            self.consume()
            return LiteralExpr(value=float(t.val), data_type="Float")
        if t.kind == "STRING":
            self.consume()
            return LiteralExpr(value=t.val, data_type="String")

        if t.kind == "OP" and t.val == "(":
            self.consume("OP", "(")
            inner = self.parse_or()
            self.consume("OP", ")")
            return inner

        if t.kind == "OP" and t.val == "[":
            self.consume("OP", "[")
            elems: list[IRExpr] = []
            if not ((nxt := self.peek()) and nxt.kind == "OP" and nxt.val == "]"):
                elems.append(self.parse_or())
                while (nxt := self.peek()) and nxt.kind == "OP" and nxt.val == ",":
                    self.consume("OP", ",")
                    elems.append(self.parse_or())
            self.consume("OP", "]")
            el_type: MemeType = "Int"
            if elems:
                guessed = _guess_expr_type(
                    elems[0], self.symbols, self.func_returns, self.records
                )
                if _is_valid_type(guessed, self.records):
                    el_type = guessed
            return ListLiteralExpr(elements=elems, element_type=el_type)

        if t.kind == "OP" and t.val == "{":
            self.consume("OP", "{")
            entries: list[MapEntry] = []
            if not ((nxt := self.peek()) and nxt.kind == "OP" and nxt.val == "}"):
                while True:
                    k = self.parse_or()
                    self.consume("OP", ":")
                    v = self.parse_or()
                    entries.append(MapEntry(key=k, value=v))
                    if (nxt := self.peek()) and nxt.kind == "OP" and nxt.val == ",":
                        self.consume("OP", ",")
                        if (nxt := self.peek()) and nxt.kind == "OP" and nxt.val == "}":
                            break
                    else:
                        break
            self.consume("OP", "}")
            k_type: MemeType = "String"
            v_type: MemeType = "String"
            if entries:
                k_guessed = _guess_expr_type(
                    entries[0].key, self.symbols, self.func_returns, self.records
                )
                v_guessed = _guess_expr_type(
                    entries[0].value, self.symbols, self.func_returns, self.records
                )
                if _is_valid_type(k_guessed, self.records):
                    k_type = k_guessed
                if _is_valid_type(v_guessed, self.records):
                    v_type = v_guessed
            return MapLiteralExpr(key_type=k_type, value_type=v_type, entries=entries)

        if t.kind == "IDENT":
            if t.val in ("true", "True"):
                self.consume()
                return LiteralExpr(value=True, data_type="Bool")
            if t.val in ("false", "False"):
                self.consume()
                return LiteralExpr(value=False, data_type="Bool")
            if t.val == "length":
                self.consume()
                if (nxt := self.peek()) and nxt.kind == "IDENT" and nxt.val == "of":
                    self.consume()
                if (
                    (nxt := self.peek())
                    and nxt.kind == "IDENT"
                    and nxt.val == "string"
                    and self.pos + 1 < len(self.tokens)
                    and self.tokens[self.pos + 1].kind in ("IDENT", "STRING", "OP")
                    and self.tokens[self.pos + 1].val not in (
                        "+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", ",", ")", "]"
                    )
                ):
                    self.consume()
                    target = self.parse_postfix()
                    return StringLengthExpr(target=target)
                target = self.parse_postfix()
                return ListLengthExpr(target=target)

            ident = self.consume("IDENT").val
            if (nxt := self.peek()) and nxt.kind == "OP" and nxt.val == "(":
                self.consume("OP", "(")
                # Check for named field arguments: ident(foo=..., bar=...)
                is_record_ctor = False
                if (
                    (p0 := self.peek())
                    and p0.kind == "IDENT"
                    and self.pos + 1 < len(self.tokens)
                    and self.tokens[self.pos + 1].kind == "OP"
                    and self.tokens[self.pos + 1].val == "="
                ):
                    is_record_ctor = True
                if is_record_ctor:
                    fields: list[RecordFieldInit] = []
                    while not ((c := self.peek()) and c.kind == "OP" and c.val == ")"):
                        f_name = self.consume("IDENT").val
                        self.consume("OP", "=")
                        f_val = self.parse_or()
                        fields.append(RecordFieldInit(name=f_name, value=f_val))
                        if (c := self.peek()) and c.kind == "OP" and c.val == ",":
                            self.consume("OP", ",")
                    self.consume("OP", ")")
                    return RecordLiteralExpr(record_name=ident, fields=fields)

                args: list[IRExpr] = []
                if not ((c := self.peek()) and c.kind == "OP" and c.val == ")"):
                    args.append(self.parse_or())
                    while (c := self.peek()) and c.kind == "OP" and c.val == ",":
                        self.consume("OP", ",")
                        args.append(self.parse_or())
                self.consume("OP", ")")
                return CallExpr(func_name=ident, args=args)

            return VarRefExpr(name=ident)

        raise LLMProviderError(f"Unexpected token in expression: {t.val!r}")


def _parse_expr(
    raw: str,
    symbols: dict[str, MemeType] | None = None,
    func_returns: dict[str, MemeType] | None = None,
    records: dict[str, dict[str, MemeType]] | None = None,
) -> IRExpr:
    s = raw.strip()

    # Special English phrase expressions
    m_empty = re.fullmatch(
        r"empty\s+List<(.+)>", s
    )
    if m_empty:
        el_t = cast(MemeType, _normalize_type(m_empty.group(1)))
        return ListLiteralExpr(elements=[], element_type=el_t)

    m_empty_map = re.fullmatch(
        r"empty\s+(Map<.+>)", s
    )
    if m_empty_map:
        mt = _map_types_of(_normalize_type(m_empty_map.group(1)))
        if mt is not None:
            return MapLiteralExpr(
                key_type=mt[0],
                value_type=mt[1],
                entries=[],
            )

    m_slice = re.fullmatch(
        r"slice\s+(.+?)\s+from\s+(.+?)\s+to\s+(.+)",
        s,
        flags=re.IGNORECASE,
    )
    if m_slice:
        return StringSliceExpr(
            target=_parse_expr(m_slice.group(1), symbols, func_returns, records),
            start=_parse_expr(m_slice.group(2), symbols, func_returns, records),
            end=_parse_expr(m_slice.group(3), symbols, func_returns, records),
        )

    m_read_json = re.fullmatch(
        r"read\s+JSON\s+number\s+list\s+from\s+(.+)",
        s,
        flags=re.IGNORECASE,
    )
    if m_read_json:
        return ReadJsonListExpr(
            filepath=_parse_expr(m_read_json.group(1), symbols, func_returns, records)
        )

    m_ends_with = re.fullmatch(
        r"(.+?)\s+ends\s+with\s+(.+)",
        s,
        flags=re.IGNORECASE,
    )
    if m_ends_with:
        return StrEndsWithExpr(
            target=_parse_expr(m_ends_with.group(1), symbols, func_returns, records),
            suffix=_parse_expr(m_ends_with.group(2), symbols, func_returns, records),
        )

    m_rand_list = re.fullmatch(
        r"(.+?)\s+random\s+(?:integers?|numbers?)(?:\s+between\s+(.+?)\s+and\s+(.+))?",
        s,
        flags=re.IGNORECASE,
    )
    if m_rand_list:
        count_e = _parse_expr(m_rand_list.group(1), symbols, func_returns, records)
        if m_rand_list.group(2) and m_rand_list.group(3):
            lo_e = _parse_expr(m_rand_list.group(2), symbols, func_returns, records)
            hi_e = _parse_expr(m_rand_list.group(3), symbols, func_returns, records)
            return RandomListExpr(count=count_e, min_val=lo_e, max_val=hi_e, implicit_bounds=False)
        return RandomListExpr(
            count=count_e,
            min_val=LiteralExpr(value=1, data_type="Int"),
            max_val=LiteralExpr(value=100, data_type="Int"),
            implicit_bounds=True,
        )

    m_dot_rand = re.fullmatch(r"(\d+)\s*\.\s*random\s+(?:integers?|numbers?)", s, flags=re.IGNORECASE)
    if m_dot_rand:
        return RandomListExpr(
            count=LiteralExpr(value=int(m_dot_rand.group(1)), data_type="Int"),
            min_val=LiteralExpr(value=1, data_type="Int"),
            max_val=LiteralExpr(value=100, data_type="Int"),
            implicit_bounds=True,
        )

    m_rand_int = re.fullmatch(
        r"(?:a\s+)?random\s+(?:integer|number)\s+between\s+(.+?)\s+and\s+(.+)",
        s,
        flags=re.IGNORECASE,
    )
    if m_rand_int:
        return RandomIntExpr(
            min_val=_parse_expr(m_rand_int.group(1), symbols, func_returns, records),
            max_val=_parse_expr(m_rand_int.group(2), symbols, func_returns, records),
        )

    m_read = re.fullmatch(
        r'read\s+(Int|Float|Bool|String)(?:\s+with\s+prompt\s+("(?:\\.|[^"\\])*"))?',
        s,
    )
    if m_read:
        t_type = cast(Literal["Int", "Float", "Bool", "String"], m_read.group(1))
        prompt = json.loads(m_read.group(2)) if m_read.group(2) else ""
        return ReadInputExpr(prompt=prompt, target_type=t_type)

    tokens = _tokenize_expr(s)
    return _ExprParser(tokens, symbols, func_returns, records).parse()


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    in_str: str | None = None
    escape = False
    for ch in text:
        if in_str:
            cur.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch
            cur.append(ch)
        elif ch in "([{<":
            depth += 1
            cur.append(ch)
        elif ch in ")]}>":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


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


def _guess_expr_type(
    expr: IRExpr,
    symbols: dict[str, MemeType],
    func_returns: dict[str, MemeType] | None = None,
    records: dict[str, dict[str, MemeType]] | None = None,
) -> MemeType:
    if isinstance(expr, LiteralExpr):
        return expr.data_type
    if isinstance(expr, ListLiteralExpr):
        return cast(MemeType, f"List<{expr.element_type}>")
    if isinstance(expr, RandomListExpr):
        return "List<Int>"
    if isinstance(expr, ReadJsonListExpr):
        return "List<Float>"
    if isinstance(expr, StrEndsWithExpr):
        return "Bool"
    if isinstance(expr, StringSliceExpr):
        return "String"
    if isinstance(expr, (RandomIntExpr, ListLengthExpr, StringLengthExpr)):
        return "Int"
    if isinstance(expr, ReadInputExpr):
        return expr.target_type
    if isinstance(expr, RecordLiteralExpr):
        return expr.record_name
    if isinstance(expr, RecordFieldExpr):
        tgt_t = _guess_expr_type(expr.target, symbols, func_returns, records)
        if records and tgt_t in records:
            return records[tgt_t].get(expr.field_name, "String")
        return "String"
    if isinstance(expr, MapLiteralExpr):
        return cast(MemeType, f"Map<{expr.key_type}, {expr.value_type}>")
    if isinstance(expr, MapGetExpr):
        tgt_t = _guess_expr_type(expr.target, symbols, func_returns, records)
        mt = _map_types_of(tgt_t)
        if mt is not None:
            return mt[1]
        if expr.default_val:
            return _guess_expr_type(expr.default_val, symbols, func_returns, records)
        return "String"
    if isinstance(expr, MapHasKeyExpr):
        return "Bool"
    if isinstance(expr, VarRefExpr) and expr.name in symbols:
        return symbols[expr.name]
    if isinstance(expr, ListIndexExpr):
        col_t = _guess_expr_type(expr.target, symbols, func_returns, records)
        if col_t.startswith("List<"):
            return cast(MemeType, col_t[5:-1])
        mt = _map_types_of(col_t)
        if mt is not None:
            return mt[1]
        return "Int"
    if isinstance(expr, CallExpr) and func_returns and expr.func_name in func_returns:
        return func_returns[expr.func_name]
    if isinstance(expr, BinaryOpExpr):
        if expr.op in ("==", "!=", "<", "<=", ">", ">=", "and", "or"):
            return "Bool"
        return _guess_expr_type(expr.left, symbols, func_returns, records)
    if isinstance(expr, UnaryOpExpr):
        return "Bool" if expr.op == "not" else _guess_expr_type(expr.operand, symbols, func_returns, records)
    return "Int"


def _refine_list_literal_types(
    expr: IRExpr,
    symbols: dict[str, MemeType],
    func_returns: dict[str, MemeType],
    records: dict[str, dict[str, MemeType]] | None = None,
) -> IRExpr:
    if isinstance(expr, ListLiteralExpr) and expr.elements:
        refined_elems = [
            _refine_list_literal_types(e, symbols, func_returns, records) for e in expr.elements
        ]
        first_t = _guess_expr_type(refined_elems[0], symbols, func_returns, records)
        if _is_valid_type(first_t, records):
            return ListLiteralExpr(
                elements=refined_elems,
                element_type=cast(MemeType, first_t),
            )
    return expr


class HeuristicProvider:
    """Deterministic local parser for Structured & Hybrid English `.meme` programs."""

    name: str = "heuristic"

    def __init__(self, retriever: object = None) -> None:
        self.retriever = retriever

    def synthesize(
        self, source_text: str, source_path: object = None
    ) -> SynthesisResult:
        if not has_executable_content(source_text):
            return SynthesisResult(items=[])

        lines: list[_SourceLine] = []
        for idx, raw in enumerate(source_text.splitlines(), start=1):
            expanded = raw.expandtabs(4)
            stripped = expanded.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(expanded) - len(expanded.lstrip(" "))
            lines.append(_SourceLine(lineno=idx, indent=indent, text=stripped))

        symbols: dict[str, MemeType] = {}
        self._func_returns: dict[str, MemeType] = {}
        self._records: dict[str, dict[str, MemeType]] = {}
        items, _ = self._parse_block(lines, 0, lines[0].indent, symbols, top_level=True)

        # Post-process top-level AmbiguityDiagnostic candidates with replaces_whole_program=True
        # so any concrete statements following the ambiguous statement are preserved!
        for idx, item in enumerate(items):
            if isinstance(item, AmbiguityDiagnostic):
                trailing = [
                    cast(IRStatement, x)
                    for x in items[idx + 1 :]
                    if not isinstance(x, AmbiguityDiagnostic)
                ]
                if trailing:
                    for cand in item.candidates:
                        if cand.replaces_whole_program:
                            cand.replacement_ir = list(cand.replacement_ir) + trailing
                            cand.canonical_meme = to_canonical_meme(
                                ProgramIR(statements=cand.replacement_ir)
                            )

        return SynthesisResult(items=items)

    def _parse_block(
        self,
        lines: list[_SourceLine],
        start_idx: int,
        base_indent: int,
        symbols: dict[str, MemeType],
        top_level: bool = False,
    ) -> tuple[list[SynthesisItem], int]:
        items: list[SynthesisItem] = []
        i = start_idx

        while i < len(lines):
            line = lines[i]
            if line.indent < base_indent:
                break
            if line.indent > base_indent:
                raise LLMProviderError(
                    f"Unexpected indentation at line {line.lineno}: {line.text!r}"
                )

            text = line.text
            stmt_num = len(items) + 1

            # 1. `for each <var> in <col>[:]` (check both inline and indented ambiguous sort!)
            m_foreach = re.fullmatch(
                r"for\s+each\s+([A-Za-z_]\w*)\s+in\s+([A-Za-z_]\w*)(?:\s*:\s*(.+))?:?",
                text,
                flags=re.IGNORECASE,
            )
            if m_foreach:
                item_var = m_foreach.group(1)
                col_name = m_foreach.group(2)
                inline_body_txt = m_foreach.group(3)

                # Check if single-child body is an ambiguous `sort [from A to B]`
                child_lines: list[_SourceLine] = []
                next_i = i + 1
                if inline_body_txt:
                    child_lines = [_SourceLine(line.lineno, base_indent + 4, inline_body_txt)]
                elif next_i < len(lines) and lines[next_i].indent > base_indent:
                    sub_indent = lines[next_i].indent
                    j = next_i
                    while j < len(lines) and lines[j].indent >= sub_indent:
                        child_lines.append(lines[j])
                        j += 1

                if top_level and len(child_lines) == 1:
                    m_amb_sort = re.fullmatch(
                        r"sort(?:\s+" + re.escape(col_name) + r")?(?:\s+from\s+(.+?)\s+to\s+(.+))?",
                        child_lines[0].text,
                        flags=re.IGNORECASE,
                    )
                    if m_amb_sort:
                        lo_e = (
                            _parse_expr(m_amb_sort.group(1))
                            if m_amb_sort.group(1)
                            else LiteralExpr(value=1, data_type="Int")
                        )
                        hi_e = (
                            _parse_expr(m_amb_sort.group(2))
                            if m_amb_sort.group(2)
                            else LiteralExpr(value=10, data_type="Int")
                        )
                        source_snippet = (
                            f"{line.text}\n    {child_lines[0].text}"
                            if not inline_body_txt
                            else line.text
                        )
                        diag = self._build_sort_loop_ambiguity(
                            stmt_num,
                            line.lineno,
                            source_snippet,
                            col_name,
                            lo_e,
                            hi_e,
                            [x for x in items if not isinstance(x, AmbiguityDiagnostic)],
                        )
                        items.append(diag)
                        i = next_i if inline_body_txt else (next_i + len(child_lines))
                        continue

                loop_syms = dict(symbols)
                col_t = symbols.get(col_name, "List<Int>")
                el_t = cast(MemeType, col_t[5:-1] if col_t.startswith("List<") else "Int")
                loop_syms[item_var] = el_t
                if inline_body_txt:
                    sub_items, _ = self._parse_block(child_lines, 0, base_indent + 4, loop_syms)
                    i = next_i
                else:
                    if next_i >= len(lines) or lines[next_i].indent <= base_indent:
                        raise LLMProviderError(f"Expected indented block after line {line.lineno}")
                    sub_items, i = self._parse_block(
                        lines, next_i, lines[next_i].indent, loop_syms
                    )
                items.append(
                    ForEachStmt(
                        item_var=item_var,
                        collection=col_name,
                        body=[cast(IRStatement, s) for s in sub_items],
                        source_line=line.lineno,
                    )
                )
                continue

            # 2. `for <var> from <start> to <end>[:]`
            m_for_range = re.fullmatch(
                r"for\s+([A-Za-z_]\w*)\s+from\s+(.+?)\s+to\s+(.+?)\s*:?",
                text,
                flags=re.IGNORECASE,
            )
            if m_for_range:
                loop_var = m_for_range.group(1)
                start_e = _parse_expr(
                    m_for_range.group(2), symbols, self._func_returns, self._records
                )
                end_e = _parse_expr(
                    m_for_range.group(3), symbols, self._func_returns, self._records
                )
                if i + 1 >= len(lines) or lines[i + 1].indent <= base_indent:
                    raise LLMProviderError(f"Expected indented block after line {line.lineno}")
                loop_syms = dict(symbols)
                loop_syms[loop_var] = "Int"
                sub_items, i = self._parse_block(lines, i + 1, lines[i + 1].indent, loop_syms)
                items.append(
                    ForRangeStmt(
                        loop_var=loop_var,
                        start=start_e,
                        end=end_e,
                        body=[cast(IRStatement, s) for s in sub_items],
                        source_line=line.lineno,
                    )
                )
                continue

            # 3. `while <cond>[:]`
            m_while = re.fullmatch(r"while\s+(.+?)\s*:?", text, flags=re.IGNORECASE)
            if m_while:
                cond_e = _parse_expr(
                    m_while.group(1), symbols, self._func_returns, self._records
                )
                if i + 1 >= len(lines) or lines[i + 1].indent <= base_indent:
                    raise LLMProviderError(f"Expected indented block after line {line.lineno}")
                sub_items, i = self._parse_block(
                    lines, i + 1, lines[i + 1].indent, dict(symbols)
                )
                items.append(
                    WhileStmt(
                        condition=cond_e,
                        body=[cast(IRStatement, s) for s in sub_items],
                        source_line=line.lineno,
                    )
                )
                continue

            # 4. `if <cond>[:]` (with optional `else if` / `elif` / `else[:]`)
            m_if = re.fullmatch(r"if\s+(.+?)\s*:?", text, flags=re.IGNORECASE)
            if m_if:
                if_stmt, i = self._parse_if_chain(lines, i, base_indent, symbols, m_if.group(1))
                items.append(if_stmt)
                continue

            # 5. `record <name>[:]`
            m_rec = re.fullmatch(r"record\s+([A-Za-z_]\w*)\s*:?", text, flags=re.IGNORECASE)
            if m_rec:
                rec_name = m_rec.group(1)
                self._records[rec_name] = {}
                if i + 1 >= len(lines) or lines[i + 1].indent <= base_indent:
                    raise LLMProviderError(f"Expected indented block after line {line.lineno}")
                rec_indent = lines[i + 1].indent
                curr = i + 1
                rec_fields: list[RecordFieldDef] = []
                while curr < len(lines) and lines[curr].indent >= rec_indent:
                    fl_txt = lines[curr].text.strip()
                    if fl_txt and not fl_txt.startswith("#") and fl_txt != "pass":
                        fn_p, _, ft_p = fl_txt.partition(":")
                        fn_p = fn_p.strip()
                        ft_p = _normalize_type(ft_p)
                        if not fn_p or not ft_p or not _is_valid_type(ft_p, self._records):
                            raise LLMProviderError(
                                f"Invalid field declaration in record {rec_name}: {lines[curr].text!r}"
                            )
                        rec_fields.append(RecordFieldDef(name=fn_p, field_type=ft_p))
                    curr += 1
                i = curr
                self._records[rec_name] = {f.name: f.field_type for f in rec_fields}
                items.append(
                    RecordDefStmt(name=rec_name, fields=rec_fields, source_line=line.lineno)
                )
                continue

            # 6. `function <name>(<params>) [-> <RetType>][:]`
            m_fn = re.fullmatch(
                r"function\s+([A-Za-z_]\w*)\s*\((.*?)\)(?:\s*->\s*([A-Za-z0-9_<>,\s]+))?\s*:?",
                text,
            )
            if m_fn:
                fn_name = m_fn.group(1)
                raw_params = m_fn.group(2).strip()
                ret_str = _normalize_type((m_fn.group(3) or "Void").strip())
                if not _is_valid_type(ret_str, self._records):
                    raise LLMProviderError(f"Unknown return type {ret_str!r} at line {line.lineno}")
                ret_mt = cast(MemeType, ret_str)
                self._func_returns[fn_name] = ret_mt
                params: list[FuncParam] = []
                fn_syms: dict[str, MemeType] = {}
                if raw_params:
                    for p_chunk in _split_top_level_commas(raw_params):
                        p_name, _, p_type = p_chunk.partition(":")
                        p_name = p_name.strip()
                        p_type = _normalize_type(p_type.strip() or "Int")
                        if not _is_valid_type(p_type, self._records):
                            raise LLMProviderError(
                                f"Unknown parameter type {p_type!r} at line {line.lineno}"
                            )
                        mt = cast(MemeType, p_type)
                        params.append(FuncParam(name=p_name, param_type=mt))
                        fn_syms[p_name] = mt
                if i + 1 >= len(lines) or lines[i + 1].indent <= base_indent:
                    raise LLMProviderError(f"Expected indented block after line {line.lineno}")
                body_items, i = self._parse_block(lines, i + 1, lines[i + 1].indent, fn_syms)
                items.append(
                    FuncDefStmt(
                        name=fn_name,
                        params=params,
                        return_type=ret_mt,
                        body=[cast(IRStatement, s) for s in body_items],
                        source_line=line.lineno,
                    )
                )
                continue

            # Single-line statements
            items.append(self._parse_single_stmt(line, symbols))
            i += 1

        return items, i

    def _parse_if_chain(
        self,
        lines: list[_SourceLine],
        if_idx: int,
        base_indent: int,
        symbols: dict[str, MemeType],
        cond_str: str,
    ) -> tuple[IfStmt, int]:
        line = lines[if_idx]
        cond_e = _parse_expr(cond_str, symbols, self._func_returns, self._records)
        if if_idx + 1 >= len(lines) or lines[if_idx + 1].indent <= base_indent:
            raise LLMProviderError(f"Expected indented block after line {line.lineno}")
        then_items, i = self._parse_block(
            lines, if_idx + 1, lines[if_idx + 1].indent, dict(symbols)
        )
        else_stmts: list[IRStatement] = []
        if i < len(lines) and lines[i].indent == base_indent:
            m_elif = re.fullmatch(
                r"(?:else\s+if|elif)\s+(.+?)\s*:?", lines[i].text, flags=re.IGNORECASE
            )
            if m_elif:
                nested_if, i = self._parse_if_chain(
                    lines, i, base_indent, symbols, m_elif.group(1)
                )
                else_stmts = [nested_if]
            elif re.fullmatch(r"else\s*:?", lines[i].text, flags=re.IGNORECASE):
                if i + 1 >= len(lines) or lines[i + 1].indent <= base_indent:
                    raise LLMProviderError(
                        f"Expected indented block after `else` at line {lines[i].lineno}"
                    )
                else_items, i = self._parse_block(
                    lines, i + 1, lines[i + 1].indent, dict(symbols)
                )
                else_stmts = [cast(IRStatement, s) for s in else_items]
        return (
            IfStmt(
                condition=cond_e,
                then_body=[cast(IRStatement, s) for s in then_items],
                else_body=else_stmts,
                source_line=line.lineno,
            ),
            i,
        )

    def _parse_single_stmt(
        self, line: _SourceLine, symbols: dict[str, MemeType]
    ) -> IRStatement:
        text = line.text
        fn_rets = getattr(self, "_func_returns", {})
        recs = getattr(self, "_records", None)

        def _pe(e_str: str) -> IRExpr:
            return _parse_expr(e_str, symbols, fn_rets, recs)

        # `define list <name> as <expr>`
        m_def_list = re.fullmatch(
            r"define\s+list\s+([A-Za-z_]\w*)(?:\s*:\s*(List<[A-Za-z<>]+>))?\s+as\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if m_def_list:
            name = m_def_list.group(1)
            val = _refine_list_literal_types(
                _pe(m_def_list.group(3)), symbols, fn_rets, recs
            )
            explicit_t = m_def_list.group(2)
            v_type = (
                cast(MemeType, explicit_t)
                if explicit_t and _is_valid_type(explicit_t, recs)
                else _guess_expr_type(val, symbols, fn_rets, recs)
            )
            if not v_type.startswith("List<"):
                v_type = "List<Int>"
            symbols[name] = v_type
            return VarDeclStmt(name=name, var_type=v_type, value=val, source_line=line.lineno)

        # `define <name>[: <Type>] as <expr>`
        m_def = re.fullmatch(
            r"define\s+([A-Za-z_]\w*)(?:\s*:\s*([A-Za-z0-9_<>,\s]+))?\s+as\s+(.+)",
            text,
        )
        if m_def:
            name = m_def.group(1)
            explicit_t = m_def.group(2)
            val = _refine_list_literal_types(
                _pe(m_def.group(3)), symbols, fn_rets, recs
            )
            if explicit_t:
                cleaned_t = _normalize_type(explicit_t)
                if not _is_valid_type(cleaned_t, recs):
                    raise LLMProviderError(f"Unknown type {explicit_t!r} at line {line.lineno}")
                v_type = cast(MemeType, cleaned_t)
            else:
                v_type = _guess_expr_type(val, symbols, fn_rets, recs)
            symbols[name] = v_type
            return VarDeclStmt(name=name, var_type=v_type, value=val, source_line=line.lineno)

        # `set <target>.<field> to <expr>`
        m_set_field = re.fullmatch(
            r"set\s+([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s+to\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if m_set_field:
            return RecordSetFieldStmt(
                target=m_set_field.group(1),
                field_name=m_set_field.group(2),
                value=_pe(m_set_field.group(3)),
                source_line=line.lineno,
            )

        # `set <target>[<index>] to <expr>`
        m_set_idx = re.fullmatch(
            r"set\s+([A-Za-z_]\w*)\s*\[\s*(.+?)\s*\]\s+to\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if m_set_idx:
            tgt = m_set_idx.group(1)
            idx_e = _pe(m_set_idx.group(2))
            val_e = _pe(m_set_idx.group(3))
            tgt_t = symbols.get(tgt, "")
            if tgt_t.startswith("Map<"):
                return MapSetStmt(
                    target=tgt,
                    key=idx_e,
                    value=val_e,
                    source_line=line.lineno,
                )
            return ListSetIndexStmt(
                target=tgt,
                index=idx_e,
                value=val_e,
                source_line=line.lineno,
            )

        # `set <name> to <expr>`
        m_set = re.fullmatch(r"set\s+([A-Za-z_]\w*)\s+to\s+(.+)", text, flags=re.IGNORECASE)
        if m_set:
            return AssignStmt(
                name=m_set.group(1),
                value=_pe(m_set.group(2)),
                source_line=line.lineno,
            )

        # `sort <target> [ascending|descending]`
        m_sort = re.fullmatch(
            r"sort\s+([A-Za-z_]\w*)(?:\s+(ascending|descending))?",
            text,
            flags=re.IGNORECASE,
        )
        if m_sort:
            direction = cast(SortDirection, (m_sort.group(2) or "ascending").lower())
            return SortCollectionStmt(
                target=m_sort.group(1), direction=direction, source_line=line.lineno
            )

        # `clamp <target> between <min> and <max>`
        m_clamp = re.fullmatch(
            r"clamp\s+([A-Za-z_]\w*)\s+between\s+(.+?)\s+and\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if m_clamp:
            return ClampCollectionStmt(
                target=m_clamp.group(1),
                min_val=_pe(m_clamp.group(2)),
                max_val=_pe(m_clamp.group(3)),
                source_line=line.lineno,
            )

        # `filter <target> where <predicate>`
        m_filter = re.fullmatch(
            r"filter\s+([A-Za-z_]\w*)\s+where\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if m_filter:
            target = m_filter.group(1)
            pred = _pe(m_filter.group(2))
            item_var = self._find_free_var(pred, symbols) or "item"
            return FilterCollectionStmt(
                target=target, item_var=item_var, predicate=pred, source_line=line.lineno
            )

        # `append|add <expr> to <target>`
        m_append = re.fullmatch(
            r"(?:append|add)\s+(.+?)\s+to\s+([A-Za-z_]\w*)", text, flags=re.IGNORECASE
        )
        if m_append:
            return ListAppendStmt(
                target=m_append.group(2),
                value=_pe(m_append.group(1)),
                source_line=line.lineno,
            )

        # `insert <expr> into <target> at <index>`
        m_insert = re.fullmatch(
            r"insert\s+(.+?)\s+into\s+([A-Za-z_]\w*)\s+at\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if m_insert:
            return ListInsertStmt(
                target=m_insert.group(2),
                index=_pe(m_insert.group(3)),
                value=_pe(m_insert.group(1)),
                source_line=line.lineno,
            )

        # `fail with <expr>`
        m_fail = re.fullmatch(r"fail\s+with\s+(.+)", text, flags=re.IGNORECASE)
        if m_fail:
            return FailStmt(
                message=_pe(m_fail.group(1)),
                source_line=line.lineno,
            )

        # `print <expr1>, <expr2>, ...`
        m_print = re.fullmatch(r"print\s+(.+)", text, flags=re.IGNORECASE)
        if m_print:
            chunks = _split_top_level_commas(m_print.group(1))
            return PrintStmt(
                expressions=[_pe(c) for c in chunks], source_line=line.lineno
            )

        # `return [<expr>]`
        if re.fullmatch(r"return", text, flags=re.IGNORECASE):
            return ReturnStmt(value=None, source_line=line.lineno)
        m_ret = re.fullmatch(r"return\s+(.+)", text, flags=re.IGNORECASE)
        if m_ret:
            return ReturnStmt(value=_pe(m_ret.group(1)), source_line=line.lineno)

        # Freeform `<name> = <expr>`
        m_eq = re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*(.+)", text)
        if m_eq:
            name = m_eq.group(1)
            val = _refine_list_literal_types(
                _pe(m_eq.group(2)), symbols, fn_rets, recs
            )
            if name in symbols:
                return AssignStmt(name=name, value=val, source_line=line.lineno)
            v_type = _guess_expr_type(val, symbols, fn_rets, recs)
            symbols[name] = v_type
            return VarDeclStmt(name=name, var_type=v_type, value=val, source_line=line.lineno)

        raise LLMProviderError(
            f"Heuristic frontend could not parse line {line.lineno}: {text!r}. "
            "Configure a local LLM (`--provider ollama`) or use Canonical Structured English."
        )

    @staticmethod
    def _find_free_var(expr: IRExpr, symbols: dict[str, MemeType]) -> str | None:
        if isinstance(expr, VarRefExpr) and expr.name not in symbols:
            return expr.name
        if isinstance(expr, BinaryOpExpr):
            return HeuristicProvider._find_free_var(
                expr.left, symbols
            ) or HeuristicProvider._find_free_var(expr.right, symbols)
        if isinstance(expr, UnaryOpExpr):
            return HeuristicProvider._find_free_var(expr.operand, symbols)
        if isinstance(expr, CallExpr):
            for arg in expr.args:
                found = HeuristicProvider._find_free_var(arg, symbols)
                if found:
                    return found
        if isinstance(expr, ListLengthExpr):
            return HeuristicProvider._find_free_var(expr.target, symbols)
        if isinstance(expr, StringLengthExpr):
            return HeuristicProvider._find_free_var(expr.target, symbols)
        if isinstance(expr, StringSliceExpr):
            return (
                HeuristicProvider._find_free_var(expr.target, symbols)
                or HeuristicProvider._find_free_var(expr.start, symbols)
                or HeuristicProvider._find_free_var(expr.end, symbols)
            )
        if isinstance(expr, StrEndsWithExpr):
            return HeuristicProvider._find_free_var(
                expr.target, symbols
            ) or HeuristicProvider._find_free_var(expr.suffix, symbols)
        if isinstance(expr, ReadJsonListExpr):
            return HeuristicProvider._find_free_var(expr.filepath, symbols)
        if isinstance(expr, ListIndexExpr):
            return HeuristicProvider._find_free_var(
                expr.target, symbols
            ) or HeuristicProvider._find_free_var(expr.index, symbols)
        if isinstance(expr, RecordFieldExpr):
            return HeuristicProvider._find_free_var(expr.target, symbols)
        if isinstance(expr, RecordLiteralExpr):
            for f in expr.fields:
                found = HeuristicProvider._find_free_var(f.value, symbols)
                if found:
                    return found
        if isinstance(expr, MapGetExpr):
            return (
                HeuristicProvider._find_free_var(expr.target, symbols)
                or HeuristicProvider._find_free_var(expr.key, symbols)
                or (
                    HeuristicProvider._find_free_var(expr.default_val, symbols)
                    if expr.default_val is not None
                    else None
                )
            )
        if isinstance(expr, MapHasKeyExpr):
            return HeuristicProvider._find_free_var(
                expr.target, symbols
            ) or HeuristicProvider._find_free_var(expr.key, symbols)
        if isinstance(expr, MapLiteralExpr):
            for e in expr.entries:
                found = HeuristicProvider._find_free_var(
                    e.key, symbols
                ) or HeuristicProvider._find_free_var(e.value, symbols)
                if found:
                    return found
        return None

    @staticmethod
    def _build_sort_loop_ambiguity(
        stmt_id: int,
        lineno: int,
        source_text: str,
        target: str,
        lo_e: IRExpr,
        hi_e: IRExpr,
        preceding_stmts: list[IRStatement],
    ) -> AmbiguityDiagnostic:
        opt1_ir: list[IRStatement] = [SortCollectionStmt(target=target, direction="ascending")]
        opt2_ir: list[IRStatement] = [
            ClampCollectionStmt(target=target, min_val=lo_e, max_val=hi_e),
            SortCollectionStmt(target=target, direction="ascending"),
        ]
        candidates: list[AmbiguityCandidate] = [
            AmbiguityCandidate(
                option=1,
                description=f"Mutate `{target}` by sorting all elements in ascending order",
                canonical_meme=to_canonical_meme(ProgramIR(statements=opt1_ir)),
                replacement_ir=opt1_ir,
                replaces_whole_program=False,
            ),
            AmbiguityCandidate(
                option=2,
                description=f"Clamp each item in `{target}` between bounds and sort ascending",
                canonical_meme=to_canonical_meme(ProgramIR(statements=opt2_ir)),
                replacement_ir=opt2_ir,
                replaces_whole_program=False,
            ),
        ]

        rebuilt_whole: list[IRStatement] = []
        found_rand = False
        for prev in preceding_stmts:
            if (
                isinstance(prev, VarDeclStmt)
                and prev.name == target
                and isinstance(prev.value, RandomListExpr)
            ):
                found_rand = True
                rebuilt_whole.append(
                    VarDeclStmt(
                        name=prev.name,
                        var_type=prev.var_type,
                        value=RandomListExpr(
                            count=prev.value.count,
                            min_val=lo_e,
                            max_val=hi_e,
                            implicit_bounds=False,
                        ),
                        source_line=prev.source_line,
                    )
                )
            else:
                rebuilt_whole.append(prev)

        if found_rand:
            rebuilt_whole.append(SortCollectionStmt(target=target, direction="ascending"))
            candidates.append(
                AmbiguityCandidate(
                    option=3,
                    description=f"Generate random integers restricted to the specified range for `{target}` and sort ascending",
                    canonical_meme=to_canonical_meme(ProgramIR(statements=rebuilt_whole)),
                    replacement_ir=rebuilt_whole,
                    replaces_whole_program=True,
                )
            )

        return AmbiguityDiagnostic(
            statement_id=stmt_id,
            source_line=lineno,
            source_text=source_text,
            reason=(
                f"Combining an element-wise loop (`for each ... in {target}`) with a range-qualified "
                "`sort` has multiple conflicting semantic interpretations."
            ),
            candidates=candidates,
        )

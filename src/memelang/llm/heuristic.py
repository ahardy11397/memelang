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
    AppendFileStmt,
    ArgAtExpr,
    ArgCountExpr,
    AssignStmt,
    BinaryOpExpr,
    BinaryOperator,
    BreakStmt,
    CallExpr,
    ClampCollectionStmt,
    CompoundAssignStmt,
    ContinueStmt,
    ExitStmt,
    FailStmt,
    FileExistsExpr,
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
    OptionalIsNothingExpr,
    OptionalNoneExpr,
    OptionalUnwrapExpr,
    OptionalUnwrapOrDefaultExpr,
    OptionalWrapExpr,
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
    SortDirection,
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
    SynthesisItem,
    SynthesisResult,
    UnaryOpExpr,
    VarDeclStmt,
    VarRefExpr,
    WhileStmt,
    WriteFileStmt,
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
    if t.startswith("Optional<") and t.endswith(">"):
        return _is_valid_type(t[9:-1], records)
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
    if t.startswith("Optional<") and t.endswith(">"):
        return f"Optional<{_normalize_type(t[9:-1])}>"
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


def _strip_inline_comment(text: str) -> str:
    """Strips trailing `# ...` comments outside single- or double-quoted string literals."""
    in_str: str | None = None
    escape = False
    for idx, ch in enumerate(text):
        if in_str is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch
        elif ch == "#":
            return text[:idx].rstrip()
    return text


def _tokenize_expr(text: str) -> list[_Tok]:
    pos = 0
    tokens: list[_Tok] = []
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        if text[pos] == "#":
            break
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
        if (
            t
            and t.kind == "IDENT"
            and t.val.lower() == "is"
            and self.pos + 1 < len(self.tokens)
        ):
            if (
                self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "nothing"
            ):
                self.consume("IDENT")
                self.consume("IDENT")
                return OptionalIsNothingExpr(target=left, negated=False)
            if (
                self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "not"
                and self.pos + 2 < len(self.tokens)
                and self.tokens[self.pos + 2].kind == "IDENT"
                and self.tokens[self.pos + 2].val.lower() == "nothing"
            ):
                self.consume("IDENT")
                self.consume("IDENT")
                self.consume("IDENT")
                return OptionalIsNothingExpr(target=left, negated=True)
        if t and t.kind == "IDENT" and t.val == "has":
            self.consume("IDENT", "has")
            if (nxt := self.peek()) and nxt.kind == "IDENT" and nxt.val == "key":
                self.consume("IDENT", "key")
            key_expr = self.parse_add()
            left = MapHasKeyExpr(target=left, key=key_expr)
            t = self.peek()
        elif t and t.kind == "IDENT" and t.val.lower() == "contains":
            self.consume("IDENT")
            sub_expr = self.parse_add()
            left = StrContainsExpr(target=left, substring=sub_expr)
            t = self.peek()
        elif t and t.kind == "IDENT" and t.val.lower() == "starts_with":
            self.consume("IDENT")
            pref_expr = self.parse_add()
            left = StrStartsWithExpr(target=left, prefix=pref_expr)
            t = self.peek()
        elif (
            t
            and t.kind == "IDENT"
            and t.val.lower() == "starts"
            and self.pos + 1 < len(self.tokens)
            and self.tokens[self.pos + 1].kind == "IDENT"
            and self.tokens[self.pos + 1].val.lower() == "with"
        ):
            self.consume("IDENT")
            self.consume("IDENT")
            pref_expr = self.parse_add()
            left = StrStartsWithExpr(target=left, prefix=pref_expr)
            t = self.peek()
        elif t and t.kind == "IDENT" and t.val.lower() == "ends_with":
            self.consume("IDENT")
            suf_expr = self.parse_add()
            left = StrEndsWithExpr(target=left, suffix=suf_expr)
            t = self.peek()
        elif (
            t
            and t.kind == "IDENT"
            and t.val.lower() == "ends"
            and self.pos + 1 < len(self.tokens)
            and self.tokens[self.pos + 1].kind == "IDENT"
            and self.tokens[self.pos + 1].val.lower() == "with"
        ):
            self.consume("IDENT")
            self.consume("IDENT")
            suf_expr = self.parse_add()
            left = StrEndsWithExpr(target=left, suffix=suf_expr)
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
            elif (
                t.kind == "IDENT"
                and t.val.lower() in ("char", "character")
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "at"
            ):
                self.consume("IDENT")
                self.consume("IDENT")
                idx_e = self.parse_unary()
                node = StringCharAtExpr(target=node, index=idx_e)
            elif t.kind == "IDENT" and t.val.lower() == "indexof":
                self.consume("IDENT")
                sub_e = self.parse_unary()
                node = StringIndexOfExpr(target=node, substring=sub_e)
            elif (
                t.kind == "IDENT"
                and t.val.lower() == "index"
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "of"
            ):
                self.consume("IDENT")
                self.consume("IDENT")
                sub_e = self.parse_unary()
                node = StringIndexOfExpr(target=node, substring=sub_e)
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
            if not elems:
                raise LLMProviderError(
                    "Cannot infer element type of untyped empty list literal `[]`; use `empty List<Type>`"
                )
            guessed = _guess_expr_type(
                elems[0], self.symbols, self.func_returns, self.records
            )
            if not _is_valid_type(guessed, self.records):
                raise LLMProviderError(
                    f"Cannot infer valid list element type, got {guessed!r}"
                )
            return ListLiteralExpr(elements=elems, element_type=guessed)

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
            if not entries:
                raise LLMProviderError(
                    "Cannot infer key/value types of untyped empty map literal `{}`; use `empty Map<KeyType, ValueType>`"
                )
            k_guessed = _guess_expr_type(
                entries[0].key, self.symbols, self.func_returns, self.records
            )
            v_guessed = _guess_expr_type(
                entries[0].value, self.symbols, self.func_returns, self.records
            )
            if not _is_valid_type(k_guessed, self.records) or not _is_valid_type(
                v_guessed, self.records
            ):
                raise LLMProviderError(
                    f"Cannot infer valid map literal types, got Map<{k_guessed}, {v_guessed}>"
                )
            return MapLiteralExpr(key_type=k_guessed, value_type=v_guessed, entries=entries)

        if t.kind == "IDENT":
            if t.val == "nothing" and t.val not in self.symbols:
                self.consume()
                return OptionalNoneExpr()
            if (
                t.val == "optional"
                and t.val not in self.symbols
                and not (self.func_returns and t.val in self.func_returns)
                and self.pos + 1 < len(self.tokens)
            ):
                self.consume("IDENT", "optional")
                val_e = self.parse_unary()
                return OptionalWrapExpr(value=val_e)
            if (
                t.val == "value"
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "of"
            ):
                self.consume("IDENT", "value")
                self.consume("IDENT")
                tgt_e = self.parse_unary()
                if (
                    (nxt := self.peek())
                    and nxt.kind == "IDENT"
                    and nxt.val.lower() == "or"
                    and self.pos + 1 < len(self.tokens)
                    and self.tokens[self.pos + 1].kind == "IDENT"
                    and self.tokens[self.pos + 1].val.lower() == "else"
                ):
                    self.consume("IDENT")
                    self.consume("IDENT")
                    dflt_e = self.parse_add()
                    return OptionalUnwrapOrDefaultExpr(target=tgt_e, default_val=dflt_e)
                return OptionalUnwrapExpr(target=tgt_e)
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
                    target = self.parse_unary()
                    return StringLengthExpr(target=target)
                target = self.parse_unary()
                return ListLengthExpr(target=target)

            if (
                t.val.lower() in ("upper", "uppercase", "lower", "lowercase", "trim")
                and t.val not in self.symbols
                and not (self.func_returns and t.val in self.func_returns)
                and not (self.records and t.val in self.records)
                and self.pos + 1 < len(self.tokens)
            ):
                verb = self.consume("IDENT").val.lower()
                if (nxt := self.peek()) and nxt.kind == "IDENT" and nxt.val.lower() == "of":
                    self.consume("IDENT")
                target = self.parse_unary()
                if verb in ("upper", "uppercase"):
                    return StringUpperExpr(target=target)
                if verb in ("lower", "lowercase"):
                    return StringLowerExpr(target=target)
                return StringTrimExpr(target=target)

            if (
                t.val.lower() == "replace"
                and t.val not in self.symbols
                and not (self.func_returns and t.val in self.func_returns)
                and self.pos + 1 < len(self.tokens)
            ):
                self.consume("IDENT")
                old_e = self.parse_add()
                sep_tok = self.consume("IDENT")
                if sep_tok.val.lower() == "with":
                    new_e = self.parse_add()
                    in_tok = self.consume("IDENT")
                    if in_tok.val.lower() != "in":
                        raise LLMProviderError(f"Expected 'in' in replace expression, got {in_tok.val!r}")
                    tgt_e = self.parse_unary()
                    return StringReplaceExpr(target=tgt_e, old=old_e, new=new_e)
                if sep_tok.val.lower() == "in":
                    tgt_e = self.parse_add()
                    with_tok = self.consume("IDENT")
                    if with_tok.val.lower() != "with":
                        raise LLMProviderError(f"Expected 'with' in replace expression, got {with_tok.val!r}")
                    new_e = self.parse_unary()
                    return StringReplaceExpr(target=tgt_e, old=old_e, new=new_e)
                raise LLMProviderError(f"Expected 'with' or 'in' in replace expression, got {sep_tok.val!r}")

            if (
                t.val.lower() == "split"
                and t.val not in self.symbols
                and not (self.func_returns and t.val in self.func_returns)
                and self.pos + 1 < len(self.tokens)
                and not (self.tokens[self.pos + 1].kind == "OP" and self.tokens[self.pos + 1].val == "(")
            ):
                self.consume("IDENT")
                tgt_e = self.parse_unary()
                by_tok = self.consume("IDENT")
                if by_tok.val.lower() not in ("by", "on", "with"):
                    raise LLMProviderError(f"Expected 'by', 'on', or 'with' in split expression, got {by_tok.val!r}")
                sep_e = self.parse_unary()
                return StringSplitExpr(target=tgt_e, separator=sep_e)

            if (
                t.val.lower() == "join"
                and t.val not in self.symbols
                and not (self.func_returns and t.val in self.func_returns)
                and self.pos + 1 < len(self.tokens)
                and not (self.tokens[self.pos + 1].kind == "OP" and self.tokens[self.pos + 1].val == "(")
            ):
                self.consume("IDENT")
                items_e = self.parse_unary()
                with_tok = self.consume("IDENT")
                if with_tok.val.lower() not in ("with", "by"):
                    raise LLMProviderError(f"Expected 'with' or 'by' in join expression, got {with_tok.val!r}")
                sep_e = self.parse_unary()
                return StringJoinExpr(items=items_e, separator=sep_e)

            if (
                t.val.lower() == "indexof"
                and t.val not in self.symbols
                and not (self.func_returns and t.val in self.func_returns)
                and self.pos + 1 < len(self.tokens)
                and not (self.tokens[self.pos + 1].kind == "OP" and self.tokens[self.pos + 1].val == "(")
            ) or (
                t.val.lower() == "index"
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "of"
            ):
                if t.val.lower() == "index":
                    self.consume("IDENT")
                    self.consume("IDENT")
                else:
                    self.consume("IDENT")
                sub_e = self.parse_add()
                in_tok = self.consume("IDENT")
                if in_tok.val.lower() != "in":
                    raise LLMProviderError(f"Expected 'in' in index of expression, got {in_tok.val!r}")
                tgt_e = self.parse_unary()
                return StringIndexOfExpr(target=tgt_e, substring=sub_e)

            if (
                t.val.lower() in ("char", "character")
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "at"
            ):
                self.consume("IDENT")
                self.consume("IDENT")
                idx_e = self.parse_add()
                of_tok = self.consume("IDENT")
                if of_tok.val.lower() not in ("of", "in"):
                    raise LLMProviderError(f"Expected 'of' or 'in' in char at expression, got {of_tok.val!r}")
                tgt_e = self.parse_unary()
                return StringCharAtExpr(target=tgt_e, index=idx_e)

            if (
                t.val.lower() == "slice"
                and t.val not in self.symbols
                and not (self.func_returns and t.val in self.func_returns)
                and self.pos + 1 < len(self.tokens)
                and not (self.tokens[self.pos + 1].kind == "OP" and self.tokens[self.pos + 1].val == "(")
            ):
                self.consume("IDENT")
                tgt_e = self.parse_add()
                from_tok = self.consume("IDENT")
                if from_tok.val.lower() != "from":
                    raise LLMProviderError(f"Expected 'from' in slice expression, got {from_tok.val!r}")
                start_e = self.parse_add()
                to_tok = self.consume("IDENT")
                if to_tok.val.lower() != "to":
                    raise LLMProviderError(f"Expected 'to' in slice expression, got {to_tok.val!r}")
                end_e = self.parse_add()
                return StringSliceExpr(target=tgt_e, start=start_e, end=end_e)

            if (
                t.val == "file"
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val == "exists"
            ):
                self.consume("IDENT", "file")
                self.consume("IDENT", "exists")
                fp = self.parse_postfix()
                return FileExistsExpr(filepath=fp)

            if (
                t.val == "read"
                and self.pos + 2 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val.lower() == "json"
                and self.tokens[self.pos + 2].kind == "IDENT"
                and self.tokens[self.pos + 2].val.lower() == "file"
            ):
                self.consume("IDENT")
                self.consume("IDENT")
                self.consume("IDENT")
                fp = self.parse_postfix()
                self.consume("IDENT", "as")
                self.consume("IDENT", "List")
                self.consume("OP", "<")
                el_tok = self.consume("IDENT")
                self.consume("OP", ">")
                if el_tok.val not in ("Int", "Float", "String", "Bool"):
                    raise LLMProviderError(
                        f"Unsupported JSON list element type {el_tok.val!r}; expected Int, Float, String, or Bool"
                    )
                return ReadJsonListExpr(
                    filepath=fp,
                    element_type=cast(Literal["Int", "Float", "String", "Bool"], el_tok.val),
                    explicit_type=True,
                )

            if (
                t.val == "read"
                and self.pos + 3 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == "IDENT"
                and self.tokens[self.pos + 1].val == "string"
                and self.tokens[self.pos + 2].kind == "IDENT"
                and self.tokens[self.pos + 2].val == "from"
                and self.tokens[self.pos + 3].kind == "IDENT"
                and self.tokens[self.pos + 3].val == "file"
            ):
                self.consume("IDENT", "read")
                self.consume("IDENT", "string")
                self.consume("IDENT", "from")
                self.consume("IDENT", "file")
                fp = self.parse_postfix()
                return ReadFileStringExpr(filepath=fp)

            if (
                t.val == "argument"
                and self.pos + 1 < len(self.tokens)
            ):
                if (
                    self.tokens[self.pos + 1].kind == "IDENT"
                    and self.tokens[self.pos + 1].val == "count"
                ):
                    self.consume("IDENT", "argument")
                    self.consume("IDENT", "count")
                    return ArgCountExpr()
                self.consume("IDENT", "argument")
                idx_expr = self.parse_unary()
                return ArgAtExpr(index=idx_expr)

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
    s = _strip_inline_comment(raw).strip()

    # Special English phrase expressions
    m_empty = re.fullmatch(
        r"empty\s+List<(.+)>", s
    )
    if m_empty:
        el_t = _normalize_type(m_empty.group(1))
        if not _is_valid_type(el_t, records):
            raise LLMProviderError(f"Unknown list element type {el_t!r} in {s!r}")
        return ListLiteralExpr(elements=[], element_type=cast(MemeType, el_t))

    m_empty_map = re.fullmatch(
        r"empty\s+(Map<.+>)", s
    )
    if m_empty_map:
        mt = _map_types_of(_normalize_type(m_empty_map.group(1)))
        if mt is None or not _is_valid_type(mt[0], records) or not _is_valid_type(mt[1], records):
            raise LLMProviderError(f"Invalid map type in {s!r}")
        return MapLiteralExpr(
            key_type=mt[0],
            value_type=mt[1],
            entries=[],
        )

    m_read_json_typed = re.fullmatch(
        r"read\s+json\s+file\s+(.+?)\s+as\s+List\s*<\s*([A-Za-z_]\w*)\s*>",
        s,
        flags=re.IGNORECASE,
    )
    if m_read_json_typed:
        raw_el = m_read_json_typed.group(2)
        if raw_el not in ("Int", "Float", "String", "Bool"):
            raise LLMProviderError(
                f"Unsupported JSON list element type {raw_el!r}; expected Int, Float, String, or Bool"
            )
        return ReadJsonListExpr(
            filepath=_parse_expr(m_read_json_typed.group(1), symbols, func_returns, records),
            element_type=cast(Literal["Int", "Float", "String", "Bool"], raw_el),
            explicit_type=True,
        )

    m_read_json = re.fullmatch(
        r"read\s+JSON\s+number\s+list\s+from\s+(.+)",
        s,
        flags=re.IGNORECASE,
    )
    if m_read_json:
        return ReadJsonListExpr(
            filepath=_parse_expr(m_read_json.group(1), symbols, func_returns, records),
            element_type="Float",
            explicit_type=False,
        )

    m_read_file_str = re.fullmatch(
        r"read\s+string\s+from\s+file\s+(.+)",
        s,
        flags=re.IGNORECASE,
    )
    if m_read_file_str:
        return ReadFileStringExpr(
            filepath=_parse_expr(m_read_file_str.group(1), symbols, func_returns, records)
        )

    m_file_exists = re.fullmatch(
        r"file\s+exists\s+(.+)",
        s,
        flags=re.IGNORECASE,
    )
    if m_file_exists:
        cand = m_file_exists.group(1)
        if not re.search(r"\b(?:and|or)\b", cand):
            return FileExistsExpr(
                filepath=_parse_expr(cand, symbols, func_returns, records)
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


# ---------------------------------------------------------------------------
# Type-Inference Failure Policy (Phase 0 Task 2)
# ---------------------------------------------------------------------------
# Consistent policy across the heuristic parser: whenever an expression's type,
# collection element type, or parameter type cannot be inferred deterministically,
# raise a hard parse error (`LLMProviderError`) rather than silently defaulting
# to `Int`, `List<Int>`, `String`, or `Map<String, String>`. This guarantees that
# untyped empty literals (`[]`, `{}`), untyped function parameters, undeclared
# symbols, or invalid index/field accesses fail fast at parse time instead of
# producing bogus IR types that surface later as cryptic verifier errors.
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
        return cast(MemeType, f"List<{expr.element_type}>")
    if isinstance(expr, StringSplitExpr):
        return "List<String>"
    if isinstance(expr, (StrEndsWithExpr, StrStartsWithExpr, StrContainsExpr, FileExistsExpr)):
        return "Bool"
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
    if isinstance(
        expr,
        (RandomIntExpr, ListLengthExpr, StringLengthExpr, StringIndexOfExpr, ArgCountExpr),
    ):
        return "Int"
    if isinstance(expr, ReadInputExpr):
        return expr.target_type
    if isinstance(expr, RecordLiteralExpr):
        return expr.record_name
    if isinstance(expr, RecordFieldExpr):
        tgt_t = _guess_expr_type(expr.target, symbols, func_returns, records)
        if records and tgt_t in records and expr.field_name in records[tgt_t]:
            return records[tgt_t][expr.field_name]
        raise LLMProviderError(
            f"Cannot infer type of field {expr.field_name!r} on expression of type {tgt_t!r}"
        )
    if isinstance(expr, MapLiteralExpr):
        return cast(MemeType, f"Map<{expr.key_type}, {expr.value_type}>")
    if isinstance(expr, MapGetExpr):
        tgt_t = _guess_expr_type(expr.target, symbols, func_returns, records)
        mt = _map_types_of(tgt_t)
        if mt is not None:
            return mt[1]
        if expr.default_val is not None:
            return _guess_expr_type(expr.default_val, symbols, func_returns, records)
        raise LLMProviderError(
            f"Cannot infer map value type from non-map target of type {tgt_t!r}"
        )
    if isinstance(expr, MapHasKeyExpr):
        return "Bool"
    if isinstance(expr, OptionalNoneExpr):
        return "Optional<Void>"
    if isinstance(expr, OptionalWrapExpr):
        inner_t = _guess_expr_type(expr.value, symbols, func_returns, records)
        return cast(MemeType, f"Optional<{inner_t}>")
    if isinstance(expr, OptionalIsNothingExpr):
        return "Bool"
    if isinstance(expr, (OptionalUnwrapExpr, OptionalUnwrapOrDefaultExpr)):
        tgt_t = _guess_expr_type(expr.target, symbols, func_returns, records)
        if tgt_t.startswith("Optional<") and tgt_t.endswith(">"):
            return cast(MemeType, tgt_t[9:-1])
        if isinstance(expr, OptionalUnwrapOrDefaultExpr):
            return _guess_expr_type(expr.default_val, symbols, func_returns, records)
        raise LLMProviderError(f"Cannot unwrap non-optional expression of type {tgt_t!r}")
    if isinstance(expr, VarRefExpr):
        if expr.name in symbols:
            return symbols[expr.name]
        raise LLMProviderError(
            f"Cannot infer type of undeclared variable {expr.name!r}"
        )
    if isinstance(expr, ListIndexExpr):
        col_t = _guess_expr_type(expr.target, symbols, func_returns, records)
        if col_t.startswith("List<"):
            return cast(MemeType, col_t[5:-1])
        mt = _map_types_of(col_t)
        if mt is not None:
            return mt[1]
        raise LLMProviderError(
            f"Cannot infer element type when indexing into non-collection type {col_t!r}"
        )
    if isinstance(expr, CallExpr):
        if func_returns and expr.func_name in func_returns:
            return func_returns[expr.func_name]
        raise LLMProviderError(
            f"Cannot infer return type of undeclared function {expr.func_name!r}"
        )
    if isinstance(expr, BinaryOpExpr):
        if expr.op in ("==", "!=", "<", "<=", ">", ">=", "and", "or"):
            return "Bool"
        return _guess_expr_type(expr.left, symbols, func_returns, records)
    if isinstance(expr, UnaryOpExpr):
        return "Bool" if expr.op == "not" else _guess_expr_type(expr.operand, symbols, func_returns, records)
    raise LLMProviderError(f"Cannot infer type of expression {expr!r}")


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
            stripped = _strip_inline_comment(expanded).strip()
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

            # 1. `for each [index <i> item] <var> in <col>[:]` (check both inline and indented ambiguous sort!)
            m_foreach = re.fullmatch(
                r"for\s+each\s+(?:index\s+([A-Za-z_]\w*)\s+item\s+([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)|([A-Za-z_]\w*))\s+in\s+([A-Za-z_]\w*)(?:\s*:\s*(.+))?:?",
                text,
                flags=re.IGNORECASE,
            )
            if m_foreach:
                if m_foreach.group(1) and m_foreach.group(2):
                    index_var: str | None = m_foreach.group(1)
                    item_var = m_foreach.group(2)
                elif m_foreach.group(3) and m_foreach.group(4):
                    index_var = m_foreach.group(3)
                    item_var = m_foreach.group(4)
                else:
                    index_var = None
                    item_var = m_foreach.group(5)
                col_name = m_foreach.group(6)
                inline_body_txt = m_foreach.group(7)

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

                if top_level and len(child_lines) == 1 and index_var is None:
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

                if col_name not in symbols:
                    raise LLMProviderError(
                        f"Cannot iterate over undeclared collection {col_name!r} at line {line.lineno}"
                    )
                col_t = symbols[col_name]
                map_t = _map_types_of(col_t)
                if col_t.startswith("List<"):
                    el_t = cast(MemeType, col_t[5:-1])
                elif map_t is not None:
                    el_t = map_t[0]
                else:
                    raise LLMProviderError(
                        f"Cannot iterate over non-collection {col_name!r} of type {col_t!r} at line {line.lineno}"
                    )
                loop_syms = dict(symbols)
                if index_var is not None:
                    loop_syms[index_var] = "Int"
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
                        index_var=index_var,
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

            # 4b. `match <target>[:]`
            m_match = re.fullmatch(r"match\s+(.+?)\s*:?", text, flags=re.IGNORECASE)
            if m_match:
                match_stmt, i = self._parse_match(lines, i, base_indent, symbols, m_match.group(1))
                items.append(match_stmt)
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
                        p_name, sep, p_type_raw = p_chunk.partition(":")
                        p_name = p_name.strip()
                        if not sep or not p_type_raw.strip():
                            raise LLMProviderError(
                                f"Parameter {p_name!r} in function {fn_name!r} at line {line.lineno} "
                                "requires an explicit `: <Type>` annotation."
                            )
                        p_type = _normalize_type(p_type_raw.strip())
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

    def _parse_match(
        self,
        lines: list[_SourceLine],
        match_idx: int,
        base_indent: int,
        symbols: dict[str, MemeType],
        target_str: str,
    ) -> tuple[SwitchStmt, int]:
        line = lines[match_idx]
        target_e = _parse_expr(target_str, symbols, self._func_returns, self._records)
        i = match_idx + 1
        if i >= len(lines) or lines[i].indent <= base_indent:
            raise LLMProviderError(f"Expected indented block after `match` at line {line.lineno}")
        case_indent = lines[i].indent
        cases: list[SwitchCase] = []
        default_body: list[IRStatement] = []

        while i < len(lines) and lines[i].indent == case_indent:
            cur_line = lines[i]
            m_when = re.fullmatch(r"when\s+(.+?)\s*:?", cur_line.text, flags=re.IGNORECASE)
            m_other = re.fullmatch(r"otherwise\s*:?", cur_line.text, flags=re.IGNORECASE)
            if m_when:
                val_e = _parse_expr(m_when.group(1), symbols, self._func_returns, self._records)
                if i + 1 >= len(lines) or lines[i + 1].indent <= case_indent:
                    raise LLMProviderError(f"Expected indented block after `when` at line {cur_line.lineno}")
                body_items, i = self._parse_block(
                    lines, i + 1, lines[i + 1].indent, dict(symbols)
                )
                cases.append(
                    SwitchCase(
                        value=val_e,
                        body=[cast(IRStatement, s) for s in body_items],
                    )
                )
            elif m_other:
                if i + 1 >= len(lines) or lines[i + 1].indent <= case_indent:
                    raise LLMProviderError(f"Expected indented block after `otherwise` at line {cur_line.lineno}")
                default_items, i = self._parse_block(
                    lines, i + 1, lines[i + 1].indent, dict(symbols)
                )
                default_body = [cast(IRStatement, s) for s in default_items]
                break
            else:
                break

        return (
            SwitchStmt(
                target=target_e,
                cases=cases,
                default_body=default_body,
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
            r"define\s+list\s+([A-Za-z_]\w*)(?:\s*:\s*([A-Za-z0-9_<>,\s]+))?\s+as\s+(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if m_def_list:
            name = m_def_list.group(1)
            val = _refine_list_literal_types(
                _pe(m_def_list.group(3)), symbols, fn_rets, recs
            )
            explicit_t = m_def_list.group(2)
            if explicit_t:
                cleaned_t = _normalize_type(explicit_t)
                if not _is_valid_type(cleaned_t, recs) or not cleaned_t.startswith("List<"):
                    raise LLMProviderError(
                        f"Invalid list type {explicit_t!r} at line {line.lineno}"
                    )
                v_type = cast(MemeType, cleaned_t)
            else:
                v_type = _guess_expr_type(val, symbols, fn_rets, recs)
            if not v_type.startswith("List<"):
                raise LLMProviderError(
                    f"Cannot infer list type for {name!r} from expression of type {v_type!r} at line {line.lineno}"
                )
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
            filter_syms = dict(symbols)
            if target in symbols and symbols[target].startswith("List<"):
                el_t = cast(MemeType, symbols[target][5:-1])
                for tok in _tokenize_expr(m_filter.group(2)):
                    if tok.kind == "IDENT" and tok.val not in filter_syms:
                        filter_syms[tok.val] = el_t
            pred = _parse_expr(m_filter.group(2), filter_syms, fn_rets, recs)
            item_var = self._find_free_var(pred, symbols) or "item"
            return FilterCollectionStmt(
                target=target, item_var=item_var, predicate=pred, source_line=line.lineno
            )

        # `write file <path> with <content>`
        m_write_file = re.fullmatch(
            r"write\s+file\s+(.+?)\s+with\s+(.+)", text, flags=re.IGNORECASE
        )
        if m_write_file:
            return WriteFileStmt(
                filepath=_pe(m_write_file.group(1)),
                content=_pe(m_write_file.group(2)),
                source_line=line.lineno,
            )

        # `append|add <content> to file <path>`
        m_append_file = re.fullmatch(
            r"(?:append|add)\s+(.+?)\s+to\s+file\s+(.+)", text, flags=re.IGNORECASE
        )
        if m_append_file:
            return AppendFileStmt(
                filepath=_pe(m_append_file.group(2)),
                content=_pe(m_append_file.group(1)),
                source_line=line.lineno,
            )

        # `append <expr> to <target>`
        m_append = re.fullmatch(
            r"append\s+(.+?)\s+to\s+([A-Za-z_]\w*)", text, flags=re.IGNORECASE
        )
        if m_append:
            return ListAppendStmt(
                target=m_append.group(2),
                value=_pe(m_append.group(1)),
                source_line=line.lineno,
            )

        # `add <expr> to <target>` (list append if target is List<...>, else compound +=)
        m_add = re.fullmatch(
            r"add\s+(.+?)\s+to\s+([A-Za-z_]\w*)", text, flags=re.IGNORECASE
        )
        if m_add:
            target = m_add.group(2)
            val = _pe(m_add.group(1))
            if symbols.get(target, "").startswith("List<"):
                return ListAppendStmt(
                    target=target,
                    value=val,
                    source_line=line.lineno,
                )
            return CompoundAssignStmt(
                target=target,
                operator="+",
                value=val,
                source_line=line.lineno,
            )

        # `subtract <expr> from <target>`
        m_sub = re.fullmatch(
            r"subtract\s+(.+?)\s+from\s+([A-Za-z_]\w*)", text, flags=re.IGNORECASE
        )
        if m_sub:
            return CompoundAssignStmt(
                target=m_sub.group(2),
                operator="-",
                value=_pe(m_sub.group(1)),
                source_line=line.lineno,
            )

        # `multiply <target> by <expr>`
        m_mul = re.fullmatch(
            r"multiply\s+([A-Za-z_]\w*)\s+by\s+(.+)", text, flags=re.IGNORECASE
        )
        if m_mul:
            return CompoundAssignStmt(
                target=m_mul.group(1),
                operator="*",
                value=_pe(m_mul.group(2)),
                source_line=line.lineno,
            )

        # `divide <target> by <expr>`
        m_div = re.fullmatch(
            r"divide\s+([A-Za-z_]\w*)\s+by\s+(.+)", text, flags=re.IGNORECASE
        )
        if m_div:
            return CompoundAssignStmt(
                target=m_div.group(1),
                operator="/",
                value=_pe(m_div.group(2)),
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

        # `exit with code <expr>`
        m_exit = re.fullmatch(r"exit\s+with\s+code\s+(.+)", text, flags=re.IGNORECASE)
        if m_exit:
            return ExitStmt(
                code=_pe(m_exit.group(1)),
                source_line=line.lineno,
            )

        # `print <expr1>, <expr2>, ...`
        m_print = re.fullmatch(r"print\s+(.+)", text, flags=re.IGNORECASE)
        if m_print:
            chunks = _split_top_level_commas(m_print.group(1))
            return PrintStmt(
                expressions=[_pe(c) for c in chunks], source_line=line.lineno
            )

        # `break` / `continue`
        if re.fullmatch(r"break(?:\s+loop)?", text, flags=re.IGNORECASE):
            return BreakStmt(source_line=line.lineno)
        if re.fullmatch(r"continue(?:\s+loop)?", text, flags=re.IGNORECASE):
            return ContinueStmt(source_line=line.lineno)

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
        if isinstance(expr, StrStartsWithExpr):
            return HeuristicProvider._find_free_var(
                expr.target, symbols
            ) or HeuristicProvider._find_free_var(expr.prefix, symbols)
        if isinstance(expr, (StrContainsExpr, StringIndexOfExpr)):
            return HeuristicProvider._find_free_var(
                expr.target, symbols
            ) or HeuristicProvider._find_free_var(expr.substring, symbols)
        if isinstance(expr, StringReplaceExpr):
            return (
                HeuristicProvider._find_free_var(expr.target, symbols)
                or HeuristicProvider._find_free_var(expr.old, symbols)
                or HeuristicProvider._find_free_var(expr.new, symbols)
            )
        if isinstance(expr, (StringUpperExpr, StringLowerExpr, StringTrimExpr)):
            return HeuristicProvider._find_free_var(expr.target, symbols)
        if isinstance(expr, StringSplitExpr):
            return HeuristicProvider._find_free_var(
                expr.target, symbols
            ) or HeuristicProvider._find_free_var(expr.separator, symbols)
        if isinstance(expr, StringJoinExpr):
            return HeuristicProvider._find_free_var(
                expr.items, symbols
            ) or HeuristicProvider._find_free_var(expr.separator, symbols)
        if isinstance(expr, StringCharAtExpr):
            return HeuristicProvider._find_free_var(
                expr.target, symbols
            ) or HeuristicProvider._find_free_var(expr.index, symbols)
        if isinstance(expr, ReadJsonListExpr):
            return HeuristicProvider._find_free_var(expr.filepath, symbols)
        if isinstance(expr, (FileExistsExpr, ReadFileStringExpr)):
            return HeuristicProvider._find_free_var(expr.filepath, symbols)
        if isinstance(expr, ArgAtExpr):
            return HeuristicProvider._find_free_var(expr.index, symbols)
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

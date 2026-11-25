"""Shared code-generation plumbing common to all target backends.

Holds the language-neutral pieces that were previously copy-pasted (and
gradually drifted) across the six backends: the MemeType expression type
inference (`infer_type`), `Map<...>` / `Set<...>` type decomposition, and
C-family string-literal escaping. Per-backend specifics (identifier
keyword tables, TS-specific typing defaults) stay in the backend modules.
"""

from __future__ import annotations

from memelang.ir.schema import (
    ArgAtExpr,
    ArgCountExpr,
    BinaryOpExpr,
    CallExpr,
    CharacterOfExpr,
    CurrentEpochExpr,
    EmptySetExpr,
    EnvVarExpr,
    FileExistsExpr,
    FloatOfExpr,
    FormatFloatExpr,
    FormatIntExpr,
    IRExpr,
    IsDigitExpr,
    IsLetterExpr,
    IsLowerExpr,
    IsUpperExpr,
    ListFilesExpr,
    ListIndexExpr,
    ListLengthExpr,
    ListLiteralExpr,
    LiteralExpr,
    MapGetExpr,
    MapHasKeyExpr,
    MapLiteralExpr,
    MemeType,
    NumberOfExpr,
    OptionalIsNothingExpr,
    OptionalNoneExpr,
    OptionalUnwrapExpr,
    OptionalUnwrapOrDefaultExpr,
    OptionalWrapExpr,
    ParseIntExpr,
    ParseIntOrDefaultExpr,
    RandomIntExpr,
    RandomListExpr,
    ReadFileLinesExpr,
    ReadFileStringExpr,
    ReadInputExpr,
    ReadJsonListExpr,
    ReadJsonRecordExpr,
    ReadJsonRecordsExpr,
    RecordFieldExpr,
    RecordLiteralExpr,
    SetContainsExpr,
    SetLengthExpr,
    Sha256Expr,
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
    VarRefExpr,
)


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


# Historical alias: c_gen and ts_gen named this helper `_set_types_of`.
_set_types_of = _set_type_of


def escape_str(val: str, ctrl_mode: str) -> str:
    """Escape ``val`` as a double-quoted string literal for C-family targets.

    ``ctrl_mode`` selects how control characters (< 0x20) are emitted:

    - ``"c"``: splice the literal (``"\\x01""...``), keeping it a single
      logical string in C
    - ``"cpp"``: splice with explicit spacing (``"\\x01" "..."``)
    - ``"go"`` / ``"rust"``: raw ``\\xNN`` escape inside the literal
    - any other value: leave the character as-is
    """
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
            if ctrl_mode == "c":
                out.append(f'\\x{ord(ch):02x}""')
            elif ctrl_mode == "cpp":
                out.append(f'\\x{ord(ch):02x}" "')
            elif ctrl_mode in ("go", "rust"):
                out.append(f"\\x{ord(ch):02x}")
            else:
                out.append(ch)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _get_transitive_json_records(initial: set[str], records: dict[str, dict[str, MemeType]]) -> set[str]:
    result = set(initial)
    queue = list(initial)
    while queue:
        rec = queue.pop()
        for ftype in records.get(rec, {}).values():
            base = ftype[9:-1] if ftype.startswith("Optional<") and ftype.endswith(">") else ftype
            if base in records:
                if base not in result:
                    result.add(base)
                    queue.append(base)
            elif base.startswith("List<") and base.endswith(">"):
                el = base[5:-1]
                el_base = el[9:-1] if el.startswith("Optional<") and el.endswith(">") else el
                if el_base in records and el_base not in result:
                    result.add(el_base)
                    queue.append(el_base)
            elif base.startswith("Set<") and base.endswith(">"):
                el = base[4:-1]
                if el in records and el not in result:
                    result.add(el)
                    queue.append(el)
            elif base.startswith("Map<") and base.endswith(">"):
                mt = _map_types_of(base)
                if mt:
                    _, v_t = mt
                    v_base = v_t[9:-1] if v_t.startswith("Optional<") and v_t.endswith(">") else v_t
                    if v_base in records and v_base not in result:
                        result.add(v_base)
                        queue.append(v_base)
    return result


class BaseGen:
    """Common base class for target code generators.

    Backends declare their own ``func_returns`` / ``records`` state and
    inherit the language-neutral expression type inference below.
    """

    func_returns: dict[str, MemeType]
    records: dict[str, dict[str, MemeType]]

    # Per-backend fallback defaults used by ``infer_type``. Backends whose
    # language defaults differ (e.g. TypeScript infers ``String`` for unknown
    # variables and ``Void`` for unknown calls) override these.
    unknown_type: MemeType = "Int"
    call_default_type: MemeType = "Int"

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
            return f"List<{expr.element_type}>"
        if isinstance(expr, VarRefExpr):
            return scope.get(expr.name, self.unknown_type)
        if isinstance(expr, RandomListExpr):
            return "List<Int>"
        if isinstance(expr, ReadJsonListExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return f"List<{expr.element_type}>"
            if expr.default_val is not None:
                return f"Optional<List<{expr.element_type}>>"
            return f"List<{expr.element_type}>"
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
        if isinstance(expr, ReadJsonRecordExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return expr.record_name
            return f"Optional<{expr.record_name}>"
        if isinstance(expr, ReadJsonRecordsExpr):
            if expr.default_val is not None and not isinstance(expr.default_val, OptionalNoneExpr):
                return f"List<{expr.record_name}>"
            return f"Optional<List<{expr.record_name}>>"
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
                Sha256Expr,
            ),
        ):
            return "String"
        if isinstance(expr, ListIndexExpr):
            col_t = self.infer_type(expr.target, scope)
            if col_t.startswith("List<"):
                return col_t[5:-1]
            map_t = _map_types_of(col_t)
            if map_t is not None:
                return map_t[1]
            return "Int"
        if isinstance(expr, CallExpr):
            return self.func_returns.get(expr.func_name, self.call_default_type)
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
        if isinstance(expr, (MapHasKeyExpr, SetContainsExpr)):
            return "Bool"
        if isinstance(expr, EmptySetExpr):
            return f"Set<{expr.element_type}>"
        if isinstance(expr, SetLengthExpr):
            return "Int"
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
        return self.unknown_type

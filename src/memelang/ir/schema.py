"""Pydantic v2 Intermediate Representation (IR) schema for Memelang."""

from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

MemeType = str

# Scope guard (Phase 2 Task 16): Bitwise and shift operators (`&`, `|`, `^`, `<<`, `>>`)
# are intentionally deferred because Python's unbounded arbitrary-precision ints vs
# 64-bit signed ints (`i64` / `long long`) in Rust and C++ make bitwise parity a trap.
BinaryOperator = Literal[
    "+",
    "-",
    "*",
    "/",
    "%",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "and",
    "or",
]

CompoundOperator = Literal["+", "-", "*", "/"]
UnaryOperator = Literal["-", "not"]
SortDirection = Literal["ascending", "descending"]


class IRNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @classmethod
    def model_json_schema(cls, *args, **kwargs) -> dict:  # type: ignore[override]
        schema = super().model_json_schema(*args, **kwargs)

        def _enforce_discriminators(obj: object) -> None:
            if isinstance(obj, dict):
                props = obj.get("properties")
                if isinstance(props, dict):
                    req = list(obj.get("required") or [])
                    for tag in ("op", "expr_type"):
                        if tag in props and tag not in req:
                            req.append(tag)
                    if req:
                        obj["required"] = req
                for val in obj.values():
                    _enforce_discriminators(val)
            elif isinstance(obj, list):
                for el in obj:
                    _enforce_discriminators(el)

        _enforce_discriminators(schema)
        return schema


# --- Expressions ---


class LiteralExpr(IRNode):
    expr_type: Literal["literal"] = "literal"
    value: bool | int | float | str
    data_type: MemeType

    @model_validator(mode="after")
    def _validate_literal_type(self) -> LiteralExpr:
        if self.data_type == "Bool":
            if not isinstance(self.value, bool):
                raise ValueError(f"Expected Bool literal, got {type(self.value).__name__}")
        elif self.data_type == "Int":
            if isinstance(self.value, bool) or not isinstance(self.value, int):
                raise ValueError(f"Expected Int literal, got {type(self.value).__name__}")
        elif self.data_type == "Float":
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError(f"Expected Float literal, got {type(self.value).__name__}")
            self.value = float(self.value)
        elif self.data_type == "String":
            if not isinstance(self.value, str):
                raise ValueError(f"Expected String literal, got {type(self.value).__name__}")
        else:
            raise ValueError(f"Unsupported scalar literal data_type: {self.data_type}")
        return self


class ListLiteralExpr(IRNode):
    expr_type: Literal["list_literal"] = "list_literal"
    elements: list[IRExpr]
    element_type: MemeType


class VarRefExpr(IRNode):
    expr_type: Literal["var_ref"] = "var_ref"
    name: str


class RandomIntExpr(IRNode):
    expr_type: Literal["random_int"] = "random_int"
    min_val: IRExpr
    max_val: IRExpr


class RandomListExpr(IRNode):
    expr_type: Literal["random_list"] = "random_list"
    count: IRExpr
    min_val: IRExpr
    max_val: IRExpr
    implicit_bounds: bool = False


class BinaryOpExpr(IRNode):
    expr_type: Literal["binary_op"] = "binary_op"
    op: BinaryOperator
    left: IRExpr
    right: IRExpr


class UnaryOpExpr(IRNode):
    expr_type: Literal["unary_op"] = "unary_op"
    op: UnaryOperator
    operand: IRExpr


class ListLengthExpr(IRNode):
    expr_type: Literal["list_length"] = "list_length"
    target: IRExpr


class ListIndexExpr(IRNode):
    expr_type: Literal["list_index"] = "list_index"
    target: IRExpr
    index: IRExpr


class CallExpr(IRNode):
    expr_type: Literal["call"] = "call"
    func_name: str
    args: list[IRExpr] = Field(default_factory=list)


class ReadInputExpr(IRNode):
    expr_type: Literal["read_input"] = "read_input"
    prompt: str = ""
    target_type: Literal["Int", "Float", "Bool", "String"] = "String"


class StrEndsWithExpr(IRNode):
    expr_type: Literal["str_ends_with"] = "str_ends_with"
    target: IRExpr
    suffix: IRExpr


class StrStartsWithExpr(IRNode):
    expr_type: Literal["str_starts_with"] = "str_starts_with"
    target: IRExpr
    prefix: IRExpr


class StrContainsExpr(IRNode):
    expr_type: Literal["str_contains"] = "str_contains"
    target: IRExpr
    substring: IRExpr


class StringReplaceExpr(IRNode):
    expr_type: Literal["string_replace"] = "string_replace"
    target: IRExpr
    old: IRExpr
    new: IRExpr


class StringUpperExpr(IRNode):
    expr_type: Literal["string_upper"] = "string_upper"
    target: IRExpr


class StringLowerExpr(IRNode):
    expr_type: Literal["string_lower"] = "string_lower"
    target: IRExpr


class StringTrimExpr(IRNode):
    expr_type: Literal["string_trim"] = "string_trim"
    target: IRExpr


class StringSplitExpr(IRNode):
    expr_type: Literal["string_split"] = "string_split"
    target: IRExpr
    separator: IRExpr


class StringJoinExpr(IRNode):
    expr_type: Literal["string_join"] = "string_join"
    items: IRExpr
    separator: IRExpr


class StringIndexOfExpr(IRNode):
    expr_type: Literal["string_index_of"] = "string_index_of"
    target: IRExpr
    substring: IRExpr


class StringCharAtExpr(IRNode):
    expr_type: Literal["string_char_at"] = "string_char_at"
    target: IRExpr
    index: IRExpr


class FileExistsExpr(IRNode):
    expr_type: Literal["file_exists"] = "file_exists"
    filepath: IRExpr


class ReadFileStringExpr(IRNode):
    expr_type: Literal["read_file_string"] = "read_file_string"
    filepath: IRExpr


class ArgCountExpr(IRNode):
    expr_type: Literal["arg_count"] = "arg_count"


class ArgAtExpr(IRNode):
    expr_type: Literal["arg_at"] = "arg_at"
    index: IRExpr


class ReadJsonListExpr(IRNode):
    expr_type: Literal["read_json_list"] = "read_json_list"
    filepath: IRExpr
    element_type: Literal["Int", "Float", "String", "Bool"] = "Float"
    explicit_type: bool = False


class StringLengthExpr(IRNode):
    expr_type: Literal["string_length"] = "string_length"
    target: IRExpr


class StringSliceExpr(IRNode):
    expr_type: Literal["string_slice"] = "string_slice"
    target: IRExpr
    start: IRExpr
    end: IRExpr


class RecordFieldInit(IRNode):
    name: str
    value: IRExpr


class RecordLiteralExpr(IRNode):
    expr_type: Literal["record_literal"] = "record_literal"
    record_name: str
    fields: list[RecordFieldInit] = Field(default_factory=list)


class RecordFieldExpr(IRNode):
    expr_type: Literal["record_field"] = "record_field"
    target: IRExpr
    field_name: str


class MapEntry(IRNode):
    key: IRExpr
    value: IRExpr


class MapLiteralExpr(IRNode):
    expr_type: Literal["map_literal"] = "map_literal"
    key_type: MemeType
    value_type: MemeType
    entries: list[MapEntry] = Field(default_factory=list)


class MapGetExpr(IRNode):
    expr_type: Literal["map_get"] = "map_get"
    target: IRExpr
    key: IRExpr
    default_val: IRExpr | None = None


class MapHasKeyExpr(IRNode):
    expr_type: Literal["map_has_key"] = "map_has_key"
    target: IRExpr
    key: IRExpr


class OptionalNoneExpr(IRNode):
    expr_type: Literal["optional_none"] = "optional_none"


class OptionalWrapExpr(IRNode):
    expr_type: Literal["optional_wrap"] = "optional_wrap"
    value: IRExpr


class OptionalIsNothingExpr(IRNode):
    expr_type: Literal["optional_is_nothing"] = "optional_is_nothing"
    target: IRExpr
    negated: bool = False


class OptionalUnwrapExpr(IRNode):
    expr_type: Literal["optional_unwrap"] = "optional_unwrap"
    target: IRExpr


class OptionalUnwrapOrDefaultExpr(IRNode):
    expr_type: Literal["optional_unwrap_or_default"] = "optional_unwrap_or_default"
    target: IRExpr
    default_val: IRExpr


IRExpr = Annotated[
    LiteralExpr
    | ListLiteralExpr
    | VarRefExpr
    | RandomIntExpr
    | RandomListExpr
    | BinaryOpExpr
    | UnaryOpExpr
    | ListLengthExpr
    | ListIndexExpr
    | CallExpr
    | ReadInputExpr
    | StrEndsWithExpr
    | StrStartsWithExpr
    | StrContainsExpr
    | StringReplaceExpr
    | StringUpperExpr
    | StringLowerExpr
    | StringTrimExpr
    | StringSplitExpr
    | StringJoinExpr
    | StringIndexOfExpr
    | StringCharAtExpr
    | FileExistsExpr
    | ReadFileStringExpr
    | ArgCountExpr
    | ArgAtExpr
    | ReadJsonListExpr
    | StringLengthExpr
    | StringSliceExpr
    | RecordLiteralExpr
    | RecordFieldExpr
    | MapLiteralExpr
    | MapGetExpr
    | MapHasKeyExpr
    | OptionalNoneExpr
    | OptionalWrapExpr
    | OptionalIsNothingExpr
    | OptionalUnwrapExpr
    | OptionalUnwrapOrDefaultExpr,
    Field(discriminator="expr_type"),
]


# --- Statements ---


class FuncParam(IRNode):
    name: str
    param_type: MemeType


class VarDeclStmt(IRNode):
    op: Literal["var_decl"] = "var_decl"
    name: str
    var_type: MemeType
    value: IRExpr
    source_line: int | None = None


class AssignStmt(IRNode):
    op: Literal["assign"] = "assign"
    name: str
    value: IRExpr
    source_line: int | None = None


class CompoundAssignStmt(IRNode):
    op: Literal["compound_assign"] = "compound_assign"
    target: str
    operator: CompoundOperator
    value: IRExpr
    source_line: int | None = None


class SortCollectionStmt(IRNode):
    op: Literal["sort_collection"] = "sort_collection"
    target: str
    direction: SortDirection = "ascending"
    source_line: int | None = None


class ClampCollectionStmt(IRNode):
    op: Literal["clamp_collection"] = "clamp_collection"
    target: str
    min_val: IRExpr
    max_val: IRExpr
    source_line: int | None = None


class FilterCollectionStmt(IRNode):
    op: Literal["filter_collection"] = "filter_collection"
    target: str
    item_var: str
    predicate: IRExpr
    source_line: int | None = None


class ListAppendStmt(IRNode):
    op: Literal["list_append"] = "list_append"
    target: str
    value: IRExpr
    source_line: int | None = None


class ListInsertStmt(IRNode):
    op: Literal["list_insert"] = "list_insert"
    target: str
    index: IRExpr
    value: IRExpr
    source_line: int | None = None


class ListSetIndexStmt(IRNode):
    op: Literal["list_set_index"] = "list_set_index"
    target: str
    index: IRExpr
    value: IRExpr
    source_line: int | None = None


class FailStmt(IRNode):
    op: Literal["fail_stmt"] = "fail_stmt"
    message: IRExpr
    source_line: int | None = None


class ExitStmt(IRNode):
    op: Literal["exit_stmt"] = "exit_stmt"
    code: IRExpr
    source_line: int | None = None


class PrintStmt(IRNode):
    op: Literal["print_stmt"] = "print_stmt"
    expressions: list[IRExpr]
    source_line: int | None = None


class IfStmt(IRNode):
    op: Literal["if_stmt"] = "if_stmt"
    condition: IRExpr
    then_body: list[IRStatement]
    else_body: list[IRStatement] = Field(default_factory=list)
    source_line: int | None = None


class SwitchCase(IRNode):
    value: IRExpr
    body: list[IRStatement]


class SwitchStmt(IRNode):
    op: Literal["switch_stmt"] = "switch_stmt"
    target: IRExpr
    cases: list[SwitchCase] = Field(default_factory=list)
    default_body: list[IRStatement] = Field(default_factory=list)
    source_line: int | None = None


class ForEachStmt(IRNode):
    op: Literal["for_each"] = "for_each"
    item_var: str
    index_var: str | None = None
    collection: str
    body: list[IRStatement]
    source_line: int | None = None


class ForRangeStmt(IRNode):
    op: Literal["for_range"] = "for_range"
    loop_var: str
    start: IRExpr
    end: IRExpr
    body: list[IRStatement]
    source_line: int | None = None


class WhileStmt(IRNode):
    op: Literal["while_loop"] = "while_loop"
    condition: IRExpr
    body: list[IRStatement]
    source_line: int | None = None


class BreakStmt(IRNode):
    op: Literal["loop_break"] = "loop_break"
    source_line: int | None = None


class ContinueStmt(IRNode):
    op: Literal["loop_continue"] = "loop_continue"
    source_line: int | None = None


class FuncDefStmt(IRNode):
    op: Literal["func_def"] = "func_def"
    name: str
    params: list[FuncParam] = Field(default_factory=list)
    return_type: MemeType = "Void"
    body: list[IRStatement]
    source_line: int | None = None


class ReturnStmt(IRNode):
    op: Literal["return_stmt"] = "return_stmt"
    value: IRExpr | None = None
    source_line: int | None = None


class RecordFieldDef(IRNode):
    name: str
    field_type: MemeType


class RecordDefStmt(IRNode):
    op: Literal["record_def"] = "record_def"
    name: str
    fields: list[RecordFieldDef] = Field(default_factory=list)
    source_line: int | None = None


class RecordSetFieldStmt(IRNode):
    op: Literal["record_set_field"] = "record_set_field"
    target: str
    field_name: str
    value: IRExpr
    source_line: int | None = None


class MapSetStmt(IRNode):
    op: Literal["map_set"] = "map_set"
    target: str
    key: IRExpr
    value: IRExpr
    source_line: int | None = None


class WriteFileStmt(IRNode):
    op: Literal["write_file"] = "write_file"
    filepath: IRExpr
    content: IRExpr
    source_line: int | None = None


class AppendFileStmt(IRNode):
    op: Literal["append_file"] = "append_file"
    filepath: IRExpr
    content: IRExpr
    source_line: int | None = None


class ImportStmt(IRNode):
    op: Literal["import_stmt"] = "import_stmt"
    module: str
    source_line: int | None = None

    @model_validator(mode="after")
    def _validate_module(self) -> ImportStmt:
        if not self.module.isidentifier() or not self.module.isascii():
            raise ValueError(f"Module name must be a bare identifier, got {self.module!r}")
        return self


IRStatement = Annotated[
    VarDeclStmt
    | AssignStmt
    | CompoundAssignStmt
    | SortCollectionStmt
    | ClampCollectionStmt
    | FilterCollectionStmt
    | ListAppendStmt
    | ListInsertStmt
    | ListSetIndexStmt
    | FailStmt
    | ExitStmt
    | PrintStmt
    | IfStmt
    | SwitchStmt
    | ForEachStmt
    | ForRangeStmt
    | WhileStmt
    | BreakStmt
    | ContinueStmt
    | FuncDefStmt
    | ReturnStmt
    | RecordDefStmt
    | RecordSetFieldStmt
    | MapSetStmt
    | WriteFileStmt
    | AppendFileStmt
    | ImportStmt,
    Field(discriminator="op"),
]


# --- Ambiguity & Top-Level Synthesis Containers ---


class AmbiguityCandidate(IRNode):
    option: int
    description: str
    canonical_meme: str
    replacement_ir: list[IRStatement]
    replaces_whole_program: bool = False


class AmbiguityDiagnostic(IRNode):
    op: Literal["ambiguity"] = "ambiguity"
    statement_id: int
    source_line: int = 1
    source_text: str
    reason: str
    candidates: list[AmbiguityCandidate]


SynthesisItem = Annotated[
    IRStatement | AmbiguityDiagnostic,
    Field(discriminator="op"),
]


class SynthesisResult(IRNode):
    items: list[SynthesisItem] = Field(default_factory=list)


class ProgramIR(IRNode):
    statements: list[IRStatement] = Field(default_factory=list)
    imported_definitions: list[IRStatement] = Field(default_factory=list)
    module_files: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_items(cls, data: object) -> object:
        if isinstance(data, dict):
            if "items" in data and "statements" not in data:
                data = dict(data)
                data["statements"] = data.pop("items")
        return data

    @property
    def items(self) -> list[IRStatement]:
        return self.statements


# Rebuild recursive models
ListLiteralExpr.model_rebuild()
RandomIntExpr.model_rebuild()
RandomListExpr.model_rebuild()
BinaryOpExpr.model_rebuild()
UnaryOpExpr.model_rebuild()
ListLengthExpr.model_rebuild()
ListIndexExpr.model_rebuild()
CallExpr.model_rebuild()
StrEndsWithExpr.model_rebuild()
StrStartsWithExpr.model_rebuild()
StrContainsExpr.model_rebuild()
StringReplaceExpr.model_rebuild()
StringUpperExpr.model_rebuild()
StringLowerExpr.model_rebuild()
StringTrimExpr.model_rebuild()
StringSplitExpr.model_rebuild()
StringJoinExpr.model_rebuild()
StringIndexOfExpr.model_rebuild()
StringCharAtExpr.model_rebuild()
FileExistsExpr.model_rebuild()
ReadFileStringExpr.model_rebuild()
ArgCountExpr.model_rebuild()
ArgAtExpr.model_rebuild()
ReadJsonListExpr.model_rebuild()
StringLengthExpr.model_rebuild()
StringSliceExpr.model_rebuild()
RecordLiteralExpr.model_rebuild()
RecordFieldExpr.model_rebuild()
MapLiteralExpr.model_rebuild()
MapGetExpr.model_rebuild()
MapHasKeyExpr.model_rebuild()
OptionalNoneExpr.model_rebuild()
OptionalWrapExpr.model_rebuild()
OptionalIsNothingExpr.model_rebuild()
OptionalUnwrapExpr.model_rebuild()
OptionalUnwrapOrDefaultExpr.model_rebuild()
VarDeclStmt.model_rebuild()
AssignStmt.model_rebuild()
CompoundAssignStmt.model_rebuild()
ClampCollectionStmt.model_rebuild()
FilterCollectionStmt.model_rebuild()
ListAppendStmt.model_rebuild()
ListInsertStmt.model_rebuild()
ListSetIndexStmt.model_rebuild()
FailStmt.model_rebuild()
ExitStmt.model_rebuild()
PrintStmt.model_rebuild()
IfStmt.model_rebuild()
SwitchCase.model_rebuild()
SwitchStmt.model_rebuild()
ForEachStmt.model_rebuild()
ForRangeStmt.model_rebuild()
WhileStmt.model_rebuild()
BreakStmt.model_rebuild()
ContinueStmt.model_rebuild()
FuncDefStmt.model_rebuild()
ReturnStmt.model_rebuild()
RecordDefStmt.model_rebuild()
RecordSetFieldStmt.model_rebuild()
MapSetStmt.model_rebuild()
WriteFileStmt.model_rebuild()
AppendFileStmt.model_rebuild()
ImportStmt.model_rebuild()
AmbiguityCandidate.model_rebuild()
AmbiguityDiagnostic.model_rebuild()
SynthesisResult.model_rebuild()
ProgramIR.model_rebuild()

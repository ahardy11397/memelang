"""Pydantic v2 Intermediate Representation (IR) schema for Memelang."""

from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

MemeType = Literal[
    "Int",
    "Float",
    "Bool",
    "String",
    "List<Int>",
    "List<Float>",
    "List<Bool>",
    "List<String>",
    "Void",
]

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
    element_type: Literal["Int", "Float", "Bool", "String"]


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
    | ReadInputExpr,
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


class ForEachStmt(IRNode):
    op: Literal["for_each"] = "for_each"
    item_var: str
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


IRStatement = Annotated[
    VarDeclStmt
    | AssignStmt
    | SortCollectionStmt
    | ClampCollectionStmt
    | FilterCollectionStmt
    | ListAppendStmt
    | PrintStmt
    | IfStmt
    | ForEachStmt
    | ForRangeStmt
    | WhileStmt
    | FuncDefStmt
    | ReturnStmt,
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


# Rebuild recursive models
ListLiteralExpr.model_rebuild()
RandomIntExpr.model_rebuild()
RandomListExpr.model_rebuild()
BinaryOpExpr.model_rebuild()
UnaryOpExpr.model_rebuild()
ListLengthExpr.model_rebuild()
ListIndexExpr.model_rebuild()
CallExpr.model_rebuild()
VarDeclStmt.model_rebuild()
AssignStmt.model_rebuild()
ClampCollectionStmt.model_rebuild()
FilterCollectionStmt.model_rebuild()
ListAppendStmt.model_rebuild()
PrintStmt.model_rebuild()
IfStmt.model_rebuild()
ForEachStmt.model_rebuild()
ForRangeStmt.model_rebuild()
WhileStmt.model_rebuild()
FuncDefStmt.model_rebuild()
ReturnStmt.model_rebuild()
AmbiguityCandidate.model_rebuild()
AmbiguityDiagnostic.model_rebuild()
SynthesisResult.model_rebuild()
ProgramIR.model_rebuild()

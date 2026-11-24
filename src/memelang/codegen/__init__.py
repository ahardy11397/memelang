"""Target code generation dispatcher (`python`, `rust`, `cpp`, `go`, `c`, `ts`)."""

from __future__ import annotations

from typing import Literal, get_args

from memelang.codegen.c_gen import generate_c
from memelang.codegen.cpp_gen import generate_cpp
from memelang.codegen.go_gen import generate_go
from memelang.codegen.python_gen import generate_python
from memelang.codegen.rust_gen import generate_rust
from memelang.codegen.ts_gen import generate_ts
from memelang.ir.schema import ProgramIR

TargetLang = Literal["python", "rust", "cpp", "go", "c", "ts"]

# Single source for the target list (derive from the Literal so CLI and
# corpus tooling never re-hardcode it).
TARGET_LANGS: tuple[TargetLang, ...] = get_args(TargetLang)


def generate_code(ir: ProgramIR, target: TargetLang) -> str:
    if target == "python":
        return generate_python(ir)
    if target == "rust":
        return generate_rust(ir)
    if target == "cpp":
        return generate_cpp(ir)
    if target == "go":
        return generate_go(ir)
    if target == "c":
        return generate_c(ir)
    if target == "ts":
        return generate_ts(ir)
    raise ValueError(f"Unsupported target language: {target!r}")


__all__ = [
    "TARGET_LANGS",
    "TargetLang",
    "generate_c",
    "generate_code",
    "generate_cpp",
    "generate_go",
    "generate_python",
    "generate_rust",
    "generate_ts",
]


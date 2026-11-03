"""Target code generation dispatcher (`python`, `rust`, `cpp`)."""

from __future__ import annotations

from typing import Literal

from memelang.codegen.cpp_gen import generate_cpp
from memelang.codegen.python_gen import generate_python
from memelang.codegen.rust_gen import generate_rust
from memelang.ir.schema import ProgramIR

TargetLang = Literal["python", "rust", "cpp"]


def generate_code(ir: ProgramIR, target: TargetLang) -> str:
    if target == "python":
        return generate_python(ir)
    if target == "rust":
        return generate_rust(ir)
    if target == "cpp":
        return generate_cpp(ir)
    raise ValueError(f"Unsupported target language: {target!r}")


__all__ = [
    "TargetLang",
    "generate_code",
    "generate_cpp",
    "generate_python",
    "generate_rust",
]

"""Static verification and structural ambiguity detection."""

from memelang.analyzer.verifier import (
    StaticVerificationError,
    VerificationOutcome,
    verify_program,
    verify_synthesis,
)

__all__ = [
    "StaticVerificationError",
    "VerificationOutcome",
    "verify_program",
    "verify_synthesis",
]

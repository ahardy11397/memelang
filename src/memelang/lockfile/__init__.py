"""Lockfile (`build.lock`) management and zero-LLM resolution."""

from memelang.lockfile.manager import (
    LockEntry,
    LockFileDocument,
    LockfileManager,
    LockfileResolutionError,
)

__all__ = [
    "LockEntry",
    "LockFileDocument",
    "LockfileManager",
    "LockfileResolutionError",
]

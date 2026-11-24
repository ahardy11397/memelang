"""Shared test helpers for the Memelang test suite."""

from __future__ import annotations

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import TargetLang
from memelang.llm.heuristic import HeuristicProvider
from memelang.runner.executor import ExecutionResult, execute_ir


def run_parity(source: str, target: TargetLang, **execute_kwargs) -> ExecutionResult:
    """Shared cross-target parity pipeline.

    Runs one `.meme` source through HeuristicProvider synthesis, static
    verification, and `execute_ir` on `target`. Extra keyword arguments
    are forwarded to `execute_ir` (e.g. `argv`, `cwd`, `source_dir`).
    """
    outcome = verify_synthesis(HeuristicProvider().synthesize(source))
    assert outcome.program is not None
    return execute_ir(outcome.program, target, **execute_kwargs)

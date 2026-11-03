"""Multi-target compiler & subprocess executor for Python, Rust, and C++20."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile

from memelang.codegen import TargetLang, generate_code
from memelang.ir.schema import ProgramIR


@dataclass
class ExecutionResult:
    stdout: str
    stderr: str
    returncode: int
    generated_code: str


def execute_ir(
    ir: ProgramIR,
    target: TargetLang,
    timeout_sec: float = 15.0,
) -> ExecutionResult:
    code = generate_code(ir, target)

    try:
        with tempfile.TemporaryDirectory(prefix=f"meme_{target}_") as tmp_dir:
            tmp = Path(tmp_dir)

            if target == "python":
                src_path = tmp / "main.py"
                src_path.write_text(code, encoding="utf-8")
                proc = subprocess.run(
                    [sys.executable, str(src_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                return ExecutionResult(
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    returncode=proc.returncode,
                    generated_code=code,
                )

            if target == "rust":
                src_path = tmp / "main.rs"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["rustc", "--edition=2021", "-O", str(src_path), "-o", str(bin_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                if comp.returncode != 0:
                    return ExecutionResult(
                        stdout=comp.stdout,
                        stderr=comp.stderr,
                        returncode=comp.returncode,
                        generated_code=code,
                    )
                proc = subprocess.run(
                    [str(bin_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                return ExecutionResult(
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    returncode=proc.returncode,
                    generated_code=code,
                )

            if target == "cpp":
                src_path = tmp / "main.cpp"
                bin_path = tmp / "app"
                src_path.write_text(code, encoding="utf-8")
                comp = subprocess.run(
                    ["g++", "-std=c++20", "-O2", str(src_path), "-o", str(bin_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                if comp.returncode != 0:
                    return ExecutionResult(
                        stdout=comp.stdout,
                        stderr=comp.stderr,
                        returncode=comp.returncode,
                        generated_code=code,
                    )
                proc = subprocess.run(
                    [str(bin_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
                return ExecutionResult(
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    returncode=proc.returncode,
                    generated_code=code,
                )
    except subprocess.TimeoutExpired as exc:
        out_str = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
        return ExecutionResult(
            stdout=out_str,
            stderr=f"Execution timed out after {timeout_sec}s\n",
            returncode=124,
            generated_code=code,
        )

    raise ValueError(f"Unsupported target language: {target!r}")

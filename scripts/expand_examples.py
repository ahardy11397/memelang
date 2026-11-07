"""Batch automation runner for expanding examples/ and tests/corpus/ to ~500 examples."""

from dataclasses import dataclass
import json
from pathlib import Path

from memelang.analyzer.verifier import verify_synthesis
from memelang.codegen import generate_code
from memelang.llm.heuristic import HeuristicProvider
from memelang.lockfile.manager import LockfileManager
from memelang.runner.executor import execute_ir

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "corpus" / "manifest.json"
LOG_PATH = REPO_ROOT / "EXAMPLES_EXPANSION_LOG.md"


@dataclass
class ExampleDef:
    id: int
    slug: str
    course: str
    topic: str
    title: str
    code: str
    expected_stdout_contains: str
    feature_tags: list[str]
    stdin: str = ""


def process_batch(batch_num: int, axis_name: str, description: str, items: list[ExampleDef]) -> None:
    prov = HeuristicProvider()
    manifest_data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    existing_ids = {s["id"] for s in manifest_data["scripts"]}

    print(f"=== Processing Batch {batch_num} ({axis_name}): {len(items)} items ===")
    for ex in items:
        if ex.id in existing_ids:
            raise ValueError(f"Duplicate script ID: {ex.id}")

        clean_code = ex.code.strip() + "\n"

        # 1. Synthesize & verify
        syn = prov.synthesize(clean_code)
        out = verify_synthesis(syn)
        if not out.is_unambiguous or out.program is None:
            raise ValueError(f"[{ex.id}] {ex.slug} failed unambiguity check: {out.ambiguities}")

        # 2. Execute on python backend and check stdout
        res = execute_ir(out.program, "python", stdin_text=ex.stdin if ex.stdin else None)
        if res.returncode != 0:
            raise RuntimeError(f"[{ex.id}] {ex.slug} execution failed: {res.stderr}")
        if ex.expected_stdout_contains and ex.expected_stdout_contains not in res.stdout:
            raise ValueError(
                f"[{ex.id}] {ex.slug} expected {ex.expected_stdout_contains!r} not in stdout: {res.stdout!r}"
            )

        # 3. Write .meme to both examples/ and tests/corpus/
        ex_meme = REPO_ROOT / "examples" / ex.course / f"{ex.slug}.meme"
        cp_meme = REPO_ROOT / "tests" / "corpus" / ex.course / f"{ex.slug}.meme"
        ex_meme.parent.mkdir(parents=True, exist_ok=True)
        cp_meme.parent.mkdir(parents=True, exist_ok=True)
        ex_meme.write_text(clean_code, encoding="utf-8")
        cp_meme.write_text(clean_code, encoding="utf-8")

        # 4. Generate lockfiles
        ex_lock = REPO_ROOT / "examples" / ex.course / f"{ex.slug}.meme.lock"
        cp_lock = REPO_ROOT / "tests" / "corpus" / ex.course / f"{ex.slug}.meme.lock"
        ex_mgr = LockfileManager(ex_lock)
        ex_mgr.record_outcome(f"examples/{ex.course}/{ex.slug}.meme", clean_code, "heuristic", syn, out)
        cp_mgr = LockfileManager(cp_lock)
        cp_mgr.record_outcome(f"tests/corpus/{ex.course}/{ex.slug}.meme", clean_code, "heuristic", syn, out)

        # 5. Manifest entry
        manifest_data["scripts"].append(
            {
                "id": ex.id,
                "slug": ex.slug,
                "path": f"tests/corpus/{ex.course}/{ex.slug}.meme",
                "course": ex.course,
                "topic": ex.topic,
                "title": ex.title,
                "style": "clean",
                "stdin": ex.stdin,
                "expected_status": "ok",
                "expected_stdout_contains": ex.expected_stdout_contains,
                "feature_tags": ex.feature_tags,
                "extensibility_gaps": {"examples": [], "language": []},
            }
        )
        print(f"  Verified & locked: {ex.id} - {ex.slug}")

    manifest_data["total_scripts"] = len(manifest_data["scripts"])
    MANIFEST_PATH.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")

    # Log to progress file
    id_range = f"{items[0].id}..{items[-1].id}"
    log_line = f"| {batch_num} | {axis_name} | {id_range} | {len(items)} | {description} | Verified clean (Python codegen + lockfile) |\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(log_line)
    print(f"=== Batch {batch_num} complete. Manifest total: {manifest_data['total_scripts']} ===\n")

"""Lockfile (`build.lock`) persistence, SHA-256 caching, and zero-LLM ambiguity resolution."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from memelang.analyzer.verifier import VerificationOutcome, verify_synthesis
from memelang.ir.canonical import to_canonical_meme
from memelang.ir.schema import (
    AmbiguityCandidate,
    AmbiguityDiagnostic,
    ProgramIR,
    SynthesisItem,
    SynthesisResult,
)


class LockfileResolutionError(Exception):
    """Raised when `--resolve` specifies an unknown statement ID or invalid candidate option."""


class LockEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sha256: str
    provider: str
    resolutions: dict[str, int] = Field(default_factory=dict)
    pending_ambiguities: list[AmbiguityDiagnostic] = Field(default_factory=list)
    draft_items: list[SynthesisItem] = Field(default_factory=list)
    canonical_meme: str | None = None
    ir: ProgramIR | None = None


class LockFileDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lockfile_version: Literal[1] = 1
    entries: dict[str, LockEntry] = Field(default_factory=dict)


class LockfileManager:
    def __init__(self, lockfile_path: Path) -> None:
        self.lockfile_path = Path(lockfile_path)

    @staticmethod
    def compute_source_hash(source_text: str) -> str:
        normalized = source_text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _load_doc(self) -> LockFileDocument:
        if not self.lockfile_path.exists():
            return LockFileDocument()
        try:
            raw = self.lockfile_path.read_text(encoding="utf-8")
            return LockFileDocument.model_validate_json(raw)
        except (ValidationError, OSError, ValueError) as exc:
            raise LockfileResolutionError(
                f"Corrupt or incompatible lockfile `{self.lockfile_path}`: {exc}"
            ) from exc

    def _save_doc(self, doc: LockFileDocument) -> None:
        self.lockfile_path.parent.mkdir(parents=True, exist_ok=True)
        self.lockfile_path.write_text(
            doc.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    def get_entry(self, source_key: str) -> LockEntry | None:
        doc = self._load_doc()
        return doc.entries.get(source_key)

    def has_matching_draft(self, source_key: str, source_text: str) -> bool:
        entry = self.get_entry(source_key)
        if entry is None:
            return False
        return entry.source_sha256 == self.compute_source_hash(source_text) and bool(
            entry.draft_items
        )

    def get_cached_program(
        self,
        source_key: str,
        source_text: str,
        requested_resolutions: dict[int, int] | None = None,
    ) -> ProgramIR | None:
        entry = self.get_entry(source_key)
        if entry is None:
            return None
        if entry.source_sha256 != self.compute_source_hash(source_text):
            return None
        if entry.pending_ambiguities or entry.ir is None:
            return None
        if requested_resolutions:
            req_str = {str(k): v for k, v in requested_resolutions.items()}
            merged = dict(entry.resolutions)
            merged.update(req_str)
            if merged != entry.resolutions:
                return None
        return entry.ir

    @staticmethod
    def _splice_resolutions(
        draft_items: list[SynthesisItem],
        resolutions: dict[int, int],
    ) -> list[SynthesisItem]:
        diag_by_id: dict[int, AmbiguityDiagnostic] = {
            item.statement_id: item
            for item in draft_items
            if isinstance(item, AmbiguityDiagnostic)
        }
        if not diag_by_id and resolutions:
            raise LockfileResolutionError(
                "No ambiguous statements exist in this program to resolve."
            )

        valid_ids_str = ", ".join(str(k) for k in sorted(diag_by_id.keys()))
        chosen_candidates: dict[int, AmbiguityCandidate] = {}
        for stmt_id, opt in resolutions.items():
            if stmt_id not in diag_by_id:
                raise LockfileResolutionError(
                    f"Unknown ambiguity statement ID `{stmt_id}`. Valid statement IDs: {valid_ids_str}"
                )
            diag = diag_by_id[stmt_id]
            cand_map = {c.option: c for c in diag.candidates}
            if opt not in cand_map:
                valid_opts = ", ".join(str(o) for o in sorted(cand_map.keys()))
                raise LockfileResolutionError(
                    f"Invalid option `{opt}` for statement {stmt_id}. Valid options: {valid_opts}"
                )
            chosen_candidates[stmt_id] = cand_map[opt]

        # If any chosen candidate replaces the whole program, apply it while preserving any other unresolved ambiguities
        for stmt_id in sorted(chosen_candidates.keys()):
            cand = chosen_candidates[stmt_id]
            if cand.replaces_whole_program:
                remaining_unresolved: list[SynthesisItem] = [
                    item
                    for item in draft_items
                    if isinstance(item, AmbiguityDiagnostic)
                    and item.statement_id not in chosen_candidates
                ]
                return list(cand.replacement_ir) + remaining_unresolved

        spliced: list[SynthesisItem] = []
        for item in draft_items:
            if isinstance(item, AmbiguityDiagnostic) and item.statement_id in chosen_candidates:
                spliced.extend(chosen_candidates[item.statement_id].replacement_ir)
            else:
                spliced.append(item)
        return spliced

    def record_outcome(
        self,
        source_key: str,
        source_text: str,
        provider_name: str,
        synthesis: SynthesisResult,
        outcome: VerificationOutcome,
        requested_resolutions: dict[int, int] | None = None,
    ) -> VerificationOutcome:
        doc = self._load_doc()
        sha = self.compute_source_hash(source_text)
        draft_items = list(outcome.normalized_items) if outcome.normalized_items else list(synthesis.items)

        applied_res: dict[str, int] = {}
        active_outcome = outcome

        if requested_resolutions:
            spliced_items = self._splice_resolutions(draft_items, requested_resolutions)
            active_outcome = verify_synthesis(SynthesisResult(items=spliced_items))
            applied_res = {str(k): v for k, v in requested_resolutions.items()}

        canonical = (
            to_canonical_meme(active_outcome.program)
            if active_outcome.program is not None
            else None
        )

        doc.entries[source_key] = LockEntry(
            source_sha256=sha,
            provider=provider_name,
            resolutions=applied_res,
            pending_ambiguities=list(active_outcome.ambiguities),
            draft_items=draft_items,
            canonical_meme=canonical,
            ir=active_outcome.program,
        )
        self._save_doc(doc)
        return active_outcome

    def apply_resolutions(
        self,
        source_key: str,
        source_text: str,
        resolutions: dict[int, int],
    ) -> VerificationOutcome:
        doc = self._load_doc()
        entry = doc.entries.get(source_key)
        sha = self.compute_source_hash(source_text)
        if entry is None or entry.source_sha256 != sha:
            raise LockfileResolutionError(
                f"No matching lockfile entry found for `{source_key}`; run compilation first."
            )

        merged_res: dict[int, int] = {int(k): v for k, v in entry.resolutions.items()}
        merged_res.update(resolutions)

        spliced_items = self._splice_resolutions(entry.draft_items, merged_res)
        new_outcome = verify_synthesis(SynthesisResult(items=spliced_items))

        entry.resolutions = {str(k): v for k, v in sorted(merged_res.items())}
        entry.pending_ambiguities = list(new_outcome.ambiguities)
        entry.ir = new_outcome.program
        entry.canonical_meme = (
            to_canonical_meme(new_outcome.program) if new_outcome.program is not None else None
        )
        doc.entries[source_key] = entry
        self._save_doc(doc)
        return new_outcome

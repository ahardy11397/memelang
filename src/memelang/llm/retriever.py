"""Pure-Python Okapi BM25 indexer and retriever for few-shot examples."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any


@dataclass
class ExamplePair:
    slug: str
    source_path: Path
    source_text: str
    locked_ir: dict[str, Any]
    score: float = 0.0


def bm25_tokenize(text: str) -> list[str]:
    """Tokenize source text into unigrams, sub-words, structural symbols, and bigrams.

    Strips inline and line comments starting with '#'.
    """
    cleaned = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    raw_tokens = re.findall(r"[a-zA-Z0-9_]+|[\[\]+\-*/]", cleaned.lower())

    tokens: list[str] = []
    for token in raw_tokens:
        tokens.append(token)
        if "_" in token:
            for part in token.split("_"):
                if part:
                    tokens.append(part)

    for i in range(len(raw_tokens) - 1):
        t1, t2 = raw_tokens[i], raw_tokens[i + 1]
        if re.match(r"^[a-zA-Z0-9_]+$", t1) and re.match(r"^[a-zA-Z0-9_]+$", t2):
            tokens.append(f"{t1} {t2}")

    return tokens


class ExampleRetriever:
    """Discovers and BM25-indexes paired .meme and .meme.lock files."""

    def __init__(
        self,
        examples_dir: Path | None = None,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if examples_dir is not None:
            self.examples_dir = Path(examples_dir)
        else:
            self.examples_dir = (
                Path(__file__).resolve().parent.parent.parent.parent / "examples"
            )

        self.k1 = k1
        self.b = b

        self._corpus: list[ExamplePair] = []
        self._doc_tokens: list[list[str]] = []
        self._doc_lengths: list[int] = []
        self._doc_freqs: dict[str, int] = {}
        self._avgdl: float = 0.0

    @property
    def corpus(self) -> list[ExamplePair]:
        return list(self._corpus)

    def index_corpus(self) -> int:
        """Scan examples_dir for .meme + .meme.lock pairs and build index."""
        self._corpus.clear()
        self._doc_tokens.clear()
        self._doc_lengths.clear()
        self._doc_freqs.clear()
        self._avgdl = 0.0

        if not self.examples_dir.exists() or not self.examples_dir.is_dir():
            return 0

        for meme_path in sorted(self.examples_dir.rglob("*.meme")):
            if meme_path.name.endswith(".lock"):
                continue

            lock_path = meme_path.parent / f"{meme_path.name}.lock"
            if not lock_path.exists():
                alt_lock = meme_path.with_suffix(".lock")
                if alt_lock.exists():
                    lock_path = alt_lock
                else:
                    continue

            try:
                source_text = meme_path.read_text(encoding="utf-8")
                locked_ir = json.loads(lock_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            tokens = bm25_tokenize(source_text)
            pair = ExamplePair(
                slug=meme_path.stem,
                source_path=meme_path,
                source_text=source_text,
                locked_ir=locked_ir,
            )

            self._corpus.append(pair)
            self._doc_tokens.append(tokens)
            self._doc_lengths.append(len(tokens))

        n_docs = len(self._corpus)
        if n_docs > 0:
            self._avgdl = sum(self._doc_lengths) / n_docs
            doc_freq_counter: Counter[str] = Counter()
            for tokens in self._doc_tokens:
                doc_freq_counter.update(set(tokens))
            self._doc_freqs = dict(doc_freq_counter)

        return n_docs

    def retrieve(
        self,
        query_text: str,
        top_k: int = 2,
        exclude_path: Path | None = None,
        min_score: float = 0.5,
    ) -> list[ExamplePair]:
        """Retrieve top_k matching examples with BM25 score >= min_score."""
        n_docs = len(self._corpus)
        if n_docs == 0:
            return []

        query_tokens = bm25_tokenize(query_text)
        if not query_tokens:
            return []

        resolved_exclude: Path | None = None
        if exclude_path is not None:
            try:
                resolved_exclude = exclude_path.resolve()
            except Exception:
                resolved_exclude = exclude_path

        candidates: list[ExamplePair] = []
        unique_query_terms = set(query_tokens)

        for i, pair in enumerate(self._corpus):
            if resolved_exclude is not None:
                try:
                    if pair.source_path.resolve() == resolved_exclude:
                        continue
                except Exception:
                    if pair.source_path == resolved_exclude:
                        continue

            doc_tokens = self._doc_tokens[i]
            doc_len = self._doc_lengths[i]
            doc_counts = Counter(doc_tokens)

            score = 0.0
            for term in unique_query_terms:
                if term not in doc_counts:
                    continue

                f = doc_counts[term]
                n = self._doc_freqs.get(term, 0)

                # Robertson-Spärck Jones IDF with Lucene smoothing (+1 inside log)
                # plus baseline smoothing (+0.5) so single-document corpus matches exceed default min_score (0.5)
                idf = math.log(1.0 + (n_docs - n + 0.5) / (n + 0.5)) + 0.5
                tf_denom = f + self.k1 * (
                    1.0 - self.b + self.b * (doc_len / self._avgdl if self._avgdl > 0 else 1.0)
                )
                tf = (f * (self.k1 + 1.0)) / tf_denom if tf_denom > 0 else 0.0
                score += idf * tf

            if score >= min_score:
                candidates.append(
                    ExamplePair(
                        slug=pair.slug,
                        source_path=pair.source_path,
                        source_text=pair.source_text,
                        locked_ir=pair.locked_ir,
                        score=score,
                    )
                )

        candidates.sort(key=lambda p: p.score, reverse=True)
        return candidates[:top_k]

"""Lexical retrieval for German and English text and product identifiers."""

import re
import unicodedata
from dataclasses import dataclass

from rank_bm25 import BM25L


_DASH_TRANSLATION = str.maketrans({"\u2010": "-", "\u2011": "-"})


def tokenize(text: str) -> list[str]:
    """Normalize Unicode and retain complete dotted or hyphenated identifiers.

    Chinese word segmentation, stemming, and unit equivalence are not provided.
    Decimal commas and decimal points are not treated as interchangeable.
    """
    normalized = unicodedata.normalize("NFC", text.casefold())
    normalized = normalized.translate(_DASH_TRANSLATION)
    words = re.findall(r"[^\W_]+(?:[.-][^\W_]+)*", normalized)
    tokens: list[str] = []
    for word in words:
        # Deduplicate generated parts within a word, not repeated source words.
        tokens.extend(dict.fromkeys([word, *re.split(r"[.-]", word)]))
    return tokens


@dataclass(frozen=True)
class _IndexSnapshot:
    chunk_ids: tuple[str, ...]
    token_sets: tuple[frozenset[str], ...]
    bm25: BM25L


class BM25Index:
    """Replaceable in-memory index returning stable chunk IDs.

    BM25L keeps matching terms positively weighted even in small corpora.
    Scores are ranking signals, not probabilities. Equal scores preserve input
    order. Callers must serialize writes. Searches use one complete snapshot.
    Build from the permitted document scope before searching; filtering only
    after top_k can lose eligible results.
    """

    def __init__(self) -> None:
        self._snapshot: _IndexSnapshot | None = None

    @property
    def ready(self) -> bool:
        return self._snapshot is not None

    def replace_documents(self, chunks: list[tuple[str, str]]) -> None:
        """Replace the index with (chunk_id, text) pairs; an empty list clears it.

        IDs must be unique, nonblank strings. Texts must be strings containing
        at least one token. Invalid chunks raise ValueError without replacing
        the previous index. Construction failures also preserve the old index.
        """
        if not chunks:
            self._snapshot = None
            return

        chunk_ids: list[str] = []
        corpus: list[list[str]] = []
        seen: set[str] = set()
        for chunk_id, text in chunks:
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise ValueError("Chunk IDs must be nonblank strings")
            if chunk_id in seen:
                raise ValueError(f"Duplicate chunk ID: {chunk_id!r}")
            if not isinstance(text, str):
                raise ValueError("Chunk text must be a string")
            tokens = tokenize(text)
            if not tokens:
                raise ValueError(f"Chunk text must contain tokens: {chunk_id!r}")
            seen.add(chunk_id)
            chunk_ids.append(chunk_id)
            corpus.append(tokens)

        snapshot = _IndexSnapshot(
            chunk_ids=tuple(chunk_ids),
            token_sets=tuple(frozenset(tokens) for tokens in corpus),
            bm25=BM25L(corpus),
        )
        self._snapshot = snapshot

    def search(self, query: str, top_k: int) -> list[str]:
        """Return matching chunk IDs, ranked by score and limited to top_k.

        top_k must be a nonnegative integer. Empty queries, zero limits, and
        uninitialized indexes return no results. Negative limits raise ValueError.
        """
        if top_k < 0:
            raise ValueError("top_k must be nonnegative")
        snapshot = self._snapshot
        if snapshot is None or top_k == 0:
            return []
        query_tokens = list(dict.fromkeys(tokenize(query)))
        if not query_tokens:
            return []
        query_set = set(query_tokens)
        scores = snapshot.bm25.get_scores(query_tokens)
        matches = [
            i for i, tokens in enumerate(snapshot.token_sets)
            if not query_set.isdisjoint(tokens)
        ]
        matches.sort(key=lambda i: scores[i], reverse=True)
        return [snapshot.chunk_ids[i] for i in matches[:top_k]]

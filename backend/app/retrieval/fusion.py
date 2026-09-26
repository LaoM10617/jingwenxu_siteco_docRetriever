"""Merge retrieval rankings with Reciprocal Rank Fusion (RRF)."""


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60, top_k: int = 10
) -> list[str]:
    """Return chunk IDs ordered by their summed reciprocal-rank scores.

    Each inner list represents one retrieval route, with the best result first.
    Ranks start at one. IDs must be nonblank strings, unique within each route,
    and consistent across routes for the same chunk. Different chunks must have
    different IDs. Cross-route matches accumulate scores without normalization.

    Callers must supply integer k and top_k values. Both must be nonnegative;
    top_k=0 returns an empty list. Ties preserve first-seen ID order, so callers
    should keep retrieval-route order fixed. Document-scope filtering belongs
    upstream, before fusion.

    Raise ValueError for negative parameters, invalid IDs, or within-route
    duplicate IDs.
    """
    if k < 0:
        raise ValueError("k must be nonnegative")
    if top_k < 0:
        raise ValueError("top_k must be nonnegative")

    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, chunk_id in enumerate(ranking, start=1):
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise ValueError("Chunk IDs must be nonblank strings")
            if chunk_id in seen:
                raise ValueError(f"Duplicate chunk ID within a ranking: {chunk_id!r}")
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]

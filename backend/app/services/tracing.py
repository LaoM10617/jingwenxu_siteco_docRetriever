"""Record bounded request snapshots and summarize the retained window."""
import math
import threading
import time
from collections import deque
from copy import deepcopy


class TraceRecorder:
    """Keep small records containing simple, serializable values.

    Capacity limits the number of records, not their byte size. Callers should
    avoid storing full questions, document excerpts, or model answers by default.
    Measure durations with a monotonic clock; ts is a wall-clock timestamp.
    """

    def __init__(self, max_entries: int = 300) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._entries: deque[dict] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(self, entry: dict) -> None:
        """Store an independent snapshot without modifying the caller's data.

        total_ms may be omitted. When provided, it must be a finite,
        nonnegative int or float; invalid values raise ValueError.
        """
        snapshot = deepcopy(entry)
        if "total_ms" in snapshot:
            duration = snapshot["total_ms"]
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration < 0
            ):
                raise ValueError("total_ms must be a finite, nonnegative number")
        snapshot["ts"] = time.time()
        with self._lock:
            self._entries.appendleft(snapshot)

    def recent(self, limit: int = 50) -> list[dict]:
        """Return independent snapshots, newest first; limit must be nonnegative."""
        if limit < 0:
            raise ValueError("limit must be nonnegative")
        with self._lock:
            return deepcopy(list(self._entries)[:limit])

    def summary(self) -> dict:
        """Summarize retained records, not lifetime request totals.

        Missing total_ms values are excluded from latency statistics. P95 uses
        nearest rank: ceil(0.95 * latency_count). With no latency samples,
        avg_ms and p95_ms are None. Durations are rounded to one decimal place.
        """
        with self._lock:
            lat = sorted(e["total_ms"] for e in self._entries if "total_ms" in e)
            latency_count = len(lat)
            p95 = lat[math.ceil(0.95 * latency_count) - 1] if lat else None
            hits = sum(1 for e in self._entries if e.get("cache_hit"))
            checked = sum(1 for e in self._entries if e.get("cache_checked"))
            by_intent: dict[str, int] = {}
            for e in self._entries:
                intent = e.get("intent") or "?"
                by_intent[intent] = by_intent.get(intent, 0) + 1
            return {
                "retained_count": len(self._entries),
                "latency_count": latency_count,
                "avg_ms": round(sum(lat) / latency_count, 1) if lat else None,
                "p95_ms": round(p95, 1) if p95 is not None else None,
                "cache_hit_rate": round(hits / checked, 3) if checked else 0.0,
                "blocked": sum(1 for e in self._entries if e.get("status") == 429),
                "by_intent": by_intent,
            }


traces = TraceRecorder()

"""Verify trace snapshots, retained-window statistics, and input validation."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.tracing import TraceRecorder  # noqa: E402


class TraceRecorderTests(unittest.TestCase):
    def test_ring_and_summary(self):
        recorder = TraceRecorder(max_entries=5)
        recorder.record({"total_ms": 100, "cache_hit": True,
                         "cache_checked": True, "intent": "knowledge"})
        recorder.record({"total_ms": 200, "cache_hit": False,
                         "cache_checked": True, "intent": "chat"})
        recorder.record({"total_ms": 300, "intent": "order"})
        recorder.record({"total_ms": 400, "status": 429})

        self.assertEqual(len(recorder.recent()), 4)
        summary = recorder.summary()
        self.assertEqual(summary["retained_count"], 4)
        self.assertEqual(summary["latency_count"], 4)
        self.assertEqual(summary["p95_ms"], 400)
        self.assertEqual(summary["avg_ms"], 250.0)
        self.assertEqual(summary["cache_hit_rate"], 0.5)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(summary["by_intent"],
                         {"knowledge": 1, "chat": 1, "order": 1, "?": 1})

    def test_capacity_limits_records_and_statistics(self):
        recorder = TraceRecorder(max_entries=2)
        recorder.record({"total_ms": 1000, "status": 429, "intent": "evicted"})
        recorder.record({"total_ms": 2})
        recorder.record({"total_ms": 3})

        self.assertEqual([e["total_ms"] for e in recorder.recent()], [3, 2])
        summary = recorder.summary()
        self.assertEqual(summary["retained_count"], 2)
        self.assertEqual(summary["latency_count"], 2)
        self.assertEqual(summary["avg_ms"], 2.5)
        self.assertEqual(summary["p95_ms"], 3)
        self.assertEqual(summary["blocked"], 0)
        self.assertNotIn("evicted", summary["by_intent"])

    def test_empty_recorder_has_no_latency_estimates(self):
        recorder = TraceRecorder()
        self.assertEqual(recorder.recent(), [])
        self.assertEqual(recorder.summary(), {
            "retained_count": 0, "latency_count": 0,
            "avg_ms": None, "p95_ms": None,
            "cache_hit_rate": 0.0, "blocked": 0, "by_intent": {},
        })

    def test_record_does_not_mutate_or_retain_caller_data(self):
        recorder = TraceRecorder()
        entry = {"total_ms": 10, "retrieval_detail": {"hits": ["chunk-a"]}}
        recorder.record(entry)
        self.assertNotIn("ts", entry)

        entry["total_ms"] = 999
        entry["retrieval_detail"]["hits"].append("chunk-b")
        snapshot = recorder.recent()[0]
        self.assertEqual(snapshot["total_ms"], 10)
        self.assertEqual(snapshot["retrieval_detail"], {"hits": ["chunk-a"]})
        self.assertIsInstance(snapshot["ts"], (int, float))
        self.assertEqual(recorder.summary()["avg_ms"], 10)

    def test_recent_returns_independent_nested_snapshots(self):
        recorder = TraceRecorder()
        recorder.record({"total_ms": 10, "retrieval_detail": {"hits": ["chunk-a"]}})
        returned = recorder.recent()
        returned[0]["total_ms"] = 999
        returned[0]["retrieval_detail"]["hits"].clear()
        returned.clear()

        snapshot = recorder.recent()[0]
        self.assertEqual(snapshot["total_ms"], 10)
        self.assertEqual(snapshot["retrieval_detail"], {"hits": ["chunk-a"]})
        self.assertEqual(recorder.summary()["avg_ms"], 10)

    def test_p95_uses_nearest_rank_for_twenty_samples(self):
        recorder = TraceRecorder()
        for duration in range(20, 0, -1):
            recorder.record({"total_ms": duration})
        self.assertEqual(recorder.summary()["p95_ms"], 19)
        self.assertEqual(recorder.summary()["avg_ms"], 10.5)

    def test_missing_latency_is_excluded_but_zero_is_measured(self):
        recorder = TraceRecorder()
        recorder.record({"status": 200})
        summary = recorder.summary()
        self.assertEqual(summary["retained_count"], 1)
        self.assertEqual(summary["latency_count"], 0)
        self.assertIsNone(summary["avg_ms"])
        self.assertIsNone(summary["p95_ms"])

        recorder.record({"total_ms": 0})
        recorder.record({"total_ms": 10.5})
        summary = recorder.summary()
        self.assertEqual(summary["retained_count"], 3)
        self.assertEqual(summary["latency_count"], 2)
        self.assertEqual(summary["avg_ms"], 5.2)
        self.assertEqual(summary["p95_ms"], 10.5)

    def test_invalid_latency_is_rejected_without_changing_records(self):
        recorder = TraceRecorder()
        recorder.record({"total_ms": 5})
        before = recorder.recent()
        for duration in (-1, float("nan"), float("inf"), -float("inf"),
                         None, "10", True, False):
            with self.subTest(duration=duration):
                entry = {"total_ms": duration}
                with self.assertRaises(ValueError):
                    recorder.record(entry)
                self.assertNotIn("ts", entry)
                self.assertEqual(recorder.recent(), before)

    def test_nonpositive_capacity_is_rejected(self):
        for capacity in (0, -1):
            with self.subTest(capacity=capacity):
                with self.assertRaises(ValueError):
                    TraceRecorder(max_entries=capacity)

    def test_recent_limit(self):
        recorder = TraceRecorder()
        recorder.record({"total_ms": 1})
        recorder.record({"total_ms": 2})
        self.assertEqual(recorder.recent(0), [])
        self.assertEqual([e["total_ms"] for e in recorder.recent(1)], [2])
        self.assertEqual([e["total_ms"] for e in recorder.recent(10)], [2, 1])
        with self.assertRaises(ValueError):
            recorder.recent(-1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

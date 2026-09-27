"""Shared embedding boundary: durable cache, bounded admission and validated vectors."""
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import sqlite3
from threading import Condition, Event
import time

import numpy as np

PREFIXES = {'document': 'Represent the document for retrieval: ',
            'query': 'Represent the query for retrieving supporting documents: '}


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list
    total_tokens: int


class EmbeddingError(Exception):
    def __init__(self, code, *, retryable=False, retry_after=0):
        super().__init__(code)
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


class BudgetScheduler:
    def __init__(self, database, *, now=time.time, wait=None, max_pending=32, max_wait=180,
                 rpm=3, tpm=10000, min_interval=20):
        self.rpm, self.tpm, self.min_interval = rpm, tpm, min_interval
        self.database, self.now = database, now
        self.wait = wait or (lambda condition, seconds: condition.wait(seconds))
        self.condition = Condition()
        self.pending, self.sequence, self.busy = [], 0, False
        self.max_pending, self.max_wait = max_pending, max_wait
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS embedding_budget (sent_at REAL NOT NULL, tokens INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS embedding_cooldown (id INTEGER PRIMARY KEY CHECK(id=1), until_at REAL NOT NULL)')

    def defer(self, seconds):
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            seconds = 60
        with self.condition, closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO embedding_cooldown VALUES (1,?) ON CONFLICT(id) DO UPDATE SET until_at=MAX(until_at,excluded.until_at)', (self.now() + seconds,))
            self.condition.notify_all()

    def run(self, call, tokens, input_type, stop, on_wait):
        if not 1 <= tokens <= 4000:
            raise EmbeddingError('embedding_input_too_large')
        with self.condition:
            if len(self.pending) >= self.max_pending:
                raise EmbeddingError('embedding_queue_full')
            ticket = (0 if input_type == 'query' else 1, self.sequence)
            self.sequence += 1
            self.pending.append(ticket)
            started, reported = self.now(), False
            try:
                while True:
                    if stop.is_set():
                        raise EmbeddingError('embedding_interrupted')
                    now = self.now()
                    if now - started >= self.max_wait:
                        raise EmbeddingError('embedding_wait_timeout')
                    eligible = not self.busy and ticket == min(self.pending)
                    delay = .1
                    if eligible:
                        with closing(sqlite3.connect(self.database)) as db, db:
                            db.execute('BEGIN IMMEDIATE')
                            db.execute('DELETE FROM embedding_budget WHERE sent_at<=?', (now - 60,))
                            events = db.execute('SELECT sent_at,tokens FROM embedding_budget ORDER BY sent_at').fetchall()
                            delay = max(0, events[-1][0] + self.min_interval - now) if events else 0
                            cooldown = db.execute('SELECT until_at FROM embedding_cooldown WHERE id=1').fetchone()
                            if cooldown:
                                delay = max(delay, cooldown[0] - now)
                            remaining = list(events)
                            while len(remaining) >= self.rpm or sum(t for _, t in remaining) + tokens > self.tpm:
                                stamp, _ = remaining.pop(0)
                                delay = max(delay, stamp + 60 - now)
                            if delay <= 0:
                                admission = db.execute('INSERT INTO embedding_budget VALUES (?,?)', (now, tokens)).lastrowid
                        if delay <= 0:
                            self.busy = True
                            break
                    if not reported and on_wait:
                        # Reporting may acquire application locks: do not hold our lock.
                        self.condition.release()
                        try:
                            on_wait()
                        finally:
                            self.condition.acquire()
                        reported = True
                    self.wait(self.condition, min(max(delay, .01), 1.0))
            finally:
                self.pending.remove(ticket)
                self.condition.notify_all()
        try:
            result = call()
            if isinstance(result, EmbeddingResponse):
                if type(result.total_tokens) is not int or result.total_tokens < 0:
                    raise EmbeddingError('embedding_invalid_usage')
                with closing(sqlite3.connect(self.database)) as db, db:
                    db.execute('UPDATE embedding_budget SET tokens=MAX(tokens,?) WHERE rowid=?',
                               (result.total_tokens, admission))
            return result
        except EmbeddingError as exc:
            if exc.retryable:
                # Install cooldown before waking another caller, including queries.
                self.defer(max(20, exc.retry_after))
            raise
        finally:
            with self.condition:
                self.busy = False
                self.condition.notify_all()


class EmbeddingGateway:
    def __init__(self, database, provider, count_tokens, scheduler, *, model='voyage-4'):
        self.database, self.provider, self.count_tokens = database, provider, count_tokens
        self.scheduler, self.model = scheduler, model
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS embedding_cache (cache_key TEXT PRIMARY KEY, vector BLOB NOT NULL)')

    def _key(self, text, input_type):
        return sha256(json.dumps(['voyage', self.model, 1024, 'float', input_type,
                                  False, 'raw-vector-v1', text], ensure_ascii=True).encode()).hexdigest()

    @staticmethod
    def _vectors(values, count):
        try:
            if np.asarray(values).dtype.kind not in 'fiu':
                raise ValueError()
            with np.errstate(over='ignore', invalid='ignore'):
                array = np.asarray(values, dtype=np.float32)
            if (array.shape != (count, 1024) or not np.isfinite(array).all()
                    or np.any(np.linalg.norm(array.astype(np.float64), axis=1) == 0)):
                raise ValueError()
            return array
        except (ValueError, TypeError, OverflowError):
            raise EmbeddingError('embedding_invalid_vectors') from None

    def embed(self, texts, input_type, *, stop=None, on_wait=None, on_start=None):
        if (not isinstance(input_type, str) or input_type not in PREFIXES or not isinstance(texts, list) or not texts
                or any(not isinstance(t, str) or not t.strip() for t in texts)):
            raise EmbeddingError('embedding_invalid_input')
        stop = stop or Event()
        if stop.is_set():
            raise EmbeddingError('embedding_interrupted')
        unique = list(dict.fromkeys(texts))
        found, missing = {}, []
        with closing(sqlite3.connect(self.database)) as db:
            for text in unique:
                row = db.execute('SELECT vector FROM embedding_cache WHERE cache_key=?', (self._key(text, input_type),)).fetchone()
                if row:
                    try:
                        vector = np.frombuffer(row[0], dtype='<f4')
                        found[text] = self._vectors([vector], 1)[0]
                        continue
                    except (ValueError, EmbeddingError):
                        pass  # Invalid cached data is a miss, never a usable vector.
                missing.append(text)
        batches, batch, used = [], [], 0
        for text in missing:
            tokens = self.count_tokens(PREFIXES[input_type] + text) + 16
            if type(tokens) is not int or not 1 <= tokens <= 4000:
                raise EmbeddingError('embedding_input_too_large')
            if used + tokens > 4000:
                batches.append((batch, used))
                batch, used = [], 0
            batch.append(text)
            used += tokens
        if batch:
            batches.append((batch, used))
        for batch, tokens in batches:
            def call():
                if on_start:
                    on_start()
                return self.provider.embed(batch, model=self.model, input_type=input_type,
                    output_dimension=1024, output_dtype='float', truncation=False)
            for attempt in range(3):
                try:
                    values = self.scheduler.run(call, tokens, input_type, stop, on_wait)
                    break
                except EmbeddingError as exc:
                    if exc.retryable:
                        self.scheduler.defer(max(20 * (attempt + 1), exc.retry_after))
                    if not exc.retryable or attempt == 2:
                        raise
            if isinstance(values, EmbeddingResponse):
                values = values.vectors
            vectors = self._vectors(values, len(batch))
            if stop.is_set():
                raise EmbeddingError('embedding_interrupted')
            with closing(sqlite3.connect(self.database)) as db, db:
                for text, vector in zip(batch, vectors):
                    db.execute('INSERT OR REPLACE INTO embedding_cache VALUES (?,?)',
                               (self._key(text, input_type), vector.astype('<f4').tobytes()))
                    found[text] = vector
        return np.stack([found[text] for text in texts])

"""Bounded, durable single-process question jobs; only this module publishes state."""
from contextlib import closing
from collections import deque
import json
import sqlite3
from threading import Condition, Event, Thread
import time
from uuid import uuid4

from fastapi import APIRouter, Request, Query

from app.documents import DocumentError
from app.questions import Identity, QuestionRequest, QuestionBudget, validated


class Submission(QuestionRequest):
    request_id: Identity


class QuestionTasks:
    def __init__(self, database, answers, *, now=time.monotonic, max_pending=8):
        self.database, self.answers, self.now = database, answers, now
        self.max_pending = max_pending
        self.condition, self.stopped = Condition(), Event()
        self.pending, self.budgets = deque(), {}
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS question_tasks (
                id TEXT PRIMARY KEY, conversation TEXT NOT NULL, request_id TEXT NOT NULL,
                request TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
                created REAL NOT NULL, deadline REAL NOT NULL, answer TEXT, error TEXT,
                UNIQUE(conversation, request_id))''')
            db.execute("UPDATE question_tasks SET status='failed',stage='failed',error=? WHERE status IN ('queued','running')",
                       (json.dumps(self.error('question_interrupted', 'The backend restarted. Submit a new question.')),))
        self.worker = Thread(target=self._work, daemon=True, name='question-worker')
        self.monitor = Thread(target=self._monitor, daemon=True, name='question-deadlines')
        self.worker.start()
        self.monitor.start()

    @staticmethod
    def error(code, message, retryable=True):
        return {'code': code, 'message': message, 'retryable': retryable}

    def _load(self, db, identity):
        db.row_factory = sqlite3.Row
        return db.execute('SELECT * FROM question_tasks WHERE id=?', (identity,)).fetchone()

    @staticmethod
    def _public(row):
        request = json.loads(row['request'])
        return {'question_id': row['id'], **request, 'status': row['status'], 'stage': row['stage'],
                'created_at': row['created'], 'deadline_at': row['deadline'],
                'answer': json.loads(row['answer']) if row['answer'] else None,
                'error': json.loads(row['error']) if row['error'] else None}

    def submit(self, value):
        received, budget = time.time(), QuestionBudget(now=self.now)
        body = validated(Submission, value, 'invalid_question').model_dump()
        request_id = body.pop('request_id')
        body['document_ids'] = list(dict.fromkeys(body['document_ids']))
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False)
        with self.condition, closing(sqlite3.connect(self.database)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("DELETE FROM question_tasks WHERE created<? AND status IN ('completed','failed')", (received - 86400,))
            old = db.execute('SELECT * FROM question_tasks WHERE conversation=? AND request_id=?',
                             (body['conversation_id'], request_id)).fetchone()
            if old:
                if old['request'] != encoded:
                    raise DocumentError('request_conflict', 'This request ID already has different content.', 409)
                return self._public(old)
            for identity in body['document_ids']:
                doc = self.answers.tools.documents.get(identity)
                if doc is None:
                    raise DocumentError('document_not_found', 'Unknown document ID.', 404)
                if doc['status'] != 'ready':
                    raise DocumentError('document_not_ready', 'Selected documents must be ready.', 409)
            if self.stopped.is_set() or len(self.pending) >= self.max_pending:
                raise DocumentError('question_queue_full', 'The question queue is full. Try later.', 503, True)
            if db.execute('SELECT count(*) FROM question_tasks').fetchone()[0] >= 1000:
                raise DocumentError('question_capacity', 'Temporary question storage is full. Try later.', 503, True)
            budget.check()
            identity = uuid4().hex
            db.execute('INSERT INTO question_tasks VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (identity, body['conversation_id'], request_id, encoded, 'queued', 'queued', received,
                        received + 240, None, None))
            db.commit()
            self.budgets[identity] = budget
            self.pending.append(identity)
            self.condition.notify_all()
            return self._public(self._load(db, identity))

    def get(self, identity, conversation):
        with self.condition, closing(sqlite3.connect(self.database)) as db, db:
            self._expire(db)
            row = self._load(db, identity)
            if row is None or row['conversation'] != conversation or row['created'] < time.time() - 86400:
                raise DocumentError('question_not_found', 'Question not found or expired.', 404)
            return self._public(row)

    def csv_page(self, identity, conversation, tool_index, offset, limit):
        task = self.get(identity, conversation)
        if task['status'] != 'completed':
            raise DocumentError('question_not_completed', 'Question is not completed.', 409)
        results = task['answer']['tool_results']
        if tool_index >= len(results) or results[tool_index]['tool'] != 'lookup_orders':
            raise DocumentError('query_not_found', 'No such CSV query in this question.', 404)
        tool = results[tool_index]
        return self.answers.tools.documents.lookup_orders(tool['result']['order_ids'],
                    tool['document_ids'], offset=offset, limit=limit)

    def _expire(self, db):
        for identity, budget in self.budgets.items():
            if budget.is_set():
                db.execute("UPDATE question_tasks SET status='failed',stage='failed',error=? WHERE id=? AND status IN ('queued','running')",
                           (json.dumps(self.error('question_timeout', 'The question deadline expired.')), identity))

    def _stage(self, identity, stage):
        with self.condition, closing(sqlite3.connect(self.database)) as db, db:
            self._expire(db)
            db.execute("UPDATE question_tasks SET stage=? WHERE id=? AND status='running'", (stage, identity))

    def _monitor(self):
        while not self.stopped.wait(.1):
            try:
                with self.condition, closing(sqlite3.connect(self.database)) as db, db:
                    self._expire(db)
                    db.execute("DELETE FROM question_tasks WHERE created<? AND status IN ('completed','failed')", (time.time() - 86400,))
            except (sqlite3.Error, OSError):
                # Reads and publication also check deadlines; never publish late on a storage error.
                continue

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.stopped.is_set())
                if self.stopped.is_set():
                    return
                identity = self.pending.popleft()
                budget = self.budgets[identity]
            answer, error = None, None
            try:
                with self.condition, closing(sqlite3.connect(self.database)) as db, db:
                    self._expire(db)
                    row = self._load(db, identity)
                    if row is None or row['status'] != 'queued':
                        continue
                    db.execute("UPDATE question_tasks SET status='running',stage='planning' WHERE id=?", (identity,))
                answer = self.answers.answer(json.loads(row['request']), budget=budget,
                    on_stage=lambda stage: self._stage(identity, stage),
                    on_wait=lambda: self._stage(identity, 'waiting_rate_limit'))
                budget.check()
            except DocumentError as exc:
                error = self.error(exc.code, str(exc), exc.retryable)
            except Exception:
                error = self.error('question_failed', 'The question could not be completed.')
            finally:
                with self.condition:
                    try:
                        with closing(sqlite3.connect(self.database)) as db, db:
                            self._expire(db)
                            if answer is not None or error is not None:
                                status = 'failed' if error else 'completed'
                                db.execute("UPDATE question_tasks SET status=?,stage=?,answer=?,error=? WHERE id=? AND status='running'",
                                    (status, status, json.dumps(answer) if not error else None,
                                     json.dumps(error) if error else None, identity))
                    except (sqlite3.Error, OSError):
                        # Preserve an explicit failure if storage recovers before retention expiry.
                        budget.deadline = 0
                        continue
                    self.budgets.pop(identity, None)

    def stop(self):
        self.stopped.set()
        with self.condition, closing(sqlite3.connect(self.database)) as db, db:
            for budget in self.budgets.values():
                budget.deadline = 0
            db.execute("UPDATE question_tasks SET status='failed',stage='failed',error=? WHERE status IN ('queued','running')",
                       (json.dumps(self.error('question_interrupted', 'The backend stopped. Submit a new question.')),))
            self.condition.notify_all()
        self.monitor.join(timeout=1)
        self.worker.join(timeout=1)


router = APIRouter()


@router.post('/api/questions', status_code=202)
def submit_question(body: Submission, request: Request):
    return request.app.state.questions.submit(body.model_dump())


@router.get('/api/questions/{question_id}')
def question_status(question_id: str, request: Request, conversation_id: str = Query(min_length=1, max_length=200)):
    return request.app.state.questions.get(question_id, conversation_id)


@router.get('/api/questions/{question_id}/csv/{tool_index}')
def csv_results(question_id: str, tool_index: int, request: Request,
                conversation_id: str = Query(min_length=1, max_length=200),
                offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
    if tool_index < 0:
        raise DocumentError('query_not_found', 'No such CSV query.', 404)
    return request.app.state.questions.csv_page(question_id, conversation_id, tool_index, offset, limit)

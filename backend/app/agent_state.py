"""Stage A persistence probe; not the production conversation graph or HTTP API."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable, Literal, TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel, ConfigDict, Field


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


class RunView(BaseModel):
    run_id: str
    turn_id: str
    task_id: str
    session_id: str
    status: Literal['recoverable', 'waiting', 'completed']
    publications: list[dict[str, str]]


class _State(TypedDict, total=False):
    run_id: str
    prompt: str
    answer: str


class StateProbe:
    """Explicit submit/inspect/resume. Construction never resumes paid work.

    Request identity is session-local; run identity is globally unique and is the
    checkpoint thread ID. SQLite locks cover a session across local processes.
    ``after_answer`` and ``after_publish`` inject faults after business commits
    to verify recovery across the separate checkpoint database.
    """

    def __init__(self, root: Path, *, after_publish: Callable[[], None] | None = None,
                 after_answer: Callable[[], None] | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.business = self.root / 'business.sqlite'
        self.checkpoints = self.root / 'checkpoints.sqlite'
        self.after_publish = after_publish
        self.after_answer = after_answer
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, request TEXT NOT NULL,
                    answer TEXT, completed INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(session_id, request_id));
                CREATE TABLE IF NOT EXISTS publications (
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id), payload TEXT NOT NULL);
            ''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.business, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _session_lock(self, session_id: str):
        # Separate lock databases avoid holding the shared business write lock
        # during graph work. OS closes/releases locks even after process death.
        lock_dir = self.root / 'session-locks'
        lock_dir.mkdir(exist_ok=True)
        key = hashlib.sha256(session_id.encode()).hexdigest()
        db = sqlite3.connect(lock_dir / f'{key}.sqlite', timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield
        finally:
            db.rollback()
            db.close()

    def _row(self, run_id: str):
        with self._db() as db:
            row = db.execute('SELECT * FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row

    @contextmanager
    def _graph(self):
        connection = sqlite3.connect(self.checkpoints, timeout=30, check_same_thread=False)
        try:
            saver = SqliteSaver(connection, serde=JsonPlusSerializer(allowed_msgpack_modules=[]))
            builder = StateGraph(_State)
            builder.add_node('clarify', self._clarify)
            builder.add_node('publish', self._publish)
            builder.add_edge(START, 'clarify')
            builder.add_edge('clarify', 'publish')
            builder.add_edge('publish', END)
            yield builder.compile(checkpointer=saver)
        finally:
            connection.close()

    def _clarify(self, state: _State):
        answer = interrupt({'question': state['prompt']})
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('A non-empty clarification answer is required')
        return {'answer': answer}

    def _publish(self, state: _State):
        payload = json.dumps({'prompt': state['prompt'], 'answer': state['answer']}, sort_keys=True)
        with self._db() as db:
            existing = db.execute('SELECT payload FROM publications WHERE run_id=?',
                                  (state['run_id'],)).fetchone()
            if existing and existing['payload'] != payload:
                raise ValueError('Replay publication differs from the persisted result')
            db.execute('INSERT OR IGNORE INTO publications VALUES (?, ?)', (state['run_id'], payload))
        if self.after_publish:
            self.after_publish()
        return {}

    @staticmethod
    def _config(run_id: str):
        return {'configurable': {'thread_id': run_id}}

    def submit(self, request: ProbeRequest) -> RunView:
        with self._session_lock(request.session_id):
            encoded = request.model_dump_json()
            with self._db() as db:
                row = db.execute('SELECT * FROM runs WHERE session_id=? AND request_id=?',
                                 (request.session_id, request.request_id)).fetchone()
                if row and row['request'] != encoded:
                    raise ValueError('Request identity already has a different payload')
                if row is None:
                    run_id = str(uuid4())
                    db.execute('INSERT INTO runs (run_id, session_id, request_id, request) VALUES (?, ?, ?, ?)',
                               (run_id, request.session_id, request.request_id, encoded))
                else:
                    run_id = row['run_id']
            if row is None:
                with self._graph() as graph:
                    graph.invoke({'run_id': run_id, 'prompt': request.prompt},
                                 self._config(run_id), durability='sync')
            return self.inspect(run_id)

    def inspect(self, run_id: str) -> RunView:
        row = self._row(run_id)
        with self._graph() as graph:
            snapshot = graph.get_state(self._config(run_id))
        with self._db() as db:
            publications = [json.loads(item['payload']) for item in db.execute(
                'SELECT payload FROM publications WHERE run_id=?', (run_id,))]
        status = 'completed' if row['completed'] else 'recoverable'
        # A business answer can commit before the graph consumes it. Such a run
        # needs explicit replay, not another user clarification.
        if not row['completed'] and row['answer'] is None and any(
                task.interrupts for task in snapshot.tasks):
            status = 'waiting'
        return RunView(run_id=run_id, turn_id=run_id, task_id=f'{run_id}:probe',
                       session_id=row['session_id'], status=status, publications=publications)

    def recoverable(self) -> list[RunView]:
        """List interrupted/incomplete work; never invoke the graph on startup."""
        with self._db() as db:
            run_ids = [row['run_id'] for row in db.execute(
                'SELECT run_id FROM runs WHERE completed=0 ORDER BY rowid')]
        return [self.inspect(run_id) for run_id in run_ids]

    def resume(self, run_id: str, answer: str | None = None) -> RunView:
        row = self._row(run_id)
        with self._session_lock(row['session_id']):
            row = self._row(run_id)
            if answer is not None:
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError('A non-empty clarification answer is required')
                if row['answer'] is not None and row['answer'] != answer:
                    raise ValueError('Clarification was already answered differently')
                with self._db() as db:
                    db.execute('UPDATE runs SET answer=? WHERE run_id=?', (answer, run_id))
                if self.after_answer:
                    self.after_answer()
                row = self._row(run_id)
            if row['completed']:
                return self.inspect(run_id)
            with self._graph() as graph:
                config = self._config(run_id)
                snapshot = graph.get_state(config)
                if not snapshot.values:
                    request = ProbeRequest.model_validate_json(row['request'])
                    graph.invoke({'run_id': run_id, 'prompt': request.prompt}, config, durability='sync')
                    snapshot = graph.get_state(config)
                if any(task.interrupts for task in snapshot.tasks):
                    if row['answer'] is None:
                        return self.inspect(run_id)
                    graph.invoke(Command(resume=row['answer']), config, durability='sync')
                elif snapshot.next:
                    graph.invoke(None, config, durability='sync')
                snapshot = graph.get_state(config)
                if snapshot.values and not snapshot.next:
                    with self._db() as db:
                        db.execute('UPDATE runs SET completed=1 WHERE run_id=?', (run_id,))
            return self.inspect(run_id)

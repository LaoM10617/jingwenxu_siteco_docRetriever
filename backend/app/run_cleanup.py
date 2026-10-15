"""Durable cleanup intent across the business and checkpoint databases."""
from langgraph.checkpoint.sqlite import SqliteSaver

from app.db import connect as sqlite_connect


def retry_purges(runs):
    with runs._db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS conversation_purges (run_id TEXT PRIMARY KEY)')
        ids = [row[0] for row in db.execute('SELECT run_id FROM conversation_purges')]
    if not ids:
        return
    with sqlite_connect(runs.checkpoints) as checkpoint:
        saver = SqliteSaver(checkpoint)
        saver.setup()
        for run_id in ids:
            with runs._db() as db:
                row = db.execute('SELECT session_id FROM conversation_runs WHERE run_id=?', (run_id,)).fetchone()
            if row is not None and runs._running(row[0]):
                continue
            saver.delete_thread(run_id)
            with runs._db() as db:
                db.execute('DELETE FROM conversation_purges WHERE run_id=?', (run_id,))
            runs._bound.pop(run_id, None)


def invalidate_source(db, version_id):
    """Called in permanent deletion's transaction, before removing original data.

    Deletes rows only; the matching on-disk payload files become orphans that
    the next ExecutionJobs startup sweep removes (see execution_jobs.py).
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='conversation_runs'").fetchone():
        return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_jobs'").fetchone():
        db.execute('''DELETE FROM execution_jobs WHERE job_id IN (
            SELECT j.job_id FROM execution_jobs j, json_each(j.task_json, '$.scope.documents') d
            WHERE json_extract(d.value, '$.version_id')=?)''', (version_id,))
    db.execute('CREATE TABLE IF NOT EXISTS conversation_purges (run_id TEXT PRIMARY KEY)')
    ids = [row[0] for row in db.execute('''SELECT r.run_id FROM conversation_runs r
        JOIN turn_snapshots s ON s.snapshot_id=r.snapshot_id
        JOIN json_each(s.scope, '$.documents') d
        WHERE json_extract(d.value, '$.version_id')=?''', (version_id,))]
    for run_id in ids:
        db.execute('DELETE FROM conversation_tasks WHERE run_id=?', (run_id,))
        db.execute('DELETE FROM conversation_model_receipts WHERE run_id=?', (run_id,))
        db.execute('DELETE FROM conversation_evidence WHERE run_id=?', (run_id,))
        db.execute("DELETE FROM conversation_events WHERE run_id=? AND channel='developer'", (run_id,))
        db.execute("UPDATE conversation_runs SET stop_requested=1, status=CASE WHEN status='completed' THEN status ELSE 'stopped' END WHERE run_id=?", (run_id,))
        db.execute('INSERT OR IGNORE INTO conversation_purges VALUES (?)', (run_id,))


def delete_session(runs, session_id):
    # Do not race a provider return or checkpoint write. The lock is separate
    # from the business database, so other sessions can still read and write.
    with runs._session_lock(session_id):
        with runs._db() as db:
            db.execute('BEGIN IMMEDIATE')
            runs.sessions._session(db, session_id)
            ids = [row[0] for row in db.execute(
                'SELECT run_id FROM conversation_runs WHERE session_id=?', (session_id,))]
            db.executemany('INSERT OR IGNORE INTO conversation_purges VALUES (?)', [(id,) for id in ids])
            runs.sessions.delete(session_id, db=db)
        retry_purges(runs)

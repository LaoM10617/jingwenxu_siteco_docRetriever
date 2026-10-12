"""A graph publication commits its artifact and message in one business transaction."""
from contextlib import closing
import sqlite3

import pytest

from app.artifacts import ArtifactStore
from app.documents import DocumentError, DocumentService
from app.sessions import SessionStore


@pytest.mark.parametrize('commit', [False, True])
def test_publication_obeys_callers_commit_or_rollback(tmp_path, commit):
    documents = DocumentService(tmp_path)
    sessions = SessionStore(documents.database)
    artifacts = ArtifactStore(documents.database)
    sid = sessions.create()['session_id']
    snapshot = sessions.snapshot(sid, 'request', expected_data_version=0, expected_rule_version=0)
    with closing(sqlite3.connect(documents.database)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        artifacts.publish(sid, 'answer', snapshot['snapshot_id'], kind='answer',
                          payload={'text': 'Hello'}, db=db)
        sessions.append_message(sid, 'answer', 'assistant', 'Hello', db=db)
        # A separate reader must not see either half before the caller commits.
        with pytest.raises(DocumentError, match='Unknown session artifact'):
            artifacts.get(sid, 'answer')
        assert sessions.messages(sid) == []
        if commit:
            db.commit()
        else:
            db.rollback()
    if commit:
        assert artifacts.get(sid, 'answer')['payload'] == {'text': 'Hello'}
        assert sessions.messages(sid)[0]['content'] == 'Hello'
    else:
        with pytest.raises(DocumentError, match='Unknown session artifact'):
            artifacts.get(sid, 'answer')
        assert sessions.messages(sid) == []

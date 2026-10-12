from app.conversation_context import ConversationContext, InteractionSummary, SummaryItem
from app.documents import DocumentService
from app.sessions import SessionStore


def test_long_conversation_retains_user_decisions_across_restart(tmp_path):
    database = DocumentService(tmp_path).database
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    sessions.append_message(sid, 'q0', 'user', 'Keep product codes with leading zeros.')
    for index in range(1, 15):
        sessions.append_message(sid, f'q{index}', 'user', f'Question {index}')
        sessions.append_message(sid, f'a{index}', 'assistant', 'Old source fact is not context')
    context = ConversationContext(database)
    assembled = context.assemble(sid)
    assert [item['message_id'] for item in assembled['summary_candidates']] == [f'q{i}' for i in range(9)]
    assert len(assembled['recent_messages']) == 6
    summary = InteractionSummary(decisions=(SummaryItem(text='Preserve leading zeros in product codes.', message_ids=('q0',)),))
    context.save_summary(sid, 'run1', summary, through_message_id='q8')
    restored = ConversationContext(database).assemble(sid)
    assert restored['interaction_summary']['decisions'][0]['text'] == 'Preserve leading zeros in product codes.'
    assert restored['summary_candidates'] == []
    assert 'Old source fact' not in str(restored)



def test_summary_cannot_skip_backlog_and_replay_does_not_rewind(tmp_path):
    import pytest
    from app.documents import DocumentError
    database = DocumentService(tmp_path).database
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    for index in range(40):
        sessions.append_message(sid, f'q{index}', 'user', f'Request {index}')
    context = ConversationContext(database)
    assembled = context.assemble(sid)
    assert assembled['summary_pending_count'] == 34
    assert assembled['summary_through_message_id'] == 'q23'
    with pytest.raises(DocumentError, match='next pending'):
        context.save_summary(sid, 'skip', InteractionSummary(), through_message_id='q33')
    first = InteractionSummary(goals=(SummaryItem(text='Initial goal', message_ids=('q0',)),))
    context.save_summary(sid, 'first', first, through_message_id='q23')
    second = InteractionSummary(goals=(SummaryItem(text='Updated goal', message_ids=('q25',)),))
    context.save_summary(sid, 'second', second, through_message_id='q33')
    context.save_summary(sid, 'first', first, through_message_id='q23')
    assert context.assemble(sid)['interaction_summary']['goals'][0]['text'] == 'Updated goal'
    with pytest.raises(DocumentError, match='different contents'):
        context.save_summary(sid, 'first', second, through_message_id='q23')
    other = sessions.create()['session_id']
    assert context.assemble(other)['interaction_summary']['goals'] == []
    sessions.delete(sid)
    with pytest.raises(DocumentError, match='Session not found'):
        context.assemble(sid)


def test_summary_rejects_assistant_or_cross_session_fact_provenance(tmp_path):
    import pytest
    from app.documents import DocumentError
    database = DocumentService(tmp_path).database
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    for index in range(7):
        sessions.append_message(sid, f'q{index}', 'user', 'Question')
    sessions.append_message(sid, 'a0', 'assistant', 'Price is EUR 10')
    context = ConversationContext(database)
    invalid = InteractionSummary(decisions=(SummaryItem(text='Price is EUR 10', message_ids=('a0',)),))
    with pytest.raises(DocumentError, match='covered user messages'):
        context.save_summary(sid, 'bad', invalid, through_message_id='q0')
    assert context.assemble(sid)['summary_through_message_id'] == 'q0'


def test_artifact_context_rechecks_purpose_and_explicit_scope_without_copying_data(tmp_path):
    from test_sessions import ready_document
    database = DocumentService(tmp_path).database
    documents = DocumentService(tmp_path)
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    a, b = [ready_document(documents, sessions, sid) for _ in range(2)]
    sessions.set_rules(sid, None, {'price': (a,)}, expected_rule_version=0)
    snapshot = sessions.snapshot(sid, 'old', purpose='price', expected_data_version=2, expected_rule_version=1)
    context = ConversationContext(database)
    context.artifacts.publish(sid, 'table', snapshot['snapshot_id'], kind='table', payload={'rows': [['OLD_PRICE']]})
    first = context.assemble(sid)['artifact_references'][0]
    assert first['applicable'] is True
    assert 'OLD_PRICE' not in str(first)
    assert context.assemble(sid, explicit_sources=(b,))['artifact_references'][0]['applicable'] is False
    sessions.set_rules(sid, None, {'price': (b,)}, expected_rule_version=1)
    changed = context.assemble(sid)['artifact_references'][0]
    assert changed['source_available'] is True
    assert changed['applicable'] is False
    sessions.remove(sid, a, expected_data_version=2)
    assert context.assemble(sid, snapshot_id=snapshot['snapshot_id'])['artifact_references'][0]['source_available'] is False


def test_summary_joins_publication_transaction_and_rolls_back_on_failure(tmp_path):
    import pytest
    database = DocumentService(tmp_path).database
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    for index in range(7):
        sessions.append_message(sid, f'q{index}', 'user', 'Question')
    context = ConversationContext(database)
    summary = InteractionSummary(goals=(SummaryItem(text='User goal', message_ids=('q0',)),))
    with pytest.raises(RuntimeError):
        with sessions._db(write=True) as db:
            context.save_summary(sid, 'cancelled', summary, through_message_id='q0', db=db)
            raise RuntimeError('Publication cancelled')
    restored = ConversationContext(database).assemble(sid)
    assert restored['interaction_summary']['goals'] == []
    assert restored['summary_through_message_id'] == 'q0'


def test_dependency_artifact_rechecks_each_source_purpose(tmp_path):
    from contextlib import closing
    from io import BytesIO
    import sqlite3
    from app.agent_protocol import ScopeSnapshot, SourceScope
    from test_sessions import ready_document
    documents = DocumentService(tmp_path)
    sessions = SessionStore(documents.database)
    sid = sessions.create()['session_id']
    csv = ready_document(documents, sessions, sid)
    pdfs = []
    for name in ('old.pdf', 'new.pdf'):
        uploaded = documents.submit(name, BytesIO(b'%PDF-1.4\n'), session_id=sid)
        with closing(sqlite3.connect(documents.database)) as db, db:
            ref = sessions.register_upload(db, uploaded['document_id'], sid)
            db.execute("UPDATE documents SET status='ready' WHERE document_id=?", (uploaded['document_id'],))
            sessions.document_ready(db, uploaded['document_id'])
        pdfs.append(ref)
    sessions.set_rules(sid, None, {'price': (csv,), 'technical': (pdfs[0],)}, expected_rule_version=0)
    scope = ScopeSnapshot(documents=(csv, pdfs[0]), purpose='price',
                          dependency_scopes=(SourceScope(documents=(pdfs[0],), purpose='technical'),))
    # Trusted graph accepts the combined specialist scopes as its publication snapshot.
    snapshot = sessions.snapshot(sid, 'combined', explicit_sources=(csv, pdfs[0]), purpose='price',
                                 expected_data_version=3, expected_rule_version=1, dependency_scopes=scope.dependency_scopes)
    context = ConversationContext(documents.database)
    context.artifacts.publish(sid, 'dependent', snapshot['snapshot_id'], kind='table', payload={'rows': []}, scope=scope)
    assert context.assemble(sid)['artifact_references'][0]['applicable'] is True
    sessions.set_rules(sid, None, {'price': (csv,), 'technical': (pdfs[1],)}, expected_rule_version=1)
    assert context.assemble(sid)['artifact_references'][0]['applicable'] is False
    assert context.assemble(sid, explicit_sources=(csv, pdfs[0]))['artifact_references'][0]['applicable'] is True


def test_delayed_older_summary_does_not_block_publication_or_replace_newer_memory(tmp_path):
    import pytest
    from app.documents import DocumentError
    database = DocumentService(tmp_path).database
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    for index in range(7):
        sessions.append_message(sid, f'q{index}', 'user', f'Request {index}')
    context = ConversationContext(database)
    delayed = InteractionSummary(goals=(SummaryItem(text='Original goal', message_ids=('q0',)),))
    assert context.assemble(sid)['summary_through_message_id'] == 'q0'
    sessions.append_message(sid, 'q7', 'user', 'Use the revised goal.')
    newer = InteractionSummary(goals=(SummaryItem(text='Revised goal', message_ids=('q1',)),))
    context.save_summary(sid, 'newer-run', newer, through_message_id='q1')
    context.save_summary(sid, 'delayed-run', delayed, through_message_id='q0')
    assert context.assemble(sid)['interaction_summary']['goals'][0]['text'] == 'Revised goal'
    context.save_summary(sid, 'delayed-run', delayed, through_message_id='q0')
    with pytest.raises(DocumentError, match='different contents'):
        context.save_summary(sid, 'delayed-run', newer, through_message_id='q0')
    invalid = InteractionSummary(goals=(SummaryItem(text='Invented goal', message_ids=('missing',)),))
    with pytest.raises(DocumentError, match='covered user messages'):
        context.save_summary(sid, 'invalid-delayed', invalid, through_message_id='q0')


def test_independent_csv_table_remains_applicable_in_mixed_material_session(tmp_path):
    from test_sessions import ready_document
    from test_conversation_runs import ready_pdf, setup
    runs, sid, _, bindings = setup(tmp_path, [])
    csv = ready_document(bindings.documents, runs.sessions, sid)
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    snapshot = runs.sessions.snapshot(sid, 'csv-only', explicit_sources=(csv,), expected_data_version=2, expected_rule_version=0)
    runs.artifacts.publish(sid, 'csv-result', snapshot['snapshot_id'], kind='table', payload={'rows': [['00123']]})
    context = ConversationContext(runs.database)
    assert context.assemble(sid)['artifact_references'][0]['applicable'] is True
    ready_document(bindings.documents, runs.sessions, sid)
    assert context.assemble(sid)['artifact_references'][0]['applicable'] is False


def test_long_messages_are_compacted_in_complete_bounded_batches(tmp_path):
    database = DocumentService(tmp_path).database
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    for index in range(12):
        sessions.append_message(sid, f'q{index}', 'user', str(index).zfill(2) + 'x' * 7998)
    context = ConversationContext(database)
    assembled = context.assemble(sid)
    assert [message['message_id'] for message in assembled['summary_candidates']] == ['q0', 'q1', 'q2']
    assert assembled['summary_through_message_id'] == 'q2'
    assert assembled['summary_pending_count'] == 6
    assert sum(len(message['content']) for message in assembled['summary_candidates']) == 24000
    assert sum(len(message['content']) for message in assembled['recent_messages']) == 48000
    context.save_summary(sid, 'batch1', InteractionSummary(goals=(SummaryItem(
        text='Ordinary conversation with no new outstanding request.', message_ids=('q0', 'q1', 'q2')),)), through_message_id='q2')
    next_batch = context.assemble(sid)
    assert [message['message_id'] for message in next_batch['summary_candidates']] == ['q3', 'q4', 'q5']
    assert all(len(message['content']) == 8000 for message in next_batch['summary_candidates'])


def test_empty_summary_never_discards_pending_messages_or_existing_memory(tmp_path):
    import pytest
    from app.documents import DocumentError
    database = DocumentService(tmp_path).database
    sessions = SessionStore(database)
    sid = sessions.create()['session_id']
    for index in range(7):
        sessions.append_message(sid, f'q{index}', 'user', 'Project Blue Bridge' if index == 0 else 'Continue')
    context = ConversationContext(database)
    with pytest.raises(DocumentError) as empty:
        context.save_summary(sid, 'empty-first', InteractionSummary(), through_message_id='q0')
    assert empty.value.code == 'invalid_summary_empty'
    assert context.assemble(sid)['summary_through_message_id'] == 'q0'
    summary = InteractionSummary(goals=(SummaryItem(text='Project Blue Bridge', message_ids=('q0',)),))
    context.save_summary(sid, 'good', summary, through_message_id='q0')
    sessions.append_message(sid, 'q7', 'user', 'Continue')
    with pytest.raises(DocumentError) as cleared:
        context.save_summary(sid, 'empty-later', InteractionSummary(), through_message_id='q1')
    assert cleared.value.code == 'invalid_summary_empty'
    restored = ConversationContext(database).assemble(sid)
    assert restored['summary_through_message_id'] == 'q1'
    assert restored['interaction_summary']['goals'][0]['text'] == 'Project Blue Bridge'

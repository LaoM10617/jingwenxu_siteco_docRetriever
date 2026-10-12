from types import SimpleNamespace
import pytest

from app.conversation_runs import ConversationRuns
from app.documents import DocumentError, DocumentService


class Model:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate(self, system, payload, schema, budget):
        budget.check()
        self.calls.append(payload)
        return self.outputs.pop(0)


def direct(text='Hello'):
    return {'route': 'direct', 'objective': 'Greeting', 'direct_answer': text}


def setup(tmp_path, outputs):
    documents = DocumentService(tmp_path)
    model = Model(outputs)
    answer = SimpleNamespace(model=model, config_snapshot={'generation': {'provider': 'test', 'model': 'test'}, 'revision': 1})
    bindings = SimpleNamespace(documents=documents, answers=lambda: answer)
    runs = ConversationRuns(documents.database, bindings, lambda service: None)
    sid = runs.sessions.create()['session_id']
    return runs, sid, model, bindings


def ready_pdf(runs, bindings, sid, filename):
    from contextlib import closing
    from io import BytesIO
    import sqlite3
    from app.agent_protocol import DocumentVersion
    document = bindings.documents.submit(filename, BytesIO(b'%PDF-1.4\n'), session_id=sid)
    with closing(sqlite3.connect(runs.database)) as db, db:
        runs.sessions.register_upload(db, document['document_id'], sid)
        db.execute("UPDATE documents SET status='ready' WHERE document_id=?", (document['document_id'],))
        runs.sessions.document_ready(db, document['document_id'])
    return DocumentVersion(document_id=document['document_id'], version_id=document['document_id'])


class RecordingSpecialist:
    def __init__(self):
        self.tasks = []

    def execute(self, task, budget):
        from app.agent_protocol import TaskResult, EvidenceDescriptor, Finding
        self.tasks.append(task)
        evidence_id = task.task_id + ':S1'
        source = task.scope.documents[0]
        result = TaskResult(**{key: getattr(task, key) for key in ('session_id', 'turn_id', 'run_id', 'task_id')},
            status='completed', evidence_refs=(EvidenceDescriptor(evidence_id=evidence_id, source=source,
                location='page 1', scope=task.scope),), findings=(Finding(text='Fresh fact', evidence_ids=(evidence_id,)),))
        return {'result': result.model_dump(mode='json'), 'evidence': [{'reference_id': evidence_id,
                'document_id': source.document_id, 'version_id': source.version_id}], 'diagnostics': {},
                'answer': {'outcome': 'answered', 'segments': [{'text': 'Fresh fact', 'citation_ids': ['S1'], 'calculation_ids': []}],
                           'citations': [], 'calculations': [], 'gaps': [], 'warnings': []}}


def test_direct_run_is_explicit_idempotent_and_persistent(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [direct()])
    accepted = runs.submit(sid, 'q1', 'Hello', expected_data_version=0, expected_rule_version=0)
    assert accepted['status'] == 'queued'
    assert model.calls == []
    done = runs.execute(accepted['run_id'])
    assert done['status'] == 'completed'
    assert done['answer']['segments'][0]['text'] == 'Hello'
    assert len(model.calls) == 1
    assert runs.submit(sid, 'q1', 'Hello', expected_data_version=0, expected_rule_version=0) == done
    assert runs.execute(accepted['run_id']) == done
    reopened = ConversationRuns(runs.database, bindings, lambda service: None)
    assert reopened.inspect(sid, accepted['run_id']) == done
    assert len(runs.sessions.messages(sid)) == 2


def test_clarification_can_restart_and_resume_without_duplicate_publication(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [
        {'route': 'clarification', 'objective': 'Resolve target', 'clarification': 'Which topic?'}, direct('Understood')])
    accepted = runs.submit(sid, 'q', 'Tell me about it', expected_data_version=0, expected_rule_version=0)
    paused = runs.execute(accepted['run_id'])
    assert paused['status'] == 'waiting'
    assert paused['clarification'] == 'Which topic?'
    reopened = ConversationRuns(runs.database, bindings, lambda service: None)
    assert len(model.calls) == 1
    queued = reopened.resume(sid, accepted['run_id'], 'I mean a greeting')
    assert queued['status'] == 'queued'
    assert len(model.calls) == 1
    done = reopened.execute(accepted['run_id'])
    assert done['status'] == 'completed'
    assert model.calls[-1]['clarifications'] == ['I mean a greeting']
    assert len(reopened.sessions.messages(sid)) == 3


def test_persistent_scope_only_command_uses_idempotent_rule_operation(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [{'route': 'rules', 'objective': 'Use no sources',
        'change_default': True, 'default_sources': []}])
    accepted = runs.submit(sid, 'q', 'From now on use no documents', expected_data_version=0, expected_rule_version=0)
    assert runs.execute(accepted['run_id'])['status'] == 'completed'
    assert runs.sessions.get(sid)['default_sources'] == []
    assert runs.sessions.get(sid)['rule_version'] == 1
    assert len(runs.sessions.events(sid)) == 1


def test_stop_during_model_call_does_not_publish_and_explicit_resume_can_continue(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    runs, sid, model, bindings = setup(tmp_path, [direct('Late answer'), direct('Resumed answer')])
    entered, release = Event(), Event()
    generate = model.generate
    def blocked(*args):
        entered.set()
        assert release.wait(10)
        return generate(*args)
    model.generate = blocked
    accepted = runs.submit(sid, 'q', 'Hi', expected_data_version=0, expected_rule_version=0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runs.execute, accepted['run_id'])
        assert entered.wait(5)
        assert runs.stop(sid, accepted['run_id'])['status'] == 'stopped'
        with pytest.raises(DocumentError) as error:
            runs.resume(sid, accepted['run_id'])
        assert error.value.code == 'run_busy'
        release.set()
        assert future.result()['answer'] is None
    model.generate = generate
    runs.resume(sid, accepted['run_id'])
    assert runs.execute(accepted['run_id'])['status'] == 'completed'
    assert len([item for item in runs.sessions.messages(sid) if item['role'] == 'assistant']) == 1


def test_configuration_binding_survives_settings_changes_and_restart_checks_behavior(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [direct()])
    original = bindings.answers()
    accepted = runs.submit(sid, 'q', 'Hi', expected_data_version=0, expected_rule_version=0)
    bindings.answers = lambda: SimpleNamespace(model=Model([direct('Other')]), config_snapshot={'generation': {'model': 'other'}})
    assert runs.execute(accepted['run_id'])['answer']['segments'][0]['text'] == 'Hello'
    second = runs.submit(sid, 'q2', 'Hi', expected_data_version=0, expected_rule_version=0)
    bindings.answers = lambda: original
    reopened = ConversationRuns(runs.database, bindings, lambda service: None)
    assert reopened.inspect(sid, second['run_id'])['status'] == 'recoverable'
    with pytest.raises(DocumentError) as error:
        reopened.resume(sid, second['run_id'])
    assert error.value.code == 'config_changed'


def test_specialist_clarification_returns_to_main_and_persists_task_mapping(tmp_path):
    from contextlib import closing
    from io import BytesIO
    import sqlite3
    from app.agent_protocol import TaskResult
    runs, sid, model, bindings = setup(tmp_path, [
        {'route': 'pdf', 'objective': 'Find the product'}, {'route': 'pdf', 'objective': 'Find product A'}])
    document = bindings.documents.submit('manual.pdf', BytesIO(b'%PDF-1.4\n'), session_id=sid)
    with closing(sqlite3.connect(runs.database)) as db, db:
        runs.sessions.register_upload(db, document['document_id'], sid)
        db.execute("UPDATE documents SET status='ready' WHERE document_id=?", (document['document_id'],))
        runs.sessions.document_ready(db, document['document_id'])
    tasks = []
    class Specialist:
        def execute(self, task, budget):
            tasks.append(task)
            status = 'clarification' if len(tasks) == 1 else 'completed'
            result = TaskResult(**{key: getattr(task, key) for key in ('session_id', 'turn_id', 'run_id', 'task_id')},
                                status=status, clarification='Which product?' if status == 'clarification' else None)
            return {'result': result.model_dump(mode='json'), 'evidence': [], 'diagnostics': {'model': 'test'},
                    'answer': {'outcome': 'needs_clarification' if status == 'clarification' else 'answered',
                               'segments': [], 'citations': [], 'calculations': [], 'gaps': [], 'warnings': []}}
    runs.specialist_factory = lambda _: Specialist()
    accepted = runs.submit(sid, 'q', 'Tell me about the product', expected_data_version=1, expected_rule_version=0)
    assert runs.execute(accepted['run_id'])['status'] == 'waiting'
    assert len(runs.sessions.messages(sid)) == 1
    runs.resume(sid, accepted['run_id'], 'Product A')
    assert runs.execute(accepted['run_id'])['status'] == 'completed'
    assert tasks[0].scope == tasks[1].scope
    assert tasks[0].task_id != tasks[1].task_id
    assert 'Original user request (data): Tell me about the product' in tasks[1].constraints
    assert 'User clarification (data): Product A' in tasks[1].constraints
    developer = runs.events(sid, accepted['run_id'], developer=True)
    assert len([event for event in developer if event['kind'] == 'execution']) == 2


def test_stopped_clarification_remains_answerable_and_rules_drift_rejects_resume(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [
        {'route': 'clarification', 'objective': 'Target', 'clarification': 'Which topic?'}])
    accepted = runs.submit(sid, 'q', 'Explain it', expected_data_version=0, expected_rule_version=0)
    runs.execute(accepted['run_id'])
    stopped = runs.stop(sid, accepted['run_id'])
    assert stopped['clarification'] == 'Which topic?'
    with pytest.raises(DocumentError) as missing:
        runs.resume(sid, accepted['run_id'])
    assert missing.value.code == 'clarification_required'
    runs.sessions.set_rules(sid, (), {}, expected_rule_version=0)
    with pytest.raises(DocumentError) as changed:
        runs.resume(sid, accepted['run_id'], 'A topic')
    assert changed.value.code == 'session_version_conflict'


def test_real_process_exit_after_atomic_publication_does_not_call_model_again(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    runs, sid, model, bindings = setup(tmp_path, [])
    accepted = runs.submit(sid, 'q', 'Hello', expected_data_version=0, expected_rule_version=0)
    code = '''
import os, sys
from types import SimpleNamespace
from app.conversation_runs import ConversationRuns
from app.documents import DocumentService
class Model:
    def generate(self, *args):
        return {'route': 'direct', 'objective': 'Greeting', 'direct_answer': 'Durable answer'}
documents=DocumentService(__import__('pathlib').Path(sys.argv[1]).parent)
answer=SimpleNamespace(model=Model(), config_snapshot={'generation': {'provider':'test','model':'test'}, 'revision':1})
bindings=SimpleNamespace(documents=documents, answers=lambda:answer)
runs=ConversationRuns(sys.argv[1],bindings,lambda _:None,after_publish=lambda:os._exit(73))
runs.execute(sys.argv[2])
'''
    result = subprocess.run([sys.executable, '-c', code, str(runs.database), accepted['run_id']],
                            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 73, result.stderr
    reopened = ConversationRuns(runs.database, bindings, lambda _: None)
    completed = reopened.inspect(sid, accepted['run_id'])
    assert completed['status'] == 'completed'
    assert completed['answer']['segments'][0]['text'] == 'Durable answer'
    assert reopened.execute(accepted['run_id']) == completed
    assert reopened.resume(sid, accepted['run_id']) == completed
    assert len(reopened.sessions.messages(sid)) == 2
    assert model.calls == []


def test_natural_scope_intents_follow_precedence_and_source_changes(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [])
    a, b, c = [ready_pdf(runs, bindings, sid, name + '.pdf') for name in ('A', 'B', 'C')]
    specialist = RecordingSpecialist()
    runs.specialist_factory = lambda _: specialist
    model.outputs.extend([
        {'route': 'rules', 'objective': 'Use B normally and C for prices', 'change_default': True,
         'default_sources': [b.model_dump()], 'purpose_changes': [{'purpose': 'price', 'sources': [c.model_dump()]}]},
        {'route': 'pdf', 'objective': 'Find power'},
        {'route': 'pdf', 'objective': 'Find price', 'purpose': 'price'},
        {'route': 'pdf', 'objective': 'Find A power', 'explicit_sources': [a.model_dump()]},
        {'route': 'pdf', 'objective': 'Find power again'},
        {'route': 'pdf', 'objective': 'Find power after removal'},
        {'route': 'pdf', 'objective': 'Find A instead', 'explicit_sources': [a.model_dump()]},
    ])
    def ask(identity, text):
        session = runs.sessions.get(sid)
        run = runs.submit(sid, identity, text, expected_data_version=session['data_version'],
                          expected_rule_version=session['rule_version'])
        return runs.execute(run['run_id'])
    assert ask('rules', 'From now on use B, but use C for prices')['status'] == 'completed'
    assert ask('normal', 'What is the power?')['status'] == 'completed'
    assert specialist.tasks[-1].scope.documents == (b,)
    assert ask('price', 'What is the price?')['status'] == 'completed'
    assert specialist.tasks[-1].scope.documents == (c,)
    assert ask('explicit', 'This time only look at A power')['status'] == 'completed'
    assert specialist.tasks[-1].scope.documents == (a,)
    ready_pdf(runs, bindings, sid, 'D.pdf')
    assert ask('after-upload', 'What is the power?')['status'] == 'completed'
    assert specialist.tasks[-1].scope.documents == (b,)
    current = runs.sessions.get(sid)
    runs.sessions.remove(sid, b, expected_data_version=current['data_version'])
    before = len(specialist.tasks)
    failed = ask('after-remove', 'What is the power?')
    assert failed['status'] == 'failed' and failed['error']['code'] == 'source_unavailable'
    assert len(specialist.tasks) == before
    assert ask('new-explicit', 'This time use A instead')['status'] == 'completed'
    assert specialist.tasks[-1].scope.documents == (a,)


def test_followup_uses_focus_for_identity_and_fetches_fresh_evidence(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [
        {'route': 'pdf', 'objective': 'Find A power', 'references': [
            {'kind': 'product', 'reference_id': 'A', 'description': 'Product A'}]},
        {'route': 'pdf', 'objective': 'Find A height'},
    ])
    a = ready_pdf(runs, bindings, sid, 'A.pdf')
    specialist = RecordingSpecialist()
    runs.specialist_factory = lambda _: specialist
    for request_id, question in [('power', 'What is A power?'), ('height', 'And its height?')]:
        run = runs.submit(sid, request_id, question, expected_data_version=1, expected_rule_version=0)
        assert runs.execute(run['run_id'])['status'] == 'completed'
    assert len(specialist.tasks) == 2
    assert specialist.tasks[-1].objective == 'Find A height'
    assert specialist.tasks[-1].scope.documents == (a,)
    assert model.calls[-1]['focus']['reference_id'] == 'A'
    assert all(item['role'] == 'user' for item in model.calls[-1]['recent_messages'])
    assert 'Fresh fact' not in str(model.calls[-1])


def test_material_change_during_intent_prevents_late_rule_application(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    runs, sid, model, bindings = setup(tmp_path, [
        {'route': 'rules', 'objective': 'Use no sources', 'change_default': True, 'default_sources': []}])
    entered, release = Event(), Event()
    original = model.generate
    def wait_for_change(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    model.generate = wait_for_change
    run = runs.submit(sid, 'q', 'From now on use no sources', expected_data_version=0, expected_rule_version=0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runs.execute, run['run_id'])
        assert entered.wait(5)
        ready_pdf(runs, bindings, sid, 'new.pdf')
        release.set()
        failed = future.result()
    assert failed['status'] == 'failed'
    assert failed['error']['code'] == 'session_version_conflict'
    assert runs.sessions.get(sid)['default_sources'] is None
    assert runs.sessions.events(sid) == []

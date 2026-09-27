"""Temporary conversational references through the task HTTP boundary."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for
from test_multi_document_tasks import ScopeModel, TaskGateway, upload, finish
from test_question_tasks import csv_bytes
from test_csv_parsing import row
from test_csv_lifecycle import service


class MemoryModel(ScopeModel):
    def generate(self, system, payload, schema, budget):
        if payload['phase'] == 'resolve_references':
            self.payloads.append(deepcopy(payload))
            return {'references': [{'question_id': payload['history'][-1]['question_id'], 'term': '001'}],
                    'needs_clarification': False}
        return super().generate(system, payload, schema, budget)


def test_followup_requeries_current_scope_and_survives_restart(tmp_path):
    settings = settings_for(tmp_path)
    model = MemoryModel()
    with TestClient(create_app(settings, processor=DocumentProcessor(TaskGateway()), model=model)) as client:
        old = upload(client, 'old.csv', csv_bytes([row('001', '12,50')]))
        new = upload(client, 'new.csv', csv_bytes([row('001', '25,00')]))
        first = finish(client, {'conversation_id': 'a', 'request_id': 'one', 'question': 'Price of 001?',
                                'document_ids': [old]})
    with TestClient(create_app(settings, processor=DocumentProcessor(TaskGateway()), model=model)) as client:
        body = {'conversation_id': 'a', 'request_id': 'two', 'question': 'And its price here?',
                'document_ids': [new], 'previous_question_id': first['question_id']}
        second = finish(client, body)
        assert second['previous_question_id'] == first['question_id']
        assert second['conversation_expires_at'] == first['conversation_expires_at']
        assert {s['document_id'] for s in second['answer']['citations']} == {new}
        assert '25,00' in str(second['answer']) and '12,50' not in str(second['answer'])
        count = len(model.payloads)
        assert client.post('/api/questions', json=body).json()['question_id'] == second['question_id']
        assert len(model.payloads) == count
        resolve = next(p for p in model.payloads if p['phase'] == 'resolve_references')
        assert resolve['history'][0]['question'] == 'Price of 001?'
        assert second['answer']['memory']['references'][0]['term'] == '001'


@pytest.mark.parametrize('term,ambiguous', [('999', False), ('00', False), ('001', True)])
def test_unverified_or_ambiguous_reference_clarifies_without_lookup(tmp_path, term, ambiguous):
    class Uncertain(MemoryModel):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'resolve_references':
                result['references'][0]['term'] = term
                result['needs_clarification'] = ambiguous
            return result
    model = Uncertain()
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=model)) as client:
        doc = upload(client, 'a.csv', csv_bytes([row('001')]))
        first = finish(client, {'conversation_id':'a', 'request_id':'one', 'question':'001?', 'document_ids':[doc]})
        count = len(model.payloads)
        second = finish(client, {'conversation_id':'a', 'request_id':'two', 'question':'Its price?',
            'document_ids':[doc], 'previous_question_id':first['question_id']})
        assert second['answer']['outcome'] == 'needs_clarification'
        assert second['answer']['tool_results'] == second['answer']['citations'] == []
        assert len(model.payloads) == count + 1


def test_history_window_is_six_whole_turns_and_fixed_expiry(tmp_path, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr('app.question_tasks.time.time', lambda:clock[0])
    model = MemoryModel()
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=model)) as client:
        doc = upload(client, 'a.csv', csv_bytes([row('001')]))
        base = {'conversation_id':'a', 'question':'001?', 'document_ids':[doc]}
        tasks = []
        for i in range(8):
            tasks.append(finish(client, {**base, 'request_id':str(i),
                **({'previous_question_id':tasks[-1]['question_id']} if tasks else {})}))
            clock[0] += 100
        last = [p for p in model.payloads if p['phase'] == 'resolve_references'][-1]
        assert [t['question_id'] for t in last['history']] == [t['question_id'] for t in tasks[1:7]]
        assert sum(len(json.dumps(t,ensure_ascii=False)) for t in last['history']) <= 12000
        assert len({t['conversation_expires_at'] for t in tasks}) == 1
        count = len(model.payloads)
        clock[0] = 1_800_000_000.0 + 86401
        assert client.get('/api/questions/'+tasks[-1]['question_id'],params={'conversation_id':'a'}).status_code == 404
        response = client.post('/api/questions',json={**base,'request_id':'expired',
            'previous_question_id':tasks[-1]['question_id']})
        assert response.status_code == 409
        assert response.json()['error']['code'] in ('memory_expired','memory_unavailable')
        assert len(model.payloads) == count
        assert client.get('/api/documents/'+doc).json()['status'] == 'ready'


def test_parent_must_be_same_conversation_completed_and_part_of_idempotent_body(tmp_path):
    model = MemoryModel()
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=model)) as client:
        doc = upload(client, 'a.csv', csv_bytes([row('001')]))
        base = {'conversation_id':'a', 'question':'001?', 'document_ids':[doc]}
        first = finish(client,{**base,'request_id':'one'})
        count = len(model.payloads)
        response = client.post('/api/questions',json={**base,'conversation_id':'other','request_id':'two',
            'previous_question_id':first['question_id']})
        assert response.status_code == 409
        assert len(model.payloads) == count
        assert client.post('/api/questions',json={**base,'request_id':'one',
            'previous_question_id':first['question_id']}).status_code == 409

@pytest.mark.parametrize('mode', ['large-turn', 'bad-json', 'provider-failure', 'foreign-reference'])
def test_history_limit_and_resolver_failures_are_explicit(tmp_path, mode):
    from app.documents import DocumentError
    from test_failure_recovery import terminal
    class Controlled(MemoryModel):
        def generate(self, system, payload, schema, budget):
            if payload['phase'] == 'resolve_references':
                if mode == 'bad-json':
                    return {'references':'not a list', 'needs_clarification':False}
                if mode == 'provider-failure':
                    raise DocumentError('generation_provider_unavailable','Provider unavailable.',502,True)
            result = super().generate(system,payload,schema,budget)
            if payload['phase'] == 'answer' and mode == 'large-turn':
                result['segments'] = [{'text':'x'*4000,'citation_ids':['S1'],'calculation_ids':[]} for _ in range(4)]
            if payload['phase'] == 'resolve_references' and mode == 'foreign-reference':
                result['references'][0]['question_id'] = 'outside-conversation'
            return result
    model = Controlled()
    with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=model)) as client:
        doc = upload(client,'a.csv',csv_bytes([row('001')]))
        base = {'conversation_id':'a','question':'001?','document_ids':[doc]}
        first = finish(client,{**base,'request_id':'one'})
        submitted = client.post('/api/questions',json={**base,'request_id':'two','question':'Its price?',
            'previous_question_id':first['question_id']})
        assert submitted.status_code == 202
        task = terminal(client,submitted.json()['question_id'])
        if mode in ('bad-json','provider-failure'):
            assert task['status'] == 'failed' and task['answer'] is None
            assert task['error']['code'] == ('generation_invalid_output' if mode == 'bad-json' else 'generation_provider_unavailable')
        else:
            assert task['answer']['outcome'] == 'needs_clarification'
            assert task['answer']['citations'] == []
        if mode == 'large-turn':
            assert not any(p['phase']=='resolve_references' for p in model.payloads)


def test_resolver_uses_original_deadline_and_late_result_cannot_publish(tmp_path, service):
    import time
    from threading import Event
    from app.answers import AnswerService
    from app.questions import QuestionTools
    from app.question_tasks import QuestionTasks
    from test_csv_lifecycle import publish
    entered, release = Event(), Event()
    clock = [0.0]
    class Late(MemoryModel):
        def generate(self,system,payload,schema,budget):
            if payload['phase']=='resolve_references':
                entered.set()
                assert release.wait(10)
            return super().generate(system,payload,schema,budget)
    model = Late()
    doc = publish(service,[row('001')])
    tasks = QuestionTasks(tmp_path/'memory-tasks.sqlite3',AnswerService(QuestionTools(service,None),model),now=lambda:clock[0])
    base = {'conversation_id':'a','question':'001?','document_ids':[doc]}
    def done(identity):
        for _ in range(250):
            task = tasks.get(identity,'a')
            if task['status'] in ('failed','completed'):
                return task
            time.sleep(.02)
        pytest.fail('Task did not complete')
    try:
        first = done(tasks.submit({**base,'request_id':'one'})['question_id'])
        second = tasks.submit({**base,'request_id':'two','question':'Its price?',
            'previous_question_id':first['question_id']})
        assert entered.wait(2)
        assert tasks.get(second['question_id'],'a')['stage'] == 'resolving_references'
        clock[0] = 241
        frozen = tasks.get(second['question_id'],'a')
        assert frozen['error']['code'] == 'question_timeout' and frozen['answer'] is None
        release.set()
        sentinel = done(tasks.submit({**base,'request_id':'new'})['question_id'])
        assert sentinel['status'] == 'completed'
        assert tasks.get(second['question_id'],'a') == frozen
    finally:
        release.set()
        tasks.stop()



def test_pdf_followup_retrieves_again_without_old_source_leakage(tmp_path):
    from test_parsing import pdf_file
    class PdfMemory(MemoryModel):
        def generate(self,system,payload,schema,budget):
            result = super().generate(system,payload,schema,budget)
            if payload['phase']=='resolve_references':
                result['references'][0]['term']='AB-123'
            return result
    model = PdfMemory()
    with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(TaskGateway()),model=model)) as client:
        old = upload(client,'old.pdf',pdf_file(tmp_path,['AB-123 power: 20 W']).read_bytes())
        new = upload(client,'new.pdf',pdf_file(tmp_path,['AB-123 power: 30 W']).read_bytes())
        first = finish(client,{'conversation_id':'a','request_id':'one','question':'AB-123 power?', 'document_ids':[old]})
        second = finish(client,{'conversation_id':'a','request_id':'two','question':'And its power here?',
            'document_ids':[new],'previous_question_id':first['question_id']})
        assert second['answer']['outcome']=='answered'
        assert {s['document_id'] for s in second['answer']['citations']}=={new}
        assert '30 W' in str(second['answer']) and '20 W' not in str(second['answer'])
        assert 'AB-123' in second['answer']['memory']['resolved_question']


def test_running_and_failed_parent_are_rejected_before_resolution(tmp_path):
    from threading import Event
    from app.documents import DocumentError
    from test_failure_recovery import terminal
    entered, release = Event(), Event()
    class Blocked(MemoryModel):
        def generate(self,*args):
            entered.set()
            assert release.wait(10)
            raise DocumentError('generation_provider_unavailable','Unavailable.',502,True)
    try:
        with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=Blocked())) as client:
            doc=upload(client,'a.csv',csv_bytes([row('001')]))
            base={'conversation_id':'a','question':'001?','document_ids':[doc]}
            first=client.post('/api/questions',json={**base,'request_id':'one'}).json()
            assert entered.wait(2)
            body={**base,'request_id':'two','previous_question_id':first['question_id']}
            assert client.post('/api/questions',json=body).json()['error']['code']=='memory_not_completed'
            release.set()
            assert terminal(client,first['question_id'])['status']=='failed'
            assert client.post('/api/questions',json=body).json()['error']['code']=='memory_not_completed'
    finally:
        release.set()


def test_upgrade_old_task_schema_keeps_completed_questions_readable(tmp_path):
    import sqlite3
    import time
    # Offline legacy-format fixture, before the backend starts; assertions remain HTTP-only.
    request={'conversation_id':'legacy','question':'001?','document_ids':['old-doc']}
    answer={'outcome':'needs_clarification','segments':[],'citations':[],'gaps':[], 'tool_results':[]}
    with sqlite3.connect(tmp_path/'app.sqlite3') as db:
        db.execute('''CREATE TABLE question_tasks (
            id TEXT PRIMARY KEY, conversation TEXT NOT NULL, request_id TEXT NOT NULL,
            request TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
            created REAL NOT NULL, deadline REAL NOT NULL, answer TEXT, error TEXT,
            UNIQUE(conversation,request_id))''')
        created=time.time()-60
        db.execute('INSERT INTO question_tasks VALUES (?,?,?,?,?,?,?,?,?,?)',
            ('legacy-q','legacy','r',json.dumps(request,sort_keys=True),'completed','completed',
             created,created+240,json.dumps(answer),None))
    with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=MemoryModel())) as client:
        result=client.get('/api/questions/legacy-q',params={'conversation_id':'legacy'})
        assert result.status_code==200
        assert result.json()['answer']==answer
        assert result.json()['conversation_expires_at']==created+86400
        replay=client.post('/api/questions',json={**request,'request_id':'r'})
        assert replay.status_code==202 and replay.json()['question_id']=='legacy-q'


def test_resolved_subject_is_explicit_at_planning_and_answer_provider_boundaries(tmp_path):
    model=MemoryModel()
    with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=model)) as client:
        doc=upload(client,'a.csv',csv_bytes([row('001')]))
        base={'conversation_id':'a','document_ids':[doc]}
        first=finish(client,{**base,'request_id':'one','question':'Price 001?'})
        before=len(model.payloads)
        second=finish(client,{**base,'request_id':'two','question':'And its date?',
            'previous_question_id':first['question_id']})
        calls=model.payloads[before:]
        plan=next(p for p in calls if p['phase']=='plan')
        answer=next(p for p in calls if p['phase']=='answer')
        assert plan.get('resolved_subjects')==['001']
        assert answer['bundle'].get('resolved_subjects')==['001']
        assert 'history' not in answer['bundle']
        assert second['answer']['memory']['references'][0]['term']=='001'

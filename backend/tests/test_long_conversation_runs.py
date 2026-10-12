"""Long conversation behavior through the durable run interface."""
from app.conversation_runs import ConversationRuns
from test_conversation_runs import setup, direct


def test_long_conversation_compresses_once_per_turn_and_survives_restart(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [])
    calls = []

    def generate(system, payload, schema, budget):
        budget.check()
        calls.append(payload)
        result = direct('Understood')
        if payload.get('summary_candidates'):
            previous = payload['interaction_summary']
            if previous['goals']:
                result['interaction_summary'] = previous
            else:
                first = payload['summary_candidates'][0]
                result['interaction_summary'] = {'goals': [{'text': 'Compare product 00123; preserve leading zeros and EUR.',
                                                            'message_ids': [first['message_id']]}]}
        return result

    model.generate = generate
    for index in range(9):
        question = 'Compare product 00123; preserve leading zeros and EUR.' if index == 0 else f'Follow-up {index}'
        accepted = runs.submit(sid, f'q{index}', question, expected_data_version=0, expected_rule_version=0)
        assert runs.execute(accepted['run_id'])['status'] == 'completed'
    assert len(calls) == 9
    assert any(call.get('summary_candidates') for call in calls)
    reopened = ConversationRuns(runs.database, bindings, lambda _: None)
    assert len(calls) == 9
    accepted = reopened.submit(sid, 'q9', 'Continue with the original product and currency.',
                               expected_data_version=0, expected_rule_version=0)
    assert reopened.execute(accepted['run_id'])['status'] == 'completed'
    assert len(calls) == 10
    final = calls[-1]
    assert len(final['recent_messages']) == 6
    assert all(item['content'] != 'Compare product 00123; preserve leading zeros and EUR.' for item in final['recent_messages'])
    assert final['interaction_summary']['goals'][0]['text'] == 'Compare product 00123; preserve leading zeros and EUR.'
    assert reopened.execute(accepted['run_id'])['status'] == 'completed'
    assert len(calls) == 10


def test_clarification_reply_is_persisted_and_can_enter_later_summary(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [
        {'route': 'clarification', 'objective': 'Resolve unit', 'clarification': 'Which currency?'}, direct()])
    accepted = runs.submit(sid, 'initial', 'Compare those products.', expected_data_version=0, expected_rule_version=0)
    assert runs.execute(accepted['run_id'])['status'] == 'waiting'
    reopened = ConversationRuns(runs.database, bindings, lambda _: None)
    reopened.resume(sid, accepted['run_id'], 'Use EUR and preserve product code 00123.')
    assert reopened.execute(accepted['run_id'])['status'] == 'completed'
    user_messages = [message for message in reopened.sessions.messages(sid) if message['role'] == 'user']
    assert [message['content'] for message in user_messages] == ['Compare those products.', 'Use EUR and preserve product code 00123.']
    calls = []

    def generate(system, payload, schema, budget):
        calls.append(payload)
        return direct()

    model.generate = generate
    for index in range(7):
        followup = reopened.submit(sid, f'next{index}', 'Continue.', expected_data_version=0, expected_rule_version=0)
        assert reopened.execute(followup['run_id'])['status'] == 'completed'
    assert any(item['content'] == 'Use EUR and preserve product code 00123.'
               for call in calls for item in call['summary_candidates'])


def test_intent_sees_artifact_inapplicability_after_price_scope_switch(tmp_path):
    from test_sessions import ready_document
    runs, sid, model, bindings = setup(tmp_path, [direct()])
    first, second = [ready_document(bindings.documents, runs.sessions, sid) for _ in range(2)]
    runs.sessions.set_rules(sid, None, {'price': (first,)}, expected_rule_version=0)
    snapshot = runs.sessions.snapshot(sid, 'past', purpose='price', expected_data_version=2, expected_rule_version=1)
    runs.artifacts.publish(sid, 'past-table', snapshot['snapshot_id'], kind='table', payload={'rows': [['old price']]})
    runs.sessions.set_rules(sid, None, {'price': (second,)}, expected_rule_version=1)
    accepted = runs.submit(sid, 'followup', 'Hello', expected_data_version=2, expected_rule_version=2)
    assert runs.execute(accepted['run_id'])['status'] == 'completed'
    reference = next(item for item in model.calls[-1]['artifact_references'] if item['artifact_id'] == 'past-table')
    assert reference['source_available'] is True
    assert reference['applicable'] is False
    assert 'old price' not in str(reference)


def test_bad_summary_is_deferred_without_losing_answer_or_advancing_memory(tmp_path):
    runs, sid, model, _ = setup(tmp_path, [])
    for i in range(6):
        runs.sessions.append_message(sid, f'old{i}', 'user', f'Remember preference {i}')
    def generate(system, payload, schema, budget):
        allowed = schema['$defs']['SummaryItem']['properties']['message_ids']['items']['enum']
        assert allowed == ['old0']
        return {**direct('Valid ordinary answer'), 'interaction_summary': {
            'preferences': [{'text': 'Untrusted compaction', 'message_ids': ['not-a-user-message']}]}}
    model.generate = generate
    run = runs.submit(sid, 'q', 'Hello', expected_data_version=0, expected_rule_version=0)
    done = runs.execute(run['run_id'])
    assert done['status'] == 'completed'
    assert done['answer']['segments'][0]['text'] == 'Valid ordinary answer'
    context = runs.context.assemble(sid)
    assert context['interaction_summary']['preferences'] == []
    assert context['summary_candidates'][0]['message_id'] == 'old0'
    assert any(e['kind'] == 'summary_deferred' for e in runs.events(sid, run['run_id'], developer=True))


def test_acknowledgment_does_not_replace_the_discussion_target(tmp_path):
    from app.agent_protocol import ResolvedReference
    runs, sid, _, _ = setup(tmp_path, [direct('You are welcome')])
    focus = ResolvedReference(kind='product', reference_id='00123', description='Current product')
    runs.sessions.set_focus(sid, focus)
    run = runs.submit(sid, 'thanks', 'Thanks', expected_data_version=0, expected_rule_version=0)
    assert runs.execute(run['run_id'])['status'] == 'completed'
    assert runs.sessions.get(sid)['focus'] == focus.model_dump(mode='json')

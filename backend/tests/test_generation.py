"""Actual provider SDKs over controlled HTTP; never use real credentials."""
import json
import httpx
import pytest

from app.config import Settings
from app.documents import DocumentError
from app.generation import StructuredModel
from app.questions import QuestionBudget, ToolPlan


@pytest.mark.parametrize('provider', ['gemini', 'groq'])
def test_sdk_json_output_and_no_tools_or_streaming(provider, tmp_path):
    seen = []
    def respond(request):
        seen.append(json.loads(request.content))
        if provider == 'gemini':
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                'content': {'parts': [{'text': '{"tools":[]}'}], 'role': 'model'}}]})
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1,
            'model': 'openai/gpt-oss-120b', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': '{"tools":[]}'}}]})
    settings = Settings(_env_file=None, data_dir=tmp_path, generation_provider=provider,
                        gemini_api_key='fake', groq_api_key='fake')
    model = StructuredModel(settings, transport=httpx.MockTransport(respond))
    result = model.generate('Return JSON', {'phase': 'plan'}, ToolPlan.model_json_schema(), QuestionBudget())
    assert result == {'tools': []} and len(seen) == 1
    assert not seen[0].get('tools') and not seen[0].get('stream')


@pytest.mark.parametrize('provider', ['gemini', 'groq'])
@pytest.mark.parametrize('status,code', [(401, 'generation_authentication_failed'),
                                       (429, 'generation_rate_limited'), (503, 'generation_provider_unavailable')])
def test_provider_failures_are_sanitized_and_not_retried(provider, status, code, tmp_path):
    calls = []
    def respond(request):
        calls.append(True)
        return httpx.Response(status, json={'error': {'code': status, 'message': 'secret-provider-body'}})
    model = StructuredModel(Settings(_env_file=None, data_dir=tmp_path, generation_provider=provider,
                                     gemini_api_key='fake-secret', groq_api_key='fake-secret'),
                            transport=httpx.MockTransport(respond))
    with pytest.raises(DocumentError) as error:
        model.generate('JSON', {}, ToolPlan.model_json_schema(), QuestionBudget())
    assert error.value.code == code and len(calls) == 1
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('provider', ['gemini', 'groq'])
@pytest.mark.parametrize('finish,content,expected', [('length', '{"tools":[]}', 'generation_truncated'),
    ('stop', 'not JSON', 'generation_invalid_output'), ('stop', '{"x":NaN}', 'generation_invalid_output')])
def test_noncomplete_or_invalid_output_never_publishes(provider, finish, content, expected, tmp_path):
    def respond(request):
        if provider == 'gemini':
            return httpx.Response(200, json={'candidates': [{'finishReason': 'MAX_TOKENS' if finish == 'length' else 'STOP',
                'content': {'parts': [{'text': content}], 'role': 'model'}}]})
        return httpx.Response(200, json={'id': 't', 'object': 'chat.completion', 'created': 1, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': finish, 'message': {'role': 'assistant', 'content': content}}]})
    model = StructuredModel(Settings(_env_file=None, data_dir=tmp_path, generation_provider=provider,
                                     gemini_api_key='fake', groq_api_key='fake'), transport=httpx.MockTransport(respond))
    with pytest.raises(DocumentError) as error:
        model.generate('JSON', {}, ToolPlan.model_json_schema(), QuestionBudget())
    assert error.value.code == expected


def test_late_provider_result_is_discarded(tmp_path):
    clock = [0.0]
    def respond(request):
        clock[0] = 61
        return httpx.Response(200, json={'id': 't', 'object': 'chat.completion', 'created': 1, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}]})
    model = StructuredModel(Settings(_env_file=None, data_dir=tmp_path, generation_provider='groq', groq_api_key='fake'),
                            transport=httpx.MockTransport(respond), now=lambda: clock[0])
    with pytest.raises(DocumentError) as error:
        model.generate('JSON', {}, ToolPlan.model_json_schema(), QuestionBudget(now=lambda: clock[0]))
    assert error.value.code == 'generation_timeout'


def test_transport_timeout_and_missing_key_are_explicit(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout('private request data', request=request)
    model = StructuredModel(Settings(_env_file=None, data_dir=tmp_path, generation_provider='groq', groq_api_key='fake'),
                            transport=httpx.MockTransport(timeout))
    with pytest.raises(DocumentError) as error:
        model.generate('JSON', {}, ToolPlan.model_json_schema(), QuestionBudget())
    assert error.value.code == 'generation_timeout' and 'private' not in str(error.value)
    missing = StructuredModel(Settings(_env_file=None, data_dir=tmp_path))
    with pytest.raises(DocumentError) as error:
        missing.generate('JSON', {}, ToolPlan.model_json_schema(), QuestionBudget())
    assert error.value.code == 'generation_not_configured'


@pytest.mark.parametrize('provider', ['gemini', 'groq'])
def test_provider_request_size_limit_is_actionable_without_retry(provider, tmp_path):
    calls = []
    def respond(request):
        calls.append(True)
        return httpx.Response(413, json={'error': {'code': 'rate_limit_exceeded',
            'message': 'Request too large; private-account-id and secret-key'}})
    model = StructuredModel(Settings(_env_file=None, data_dir=tmp_path,
        generation_provider=provider, gemini_api_key='fake', groq_api_key='fake'),
        transport=httpx.MockTransport(respond))
    with pytest.raises(DocumentError) as error:
        model.generate('JSON', {}, ToolPlan.model_json_schema(), QuestionBudget())
    assert error.value.code == 'generation_context_too_large'
    assert 'Top K' in str(error.value)
    assert not error.value.retryable and len(calls) == 1
    assert 'private-account-id' not in str(error.value) and 'secret-key' not in str(error.value)

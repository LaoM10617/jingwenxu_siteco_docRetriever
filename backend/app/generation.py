"""Small synchronous JSON adapters. No automatic retry, tools, fallback or streaming."""
from copy import deepcopy
import json
import time
import logging

import httpx

from app.documents import DocumentError


def wire_schema(schema):
    """Conservative provider subset; authoritative validation remains in Pydantic."""
    definitions = schema.get('$defs', {})
    def visit(value):
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            return visit(definitions[value['$ref'].rsplit('/', 1)[-1]])
        result = {}
        for key, item in value.items():
            if key in ('$defs', 'title', 'default', 'discriminator', 'minLength', 'maxLength',
                       'minItems', 'maxItems', 'minimum', 'maximum'):
                continue
            if key == 'const':
                result['enum'] = [item]
            else:
                result['anyOf' if key == 'oneOf' else key] = visit(item)
        if result.get('type') == 'object':
            result['additionalProperties'] = False
            result['required'] = list(result.get('properties', {}))
        return result
    return visit(deepcopy(schema))


class StructuredModel:
    def __init__(self, settings, *, transport=None, now=time.monotonic):
        self.provider = settings.generation_provider
        self.model = (settings.gemini_generation_model if self.provider == 'gemini'
                      else settings.groq_generation_model)
        self._key = settings.gemini_api_key if self.provider == 'gemini' else settings.groq_api_key
        self._transport, self._now = transport, now

    def generate(self, system, payload, schema, budget):
        start, status = time.monotonic(), 'ok'
        try:
            return self._generate(system, payload, schema, budget)
        except DocumentError as exc:
            status = exc.code
            raise
        finally:
            logging.getLogger('siteco.providers').info('generation provider=%s model=%s phase=%s status=%s seconds=%.3f',
                self.provider, self.model, payload.get('phase', 'unknown'), status, time.monotonic() - start)

    def _generate(self, system, payload, schema, budget):
        budget.check()
        if self._key is None:
            raise DocumentError('generation_not_configured', 'Configure the selected generation provider.', 503)
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(content) > 160000:
            raise DocumentError('generation_context_too_large', 'Generation context exceeds the safe limit.', 422)
        timeout = min(60.0, budget.remaining())
        started = self._now()
        try:
            with httpx.Client(transport=self._transport, timeout=timeout) as http:
                if self.provider == 'gemini':
                    from google import genai
                    from google.genai import types
                    with genai.Client(api_key=self._key.get_secret_value(), http_options=types.HttpOptions(
                            timeout=max(1, int(timeout * 1000)), httpx_client=http,
                            retry_options=types.HttpRetryOptions(attempts=1))) as client:
                        response = client.models.generate_content(model=self.model, contents=content,
                            config=types.GenerateContentConfig(system_instruction=system,
                                response_mime_type='application/json', response_json_schema=wire_schema(schema),
                                max_output_tokens=6000,
                                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
                    if response.prompt_feedback and response.prompt_feedback.block_reason:
                        raise DocumentError('generation_refused', 'The provider declined the request.', 502)
                    if not response.candidates or len(response.candidates) != 1:
                        raise DocumentError('generation_invalid_output', 'The provider returned no usable answer.', 502)
                    finish = response.candidates[0].finish_reason
                    if finish != 'STOP':
                        code = 'generation_truncated' if finish == 'MAX_TOKENS' else 'generation_refused'
                        raise DocumentError(code, 'The provider did not complete the answer.', 502)
                    text = response.text
                else:
                    from groq import Groq
                    with Groq(api_key=self._key.get_secret_value(), http_client=http,
                              timeout=timeout, max_retries=0) as client:
                        response = client.chat.completions.create(model=self.model, stream=False,
                            messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
                            max_completion_tokens=6000,
                            response_format={'type': 'json_schema', 'json_schema': {
                                'name': 'question_response', 'strict': True, 'schema': wire_schema(schema)}})
                    if len(response.choices) != 1:
                        raise DocumentError('generation_invalid_output', 'The provider returned no usable answer.', 502)
                    choice = response.choices[0]
                    if getattr(choice.message, 'refusal', None) or choice.finish_reason != 'stop':
                        code = 'generation_truncated' if choice.finish_reason == 'length' else 'generation_refused'
                        raise DocumentError(code, 'The provider did not complete the answer.', 502)
                    text = choice.message.content
        except DocumentError:
            budget.check()
            raise
        except Exception as exc:
            budget.check()
            status = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
            if status == 413:
                raise DocumentError('generation_context_too_large',
                    'The provider rejected the request size. Reduce PDF Top K or selected materials and check your model account limits.',
                    413, False) from None
            if status in (401, 403):
                code, retry = 'generation_authentication_failed', False
            elif status == 429:
                code, retry = 'generation_rate_limited', True
            elif isinstance(exc, httpx.TimeoutException) or 'timeout' in type(exc).__name__.lower():
                code, retry = 'generation_timeout', True
            elif isinstance(exc, httpx.TransportError) or 'connection' in type(exc).__name__.lower() or status in (500, 502, 503, 504):
                code, retry = 'generation_provider_unavailable', True
            else:
                code, retry = 'generation_provider_error', False
            raise DocumentError(code, 'The generation provider request failed.', 503, retry) from None
        budget.check()
        if self._now() - started >= timeout:
            raise DocumentError('generation_timeout', 'The generation call deadline expired.', 504, True)
        try:
            if not isinstance(text, str) or len(text) > 100000:
                raise ValueError()
            result = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError):
            raise DocumentError('generation_invalid_output', 'The provider returned invalid JSON.', 502, True) from None

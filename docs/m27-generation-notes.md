# M2.7 generation adapter verification

2026-09-26. Scope: the official Python SDK request shape, structured JSON, retries,
timeouts and finish reasons. This is targeted implementation research, not a new
provider/model selection. Installed versions: google-genai 2.25.0 and groq 1.7.0.
Both are pinned in the runtime lock and exercised through their real SDKs with
controlled HTTP transports. Windows and Linux dependency checks passed.

## Gemini

Use `generate_content`, `response_mime_type=application/json` and
`response_json_schema`; do not also supply response_schema. Disable automatic
function calling and omit tools. HttpOptions.timeout is milliseconds;
HttpRetryOptions(attempts=1) means the initial request only. The configured httpx
client supplies the synchronous API-key transport used here. Accept exactly one
candidate with STOP; reject MAX_TOKENS as truncated, safety/refusal/other finishes
as unusable. No partially generated text is published.

Sources (versioned SDK code):
- https://raw.githubusercontent.com/googleapis/python-genai/v2.25.0/google/genai/_api_client.py
- https://raw.githubusercontent.com/googleapis/python-genai/v2.25.0/google/genai/models.py
- https://raw.githubusercontent.com/googleapis/python-genai/v2.25.0/google/genai/types.py
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite

## Groq

Use chat completions with response_format json_schema/strict and stream=false.
The configured openai/gpt-oss-120b is in the documented strict-output support list.
Set max_retries=0 explicitly. Accept stop only; length is truncated and refusal or
other finish reasons fail. Groq was verified using controlled SDK HTTP, not private
material sent to the real service in this increment.

Sources:
- https://console.groq.com/docs/structured-outputs
- https://github.com/groq/groq-python/blob/main/README.md
- https://raw.githubusercontent.com/groq/groq-python/main/src/groq/types/chat/chat_completion.py

## Common limits

The provider schema expands local references, uses enum/anyOf, requires all object
properties and rejects extras; nullable fields remain nullable. Provider-unsupported
length/range hints are removed from this projection, but the original strict
Pydantic schema still validates every response before execution or publication.
No arbitrary model SQL/Python is executed. SDK error bodies are not exposed.

httpx timeouts bound connect/read/write/pool phases, not an absolute thread kill:
https://www.python-httpx.org/advanced/timeouts/
The adapter takes min(60s, question remaining), checks elapsed time after return
and discards late results. M2.8 must own the task deadline/terminal state independently
of a still-returning worker. There is no automatic model retry, repair or fallback.

The SDK requires websockets<17: the existing 17.1 lock was reduced to 16.1.1 while
retaining the other existing runtime pins. Added transitive packages are google-auth,
pyasn1 and pyasn1-modules. No local model, model weights, OCR or extra runtime service.

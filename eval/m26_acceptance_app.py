"""Temporary backend-owned retrieval diagnostics; excluded from production image."""
from contextlib import asynccontextmanager
import os
import sys
import time

sys.path.insert(0, '/app/backend')
from app.main import create_app as production_app


def create_app():
    app = production_app()
    lifespan = app.router.lifespan_context
    calls = []

    @asynccontextmanager
    async def instrumented(application):
        async with lifespan(application):
            gateway = app.state.retriever.gateway
            provider = gateway.provider
            class CountedProvider:
                def embed(self, texts, **options):
                    call = {'input_type': options['input_type'], 'started': time.time(), 'items': len(texts)}
                    calls.append(call)
                    if os.environ.get('M26_FORBID_PROVIDER') == '1':
                        raise RuntimeError('Provider forbidden during restart acceptance')
                    result = provider.embed(texts, **options)
                    call['tokens'] = result.total_tokens
                    return result
            gateway.provider = CountedProvider()
            yield
    app.router.lifespan_context = instrumented

    @app.post('/api/acceptance/retrieve')
    def retrieve(body: dict):
        return app.state.retriever.retrieve(body.get('question'), body.get('document_ids'), body.get('top_k', 8))

    @app.get('/api/acceptance/calls')
    def metrics():
        return {'process_started': started, 'calls': calls}

    started = time.time()
    return app

"""Acceptance-only adapter, mounted into a temporary Docker deployment.

Not in the runtime image or production router. Lookup runs in the owning
backend process, never against its SQLite file from another process.
"""
import sys

sys.path.insert(0, '/app/backend')
from fastapi import Request
from app.main import create_app as production_app


def create_app():
    app = production_app()

    @app.post('/api/acceptance/orders')
    def lookup(body: dict, request: Request):
        return request.app.state.documents.lookup_orders(
            body.get('order_ids'), body.get('document_ids'),
            body.get('offset', 0), body.get('limit', 50))

    return app

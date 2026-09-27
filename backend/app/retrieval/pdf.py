"""Scoped hybrid PDF retrieval with traceable lexical, semantic and RRF ranks."""
from contextlib import closing
import json
import re
import sqlite3
import unicodedata

from app.documents import DocumentError
from app.embeddings import EmbeddingError
from app.pdf_store import normalize
from app.retrieval.fusion import reciprocal_rank_fusion


class PdfRetriever:
    def __init__(self, documents, lexical, gateway=None, *, reranker=None, default_top_k=8):
        self.documents, self.lexical = documents, lexical
        self.gateway = gateway
        self.reranker = reranker
        self.default_top_k = default_top_k

    def _scope(self, question, document_ids, top_k):
        if (not isinstance(question, str) or not question.strip() or len(question) > 8000
                or not isinstance(document_ids, list) or not document_ids
                or any(not isinstance(v, str) or not v for v in document_ids)):
            raise DocumentError('invalid_query', 'Provide a question and explicit document IDs.', 422)
        if type(top_k) is not int or not 1 <= top_k <= 100:
            raise DocumentError('invalid_query', 'top_k must be an integer from 1 to 100.', 422)
        scope = list(dict.fromkeys(document_ids))
        for identity in scope:
            doc = self.documents.get(identity)
            if doc is None:
                raise DocumentError('document_not_found', 'Unknown document ID.', 404)
            if doc['status'] != 'ready':
                raise DocumentError('document_not_ready', 'The document is not available for queries.', 409)
            if not doc['original_filename'].lower().endswith('.pdf'):
                raise DocumentError('document_not_pdf', 'PDF retrieval requires PDF documents.', 422)
        return scope

    def retrieve(self, question, document_ids, top_k=None, *, stop=None, on_wait=None, on_start=None):
        top_k = self.default_top_k if top_k is None else top_k
        scope = self._scope(question, document_ids, top_k)
        if self.gateway is None:
            raise DocumentError('retrieval_not_configured', 'Hybrid retrieval is not configured.', 503)
        # Capture immutable published indexes; no lifecycle lock during quota/network waits.
        snapshots = self.documents.pdf_snapshot(scope)
        lifecycle_stop = self.documents.stop_event
        class QueryStop:
            def is_set(self):
                return lifecycle_stop.is_set() or (stop is not None and stop.is_set())
        try:
            callbacks = {'on_start': on_start} if on_start is not None else {}
            query = normalize(self.gateway.embed([question], input_type='query', stop=QueryStop(), on_wait=on_wait, **callbacks))
        except EmbeddingError as exc:
            from app.documents import ERRORS
            message, retryable = ERRORS.get(exc.code, ERRORS['processing_failed'])
            raise DocumentError(exc.code, message, 503, retryable) from None
        semantic = []
        for document_id, (prepared, index) in snapshots.items():
            for position, score in index.search(query):
                semantic.append({**prepared.evidence[position], 'document_id': document_id,
                                 'semantic_score': score})
        semantic.sort(key=lambda row: (-row['semantic_score'], row['document_id'], row['evidence_id']))
        semantic = semantic[:20]
        for rank, row in enumerate(semantic, 1):
            row['semantic_rank'] = rank
        # Check publication again and read the lexical list in the same short lock.
        lexical = self.documents.pdf_lexical(question, scope, snapshots, 20)
        identity = lambda row: json.dumps([row['document_id'], row['evidence_id']])
        merged = {}
        for row in lexical + semantic:
            key = identity(row)
            merged.setdefault(key, {'lexical_rank': None, 'lexical_score': None,
                                    'semantic_rank': None, 'semantic_score': None,
                                    'matched_literals': []}).update(row)
        order = reciprocal_rank_fusion([[identity(r) for r in lexical],
                                       [identity(r) for r in semantic]], k=60, top_k=40 if self.reranker is not None else top_k)
        rows = []
        for rank, key in enumerate(order, 1):
            row = merged[key]
            row['fused_rank'] = rank
            row['fused_score'] = sum(1 / (60 + row[field]) for field in ('lexical_rank', 'semantic_rank')
                                     if row[field] is not None)
            rows.append(row)
        rerank_route = {}
        warnings = []
        if self.reranker is not None and rows:
            rows, info = self.reranker.rank(question, rows, stop=stop)
            rerank_route = {'rerank': info}
            if info['status'] == 'fallback':
                warnings.append({'code': 'rerank_fallback',
                    'message': 'Optional reranking unavailable; using the original RRF order.'})
        return {'document_ids': scope, 'routes': {
                    'lexical': {'status': 'ok', 'count': len(lexical)},
                    'semantic': {'status': 'ok', 'count': len(semantic)}, **rerank_route},
                'warnings': warnings, 'records': json.loads(json.dumps(rows[:top_k])),
                'diagnostics': {'strategy': ('rrf_reranked' if rerank_route['rerank']['status']=='ok' else 'rrf_fallback') if rerank_route else 'rrf',
                    'lexical_candidates': len(lexical), 'semantic_candidates': len(semantic),
                    'union_count': len(merged), 'requested_top_k': top_k, 'selected_count': len(rows[:top_k]),
                    'rerank': rerank_route.get('rerank')}}

    def lexical_candidates(self, question, document_ids, top_k=20):
        scope = self._scope(question, document_ids, top_k)
        return {'document_ids': scope, 'route': 'lexical',
                'records': self.lexical.search(question, scope, top_k)}


def _terms(text):
    # Preserve a complete alphanumeric model, decimal or signed numeric literal.
    normalized = unicodedata.normalize('NFC', text).casefold()
    return list(dict.fromkeys(re.findall(r'[+-]?[\w]+(?:[-.,/][\w]+)*', normalized)))


def _numeric(term):
    return any(c.isdigit() for c in term)


def _key(term):
    return 'v' + term.encode('utf-8').hex()


class FtsStore:
    """Only the publication owner may replace the published lexical corpus.

    SQLite's BM25 statistics cover this whole table, even for scoped searches.
    The publication owner supplies its ready transaction to replace_document.
    """
    def __init__(self, database):
        self.database = database
        with closing(sqlite3.connect(database)) as db:
            db.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS pdf_fts USING fts5(
                document_id UNINDEXED, evidence_id UNINDEXED, payload UNINDEXED,
                text, literal_keys, tokenize='unicode61 remove_diacritics 0')''')

    def replace_document(self, document_id, evidence, *, connection=None):
        ids = [e['evidence_id'] for e in evidence]
        if (not evidence or len(set(ids)) != len(ids)
                or any(not isinstance(i, str) or not i for i in ids)):
            raise ValueError('Invalid evidence identities')
        rows = []
        for item in evidence:
            text = item.get('retrieval_text') or item['text']
            if not isinstance(text, str) or not text.strip() or not isinstance(item.get('locator'), dict):
                raise ValueError('Invalid evidence')
            keys = ' '.join(_key(t) for t in _terms(text) if _numeric(t))
            rows.append((document_id, item['evidence_id'], json.dumps(item, allow_nan=False),
                         unicodedata.normalize('NFC', text).casefold(), keys))
        def write(db):
            db.execute('DELETE FROM pdf_fts WHERE document_id=?', (document_id,))
            db.executemany('INSERT INTO pdf_fts VALUES (?,?,?,?,?)', rows)
        if connection is not None:
            write(connection)
        else:
            with closing(sqlite3.connect(self.database)) as db, db:
                write(db)

    def search(self, question, document_ids, top_k):
        clauses = []
        for term in _terms(question):
            if _numeric(term):
                clauses.append(f'literal_keys:"{_key(term)}"')
            else:
                # Terms contain no quotes/operators; column names are fixed.
                clauses.append('text:"' + term + '"')
        if not clauses:
            return []
        placeholders = ','.join('?' for _ in document_ids)
        with closing(sqlite3.connect(self.database)) as db:
            rows = db.execute(f'''SELECT document_id,evidence_id,payload,bm25(pdf_fts) FROM pdf_fts
                WHERE pdf_fts MATCH ? AND document_id IN ({placeholders})
                ORDER BY bm25(pdf_fts),document_id,evidence_id LIMIT ?''',
                (' OR '.join(clauses), *document_ids, top_k)).fetchall()
        query_literals = set(t for t in _terms(question) if _numeric(t))
        result = []
        for rank, (doc, evidence_id, payload, score) in enumerate(rows, 1):
            item = json.loads(payload)
            literals = set(_terms(item.get('retrieval_text') or item['text']))
            result.append({**item, 'document_id': doc, 'evidence_id': evidence_id,
                           'lexical_rank': rank, 'lexical_score': score,
                           'matched_literals': sorted(query_literals & literals)})
        return result

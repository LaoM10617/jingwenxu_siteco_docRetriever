"""Complete PDF artifacts: ordered source mapping, normalized vectors and FAISS."""
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import json
import sqlite3

import faiss
import numpy as np

from app.parsing import PARSER_VERSION

CONFIG = {'model': 'voyage-4', 'dimensions': 1024, 'dtype': 'float32',
          'normalization': 'l2-v1', 'index': 'IndexFlatIP', 'parser': PARSER_VERSION}


def normalize(vectors):
    raw = np.asarray(vectors)
    if raw.dtype.kind not in 'fiu' or raw.ndim != 2 or raw.shape[1] != 1024 or not len(raw):
        raise ValueError('Invalid vector shape')
    values = raw.astype('float64')
    norms = np.linalg.norm(values, axis=1)
    if not np.isfinite(values).all() or not np.isfinite(norms).all() or (norms == 0).any():
        raise ValueError('Invalid vectors')
    return np.ascontiguousarray(values / norms[:, None], dtype='float32')


@dataclass
class PreparedPdf:
    evidence: list
    vectors: np.ndarray


class PdfIndex:
    def __init__(self, prepared):
        ids = [row['evidence_id'] for row in prepared.evidence]
        if (not ids or len(set(ids)) != len(ids)
                or any(not isinstance(i, str) or not i for i in ids)
                or any(not isinstance(r.get('text'), str) or not r['text'].strip()
                       or not isinstance(r.get('locator'), dict) or r['locator'].get('kind') != 'pdf'
                       for r in prepared.evidence)):
            raise ValueError('Invalid source mapping')
        vectors = np.ascontiguousarray(prepared.vectors, dtype='float32')
        if (vectors.shape != (len(ids), 1024) or not np.isfinite(vectors).all()
                or not np.allclose(np.linalg.norm(vectors.astype('float64'), axis=1), 1, rtol=1e-6)):
            raise ValueError('Incomplete source mapping')
        self.evidence_ids = tuple(ids)
        self.index = faiss.IndexFlatIP(1024)
        self.index.add(vectors)

    def search(self, query):
        # Flat scan all rows so a tie at candidate 20 cannot hide a stable source.
        scores, positions = self.index.search(query, self.index.ntotal)
        return [(int(pos), float(score)) for score, pos in zip(scores[0], positions[0])]


class PdfStore:
    def __init__(self, database):
        self.database = database
        with closing(sqlite3.connect(database)) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS pdf_artifacts (
                document_id TEXT PRIMARY KEY, metadata TEXT NOT NULL,
                vectors BLOB NOT NULL, digest TEXT NOT NULL)''')

    def write(self, db, document_id, prepared):
        metadata = json.dumps({'config': CONFIG, 'evidence': prepared.evidence}, allow_nan=False)
        vectors = prepared.vectors.astype('<f4').tobytes()
        digest = sha256(metadata.encode() + vectors).hexdigest()
        db.execute('INSERT OR REPLACE INTO pdf_artifacts VALUES (?,?,?,?)',
                   (document_id, metadata, vectors, digest))

    def restore(self, document_id):
        with closing(sqlite3.connect(self.database)) as db:
            row = db.execute('SELECT metadata,vectors,digest FROM pdf_artifacts WHERE document_id=?',
                             (document_id,)).fetchone()
        if row is None:
            return None
        metadata, vectors, digest = row
        if sha256(metadata.encode() + vectors).hexdigest() != digest:
            raise ValueError('Invalid artifact digest')
        data = json.loads(metadata)
        if data['config'] != CONFIG:
            raise ValueError('Unsupported artifact version')
        prepared = PreparedPdf(data['evidence'], np.frombuffer(vectors, dtype='<f4').reshape(-1, 1024))
        return prepared, PdfIndex(prepared)

    @staticmethod
    def clear(db, document_id):
        db.execute('DELETE FROM pdf_artifacts WHERE document_id=?', (document_id,))

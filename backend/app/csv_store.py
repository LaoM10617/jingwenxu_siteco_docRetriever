"""Durable exact records. The lifecycle owner gates access until publication."""
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
import json
import sqlite3

from app.csv_parsing import CSV_PARSER_VERSION, HEADERS


def summary(parsed):
    return {'kind': 'csv', 'parser_version': parsed.parser_version,
            'record_count': parsed.record_count,
            'indexed_record_count': sum(bool(r.order_id) for r in parsed.records),
            'price_counts': {s: sum(r.price_status == s for r in parsed.records)
                             for s in ('valid', 'missing', 'invalid')},
            'warnings': [asdict(w) for w in parsed.warnings]}


def _digest(rows):
    digest = sha256()
    for row in rows:
        digest.update(json.dumps(tuple(row), ensure_ascii=True).encode())
        digest.update(b'\n')
    return digest.hexdigest()


class CsvStore:
    def __init__(self, database):
        self.database = database
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS csv_documents (
                document_id TEXT PRIMARY KEY, parser_version TEXT NOT NULL,
                headers TEXT NOT NULL, record_count INTEGER NOT NULL, digest TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS csv_records (
                document_id TEXT NOT NULL, record_number INTEGER NOT NULL,
                evidence_id TEXT NOT NULL, order_id TEXT NOT NULL COLLATE BINARY,
                raw_values TEXT NOT NULL, price_status TEXT NOT NULL, price TEXT,
                PRIMARY KEY(document_id, record_number), UNIQUE(document_id, evidence_id))''')
            db.execute('CREATE INDEX IF NOT EXISTS csv_order_index ON csv_records(document_id, order_id)')

    @staticmethod
    def clear(db, document_id):
        db.execute('DELETE FROM csv_records WHERE document_id=?', (document_id,))
        db.execute('DELETE FROM csv_documents WHERE document_id=?', (document_id,))

    def stage(self, document_id, parsed):
        rows = [(r.record_number, r.evidence_id, r.order_id, json.dumps(r.raw_values),
                 r.price_status, str(r.price) if r.price is not None else None)
                for r in parsed.records]
        with closing(sqlite3.connect(self.database)) as db, db:
            self.clear(db, document_id)
            db.executemany('INSERT INTO csv_records VALUES (?,?,?,?,?,?,?)',
                           ((document_id, *r) for r in rows))
            db.execute('INSERT INTO csv_documents VALUES (?,?,?,?,?)',
                       (document_id, parsed.parser_version, json.dumps(parsed.headers),
                        len(rows), _digest(rows)))

    def restore(self, document_id, checkpoint):
        """Validate the complete durable snapshot without parsing or provider calls."""
        with closing(sqlite3.connect(self.database)) as db:
            meta = db.execute('SELECT parser_version,headers,record_count,digest FROM csv_documents WHERE document_id=?', (document_id,)).fetchone()
            if meta is None:
                return False
            rows = db.execute('SELECT record_number,evidence_id,order_id,raw_values,price_status,price FROM csv_records WHERE document_id=? ORDER BY record_number', (document_id,)).fetchall()
            if (not checkpoint or checkpoint.get('kind') != 'csv'
                    or checkpoint.get('parser_version') != meta[0]
                    or checkpoint.get('record_count') != len(rows)
                    or checkpoint.get('indexed_record_count') != sum(bool(r[2]) for r in rows)
                    or checkpoint.get('price_counts') != {s: sum(r[4] == s for r in rows) for s in ('valid', 'missing', 'invalid')}
                    or meta[0] != CSV_PARSER_VERSION or tuple(json.loads(meta[1])) != HEADERS
                    or len(rows) != meta[2] or not rows or not any(r[2] for r in rows)
                    or [r[0] for r in rows] != list(range(1, len(rows) + 1))
                    or _digest(rows) != meta[3]):
                raise ValueError('Incomplete CSV snapshot')
        return True

    @staticmethod
    def evidence(row):
        headers, values = json.loads(row['headers']), json.loads(row['raw_values'])
        return {'document_id': row['document_id'], 'original_filename': row['original_filename'],
                'evidence_id': row['evidence_id'], 'order_id': row['order_id'],
                'locator': {'kind': 'csv', 'record_number': row['record_number']},
                'headers': headers, 'raw_values': values,
                'text': '\n'.join(f'{h}: {v}' for h, v in zip(headers, values)),
                'price_status': row['price_status'], 'price': row['price']}

    def read(self, document_id, offset, limit):
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('''SELECT r.*,c.headers,d.original_filename FROM csv_records r
                JOIN csv_documents c USING(document_id) JOIN documents d USING(document_id)
                WHERE r.document_id=? ORDER BY r.record_number LIMIT ? OFFSET ?''',
                (document_id, limit, offset)).fetchall()
            return [self.evidence(r) for r in rows]

    def lookup(self, orders, documents, offset, limit):
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TEMP TABLE requested_orders (position INTEGER, order_id TEXT PRIMARY KEY COLLATE BINARY)')
            db.executemany('INSERT INTO requested_orders VALUES (?,?)', enumerate(orders))
            scope = ','.join('?' for _ in documents)
            counts = [dict(r) for r in db.execute(f'''SELECT q.order_id,COUNT(r.record_number) AS count
                FROM requested_orders q LEFT JOIN csv_records r
                ON r.order_id=q.order_id AND r.document_id IN ({scope})
                GROUP BY q.position,q.order_id ORDER BY q.position''', documents)]
            rows = db.execute(f'''SELECT r.*,c.headers,d.original_filename FROM requested_orders q
                JOIN csv_records r ON r.order_id=q.order_id
                JOIN csv_documents c USING(document_id) JOIN documents d USING(document_id)
                WHERE r.document_id IN ({scope})
                ORDER BY q.position,r.document_id,r.record_number LIMIT ? OFFSET ?''',
                (*documents, limit, offset)).fetchall()
            total = sum(r['count'] for r in counts)
            return {'document_ids': documents, 'order_ids': orders, 'counts': counts,
                    'unmatched_order_ids': [r['order_id'] for r in counts if not r['count']],
                    'total': total, 'offset': offset, 'limit': limit,
                    'has_more': offset + len(rows) < total,
                    'records': [self.evidence(r) for r in rows]}

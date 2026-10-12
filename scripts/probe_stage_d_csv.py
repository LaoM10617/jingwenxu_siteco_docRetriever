"""Real CSV import/snapshot and fixed Docker computation; no model calls."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agent_protocol import DocumentVersion
from app.documents import DocumentService
from app.python_executor import PythonExecutor
from app.sessions import SessionStore


def main():
    source = ROOT / 'test_data/leuchten_siteco_LPR_2026_06.csv'
    original_hash = sha256(source.read_bytes()).hexdigest()
    output = ROOT / 'data/stage-d' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    documents = DocumentService(output / 'runtime')
    sessions = SessionStore(documents.database)
    documents.lifecycle = sessions
    sid = sessions.create()['session_id']
    documents.start()
    try:
        with source.open('rb') as stream:
            uploaded = documents.submit(source.name, stream, session_id=sid)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            document = documents.get(uploaded['document_id'])
            if document['status'] in ('ready', 'failed'):
                break
            time.sleep(.05)
        assert document['status'] == 'ready', document['error']
        linked, = sessions.get(sid)['sources']
        ref = DocumentVersion(document_id=linked['document_id'], version_id=linked['version_id'])
        table, = documents.csv_snapshot(sid, (ref,))
        assert len(table['rows']) == 11386
        price_index = table['headers'].index('Listenpreis')
        total = sum((Decimal(row['values'][price_index].replace('.', '').replace(',', '.'))
                     for row in table['rows']), Decimal('0.00'))
        assert total == Decimal('9623342.01')
        result = PythonExecutor(output / 'jobs').execute(
            (ROOT / 'scripts/siteco_statistics.py').read_text(encoding='utf-8'), {'data.csv': source})
        assert result.status == 'completed', result.status
        assert result.value['rows'] == [[11386, 11386, 0, '9623342.01']]
        assert result.value['source_sha256'] == original_hash
        assert sha256(source.read_bytes()).hexdigest() == original_hash
        receipt = {'kind': 'fixed_script_validation_not_agent_integration',
                   'source_sha256': original_hash, 'source': ref.model_dump(),
                   'parser_version': table['parser_version'], 'row_count': len(table['rows']),
                   'distinct_row_ids': len({row['row_id'] for row in table['rows']}),
                   'decimal_sum': str(total), 'execution': result.value,
                   'controller_seconds': result.seconds, 'cleaned_up': result.cleaned_up}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(output / 'receipt.json')
    finally:
        documents.stop()


if __name__ == '__main__':
    main()

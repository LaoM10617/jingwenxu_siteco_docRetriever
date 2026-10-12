"""Run the SITECO baseline against an independent existing parser oracle."""
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.csv_parsing import parse_csv
from app.python_executor import PythonExecutor
from app.agent_protocol import ArtifactDescriptor, DocumentVersion, ScopeSnapshot


def main():
    source = ROOT / 'test_data/leuchten_siteco_LPR_2026_06.csv'
    parsed = parse_csv(source, max_records=20_000)
    valid = [record.price for record in parsed.records if record.price_status == 'valid']
    assert not [record for record in parsed.records if record.price_status == 'invalid']
    expected = [len(parsed.records), len(valid), len(parsed.records) - len(valid),
                str(sum(valid, Decimal('0.00')))]
    output = ROOT / 'data/stage-a'
    output.mkdir(parents=True, exist_ok=True)
    receipts = []
    for attempt in range(2):
        result = PythonExecutor(output / 'jobs').execute(
            (ROOT / 'scripts/siteco_statistics.py').read_text(encoding='utf-8'), {'data.csv': source})
        assert result.status == 'completed', result.status
        assert result.value['rows'] == [expected], (result.value['rows'], expected)
        assert result.value['source_sha256'] == sha256(source.read_bytes()).hexdigest()
        destination = output / f'statistics-{attempt}.json'
        destination.write_text(json.dumps(result.value, indent=2), encoding='utf-8')
        descriptor = ArtifactDescriptor(
            artifact_id=f'phase-a-statistics-{attempt}', version_id='1', kind='table',
            scope=ScopeSnapshot(documents=(DocumentVersion(document_id='siteco-baseline',
                version_id=result.value['source_sha256']),)),
            storage_ref=destination.name, calculation=result.value['scope'], unit=result.value['unit'])
        receipts.append({'attempt': attempt, 'expected': expected, 'status': result.status,
                         'controller_seconds': result.seconds, 'worker_seconds': result.value['seconds'],
                         'artifact': descriptor.model_dump(mode='json'), 'cleaned_up': result.cleaned_up})
    (output / 'executor-receipt.json').write_text(json.dumps(receipts, indent=2), encoding='utf-8')
    print(json.dumps(receipts, indent=2))


if __name__ == '__main__':
    main()

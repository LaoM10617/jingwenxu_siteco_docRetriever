"""One-call synthesis replay using real persisted reading receipts; NOT end-to-end."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if not runtime.is_relative_to((ROOT / 'data/stage-e').resolve()):
        parser.error('Runtime must be an existing Stage E probe directory')
    with closing(sqlite3.connect((runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        task_text, result_text = db.execute('SELECT task,result FROM conversation_tasks WHERE run_id=?',
                                           (args.run_id,)).fetchone()
        responses = [json.loads(row[0]) for row in db.execute(
            'SELECT response FROM conversation_model_receipts WHERE run_id=?', (args.run_id,))]
        filenames = dict(db.execute('SELECT document_id,original_filename FROM documents'))
    task, result = json.loads(task_text), json.loads(result_text)
    plan = next(response for response in responses if 'dimensions' in response)
    readings = [response for response in responses if 'findings' in response and 'documents' not in response]
    assert len(readings) == 2
    findings = [finding for reading in readings for finding in reading['findings']]
    coverage = deepcopy(result['coverage'])
    batch_gaps = []
    for reading in readings:
        versions = {identity.split('@', 1)[0] for finding in reading['findings'] for identity in finding['evidence_ids']}
        assert len(versions) == 1
        version = versions.pop()
        entry = next(c for c in coverage if c['source']['version_id'] == version)
        entry['semantic_sufficiency'] = reading['semantic_sufficiency']
        batch_gaps.append({'version_id': version, 'processed': entry['processed'],
                           'gaps': reading['gaps'], 'semantic_sufficiency': reading['semantic_sufficiency']})
    payload = {'phase': 'pdf_synthesis', 'task_id': task['task_id'], 'question': task['objective'],
        'resolved_references': task['resolved_references'], 'constraints': task['constraints'],
        'filters': task['scope']['filters'], 'dimensions': plan['dimensions'], 'findings': findings,
        'coverage': coverage, 'batch_gaps': batch_gaps, 'gaps': [], 'page_ranges': plan['page_ranges'],
        'target_version_ids': sorted(c['source']['version_id'] for c in coverage), 'comparison_requested': True,
        'source_documents': [{'version_id': c['source']['version_id'],
                              'original_filename': filenames[c['source']['version_id']]} for c in coverage]}
    from app.config import load_settings
    from app.generation import StructuredModel
    from app.pdf_analysis import SYNTHESIS, SynthesisResult
    from app.questions import QuestionBudget

    target = ROOT / 'data/stage-e' / ('synthesis-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    target.mkdir()
    schema = SynthesisResult.model_json_schema()
    (target / 'input.json').write_text(json.dumps({'system': SYNTHESIS, 'payload': payload, 'schema': schema},
        ensure_ascii=False, indent=2), encoding='utf-8')
    settings = load_settings().model_copy(update={'generation_provider': 'gemini'})
    model = StructuredModel(settings)
    receipt = {'verification_kind': 'one_call_synthesis_replay_not_end_to_end', 'source_runtime': str(runtime),
               'source_run_id': args.run_id, 'provider': model.provider, 'model': model.model, 'model_calls': 1}
    try:
        raw = model.generate(SYNTHESIS, payload, schema, QuestionBudget())
        receipt['response'] = raw
        SynthesisResult.model_validate_json(json.dumps(raw))
        allowed = {identity for finding in findings for identity in finding['evidence_ids']}
        comparisons = raw.get('comparisons', [])
        assert comparisons, 'missing_comparisons'
        for comparison in comparisons:
            identities = set(comparison['evidence_ids'])
            assert identities <= allowed
            assert len({identity.split('@', 1)[0] for identity in identities}) >= 2
        receipt['status'] = 'passed_structure_pending_semantic_review'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['error_type'] = type(error).__name__
    (target / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'receipt': str(target / 'receipt.json'), 'status': receipt['status']}))
    return int(receipt['status'] == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())

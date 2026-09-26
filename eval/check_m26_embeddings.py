"""Two small serial hosted calls, or offline restoration of their durable cache.

Never print keys, provider responses or vectors. Uses synthetic text, not holdouts.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.embeddings import EmbeddingGateway, BudgetScheduler, EmbeddingError, PREFIXES
from app.voyage import VoyageProvider, load_token_counter

DOCUMENTS = ['Synthetic sample A: a luminaire with protection IP65 and power 20 W.',
             'Synthetic sample B: an indoor luminaire with protection IP20 and power 10 W.']
QUERY = 'Which synthetic sample has protection IP65?'


class Offline:
    def embed(self, *args, **kwargs):
        raise AssertionError('Offline cache verification attempted a provider call')


def check(args):
    args.runtime.mkdir(parents=True, exist_ok=True)
    counter = load_token_counter(args.tokenizer)
    calls, usage, starts = [], [], []
    if args.live:
        raw = args.key_file.read_text(encoding='utf-8-sig')
        keys = re.findall(r'pa-[A-Za-z0-9_-]+', raw)
        if len(set(keys)) != 1:
            raise ValueError('Expected one Voyage key in the explicitly provided key file')
        provider = VoyageProvider(keys[0])
        del raw, keys
        class Counted:
            def embed(self, texts, **options):
                starts.append(time.time())
                calls.append(options['input_type'])
                result = provider.embed(texts, **options)
                usage.append(result.total_tokens)
                return result
        adapter = Counted()
    else:
        adapter = Offline()
    database = args.runtime / 'embeddings.sqlite3'
    budget = BudgetScheduler(database)
    gateway = EmbeddingGateway(database, adapter, counter, budget)
    documents = gateway.embed(DOCUMENTS, 'document')
    query = gateway.embed([QUERY], 'query')
    assert documents.shape == (2, 1024) and query.shape == (1, 1024)
    assert np.isfinite(documents).all() and np.isfinite(query).all()
    restored = EmbeddingGateway(database, Offline(), counter, BudgetScheduler(database))
    assert np.array_equal(restored.embed(DOCUMENTS, 'document'), documents)
    assert np.array_equal(restored.embed([QUERY], 'query'), query)
    scores = (documents / np.linalg.norm(documents, axis=1, keepdims=True)) @ (query[0] / np.linalg.norm(query[0]))
    return {'mode': 'live' if args.live else 'offline-cache', 'model': 'voyage-4',
        'dimension': 1024, 'requests': calls, 'server_usage_tokens': usage,
        'local_tokens_with_prefix': [sum(counter(PREFIXES['document'] + t) for t in DOCUMENTS), counter(PREFIXES['query'] + QUERY)],
        'request_gaps_seconds': [round(b-a, 2) for a, b in zip(starts, starts[1:])],
        'cache_restored_without_provider': True,
        'synthetic_top_sample': 'A' if int(np.argmax(scores)) == 0 else 'B',
        'quality_claim': 'Connectivity/cache check only; not PDF retrieval acceptance'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    if args.live and not args.key_file:
        parser.error('--live requires --key-file; content is never printed')
    try:
        print(json.dumps(check(args), indent=2))
    except EmbeddingError as exc:
        print(json.dumps({'error': exc.code}))
        raise SystemExit(1) from None
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__}))
        raise SystemExit(1) from None

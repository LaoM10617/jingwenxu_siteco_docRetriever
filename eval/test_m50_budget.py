"""Approved evaluation provider boundary: over-budget attempts never reach a provider."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent))
from run_m50 import Ledger, LimitReached


def test_failed_attempt_consumes_authorized_allowance(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.case = 'E01'
    def fail():
        raise ValueError('private provider body')
    for _ in range(2):
        with pytest.raises(ValueError):
            ledger.call('generation', 100, fail)
    sent = []
    with pytest.raises(LimitReached):
        ledger.call('generation', 100, lambda: sent.append(True))
    assert sent == []
    assert ledger.counts['generation'] == 2
    assert 'private provider body' not in (tmp_path/'attempts.jsonl').read_text()


def test_unapproved_provider_and_oversized_input_do_not_send(tmp_path):
    for kind,tokens in [('groq',100),('generation',50001),('rerank',160001)]:
        ledger=Ledger(tmp_path); ledger.case='E01'; sent=[]
        with pytest.raises(LimitReached):
            ledger.call(kind,tokens,lambda:sent.append(True))
        assert sent==[]
        assert sum(ledger.counts.values())==0


def test_embedding_attempts_are_bounded_per_batch(tmp_path):
    ledger=Ledger(tmp_path)
    for _ in range(3): ledger.call('document',100,lambda:None,signature='same-batch')
    sent=[]
    with pytest.raises(LimitReached):
        ledger.call('document',100,lambda:sent.append(True),signature='same-batch')
    assert sent==[]
    assert ledger.counts['document']==3


def test_cost_limit_blocks_before_sending(tmp_path):
    ledger=Ledger(tmp_path); ledger.case='E01'; ledger.reserve=1.999
    sent=[]
    with pytest.raises(LimitReached):
        ledger.call('generation',100,lambda:sent.append(True))
    assert sent==[]

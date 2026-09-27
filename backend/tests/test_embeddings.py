"""T-004: fake provider and clock, real durable cache and quota ledger."""
from threading import Event
import pytest
import numpy as np
from app.embeddings import EmbeddingGateway, EmbeddingError, BudgetScheduler


class Clock:
    def __init__(self):
        self.value = 1000.0
    def now(self):
        return self.value
    def wait(self, condition, seconds):
        self.value += seconds
        condition.wait(0)


class Provider:
    def __init__(self):
        self.calls = []
    def embed(self, texts, **options):
        self.calls.append((list(texts), options))
        return [[1.0] + [0.0] * 1023 for _ in texts]


def gateway(tmp_path, provider=None, clock=None, **kwargs):
    provider, clock = provider or Provider(), clock or Clock()
    database = tmp_path / 'cache.sqlite3'
    budget = BudgetScheduler(database, now=clock.now, wait=clock.wait)
    return EmbeddingGateway(database, provider, lambda text: len(text.split()), budget, **kwargs), provider, clock


def test_embedding_cache_restores_and_input_type_isolated(tmp_path):
    embedder, provider, clock = gateway(tmp_path)
    first = embedder.embed(['A lamp', 'A lamp'], 'document')
    assert first.shape == (2, 1024) and first.dtype == np.float32
    assert len(provider.calls) == 1 and provider.calls[0][0] == ['A lamp']
    assert provider.calls[0][1] == {'model': 'voyage-4', 'input_type': 'document',
        'output_dimension': 1024, 'output_dtype': 'float', 'truncation': False}
    restored, _, _ = gateway(tmp_path, provider, clock)
    assert np.array_equal(restored.embed(['A lamp'], 'document'), first[:1])
    assert len(provider.calls) == 1
    restored.embed(['A lamp'], 'query')
    assert len(provider.calls) == 2


def test_shared_rpm_budget_persists_across_restart(tmp_path):
    embedder, provider, clock = gateway(tmp_path)
    for n in range(3):
        embedder.embed([f'item {n}'], 'document')
    restarted, _, _ = gateway(tmp_path, provider, clock)
    waits = []
    restarted.embed(['question'], 'query', on_wait=lambda: waits.append(True))
    assert clock.value >= 1060
    assert waits == [True]


def test_token_budget_includes_prefix_and_batches_without_truncation(tmp_path):
    embedder, provider, clock = gateway(tmp_path)
    # 3,979 body tokens + 5 prefix words + 16 safety tokens = 4,000 reserved.
    texts = [('word ' * 3978) + str(n) for n in range(3)]
    embedder.embed(texts, 'document')
    assert len(provider.calls) == 3
    assert clock.value >= 1060  # TPM prevents the third batch in the same window.
    before = len(provider.calls)
    with pytest.raises(EmbeddingError) as error:
        embedder.embed(['word ' * 4000], 'document')
    assert error.value.code == 'embedding_input_too_large'
    assert len(provider.calls) == before


def test_retry_is_bounded_charged_and_shared_cooldown(tmp_path):
    class Flaky(Provider):
        def embed(self, texts, **options):
            super().embed(texts, **options)
            if len(self.calls) < 3:
                raise EmbeddingError('embedding_rate_limited', retryable=True, retry_after=61)
            return [[1.0] + [0.0] * 1023]
    embedder, provider, clock = gateway(tmp_path, Flaky())
    result = embedder.embed(['lamp'], 'document')
    assert result.shape == (1, 1024) and len(provider.calls) == 3
    assert clock.value >= 1122


@pytest.mark.parametrize('bad', [[], [[1.0]], [[0.0] * 1024], [[float('nan')] * 1024],
    [[float('inf')] * 1024], [['bad'] * 1024], [['1.0'] * 1024]])
def test_invalid_vectors_never_cached(tmp_path, bad):
    class Invalid(Provider):
        def embed(self, *args, **kwargs):
            self.calls.append(True)
            return bad
    embedder, provider, _ = gateway(tmp_path, Invalid())
    for _ in range(2):
        with pytest.raises(EmbeddingError) as error:
            embedder.embed(['lamp'], 'document')
        assert error.value.code == 'embedding_invalid_vectors'
    assert len(provider.calls) == 2


def test_permanent_error_and_stop_are_explicit(tmp_path):
    class Denied(Provider):
        def embed(self, *args, **kwargs):
            self.calls.append(True)
            raise EmbeddingError('embedding_authentication_failed')
    embedder, provider, _ = gateway(tmp_path, Denied())
    with pytest.raises(EmbeddingError) as error:
        embedder.embed(['lamp'], 'document')
    assert error.value.code == 'embedding_authentication_failed' and len(provider.calls) == 1
    stop = Event()
    stop.set()
    with pytest.raises(EmbeddingError) as error:
        embedder.embed(['lamp'], 'document', stop=stop)
    assert error.value.code == 'embedding_interrupted' and len(provider.calls) == 1


def test_retry_limit_and_wait_deadline(tmp_path):
    class Unavailable(Provider):
        def embed(self, *args, **kwargs):
            self.calls.append(True)
            raise EmbeddingError('embedding_provider_unavailable', retryable=True)
    embedder, provider, _ = gateway(tmp_path, Unavailable())
    with pytest.raises(EmbeddingError):
        embedder.embed(['lamp'], 'document')
    assert len(provider.calls) == 3
    class LongWait(Provider):
        def embed(self, *args, **kwargs):
            self.calls.append(True)
            raise EmbeddingError('embedding_rate_limited', retryable=True, retry_after=3600)
    other = tmp_path / 'other'
    other.mkdir()
    embedder, provider, _ = gateway(other, LongWait())
    with pytest.raises(EmbeddingError) as error:
        embedder.embed(['lamp'], 'document')
    assert error.value.code == 'embedding_wait_timeout' and len(provider.calls) == 1


def test_usage_above_reservation_and_model_cache_isolation(tmp_path):
    from app.embeddings import EmbeddingResponse
    class Usage(Provider):
        def embed(self, texts, **options):
            return EmbeddingResponse(super().embed(texts, **options), 9999)
    embedder, provider, clock = gateway(tmp_path, Usage())
    embedder.embed(['lamp'], 'document')
    embedder.embed(['different'], 'query')
    assert clock.value >= 1060
    changed, _, _ = gateway(tmp_path, provider, clock, model='test-other-model')
    changed.embed(['lamp'], 'document')
    assert len(provider.calls) == 3


def test_cancel_during_wait_and_late_result_never_cached(tmp_path):
    embedder, provider, _ = gateway(tmp_path)
    embedder.embed(['first'], 'document')
    stop = Event()
    with pytest.raises(EmbeddingError) as error:
        embedder.embed(['second'], 'query', stop=stop, on_wait=stop.set)
    assert error.value.code == 'embedding_interrupted' and len(provider.calls) == 1
    class Late(Provider):
        def embed(self, texts, **options):
            result = super().embed(texts, **options)
            stop.set()
            return result
    stop.clear()
    late = Late()
    embedder, _, clock = gateway(tmp_path, late)
    with pytest.raises(EmbeddingError):
        embedder.embed(['late'], 'document', stop=stop)
    good, provider, _ = gateway(tmp_path, Provider(), clock)
    good.embed(['late'], 'document')
    assert len(provider.calls) == 1


def test_query_priority_and_bounded_pending_queue(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    # A fake clock skips quota time; synchronization uses Events, not sleeps.
    clock, entered, release = Clock(), Event(), Event()
    sequence, guard = [], Lock()
    class Blocked(Provider):
        def embed(self, texts, **options):
            with guard:
                sequence.append(texts[0])
                # Simulate a 20-second provider duration, not elapsed time for
                # every competing thread's condition wait.
                clock.value += 20
            if texts[0] == 'active':
                entered.set()
                assert release.wait(5)
            return super().embed(texts, **options)
    # Quota arithmetic has separate fake-clock tests. Here only completed
    # provider work advances the shared clock; thread scheduling cannot age it.
    def wait(condition, seconds):
        condition.wait(.01)
    database = tmp_path / 'priority.sqlite3'
    budget = BudgetScheduler(database, now=clock.now, wait=wait, max_pending=2)
    embedder = EmbeddingGateway(database, Blocked(), lambda text: 10, budget)
    document_waiting, query_waiting = Event(), Event()
    with ThreadPoolExecutor(max_workers=3) as pool:
        active = pool.submit(embedder.embed, ['active'], 'document')
        assert entered.wait(5)
        document = pool.submit(embedder.embed, ['document'], 'document', on_wait=document_waiting.set)
        assert document_waiting.wait(5)
        query = pool.submit(embedder.embed, ['query'], 'query', on_wait=query_waiting.set)
        try:
            assert query_waiting.wait(5)
            with pytest.raises(EmbeddingError) as error:
                embedder.embed(['overflow'], 'document')
            assert error.value.code == 'embedding_queue_full'
        finally:
            release.set()
        for result in (active, document, query):
            result.result(timeout=5)
    assert sequence == ['active', 'query', 'document']


@pytest.mark.parametrize('name,headers,code,retryable,delay', [
    ('AuthenticationError', {}, 'embedding_authentication_failed', False, 0),
    ('RateLimitError', {'Retry-After': '61'}, 'embedding_rate_limited', True, 61),
    ('RateLimitError', {'retry-after': 'NaN'}, 'embedding_rate_limited', True, 60),
    ('Timeout', {}, 'embedding_provider_unavailable', True, 0),
    ('ServerError', {}, 'embedding_provider_unavailable', True, 0),
])
def test_voyage_adapter_sanitizes_sdk_errors_and_disables_hidden_retries(monkeypatch, name, headers, code, retryable, delay):
    import voyageai
    from voyageai import error
    from app.voyage import VoyageProvider
    parameters = []
    class SDK:
        def embed(self, *args, **kwargs):
            raise getattr(error, name)('private provider detail', headers=headers)
    def client(**kwargs):
        parameters.append(kwargs)
        return SDK()
    monkeypatch.setattr(voyageai, 'Client', client)
    provider = VoyageProvider('test-placeholder')
    assert parameters[0]['max_retries'] == 0 and parameters[0]['timeout'] == 30
    with voyageai.requestssession() as session:
        assert session.get_adapter('https://api.voyageai.com').max_retries.total == 0
    with pytest.raises(EmbeddingError) as caught:
        provider.embed(['synthetic'], model='voyage-4')
    assert caught.value.code == code and caught.value.retryable == retryable
    assert caught.value.retry_after == delay
    assert 'private' not in str(caught.value)

def test_tier1_local_limits_keep_serial_admission_without_twenty_second_wait(tmp_path):
    clock = Clock()
    budget = BudgetScheduler(tmp_path/'budget.sqlite3', now=clock.now, wait=clock.wait,
                             rpm=60, tpm=200000, min_interval=1)
    for _ in range(8):
        budget.run(lambda: None, 4000, 'document', Event(), None)
    assert 1007 <= clock.value < 1008

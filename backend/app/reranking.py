"""Bounded optional reranking. Provider failures never replace the RRF baseline."""
import logging
from threading import Event, Lock, Thread
import time


class Reranker:
    def __init__(self, provider, *, min_interval=20):
        self.provider = provider
        self.min_interval = min_interval
        self._lock = Lock()
        self._next_at = 0.0

    def rank(self, question, records, stop=None, *, provider=None):
        start = time.monotonic()
        limit = min(5.0, stop.remaining()) if hasattr(stop, 'remaining') else 5.0
        def finish(reason, order=None):
            info = {'status': 'ok' if order is not None else 'fallback',
                    'seconds': round(time.monotonic()-start, 3)}
            if reason:
                info['reason'] = reason
            logging.getLogger('siteco.providers').info('rerank status=%s reason=%s seconds=%.3f',
                info['status'], reason or 'none', info['seconds'])
            return ([records[i] for i in order] if order is not None else records), info
        if limit <= .01 or (stop is not None and stop.is_set()):
            return finish('budget')
        if not self._lock.acquire(blocking=False):
            return finish('busy')
        if start < self._next_at:
            self._lock.release()
            return finish('rate_limit')
        done, result = Event(), {}
        def work():
            try:
                result['order'] = (provider or self.provider)(question,
                    [r.get('retrieval_text') or r['text'] for r in records], limit)
            except Exception as exc:
                # Never expose SDK errors, request bodies or credentials.
                result['error'] = True
                from app.voyage import _retry_after
                result['cooldown'] = max(60, _retry_after(getattr(exc, 'headers', None)))
            finally:
                self._next_at = time.monotonic()+result.get('cooldown', self.min_interval)
                self._lock.release()
                done.set()
        # The socket timeout bounds the worker; a slow transport cannot hold up the
        # caller. The lock stays held until it finishes, preventing worker buildup.
        Thread(target=work, name='pdf-rerank', daemon=True).start()
        while not done.wait(min(.02, max(0, start+limit-time.monotonic()))):
            if time.monotonic() >= start+limit or (stop is not None and stop.is_set()):
                return finish('timeout')
        if time.monotonic() >= start+limit or (stop is not None and stop.is_set()):
            return finish('timeout')
        order = result.get('order')
        if result.get('error'):
            return finish('provider_error')
        if (not isinstance(order, list) or any(type(i) is not int for i in order)
                or sorted(order) != list(range(len(records)))):
            return finish('invalid_response')
        return finish(None, order)


def configured_reranker(settings):
    if not settings.pdf_rerank_enabled:
        return None
    def provider(question, texts, timeout):
        import voyageai
        if settings.voyage_api_key is None:
            raise ValueError('Missing provider key')
        client = voyageai.Client(api_key=settings.voyage_api_key.get_secret_value(),
                                 max_retries=0, timeout=timeout)
        response = client.rerank(question, texts, model='rerank-2.5-lite',
                                 top_k=None, truncation=False)
        return [item.index for item in response.results]
    return Reranker(provider, min_interval=settings.rerank_min_interval)

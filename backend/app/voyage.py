"""Hosted Voyage adapter and a pinned local tokenizer (no model weights)."""
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
import math
import time

from app.embeddings import EmbeddingError, EmbeddingResponse

TOKENIZER_REVISION = '44f3b2ae4ddf33403ed4dd66bec3fa48ff7dbbf9'
TOKENIZER_SHA256 = 'c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539'
TOKENIZER_URL = f'https://huggingface.co/voyageai/voyage-4/resolve/{TOKENIZER_REVISION}/tokenizer.json'


def load_token_counter(path):
    from tokenizers import Tokenizer
    path = Path(path)
    if sha256(path.read_bytes()).hexdigest() != TOKENIZER_SHA256:
        raise EmbeddingError('embedding_tokenizer_invalid')
    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return lambda text: len(tokenizer.encode(text).ids)


def _session():
    from requests import Session
    from requests.adapters import HTTPAdapter
    session = Session()
    session.mount('https://', HTTPAdapter(max_retries=0))
    session.mount('http://', HTTPAdapter(max_retries=0))
    return session


def _retry_after(headers):
    value = next((v for k, v in (headers or {}).items() if k.lower() == 'retry-after'), None)
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return 60
    return max(0, seconds) if math.isfinite(seconds) else 60


class VoyageProvider:
    def __init__(self, api_key):
        import voyageai
        # Public SDK transport hook, configured before the first SDK request.
        voyageai.requestssession = _session
        self.client = voyageai.Client(api_key=api_key, max_retries=0, timeout=30)
        self.last_usage = None

    def embed(self, texts, **options):
        from voyageai import error
        try:
            response = self.client.embed(texts, **options)
            self.last_usage = response.total_tokens
            return EmbeddingResponse(response.embeddings, response.total_tokens)
        except error.AuthenticationError:
            raise EmbeddingError('embedding_authentication_failed') from None
        except error.RateLimitError as exc:
            raise EmbeddingError('embedding_rate_limited', retryable=True,
                                 retry_after=_retry_after(getattr(exc, 'headers', None))) from None
        except (error.Timeout, error.APIConnectionError, error.ServiceUnavailableError, error.ServerError):
            raise EmbeddingError('embedding_provider_unavailable', retryable=True) from None
        except Exception:
            # SDK/provider bodies can contain private input; expose a fixed code only.
            raise EmbeddingError('embedding_provider_error') from None


def configured_gateway(settings):
    """One gateway/scheduler per backend, shared by ingestion and queries."""
    from app.embeddings import EmbeddingGateway, BudgetScheduler
    if settings.voyage_api_key is None:
        return None
    try:
        if settings.embedding_model != 'voyage-4':
            raise ValueError('Unsupported embedding model')
        counter = load_token_counter(settings.data_dir / 'tokenizers/voyage-4-tokenizer.json')
    except (OSError, ValueError, EmbeddingError):
        class Unconfigured:
            def embed(self, *args, **kwargs):
                raise EmbeddingError('embedding_configuration_invalid')
        return Unconfigured()
    database = settings.data_dir / 'app.sqlite3'
    return EmbeddingGateway(database, VoyageProvider(settings.voyage_api_key.get_secret_value()),
                            counter, BudgetScheduler(database))

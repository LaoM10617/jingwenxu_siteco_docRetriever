"""Prepare pinned public tokenizer infrastructure, without credentials or indexes."""
from hashlib import sha256
from pathlib import Path
import sys
from urllib.request import urlopen
from .voyage import TOKENIZER_URL, TOKENIZER_SHA256


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'voyage-4-tokenizer.json'
    if target.exists() and sha256(target.read_bytes()).hexdigest() == TOKENIZER_SHA256:
        return target
    with urlopen(TOKENIZER_URL, timeout=30) as response:
        data = response.read(8 * 1024 * 1024)
    if sha256(data).hexdigest() != TOKENIZER_SHA256:
        raise ValueError('Tokenizer checksum mismatch')
    temporary = target.with_suffix('.part')
    temporary.write_bytes(data)
    temporary.replace(target)
    return target


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Pass the runtime/tokenizers directory.')
    try:
        print(prepare(Path(sys.argv[1]).resolve()))
    except (OSError, ValueError):
        raise SystemExit('Tokenizer preparation failed; check network and directory permissions.') from None

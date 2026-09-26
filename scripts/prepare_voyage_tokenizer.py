"""Download only the pinned tokenizer JSON to an explicit runtime directory."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.prepare_tokenizer import prepare


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Pass the explicit runtime/tokenizers directory.')
    print(prepare(Path(sys.argv[1]).resolve()))

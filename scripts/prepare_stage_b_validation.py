"""Copy a consistent old runtime for migration validation; never modify its source."""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'data/docker-e2e'
    target = ROOT / 'data/stage-b' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup, runtime = target / 'backup', target / 'runtime'
    backup.mkdir(parents=True)
    (backup / 'uploads').mkdir()
    with closing(sqlite3.connect(f'{source.joinpath("app.sqlite3").as_uri()}?mode=ro', uri=True)) as old:
        with closing(sqlite3.connect(backup / 'app.sqlite3')) as copy:
            old.backup(copy)
            rows = copy.execute('SELECT stored_name,content_hash FROM documents').fetchall()
    for stored_name, expected in rows:
        original = (source / 'uploads' / stored_name).resolve()
        if original.parent != (source / 'uploads').resolve():
            raise ValueError('Unexpected original path')
        destination = backup / 'uploads' / stored_name
        shutil.copyfile(original, destination)
        if sha256(destination.read_bytes()).hexdigest() != expected:
            raise ValueError('Original changed during backup; retry from a new snapshot')
    shutil.copytree(backup, runtime)
    receipt = {'source': str(source), 'backup': str(backup), 'runtime': str(runtime),
               'original_count': len(rows), 'originals_verified': True,
               'database_backup': 'sqlite backup API; source read-only'}
    (target / 'backup-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()

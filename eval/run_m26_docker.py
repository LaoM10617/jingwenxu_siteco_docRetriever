"""Explicit isolated Docker acceptance; never print or persist credentials."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['up', 'restart-offline', 'production'])
    parser.add_argument('--key-file', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    keys = set(re.findall(r'pa-[A-Za-z0-9_-]+', Path(args.key_file).read_text(encoding='utf-8-sig')))
    if len(keys) != 1:
        raise SystemExit('Expected one Voyage key in the specified ignored file')
    runtime = root / 'tmp/m26-docker/runtime'
    (runtime / 'tokenizers').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'tmp/m26-acceptance/tokenizers/voyage-4-tokenizer.json',
                    runtime / 'tokenizers/voyage-4-tokenizer.json')
    env = dict(os.environ, HOST_PORT='18090', FRONTEND_PORT='18091',
               HOST_DATA_DIR=runtime.as_posix(), VOYAGE_API_KEY=keys.pop(),
               M26_FORBID_PROVIDER='1' if args.action == 'restart-offline' else '0')
    docker = Path(os.environ['LOCALAPPDATA']) / 'Programs/DockerDesktop/resources/bin/docker.exe'
    command = [str(docker), 'compose', '-p', 'siteco-m26-acceptance', '-f', 'compose.yaml']
    if args.action != 'production':
        command += ['-f', 'eval/m26-acceptance.compose.yaml']
    command += ['up', '-d', '--wait']
    command += ['--build'] if args.action == 'up' else ['--force-recreate', 'backend']
    subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == '__main__':
    main()

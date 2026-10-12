"""Run each command in a fresh process to inspect explicit SQLite recovery.

python scripts/probe_agent_state.py --root data/stage-a/state-probe submit s1 q1 "Unit?"
python scripts/probe_agent_state.py --root data/stage-a/state-probe list
python scripts/probe_agent_state.py --root data/stage-a/state-probe resume RUN_ID EUR
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from app.agent_state import ProbeRequest, StateProbe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='Dedicated probe data directory')
    actions = parser.add_subparsers(dest='action', required=True)
    submit = actions.add_parser('submit')
    submit.add_argument('session_id')
    submit.add_argument('request_id')
    submit.add_argument('prompt')
    inspect = actions.add_parser('inspect')
    inspect.add_argument('run_id')
    resume = actions.add_parser('resume')
    resume.add_argument('run_id')
    resume.add_argument('answer', nargs='?')
    actions.add_parser('list')
    args = parser.parse_args()
    probe = StateProbe(args.root)
    if args.action == 'submit':
        views = [probe.submit(ProbeRequest(session_id=args.session_id,
                                          request_id=args.request_id, prompt=args.prompt))]
    elif args.action == 'inspect':
        views = [probe.inspect(args.run_id)]
    elif args.action == 'resume':
        views = [probe.resume(args.run_id, args.answer)]
    else:
        views = probe.recoverable()
    for view in views:
        print(view.model_dump_json())


if __name__ == '__main__':
    main()

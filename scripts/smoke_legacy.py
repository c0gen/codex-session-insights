"""Packaged Windows decoding smoke test with no Python on the child PATH."""
import argparse
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('executable',type=Path)
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--profile',type=Path,required=True)
parser.add_argument('--output-directory',type=Path,required=True)
args = parser.parse_args()
directory = args.output_directory.resolve()
directory.mkdir(parents=True,exist_ok=True)
output = directory / 'census.json'
environment = dict(os.environ)
environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
result = subprocess.run([str(args.executable.resolve()),'--data-dir',str(directory),
    'diagnose-antigravity-legacy','--root',str(args.root.resolve()),'--profile',str(args.profile.resolve()),
    '--output',str(output)], env=environment, creationflags=subprocess.CREATE_NO_WINDOW, timeout=55)
if result.returncode != 0:
    raise SystemExit('Packaged legacy decoder did not pass its release gate; inspect sanitized diagnostics')
report = json.loads(output.read_text(encoding='utf-8'))
assert report['release_gate'] and report['counts']['decoded'] == report['archive_count']
assert report['originals_unchanged'] is True
assert report['profile_unlock'] == 'available'
assert not list(directory.glob('*.sqlite*')), 'Read-only diagnostics must not create an analytics database'
assert all('profile_location' not in entry for entry in report['archives'])
print(json.dumps({'packaged_decoder':'passed','archives':report['archive_count'],
    'index_matches':report['index_matches'],'invocations':report['metrics']['invocations'],
    'confirmed_edits':report['metrics']['confirmed_edits'],'originals_unchanged':report['originals_unchanged']}))

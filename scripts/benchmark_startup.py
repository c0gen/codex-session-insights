"""Native startup-event timings from the packaged EXE using isolated demo data."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('executable', type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--runs', type=int, default=5)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
values = []
for i in range(args.runs):
    directory = (args.output / str(i)).resolve()
    started = datetime.now()
    process = subprocess.run([str(args.executable.resolve()), '--data-dir', str(directory), '--demo', 'gui',
                              '--smoke-result', str(directory / 'smoke.json')],
                             timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    assert process.returncode == 0
    assert json.loads((directory / 'smoke.json').read_text())['ok']
    lines = (directory / 'startup.log').read_text(encoding='utf-8').splitlines()
    shown = next(line[:23] for line in lines if 'Native window shown' in line)
    values.append((datetime.strptime(shown, '%Y-%m-%d %H:%M:%S,%f') - started).total_seconds())
    print(json.dumps({'run': i + 1, 'native_shown_event_seconds': round(values[-1], 3)}), flush=True)
values.sort()
result = {'runs': args.runs, 'p95_seconds': round(values[math.ceil(len(values)*.95)-1], 3),
          'metric': 'process creation to native shown event; hidden synthetic smoke window'}
(args.output / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result), flush=True)
assert result['p95_seconds'] <= 2

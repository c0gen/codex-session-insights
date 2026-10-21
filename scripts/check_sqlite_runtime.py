"""Check a development runtime or the exact library loaded by a packaged app."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from codex_insights.sqlite_runtime import require_supported

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('executable', nargs='?', type=Path)
args = parser.parse_args()
if args.executable:
    with tempfile.TemporaryDirectory(prefix='insights-sqlite-') as temporary:
        result = subprocess.run([str(args.executable.resolve()), '--sqlite-runtime-result', str(Path(temporary) / 'runtime.json')],
                                timeout=60, capture_output=True)
        value = json.loads((Path(temporary) / 'runtime.json').read_text())
        print(json.dumps(value))
        sys.exit(0 if result.returncode == 0 and value['supported'] else 1)
print(json.dumps(require_supported()))

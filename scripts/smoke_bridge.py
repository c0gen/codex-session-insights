"""Exercise a packaged bridge in an isolated directory without provider clients."""
import json
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    result = subprocess.run([sys.argv[1], "--data-dir", temporary, "--provider", "claude_code", "--mode", "status"],
                            input=json.dumps({"rate_limits": {"five_hour": {"used_percentage": 0}},
                                              "prompt": "private-smoke-canary"}), text=True,
                            capture_output=True, timeout=15)
    if result.returncode and sys.platform == 'darwin' and shutil.which('lldb'):
        diagnostic = subprocess.run(['lldb', '--batch', '-o', 'run', '-k', 'bt', '--', sys.argv[1],
                                     '--data-dir', temporary, '--provider', 'claude_code', '--mode', 'status'],
                                    input='', text=True, capture_output=True, timeout=40)
        print(diagnostic.stdout, diagnostic.stderr, flush=True)
    assert result.returncode == 0, {'exitcode': result.returncode, 'stderr': result.stderr, 'stdout': result.stdout}
    snapshot = (directory / "bridge/claude_code-allowance.json").read_text()
    assert "private-smoke-canary" not in snapshot
    assert json.loads(snapshot)["buckets"][0]["remaining_percent"] == 100
    previous = directory / "previous.json"
    previous.write_text(json.dumps({"type": "command", "command": "echo Existing status"}), encoding="utf-8")
    result = subprocess.run([sys.argv[1], "--data-dir", temporary, "--provider", "claude_code", "--mode", "status", "--previous-file", str(previous)],
                            input='{}', text=True, capture_output=True, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == "Existing status"
    result = subprocess.run([sys.argv[1], "--data-dir", temporary, "--provider", "antigravity", "--mode", "hook", "--event", "PostInvocation"],
                            input='{"conversationId":"smoke","workspacePaths":[]}',
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == "{}"
    print("Packaged bridge smoke passed")

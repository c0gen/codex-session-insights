"""Probe the packaged review API using only an isolated synthetic index."""
import json
import re
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def check(executable, directory, env):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
    process = subprocess.Popen([str(executable), '--data-dir', str(directory), 'serve', '--port', str(port)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    try:
        deadline = time.monotonic() + 45
        token = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError('Packaged review server exited during startup')
            try:
                with urlopen(url, timeout=2) as response:
                    html = response.read().decode('utf-8')
                token = re.search(r'name="insights-token"\s+content="([^"]+)"', html).group(1)
                break
            except (URLError, TimeoutError):
                time.sleep(.1)
        assert token, 'Packaged review server did not become ready'

        def call(name, args=None):
            request = Request(url + '/api/' + name, data=json.dumps(args or {}).encode(),
                              headers={'Content-Type': 'application/json', 'X-Insights-Token': token})
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read())

        group = call('history_conflicts')[0]
        assert group['state'] == 'needs_review' and len(group['versions']) >= 2
        accepted = next(v for v in group['versions'] if v['accepted'])
        job = call('resolve_history_conflict', {'id': group['id'], 'revision': group['revision'], 'selected': accepted['id']})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            completion = next((j for j in call('status')['completed'] if j['id'] == job['job_id']), None)
            if completion:
                assert completion['state'] == 'completed', completion
                break
            time.sleep(.05)
        else:
            raise AssertionError('Packaged review selection did not finish')
        assert call('history_conflicts')[0]['state'] == 'manually_resolved'
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

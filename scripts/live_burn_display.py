"""Isolated production-browser rate probe; no account or application service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading


class DisplayProbe:
    def __init__(self, store, jobs, written, output, maintenance):
        from codex_insights.local_token_burn import LocalTokenBurn
        self.ready = threading.Event()
        rates = LocalTokenBurn(store)
        ready = self.ready
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                if self.path == '/ready':
                    ready.set()
                value = {'rates': rates.read_rates(), 'job': jobs.snapshot(), 'maintenance': dict(maintenance),
                    'written': [{'id': key, 'at': at['epoch'], 'expected': at['expected'], 'phase': at['phase']} for key, at in list(written.items())]}
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.output = Path(output).resolve()
        self.log = self.output.with_suffix('.log').open('w', encoding='utf-8')
        self.process = subprocess.Popen(['node', 'scripts/probe_live_burn.mjs',
            'http://127.0.0.1:' + str(self.server.server_port), str(self.output)],
            stdout=self.log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not self.ready.wait(30):
            self.close()
            raise RuntimeError('Browser rate probe did not start; inspect its local log')

    def result(self):
        if self.process.wait(timeout=15):
            raise RuntimeError('Browser rate probe failed; inspect its local log')
        return json.loads(self.output.read_text(encoding='utf-8'))

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.server.shutdown()
        self.server.server_close()
        self.log.close()

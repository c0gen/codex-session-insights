"""Loopback-only assets and authenticated browser-preview API."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

from .report import ui_directory


def start_server(engine, port=0):
    token = secrets.token_urlsafe(32)
    assets = ui_directory().resolve()
    if not (assets/"index.html").is_file():
        raise ValueError("Frontend assets missing. Run npm run build in frontend.")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def json(self,value,status=200):
            body=json.dumps(value).encode("utf-8")
            self.send_response(status);self.send_header("Content-Type","application/json")
            self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)))
            self.end_headers();self.wfile.write(body)
        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
        def do_GET(self):
            if not self.valid_host():
                self.json({"error":"Invalid host"},403);return
            relative=unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
            file=(assets/relative).resolve()
            if not file.is_relative_to(assets) or not file.is_file():
                self.send_error(404);return
            body=file.read_bytes()
            if file.name=='index.html':
                body=body.replace(b'__INSIGHTS_TOKEN__',token.encode())
            self.send_response(200)
            self.send_header("Content-Type",{'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css'}.get(file.suffix,'application/octet-stream'))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
        def do_POST(self):
            origin=self.headers.get("Origin")
            expected=f"http://127.0.0.1:{self.server.server_port}"
            if not self.valid_host() or (origin and origin!=expected) or not secrets.compare_digest(self.headers.get("X-Insights-Token",''),token):
                self.json({"error":"Invalid local request"},403);return
            if not self.path.startswith('/api/'):
                self.send_error(404);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>65536:
                    raise ValueError("Request too large")
                args=json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(args,dict):
                    raise ValueError("Invalid request")
                self.json(engine.call(self.path[5:],args))
            except Exception as exc:
                self.json({"error":str(exc)},400)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True,name='insights-assets').start()
    return server,f"http://127.0.0.1:{server.server_port}"

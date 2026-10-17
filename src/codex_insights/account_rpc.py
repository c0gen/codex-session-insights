"""Bounded, account-only stdio transport. Never log protocol payloads."""
from collections import deque
import json
import os
import queue
import subprocess
import threading
import time

from . import __version__


class AllowanceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class AccountRPC:
    def __init__(self, executable, timeout=15, popen=subprocess.Popen, home=None):
        self.timeout = timeout
        command = [executable, "app-server", "--listen", "stdio://"]
        options = {}
        if home is not None:
            # Child-only environment: never switch the user's main Codex login.
            environment = dict(os.environ, CODEX_HOME=str(home))
            for name in ("OPENAI_API_KEY", "CODEX_API_KEY"):
                environment.pop(name, None)
            options.update(env=environment, cwd=str(home))
            command += ["-c", 'cli_auth_credentials_store="file"',
                        "-c", 'forced_login_method="chatgpt"']
        try:
            self.process = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                 **options)
        except OSError:
            raise AllowanceError("missing_codex", "Could not start Codex. Check its installation and refresh.") from None
        self.messages = queue.Queue(maxsize=256)
        self.notifications = deque(maxlen=256)
        self.ended = threading.Event()
        self.close_lock = threading.Lock()
        self.closed = False
        self.sequence = 0
        self.reader = threading.Thread(target=self._read, daemon=True, name="insights-account-stdio")
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        self.messages.put_nowait(value)
                except (ValueError, TypeError):
                    continue
                except queue.Full:
                    break
        except (OSError, ValueError):
            pass
        finally:
            self.ended.set()

    def send(self, value):
        try:
            self.process.stdin.write(json.dumps(value) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise AllowanceError("connection", "Codex disconnected. Refresh to retry.") from None

    def _next(self, deadline):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AllowanceError("timeout", "Account read timed out. Retrying automatically.")
            try:
                return self.messages.get(timeout=min(remaining, .1))
            except queue.Empty:
                if self.ended.is_set():
                    raise AllowanceError("connection", "Codex disconnected. Refresh to retry.") from None

    def request(self, method, params=None):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while True:
            message = self._next(deadline)
            if message.get("id") != request_id:
                if "id" not in message:
                    self.notifications.append(message)
                continue
            if "error" in message:
                error = message["error"]
                if isinstance(error, dict) and error.get("code") == -32601:
                    raise AllowanceError("unsupported", "This Codex version does not support this feature. Update Codex to enable it.")
                # Server errors may contain URLs or tokens. Only fixed messages leave this module.
                raise AllowanceError("connection", "Codex could not read this account. Reconnect or refresh to retry.")
            result = message.get("result")
            if not isinstance(result, dict):
                raise AllowanceError("connection", "Codex returned an unavailable account response.")
            return result

    def initialize(self):
        self.request("initialize", {"clientInfo": {"name": "codex_session_insights",
                     "title": "Codex Session Insights", "version": __version__}})
        self.send({"method": "initialized", "params": {}})

    def notification(self, method, timeout=.2):
        for message in list(self.notifications):
            if message.get("method") == method:
                self.notifications.remove(message)
                return message.get("params", {})
        deadline = time.monotonic() + timeout
        while True:
            try:
                message = self._next(deadline)
            except AllowanceError as error:
                if error.code == "timeout":
                    return None
                raise
            if message.get("method") == method:
                return message.get("params", {})
            if "id" not in message:
                self.notifications.append(message)

    def close(self):
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
            except OSError:
                pass
            self.reader.join(timeout=1)
            for stream in (self.process.stdin, self.process.stdout):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass

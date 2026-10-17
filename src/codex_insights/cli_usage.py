"""Bounded, cancellable execution of an official client's read-only command."""
import os
import subprocess
import threading
from pathlib import Path

from .account_rpc import AllowanceError
from .providers.bridge_io import MAX_INPUT


class UsageCommand:
    label = "CLI"
    removed_environment = ()
    missing_code = "missing_cli"

    def __init__(self, workspace, executable=None, timeout=30, discover=lambda: None, popen=subprocess.Popen):
        self.workspace, self.executable, self.timeout = Path(workspace), executable, timeout
        self.discover, self.popen = discover, popen
        self.lock = threading.Lock()
        self.process = None
        self.closed = False
        self.last_returncode = None

    def _spawn(self, arguments):
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        environment = {k: v for k, v in os.environ.items() if k not in self.removed_environment}
        return self.popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, cwd=str(self.workspace), env=environment, **options)

    def _run(self, arguments, timeout):
        from .account_storage import protect_directory
        protect_directory(self.workspace)
        with self.lock:
            if self.closed:
                raise AllowanceError("stopping", f"{self.label} usage check is closing.")
            try:
                process = self.process = self._spawn(arguments)
            except OSError:
                raise AllowanceError(self.missing_code, f"Could not start {self.label}. Check its installation and refresh.") from None
        output = []
        reader = threading.Thread(target=lambda: output.append(process.stdout.read(MAX_INPUT + 1)), daemon=True)
        reader.start()
        reader.join(timeout)
        try:
            if reader.is_alive():
                self._kill(process)
                raise AllowanceError("timeout", f"{self.label} did not answer in time. Retrying automatically.")
            data = output[0] if output else b""
            if len(data) > MAX_INPUT:
                self._kill(process)
                raise AllowanceError("invalid_report", f"{self.label}'s usage output was too large to read.")
            try:
                self.last_returncode = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._kill(process)
                raise AllowanceError("timeout", f"{self.label} did not exit after its report.") from None
            return data
        finally:
            with self.lock:
                if self.process is process:
                    self.process = None

    @staticmethod
    def _kill(process):
        try:
            if os.name == "nt" and isinstance(process, subprocess.Popen):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            process.kill()
            process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            pass

    def close(self):
        with self.lock:
            self.closed = True
            process = self.process
        if process is not None:
            self._kill(process)

"""Codex-managed account reads and browser login in an optional isolated home."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

from .account_rpc import AccountRPC, AllowanceError
from .account_identity import AccountIdentity, confirmed_member_identity, fingerprint


_UNCHANGED = object()


def find_codex():
    names = ("codex.exe",) if os.name == "nt" else ("codex",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    candidates = []
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates.extend(local / "Programs/OpenAI/Codex" / suffix for suffix in
                          ("bin/codex.exe", "resources/codex.exe", "app/resources/codex.exe"))
        try:
            packages = sorted((Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WindowsApps").glob("OpenAI.Codex_*"), reverse=True)
            candidates.extend(p / "app/resources/codex.exe" for p in packages)
        except OSError:
            pass
    else:
        candidates.extend([Path("/Applications/Codex.app/Contents/Resources/codex"),
                           Path.home() / "Applications/Codex.app/Contents/Resources/codex"])
    return next((str(p) for p in candidates if p.is_file()), None)


class AppServerProvider:
    def __init__(self, executable=None, timeout=15, discover=find_codex, popen=subprocess.Popen, home=None):
        self.executable, self.timeout, self.discover, self.popen = executable, timeout, discover, popen
        self.home = home
        self.lock = threading.RLock()
        self.operation = threading.Lock()
        self.client = self.process = None
        self.closed = False
        self.base_identity = self.account_id = None
        self.plan = None

    @contextmanager
    def session(self):
        # Serialize one credential store, including refresh-token rotation.
        with self.operation:
            with self.lock:
                if self.closed:
                    raise AllowanceError("stopping", "Account connection is closing.")
                executable = self.executable or self.discover()
                if not executable:
                    raise AllowanceError("missing_codex", "Install Codex or add its executable to PATH, then refresh.")
                client = AccountRPC(executable, self.timeout, self.popen, self.home)
                self.client, self.process = client, client.process
            try:
                client.initialize()
                yield client
            finally:
                client.close()
                with self.lock:
                    if self.client is client:
                        self.client = self.process = None

    def _identity(self, account, changed, account_id=_UNCHANGED):
        if not isinstance(account, dict) or account.get("type") not in {"chatgpt", "chatgptAuthTokens", "agentIdentity", "personalAccessToken"}:
            self.base_identity = self.account_id = self.plan = None
            changed(None)
            raise AllowanceError("sign_in", "Sign in to Codex with ChatGPT, then refresh this account.")
        identity = fingerprint({k: v for k, v in account.items() if k != "planType"})
        if identity != self.base_identity:
            self.base_identity, self.account_id = identity, None
        if account_id is not _UNCHANGED:
            self.account_id = account_id if isinstance(account_id, str) and account_id.strip() else None
        self.plan = account.get("planType") if isinstance(account.get("planType"), str) else None
        changed(AccountIdentity(fingerprint([identity, self.account_id]),
                                confirmed_member_identity(account, self.account_id)))

    def fetch(self, account_changed):
        with self.session() as client:
            account = client.request("account/read", {"refreshToken": False}).get("account")
            self._identity(account, account_changed)
            value = client.request("account/rateLimits/read")
            if value.get("accountId") != self.account_id:
                self._identity(account, account_changed, value.get("accountId"))
            return value

    def fetch_history(self, account_changed):
        with self.session() as client:
            account = client.request("account/read", {"refreshToken": False}).get("account")
            self._identity(account, account_changed)
            # Read history first: a hung allowance request may make this RPC
            # process unusable, but cannot discard already successful history.
            history = client.request("account/usage/read")
            # Bind each new history read to a freshly verified workspace. Equal
            # account/read fields (including email) cannot detect workspace
            # switches. An unavailable identity endpoint must not attach the
            # previous workspace's stable ID to this history.
            try:
                identity = client.request("account/rateLimits/read").get("accountId")
            except AllowanceError:
                identity = None
            self._identity(account, account_changed, identity)
            # History remains independently usable after allowance failure.
            return history

    def login(self, opened, cancel, timeout=300):
        if self.home is None:
            raise AllowanceError("protected", "The current Codex sign-in is managed by Codex.")
        deadline = time.monotonic() + timeout
        with self.session() as client:
            value = client.request("account/login/start", {"type": "chatgpt"})
            login_id, url = value.get("loginId"), value.get("authUrl")
            if not isinstance(login_id, str) or not isinstance(url, str):
                raise AllowanceError("connection", "Codex did not return a browser sign-in link.")
            opened(url)
            while not cancel.is_set() and time.monotonic() < deadline:
                message = client.notification("account/login/completed")
                if message and message.get("loginId") == login_id:
                    if message.get("success") is not True:
                        raise AllowanceError("sign_in", "Sign-in did not complete. Try connecting again.")
                    return
            try:
                client.request("account/login/cancel", {"loginId": login_id})
            except AllowanceError:
                pass
            raise AllowanceError("cancelled" if cancel.is_set() else "login_timeout",
                                 "Sign-in cancelled." if cancel.is_set() else "Sign-in expired after five minutes. Try again.")

    def logout(self):
        if self.home is None:
            raise AllowanceError("protected", "The current Codex sign-in is managed by Codex.")
        with self.session() as client:
            client.request("account/logout")

    def close(self):
        with self.lock:
            self.closed = True
            client = self.client
        if client:
            client.close()

"""One cancellable browser login, independent of all account refresh workers."""
import threading
from urllib.parse import urlsplit

from .account_rpc import AllowanceError


class AccountLogin:
    def __init__(self, opener, timeout=300):
        self.opener, self.timeout = opener, timeout
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.thread = self.provider = None
        self.url = None
        self.state = {"status": "idle"}

    def read(self):
        with self.lock:
            result = dict(self.state)
            if self.state["status"] == "waiting" and self.url:
                result["url"] = self.url
            return result

    def start(self, identifier, account_label, provider, completed):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("Finish or cancel the current sign-in first.")
            self.cancel_event.clear()
            self.provider, self.url = provider, None
            self.state = {"status": "starting", "account_id": identifier, "label": account_label, "error": None}

            def opened(url):
                parsed = urlsplit(url)
                hostname = parsed.hostname or ""
                if parsed.scheme != "https" or parsed.username or parsed.password or not any(
                    hostname == domain or hostname.endswith("." + domain) for domain in ("openai.com", "chatgpt.com")):
                    raise AllowanceError("connection", "Codex returned an unexpected sign-in URL.")
                with self.lock:
                    if self.cancel_event.is_set():
                        return
                    self.url = url
                    self.state["status"] = "waiting"
                try:
                    if not self.opener(url):
                        raise OSError()
                except Exception:
                    with self.lock:
                        self.state["error"] = "The browser could not be opened. Choose Open sign-in page to retry."

            def run():
                success, error, status = False, None, "failed"
                try:
                    provider.login(opened, self.cancel_event, self.timeout)
                    success = not self.cancel_event.is_set()
                    status = "completed" if success else "cancelled"
                except Exception as exc:
                    status = "cancelled" if self.cancel_event.is_set() else "failed"
                    error = str(exc) if isinstance(exc, AllowanceError) else "Account sign-in failed. Try again."
                finally:
                    provider.close()
                    try:
                        completed(success)
                    except Exception:
                        status, error = "failed", "The connection could not be saved. Try connecting again."
                    with self.lock:
                        self.url = None
                        self.state.update(status=status, error=error)
            self.thread = threading.Thread(target=run, daemon=True, name="insights-account-login")
            self.thread.start()
            return self.read()

    def open_browser(self):
        with self.lock:
            url = self.url
        if not url:
            raise ValueError("No browser sign-in is pending.")
        try:
            if self.opener(url):
                return {"status": "opened"}
        except Exception:
            pass
        raise ValueError("Could not open the browser. Check your default browser and retry.")

    def cancel(self):
        with self.lock:
            if self.state["status"] not in {"starting", "waiting", "cancelling"}:
                return self.read()
            self.cancel_event.set()
            self.state["status"] = "cancelling"
        # The login loop sends account/login/cancel; regular network reads are bounded.
        return self.read()

    def close(self):
        self.cancel_event.set()
        if self.provider:
            self.provider.close()
        if self.thread:
            self.thread.join(timeout=3)

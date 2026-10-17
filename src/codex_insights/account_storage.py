"""Non-secret connection registry and private, app-owned Codex homes."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re


def protect_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    security.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    token, sid_text, descriptor = wintypes.HANDLE(), wintypes.LPWSTR(), ctypes.c_void_p()
    try:
        if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError()
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise OSError()
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not security.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError()
        # Protected DACL; child files inherit only this Windows user's full access.
        sddl = f"D:P(A;OICI;FA;;;{sid_text.value})"
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise OSError()
        if not security.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise OSError()
    except OSError:
        raise ValueError("Could not protect the account directory. No sign-in was started.") from None
    finally:
        if token:
            kernel.CloseHandle(token)
        if sid_text:
            kernel.LocalFree(sid_text)
        if descriptor:
            kernel.LocalFree(descriptor)


def connection_id(value):
    return isinstance(value, str) and (value == "current" or re.fullmatch(r"[0-9a-f]{32}", value) is not None)


def label(value):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 80:
        raise ValueError("Enter an account label of 1–80 characters.")
    return value.strip()


class AccountRegistry:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.path = self.directory / "account-connections.json"
        self.root = self.directory / "account-profiles"
        self.error = None

    def load(self):
        default = {"id": "current", "label": "Current Codex", "enabled": True}
        try:
            if not self.path.exists():
                return [default]
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, list):
                raise ValueError()
            result, seen = [], set()
            for entry in value:
                if not isinstance(entry, dict) or not connection_id(entry.get("id")) or entry["id"] in seen:
                    raise ValueError()
                if type(entry.get("enabled")) is not bool:
                    raise ValueError()
                seen.add(entry["id"])
                result.append({"id": entry["id"], "label": label(entry.get("label")), "enabled": entry["enabled"]})
            if "current" not in seen:
                result.insert(0, default)
            return result
        except (OSError, ValueError):
            self.error = "Saved account connections could not be read. Restore account-connections.json before changing connections."
            return [default]

    def save(self, entries):
        if self.error:
            raise ValueError(self.error)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(entries, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            raise ValueError("Account preferences could not be saved. Try again.") from None

    def home(self, identifier, create=False):
        if not connection_id(identifier) or identifier == "current":
            raise ValueError("Choose an added account.")
        home = self.root / identifier
        if not home.resolve().is_relative_to(self.directory) or home.resolve().parent != self.root.resolve():
            raise ValueError("Account directory is outside the app's data folder.")
        if create:
            protect_directory(self.root)
            protect_directory(home)
        return home

    def forget_credentials(self, identifier):
        # Only this known credential file is removed; never recursively remove a Codex home.
        self.home(identifier).joinpath("auth.json").unlink(missing_ok=True)

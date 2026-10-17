"""Windows per-index process ownership and activation without a network endpoint."""
import ctypes
import hashlib
import os
import threading
from ctypes import wintypes
from pathlib import Path


def instance_key(directory):
    path = os.path.normcase(str(Path(directory).expanduser().resolve()))
    return "Local\\CodexSessionInsights-" + hashlib.sha256(path.encode()).hexdigest()[:32]


class SingleInstance:
    def __init__(self, directory):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateEventW.restype = wintypes.HANDLE
        for name in ("CloseHandle", "SetEvent", "ReleaseMutex"):
            getattr(self.api, name).argtypes = [wintypes.HANDLE]
            getattr(self.api, name).restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.stopped = threading.Event()
        self.thread = None
        key = instance_key(directory)
        self.mutex = self.api.CreateMutexW(None, False, key)
        self.event = self.api.CreateEventW(None, False, False, key + "-activate")
        if not self.mutex or not self.event:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        # Abandoned mutexes are acquired after a crashed owner, even if another
        # launch still briefly holds a handle to the old kernel object.
        result = self.api.WaitForSingleObject(self.mutex, 0)
        self.owner = result in (0, 0x80)
        if result not in (0, 0x80, 0x102):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.owner:
            self.api.SetEvent(self.event)

    def listen(self, activate):
        def wait():
            while not self.stopped.is_set():
                if self.api.WaitForSingleObject(self.event, 250) == 0 and not self.stopped.is_set():
                    activate()
        self.thread = threading.Thread(target=wait, daemon=True, name="insights-activation")
        self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=1)
        if getattr(self, "owner", False) and self.mutex:
            self.api.ReleaseMutex(self.mutex)
        for key in ("event", "mutex"):
            handle = getattr(self, key, None)
            if handle:
                self.api.CloseHandle(handle)
                setattr(self, key, None)

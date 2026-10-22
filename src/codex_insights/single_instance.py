"""Windows per-index process ownership and activation without a network endpoint."""
import ctypes
import hashlib
import os
import threading
from ctypes import wintypes
from pathlib import Path

WAIT_OBJECT_0, WAIT_ABANDONED = 0, 0x80


def instance_key(directory):
    path = os.path.normcase(str(Path(directory).expanduser().resolve()))
    return "Local\\CodexSessionInsights-" + hashlib.sha256(path.encode()).hexdigest()[:32]


class SingleInstance:
    """A running owner acknowledges activation; a closing owner hands over its index.

    A launch during the previous window's shutdown used to signal a listener
    that had already stopped and exit silently. Without an acknowledgement it
    now waits for the closing process to release the mutex, then starts.
    """
    def __init__(self, directory, ack_timeout=3000, handoff_timeout=30000):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateMutexW.restype = wintypes.HANDLE
        self.api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.api.CreateEventW.restype = wintypes.HANDLE
        for name in ("CloseHandle", "SetEvent", "ResetEvent", "ReleaseMutex"):
            getattr(self.api, name).argtypes = [wintypes.HANDLE]
            getattr(self.api, name).restype = wintypes.BOOL
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.stopped = threading.Event()
        self.thread = None
        self.owner = self.handed_over = self.acknowledged = False
        key = instance_key(directory)
        self.mutex = self.api.CreateMutexW(None, False, key)
        self.event = self.api.CreateEventW(None, False, False, key + "-activate")
        self.ack = self.api.CreateEventW(None, False, False, key + "-activated")
        if not self.mutex or not self.event or not self.ack:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        # Abandoned mutexes are acquired after a crashed owner, even if another
        # launch still briefly holds a handle to the old kernel object.
        result = self.api.WaitForSingleObject(self.mutex, 0)
        self.owner = result in (WAIT_OBJECT_0, WAIT_ABANDONED)
        if result not in (WAIT_OBJECT_0, WAIT_ABANDONED, 0x102):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if self.owner:
            return
        self.api.ResetEvent(self.ack)
        self.api.SetEvent(self.event)
        if self.api.WaitForSingleObject(self.ack, ack_timeout) == WAIT_OBJECT_0:
            self.acknowledged = True  # The running window was shown.
            return
        # No listener answered: the owner is closing. Take over once it exits.
        result = self.api.WaitForSingleObject(self.mutex, handoff_timeout)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self.owner = self.handed_over = True
            self.api.ResetEvent(self.event)  # Our own request, not a later launch.

    def listen(self, activate):
        def wait():
            while not self.stopped.is_set():
                if self.api.WaitForSingleObject(self.event, 250) == WAIT_OBJECT_0 and not self.stopped.is_set():
                    # Acknowledge before activating: a busy GUI thread must not
                    # make the new launch mistake this window for a closing one.
                    self.api.SetEvent(self.ack)
                    activate()
        self.thread = threading.Thread(target=wait, daemon=True, name="insights-activation")
        self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
        if getattr(self, "owner", False) and self.mutex:
            self.api.ReleaseMutex(self.mutex)
            self.owner = False
        for key in ("ack", "event", "mutex"):
            handle = getattr(self, key, None)
            if handle:
                self.api.CloseHandle(handle)
                setattr(self, key, None)

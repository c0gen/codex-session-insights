"""Open the native shell before index construction, backups or migrations."""
import logging
from pathlib import Path
import threading
from types import SimpleNamespace

from .dashboard_cache import OverviewSnapshot


class DeferredEngine:
    def __init__(self, directory, demo=False, exporter=False, factory=None):
        self.directory, self.demo, self.exporter = Path(directory), demo, exporter
        self.factory = factory
        self._engine, self.error = None, None
        self.ready, self.stop, self.cancel = threading.Event(), threading.Event(), threading.Event()
        self._window = self._desktop = None
        self._callbacks, self._lock = [], threading.RLock()
        self._thread = None
        self.snapshot = OverviewSnapshot(directory)

    @property
    def store(self):
        return self._engine.store if self._engine else SimpleNamespace(directory=self.directory)

    @property
    def window(self):
        return self._window

    @window.setter
    def window(self, value):
        self._window = value
        if self._engine:
            self._engine.window = value

    @property
    def desktop(self):
        return self._desktop

    @desktop.setter
    def desktop(self, value):
        self._desktop = value
        if self._engine:
            self._engine.desktop = value

    def start(self):
        with self._lock:
            if self._thread is None and not self.stop.is_set():
                self._thread = threading.Thread(target=self._initialize, name='insights-startup', daemon=True)
                self._thread.start()

    def _initialize(self):
        try:
            if self.factory is None:
                from .service import Engine
                self.factory = Engine
            engine = self.factory(self.directory, self.demo, self.exporter, defer_projection=True)
            engine.window, engine.desktop = self._window, self._desktop
            self._engine = engine
            if self.stop.is_set():
                engine.close()
                return
            engine.start()
        except Exception:
            logging.exception('Background initialization failed')
            self.error = 'The local usage index could not be opened. See startup diagnostics for recovery.'
        finally:
            self.ready.set()
        with self._lock:
            callbacks, self._callbacks = self._callbacks, []
        if not self.error and not self.stop.is_set():
            for callback in callbacks:
                callback()

    def when_ready(self, callback):
        with self._lock:
            if not self.ready.is_set():
                self._callbacks.append(callback)
                return
        if not self.error and not self.stop.is_set():
            callback()

    def call(self, action, args=None):
        self.start()
        if action == 'bootstrap':
            if self.ready.is_set() and self._engine and not self.error:
                return self._engine.call(action, args)
            return {'ready': self.ready.is_set() and not self.error,
                    'cached_overview': None if self.demo or self.exporter else self.snapshot.load(args or {}), 'error': self.error}
        if action == 'live_status' and not self.ready.is_set():
            return {'ready': False}
        while not self.ready.wait(.1):
            if self.stop.is_set():
                raise ValueError('The app is closing.')
        if self.error:
            raise ValueError(self.error)
        return self._engine.call(action, args)

    def begin_close(self):
        """Quit begins winding the real engine down while the window closes."""
        self.stop.set()
        self.cancel.set()
        begin_close = getattr(self._engine, 'begin_close', None)
        if begin_close:
            begin_close()

    def close(self):
        self.begin_close()
        if self._engine:
            self._engine.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def __getattr__(self, name):
        if self._engine:
            return getattr(self._engine, name)
        raise AttributeError(name)

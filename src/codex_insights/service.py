"""Shared app/exporter orchestration, background jobs and native-dialog API."""
import json
import platform
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

from .ingestion import refresh, register_defaults
from .pricing_catalog import apply_catalog, import_catalog
from .projection import rebuild_projection
from .queries import dashboard
from .storage import Store
from .transfers import export_snapshot, import_snapshot


class Engine:
    def __init__(self, directory, demo=False, exporter=False):
        self.store = Store(directory)
        self.exporter = exporter
        self.window = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="insights-indexer")
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.dirty = threading.Event()
        self.job_lock = threading.Lock()
        self.job = {"running":False,"message":"Ready","progress":{},"error":None}
        self.observer = None
        if self.store.setting("timezone") is None:
            try:
                from tzlocal import get_localzone_name
                zone = get_localzone_name()
            except ImportError:
                zone = "UTC"
            self.store.set_setting("timezone", zone)
        self.store.set_setting("device_label", self.store.setting("device_label", "Intel Mac" if platform.system()=="Darwin" else "Windows PC"))
        if self.store.setting("pricing_catalog"):
            apply_catalog(self.store.setting("pricing_catalog"))
        if demo:
            from .demo import seed_demo
            seed_demo(self.store)
        elif not self.store.sources():
            register_defaults(self.store)

    def submit(self, message, action):
        with self.job_lock:
            if self.job["running"]:
                return {"status":"busy"}
            self.cancel.clear()
            self.job = {"running":True,"message":message,"progress":{},"error":None}
        def work():
            try:
                result = action()
                with self.job_lock:
                    self.job.update(running=False, message="Cancelled" if self.cancel.is_set() else "Up to date", result=result)
            except Exception as exc:
                with self.job_lock:
                    self.job.update(running=False,message="Update failed",error=str(exc))
        self.executor.submit(work)
        return {"status":"started"}

    def progress(self, value):
        with self.job_lock:
            self.job["progress"] = value

    def refresh(self, rebuild=False):
        if self.store.setting("demo", False):
            return {"status":"unchanged"}
        return self.submit("Rebuilding index" if rebuild else "Reading session updates", lambda:refresh(self.store,self.progress,self.cancel,rebuild))

    def start(self):
        if self.store.setting("demo", False):
            return
        self.refresh()
        self.configure_watchers()
        def watch():
            last_scan = time.monotonic()
            while not self.stop.wait(1):
                if self.dirty.is_set() or time.monotonic()-last_scan >= 30:
                    self.dirty.clear()
                    result = self.refresh()
                    if result["status"] == "busy":
                        self.dirty.set()
                    else:
                        last_scan = time.monotonic()
        self.watch_thread = threading.Thread(target=watch,daemon=True)
        self.watch_thread.start()

    def configure_watchers(self):
        if self.observer:
            self.observer.stop(); self.observer.join(timeout=3)
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
            engine = self
            class Events(FileSystemEventHandler):
                def on_any_event(self,event):
                    if event.event_type in {"created","modified","moved","deleted"} and (event.is_directory or event.src_path.endswith(".jsonl")):
                        engine.dirty.set()
            observer = Observer()
            for source in self.store.sources():
                if source["kind"] == "folder" and source["enabled"] and source["root"] and Path(source["root"]).is_dir():
                    observer.schedule(Events(), source["root"], recursive=True)
            observer.start(); self.observer = observer
        except (ImportError,OSError):
            self.observer = None

    def close(self):
        self.stop.set(); self.cancel.set()
        if self.observer:
            self.observer.stop(); self.observer.join(timeout=3)
        self.executor.shutdown(wait=True,cancel_futures=True)

    def choose(self, kind, filename=""):
        if not self.window:
            raise ValueError("File dialogs are available in the desktop app. Use the CLI for headless transfers.")
        import webview
        mode = {"folder":webview.FileDialog.FOLDER,"open":webview.FileDialog.OPEN,"save":webview.FileDialog.SAVE}[kind]
        result = self.window.create_file_dialog(mode,save_filename=filename)
        return result[0] if isinstance(result,(list,tuple)) and result else result or None

    def call(self, action, args=None):
        args = args or {}
        if action == "dashboard":
            data = dashboard(self.store,args)
            with self.job_lock:
                data["job"] = dict(self.job)
            data["exporter"] = self.exporter
            return data
        if action == "status":
            with self.job_lock:
                return {**self.job,"revision":self.store.setting("data_revision",0)}
        if action == "refresh":
            return self.refresh(bool(args.get("rebuild")))
        if action == "cancel":
            self.cancel.set(); return {"status":"cancelling"}
        if action == "add_source":
            path = self.choose("folder")
            if not path:
                return {"status":"cancelled"}
            sid = self.store.add_source(path,args.get("label"))
            self.configure_watchers(); self.refresh()
            return {"source_id":sid}
        if action in {"source_enabled","forget_source"}:
            sid = args["id"]
            def update_sources():
                if action == "forget_source":
                    self.store.forget_source(sid)
                else:
                    with self.store.connect() as db:
                        db.execute("UPDATE sources SET enabled=? WHERE id=?",(int(bool(args["enabled"])),sid))
                rebuild_projection(self.store)
                self.configure_watchers()
            return self.submit("Updating included sources",update_sources)
        if action == "export":
            path = self.choose("save", "usage.codex-insights")
            return {"status":"cancelled"} if not path else self.submit("Exporting compact usage",lambda:export_snapshot(self.store,path,self.store.setting("device_label","This computer")))
        if action == "import":
            path = self.choose("open")
            return {"status":"cancelled"} if not path else self.submit("Importing usage snapshot",lambda:import_snapshot(self.store,path))
        if action == "settings":
            zone = str(args.get("timezone",self.store.setting("timezone")))
            ZoneInfo(zone)
            fast = float(args.get("assumed_fast_percent",0))
            if not 0 <= fast <= 100:
                raise ValueError("Fast share must be between 0 and 100")
            def update_settings():
                self.store.set_setting("timezone",zone)
                self.store.set_setting("assumed_fast_percent",fast)
                self.store.set_setting("device_label",str(args.get("device_label","This computer"))[:200])
                rebuild_projection(self.store)
            return self.submit("Updating timezone and pricing",update_settings)
        if action == "alias":
            projects = dashboard(self.store)["options"]["projects"]
            target = next(p for p in projects if p["id"] == args["target"])
            def update_alias():
                aliases = self.store.setting("project_aliases",{})
                aliases[args["source"]] = target
                self.store.set_setting("project_aliases",aliases)
                rebuild_projection(self.store)
            return self.submit("Merging project groups",update_alias)
        if action == "import_pricing":
            path = self.choose("open")
            if not path:
                return {"status":"cancelled"}
            def update():
                result = import_catalog(self.store,path); rebuild_projection(self.store); return result
            return self.submit("Updating pricing catalog",update)
        if action == "export_html":
            from .report import export_html
            path = self.choose("save","codex-insights-report.html")
            if not path:
                return {"status":"cancelled"}
            return self.submit("Exporting HTML report",lambda:export_html(dashboard(self.store,args.get("filters")),path,bool(args.get("anonymous",True))))
        raise ValueError("Unknown app action")

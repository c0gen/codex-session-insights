"""Shared app/exporter orchestration, background jobs and native-dialog API."""
import json
import platform
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from .ingestion import refresh, register_defaults, register_provider_defaults
from .jobs import Jobs
from .pricing_catalog import apply_catalog, import_catalog
from .projection import PROJECTION_VERSION, ensure_projection, rebuild_projection
from .queries import dashboard
from .storage import Store
from .transfers import import_snapshot
from .snapshot_export import export_usage
from . import project_groups
from .accounts import Accounts
from .claude_usage import ClaudeUsage
from .antigravity_usage import AntigravityUsage
from .local_token_burn import LocalTokenBurn


class Engine:
    def __init__(self, directory, demo=False, exporter=False, allowance_provider=None, defer_projection=False):
        self.store = Store(directory)
        self.exporter = exporter
        self.window = None
        self.desktop = None
        from .widget_queries import WidgetSummaries
        self.widget_summaries = WidgetSummaries(self.store)
        self.jobs = Jobs()
        self.executor = self.jobs.executor
        self.stop, self.cancel, self.dirty = self.jobs.stop, self.jobs.cancel, self.jobs.dirty
        self.job_lock = self.jobs.lock
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
        if not demo and not self.store.setting("provider_defaults_registered", False):
            register_provider_defaults(self.store)
            self.store.set_setting("provider_defaults_registered", True)
        if not demo:
            from .providers.profiles import register_claude_profiles
            register_claude_profiles(self.store)
        from .providers.setup import Setup
        self.provider_setup = Setup(self.store.directory)
        from .providers.legacy.setup import LegacySources
        self.legacy_sources = LegacySources(self.store)
        # Headless commands must read corrected records. Native startup defers
        # expensive maintenance until its window is visible.
        if not defer_projection:
            ensure_projection(self.store)
        self.accounts = Accounts(self.store.directory, current_provider=allowance_provider,
                                 enabled=self.store.setting("live_usage_enabled", True),
                                 allowed=not (self.store.setting("demo", False) or exporter))
        self.usage_limits = self.accounts.current
        self.claude_usage = ClaudeUsage(self.store.directory, enabled=self.store.setting("claude_usage_enabled", False),
                                        allowed=not (self.store.setting("demo", False) or exporter))
        self.antigravity_usage = AntigravityUsage(self.store.directory,
            enabled=self.store.setting('antigravity_usage_enabled', False),
            allowed=not (self.store.setting('demo', False) or exporter))
        self.local_token_burn = LocalTokenBurn(self.store,
            allowed=not (self.store.setting("demo", False) or exporter))

    @property
    def job(self):
        return self.jobs.job

    def submit(self, message, action, **options):
        return self.jobs.submit(message, action, **options)

    def progress(self, value):
        self.jobs.progress(value)

    def refresh(self, rebuild=False, automatic=False):
        if self.store.setting("demo", False):
            return {"status":"unchanged"}
        result = self.submit(
            "Rebuilding index" if rebuild else "Reading session updates",
            lambda: refresh(self.store, self.progress, self.cancel, rebuild, automatic),
            origin="automatic" if automatic else "user", cancelable=True,
            key="automatic-refresh" if automatic else "rebuild" if rebuild else "refresh")
        if result["status"] == "deferred":
            self.dirty.set()
        return result

    def start(self):
        if getattr(self, "_started", False):
            return
        self._started = True
        if (self.store.setting('projection_version') != PROJECTION_VERSION
                or self.store.setting('bucket_version') != 1 or self.store.setting('project_groups_version') != 1):
            def maintenance():
                ensure_projection(self.store, self.progress)
                if self.store.setting('project_groups_version') != 1:
                    project_groups.migrate(self.store, self.progress, self.stop)
                if self.store.setting('bucket_version') != 1:
                    from .buckets import rebuild_buckets
                    rebuild_buckets(self.store)
            self.submit('Updating usage index', maintenance, origin="user", key="index-upgrade")
        self.accounts.start()
        self.claude_usage.start()
        self.antigravity_usage.start()
        if self.store.setting("demo", False):
            return
        self.refresh(automatic=True)
        self.configure_watchers()
        def watch():
            while not self.stop.wait(1):
                if self.jobs.automatic_ready(self.dirty.is_set()):
                    self.dirty.clear()
                    self.refresh(automatic=True)
        self.watch_thread = threading.Thread(target=watch,daemon=True)
        self.watch_thread.start()

    def configure_watchers(self):
        if self.observer:
            self.observer.stop(); self.observer.join(timeout=3)
        if self.stop.is_set():
            return
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
            engine = self
            class Events(FileSystemEventHandler):
                def __init__(self, suffix='.jsonl'):
                    super().__init__()
                    self.suffix = suffix
                def on_any_event(self,event):
                    if event.event_type in {"created","modified","moved","deleted"} and (event.is_directory or event.src_path.lower().endswith(self.suffix)):
                        engine.dirty.set()
            observer = Observer()
            for source in self.store.sources():
                if source["kind"] in {"folder", "bridge"} and source["enabled"] and source["root"] and Path(source["root"]).is_dir():
                    if source.get('format') == 'antigravity_legacy':
                        continue
                    else:
                        observer.schedule(Events(), source["root"], recursive=True)
            observer.start(); self.observer = observer
        except (ImportError,OSError):
            self.observer = None

    def close(self):
        self.stop.set(); self.cancel.set()
        self.accounts.close()
        self.claude_usage.close()
        self.antigravity_usage.close()
        if getattr(self, "watch_thread", None):
            self.watch_thread.join(timeout=3)
        self.jobs.close()
        if self.observer:
            self.observer.stop(); self.observer.join(timeout=3)

        if self.desktop:
            self.desktop.dispose()
            self.desktop = None

    def choose(self, kind, filename=""):
        if not self.window:
            raise ValueError("File dialogs are available in the desktop app. Use the CLI for headless transfers.")
        import webview
        mode = {"folder":webview.FileDialog.FOLDER,"open":webview.FileDialog.OPEN,"save":webview.FileDialog.SAVE}[kind]
        result = self.window.create_file_dialog(mode,save_filename=filename)
        return result[0] if isinstance(result,(list,tuple)) and result else result or None

    def provider_allowances(self):
        from .providers.allowances import read
        return read(self.store.directory, live={"claude_code": self.claude_usage.read(), 'antigravity': self.antigravity_usage.read()})

    def call(self, action, args=None):
        args = args or {}
        if action == 'refresh_antigravity_usage':
            return self.antigravity_usage.refresh()
        if action == 'antigravity_usage_settings':
            enabled = args.get('enabled')
            if type(enabled) is not bool:
                raise ValueError('Antigravity usage switch must be true or false')
            if not self.antigravity_usage.allowed:
                raise ValueError('Antigravity usage checks are unavailable in demo and exporter modes')
            self.antigravity_usage.configure(enabled)
            return self.submit('Saving Antigravity usage preference', lambda: self.store.set_setting('antigravity_usage_enabled', enabled))
        if action in {'legacy_source_preview', 'add_legacy_source'}:
            raise ValueError('Encrypted Antigravity archive collection is disabled. Use public transcripts and official hooks.')
        if action == "provider_setup_preview":
            return self.provider_setup.preview(args["target"])
        if action == "provider_setup":
            if self.store.setting("demo", False):
                raise ValueError("Provider setup is disabled in demo mode")
            return self.provider_setup.update(args["target"], args["operation"])
        if action == "provider_allowances":
            return self.provider_allowances()
        if action == "refresh_claude_usage":
            return self.claude_usage.refresh()
        if action == "claude_usage_settings":
            enabled = args.get("enabled")
            if type(enabled) is not bool:
                raise ValueError("Claude usage switch must be true or false")
            if not self.claude_usage.allowed:
                raise ValueError("Claude usage checks are unavailable in demo and exporter modes")
            self.claude_usage.configure(enabled)
            return self.submit("Saving Claude usage preference", lambda: self.store.set_setting("claude_usage_enabled", enabled))
        if action == "accounts":
            return self.local_token_burn.decorate(self.accounts.read())
        if action == "account_refresh":
            result = self.accounts.refresh(args.get("id"))
            if args.get("refresh_local") is True:
                self.refresh()
            return result
        if action == "account_settings":
            return self.local_token_burn.decorate(self.accounts.update(
                args.get("id"), {k: v for k, v in args.items() if k != "id"}))
        if action == "account_login_start":
            return self.accounts.connect(args.get("label"), args.get("id"))
        if action == "account_login_status":
            return self.accounts.login.read()
        if action == "account_login_cancel":
            return self.accounts.login.cancel()
        if action == "account_login_open":
            return self.accounts.login.open_browser()
        if action == "account_remove":
            return self.accounts.remove(args.get("id"))
        if action == "usage_limits":
            return self.local_token_burn.decorate(self.accounts.current_allowance())
        if action == "refresh_usage_limits":
            result = self.accounts.refresh_current()
            self.refresh()
            return result
        if action == "usage_limits_settings":
            enabled = args.get("enabled")
            if type(enabled) is not bool:
                raise ValueError("Live allowance switch must be true or false")
            self.accounts.configure(enabled)
            return self.submit("Saving live allowance preference", lambda: self.store.set_setting("live_usage_enabled", enabled))
        if action == "desktop_state":
            return self.desktop.state() if self.desktop else {"available": False}
        if action in {"desktop_settings", "desktop_command"}:
            if not self.desktop:
                raise ValueError("Desktop controls are available in the Windows dashboard")
            return self.desktop.update(args) if action == "desktop_settings" else self.desktop.command(args.get("command"), args.get("account_id"))
        if action == "widget_summary":
            value = self.widget_summaries.read()
            value["provider_allowances"] = self.provider_allowances()
            value["job"] = self.jobs.snapshot()
            value["desktop"] = self.call("desktop_state")
            value["usage_limits"] = self.local_token_burn.decorate(self.accounts.current_allowance())
            value["accounts"] = self.local_token_burn.decorate(self.accounts.read())
            return value
        if action == "dashboard":
            data = dashboard(self.store,args)
            data["provider_allowances"] = self.provider_allowances()
            data["provider_setup"] = self.provider_setup.states()
            data["job"] = self.jobs.snapshot()
            data["exporter"] = self.exporter
            data["desktop"] = self.call("desktop_state")
            data["usage_limits"] = self.local_token_burn.decorate(self.accounts.current_allowance())
            data["account_token_total"] = self.accounts.read()["token_total"]
            data["settings"]["live_usage_enabled"] = self.accounts.enabled
            data["settings"]["claude_usage_enabled"] = self.claude_usage.enabled
            data['settings']['antigravity_usage_enabled'] = self.antigravity_usage.enabled
            return data
        if action == "status":
            return {**self.jobs.snapshot(), "revision": self.store.setting("data_revision", 0)}
        if action == "refresh":
            return self.refresh(bool(args.get("rebuild")))
        if action == "cancel":
            return self.jobs.cancel_current()
        if action == "add_source":
            path = self.choose("folder")
            if not path:
                return {"status":"cancelled"}
            def add_source():
                sid = self.store.add_source(path, args.get("label"), args.get("provider", "codex"))
                self.configure_watchers()
                self.dirty.set()
                return {"source_id": sid}
            return self.submit("Adding session folder", add_source)
        if action in {"source_enabled","forget_source"}:
            sid = args["id"]
            def update_sources():
                if action == "forget_source":
                    self.store.forget_source(sid)
                else:
                    with self.store.lock, self.store.connect() as db:
                        db.execute("UPDATE sources SET enabled=? WHERE id=?",(int(bool(args["enabled"])),sid))
                rebuild_projection(self.store)
                self.configure_watchers()
            return self.submit("Updating included sources",update_sources)
        if action == "export":
            path = self.choose("save", "usage.codex-insights")
            return {"status":"cancelled"} if not path else self.submit("Refreshing and exporting usage",lambda:export_usage(self.store,path,self.store.setting("device_label","This computer"),self.progress,self.cancel), cancelable=True)
        if action == "import":
            path = self.choose("open")
            return {"status":"cancelled"} if not path else self.submit("Importing usage snapshot",lambda:import_snapshot(self.store,path,self.progress,self.cancel), cancelable=True)
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
        if action in {"alias", "merge_projects"}:
            sources = [args.get("source")] if action == "alias" else args.get("sources")
            target = args.get("target")
            key = "project-merge:" + json.dumps([sorted(set(sources)) if isinstance(sources, list) and all(isinstance(s, str) for s in sources) else sources, target])
            return self.submit("Merging project groups", lambda: project_groups.merge_projects(self.store, sources, target), key=key)
        if action == "undo_project_merge":
            operation_id = args.get("operation_id")
            return self.submit("Undoing last project merge", lambda: project_groups.undo_project_merge(self.store, operation_id), key="project-undo:" + str(operation_id))
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

"""Shared app/exporter orchestration, background jobs and native-dialog API."""
import json
import logging
import platform
import threading
import time
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
from .live_index import LivePaths

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, directory, demo=False, exporter=False, allowance_provider=None, defer_projection=False):
        self.store = Store(directory)
        from .dashboard_cache import DashboardCache
        self.dashboard_cache = DashboardCache(self.store)
        self.exporter = exporter
        self.window = None
        self.desktop = None
        from .widget_queries import WidgetSummaries
        self.widget_summaries = WidgetSummaries(self.store)
        self.jobs = Jobs()
        self.store.live_paths = LivePaths()
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
            from .buckets import VERSION as BUCKET_VERSION, rebuild_buckets
            if self.store.setting('bucket_version') != BUCKET_VERSION:
                rebuild_buckets(self.store, resume=True)
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
        def run():
            from .cooperative import live_work
            self.store.maintenance_cancel = self.cancel if options.get('cancelable') else self.stop
            try:
                with live_work(self.store, self.store.maintenance_cancel):
                    return action()
            finally:
                self.store.maintenance_cancel = None
        return self.jobs.submit(message, run, **options)

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
        from .projection_state import needs_rebuild
        if (needs_rebuild(self.store, PROJECTION_VERSION)
                or self.store.setting('bucket_version') != 2 or self.store.setting('project_groups_version') != 1):
            def maintenance():
                ensure_projection(self.store, self.progress)
                if self.store.setting('project_groups_version') != 1:
                    project_groups.migrate(self.store, self.progress, self.stop)
                if self.store.setting('bucket_version') != 2:
                    from .buckets import rebuild_buckets
                    rebuild_buckets(self.store, resume=True)
            self.submit('Updating usage index', maintenance, origin="user", key="index-upgrade")
        self.accounts.start()
        self.claude_usage.start()
        self.antigravity_usage.start()
        if self.store.setting("demo", False):
            return
        threading.Thread(target=self._prune_backups, daemon=True, name="insights-backups").start()
        self.refresh(automatic=True)
        self.configure_watchers()
        def watch():
            while not self.stop.wait(1):
                live = self.store.live_paths
                retry_due = live.poll_retries(self.store)
                if self.jobs.automatic_ready(self.dirty.is_set() or retry_due or live.discovery_due() or bool(live.pending())):
                    self.dirty.clear()
                    self.refresh(automatic=True)
        self.watch_thread = threading.Thread(target=watch,daemon=True)
        self.watch_thread.start()

    def _prune_backups(self):
        try:
            from .backup_retention import prune_upgrade_backups
            prune_upgrade_backups(self.store)
        except Exception:
            log.exception("Could not check upgrade backups")

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
                def __init__(self, source, suffix='.jsonl'):
                    super().__init__()
                    self.source = source
                    self.suffix = suffix
                def on_any_event(self,event):
                    if event.event_type in {"created","modified","moved","deleted"}:
                        engine.store.live_paths.event(self.source['id'], self.source['root'], event)
                        engine.dirty.set()
            observer = Observer()
            for source in self.store.sources():
                if source["kind"] in {"folder", "bridge"} and source["enabled"] and source["root"] and Path(source["root"]).is_dir():
                    if source.get('format') == 'antigravity_legacy':
                        continue
                    else:
                        observer.schedule(Events(source), source["root"], recursive=True)
            observer.start(); self.observer = observer
            self.store.live_paths.watcher_available = True
        except (ImportError,OSError):
            self.observer = None

    def begin_close(self):
        """Signal every worker to wind down without waiting; safe on the GUI thread."""
        self.stop.set(); self.cancel.set()
        self.dashboard_cache.begin_close()
        self.accounts.begin_close()
        self.claude_usage.begin_close()
        self.antigravity_usage.begin_close()
        if self.observer:
            self.observer.stop()

    def close(self, timeout=8):
        """Release workers within one deadline; work left running is redone next launch."""
        deadline = time.monotonic() + timeout
        remaining = lambda: max(0.0, deadline - time.monotonic())
        timings = []
        def phase(name, action):
            started = time.monotonic()
            try:
                action()
            except Exception:
                log.exception("Shutdown phase failed: %s", name)
            timings.append(f"{name} {time.monotonic() - started:.1f}s")
        self.begin_close()
        phase("accounts", lambda: self.accounts.close(timeout=remaining()))
        phase("usage checks", lambda: (self.claude_usage.close(), self.antigravity_usage.close()))
        if getattr(self, "watch_thread", None):
            phase("watcher", lambda: self.watch_thread.join(timeout=min(3, remaining())))
        def jobs():
            # Cooperative work stops at its next cancellation check; a report or
            # export still aggregating is interrupted after a short grace.
            if not self.jobs.close(timeout=min(2, remaining())):
                self.store.readers.interrupt()
                if not self.jobs.close(timeout=remaining()):
                    log.warning("Indexing work is still running at shutdown; it resumes on next launch")
        phase("jobs", jobs)
        phase("analytics", lambda: self.dashboard_cache.close(timeout=remaining()))
        if self.observer:
            phase("file watchers", lambda: self.observer.join(timeout=min(3, remaining())))
        if self.desktop:
            self.desktop.dispose()
            self.desktop = None
        log.info("Engine closed in %.1fs (%s)", timeout - remaining(), ", ".join(timings))

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
        if action == 'bootstrap':
            from .projection_state import status
            with self.store.connect() as db:
                pending = status(db)
            return {'ready': True, 'cached_overview': self.dashboard_cache.snapshot.load(args), 'projection': pending}
        if action == 'live_status':
            from .projection_state import status
            with self.store.connect() as db:
                pending = status(db)
            rates = self.local_token_burn.read_rates()
            include_accounts = args.get('accounts') is True
            value = {'ready': True, 'projection': pending, 'job': self.call('status'), 'desktop': self.call('desktop_state'),
                     'usage_limits': {**self.accounts.current_allowance(), **rates},
                     'provider_allowances': self.provider_allowances(), 'account_token_total': self.accounts.token_total(),
                     'indexing': rates.get('token_burn_rate', {}).get('indexing'),
                     'analytics_generation': self.dashboard_cache.generation}
            if include_accounts:
                value['accounts'] = {**self.accounts.read(), **rates}
            return value
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
            data = self.dashboard_cache.read(args)
            from .source_status import decorate
            decorate(self.store, data)
            data["provider_allowances"] = self.provider_allowances()
            data["provider_setup"] = self.provider_setup.states()
            data["job"] = self.jobs.snapshot()
            data["exporter"] = self.exporter
            data['claude_recovery'] = self.call('claude_history_recovery')
            data['coverage']['identity_issues'] = data['claude_recovery']['identity_issues']
            data["desktop"] = self.call("desktop_state")
            data["usage_limits"] = self.local_token_burn.decorate(self.accounts.current_allowance())
            data["account_token_total"] = self.accounts.token_total()
            data["settings"]["live_usage_enabled"] = self.accounts.enabled
            data["settings"]["claude_usage_enabled"] = self.claude_usage.enabled
            data['settings']['antigravity_usage_enabled'] = self.antigravity_usage.enabled
            return data
        if action == "history_conflicts":
            from .history_review import read
            with self.store.lock, self.store.connect() as db:
                db.execute('BEGIN')
                return read(db)
        if action == 'claude_history_recovery':
            from .claude_recovery_store import status
            with self.store.connect() as db:
                return status(db)
        if action == "resolve_history_conflict":
            from .history_review import resolve
            return self.submit("Updating accepted history", lambda: resolve(self.store, args))
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
                    self.store.forget_source(sid, reprojection=True)
                else:
                    with self.store.lock, self.store.connect() as db:
                        from .projection_state import request
                        db.execute("UPDATE sources SET enabled=? WHERE id=?",(int(bool(args["enabled"])),sid))
                        request(db)
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
                from .projection_state import request
                with self.store.lock, self.store.connect() as db:
                    request(db, {'timezone': zone, 'assumed_fast_percent': fast})
                    db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',
                               ('device_label', json.dumps(str(args.get('device_label', 'This computer'))[:200])))
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
                from .pricing_catalog import parse_catalog
                from .projection_state import request
                value = json.loads(Path(path).read_text(encoding='utf-8'))
                parsed = parse_catalog(value)
                with self.store.lock, self.store.connect() as db:
                    request(db, {'pricing_catalog': value})
                rebuild_projection(self.store)
                apply_catalog(value)
                return {'models': len(parsed), 'verified_at': value.get('verified_at')}
            return self.submit("Updating pricing catalog",update)
        if action == "export_html":
            from .report import export_html
            path = self.choose("save","codex-insights-report.html")
            if not path:
                return {"status":"cancelled"}
            return self.submit("Exporting HTML report",lambda:export_html(dashboard(self.store,args.get("filters")),path,bool(args.get("anonymous",True))))
        raise ValueError("Unknown app action")

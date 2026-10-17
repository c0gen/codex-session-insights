"""Claude profile locations and remembered local source discovery."""
import json
import os
from pathlib import Path

SEEN_ROOTS = "claude_discovery_seen"


def config_directory(home=None, environ=None):
    home = Path(home) if home is not None else Path.home()
    environ = os.environ if environ is None else environ
    configured = environ.get("CLAUDE_CONFIG_DIR", "")
    return Path(configured if configured.strip() else home / ".claude").expanduser().resolve()


def root_key(root):
    return os.path.normcase(str(Path(root).expanduser().resolve()))


def remember_root(db, root):
    row = db.execute("SELECT value FROM settings WHERE key=?", (SEEN_ROOTS,)).fetchone()
    seen = set(json.loads(row[0]) if row else [])
    if row is None:
        legacy = db.execute("SELECT value FROM settings WHERE key='provider_defaults_registered'").fetchone()
        if legacy and json.loads(legacy[0]):
            seen.add(root_key(Path.home() / '.claude' / 'projects'))
    seen.add(root_key(root))
    db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (SEEN_ROOTS, json.dumps(sorted(seen))))


def register_claude_profiles(store, home=None, environ=None):
    home = Path(home) if home is not None else Path.home()
    standard = home / ".claude" / "projects"
    saved = store.setting(SEEN_ROOTS)
    # Older releases already offered the standard root. Do not restore it if
    # the user forgot it before this discovery upgrade.
    seen = set(saved or [])
    if saved is None and store.setting("provider_defaults_registered", False):
        seen.add(root_key(standard))
    roots = [(standard, "Claude Code · local profile"),
             (config_directory(home, environ) / "projects", "Claude Code · configured profile")]
    existing = {root_key(s["root"]) for s in store.sources()
                if s["root"] and s["provider"] == "claude_code" and s["kind"] == "folder"}
    for root, label in roots:
        key = root_key(root)
        if key not in seen:
            if key not in existing:
                store.add_source(root, label, "claude_code")
                existing.add(key)
            seen.add(key)
    if saved != sorted(seen):
        store.set_setting(SEEN_ROOTS, sorted(seen))

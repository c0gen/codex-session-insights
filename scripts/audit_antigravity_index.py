"""Back up and check the live index before an Antigravity parser migration."""
import json
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from codex_insights.account_storage import protect_directory


def audit(directory, destination):
    directory, destination = Path(directory), Path(destination)
    protect_directory(destination)
    source = directory / 'insights.sqlite3'
    backup = destination / 'insights.sqlite3'
    if backup.exists():
        raise ValueError('Choose a fresh backup directory')
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'verified': False}
    try:
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=3) as live:
            live.execute('PRAGMA query_only=ON')
            live.execute('SELECT count(*) FROM sqlite_master').fetchone()
            deadline = time.monotonic() + 60
            def progress(*args):
                if time.monotonic() > deadline:
                    raise TimeoutError('Backup exceeded one minute')
            with sqlite3.connect(backup) as copy:
                live.backup(copy, pages=8192, progress=progress)
        result['backup_method'] = 'sqlite-online-backup'
    except (OSError, sqlite3.Error, TimeoutError) as exc:
        result['live_read_error'] = str(exc)
        # Keep an evidence copy without checkpointing/resetting the live DB.
        raw = destination / 'unverified-files'
        protect_directory(raw)
        paths = [p for p in directory.glob('insights.sqlite3*') if p.is_file()]
        before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
        for path in paths:
            shutil.copyfile(path, raw / path.name)
        after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
        result.update(backup_method='unverified-file-copy', source_files_stable=before == after)
        backup = raw / 'insights.sqlite3'
    try:
        with sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True) as db:
            deadline = time.monotonic() + 60
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
            checks = [row[0] for row in db.execute('PRAGMA quick_check')]
            result['integrity'] = checks[:10]
            result['verified'] = checks == ['ok'] and result['backup_method'] == 'sqlite-online-backup'
    except (OSError, sqlite3.Error) as exc:
        result['backup_read_error'] = str(exc)
    (destination / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory.resolve(), args.destination.resolve()), indent=2))

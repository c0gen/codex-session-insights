"""Reusable bounded file reader and atomic projection publication."""
import hashlib
import json
from .codec import pack, unpack
from .parser import portable_fact
from .providers import adapter
from .projection import project_segments
from .index_health import file_checked, event_time_bound
from .codec import timestamp


def anchor(path, offset):
    with path.open("rb") as stream:
        stream.seek(max(0, offset - 4096))
        return hashlib.sha256(stream.read(min(offset, 4096))).hexdigest()


class FileIndexer:
    def __init__(self, store, report, cancel=None, rebuild=False, automatic=False):
        self.store, self.report, self.cancel = store, report, cancel
        self.rebuild, self.automatic = rebuild, automatic

    def checkpoint(self, source_id, path):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM files WHERE source_id=? AND path=?', (source_id, str(path))).fetchone()
            return dict(row) if row else None

    def flush(self, preferred=(), *, max_batches=None):
        store = self.store
        preferred = set(preferred)
        batches = 0
        while True:
            with store.lock, store.connect() as db:
                queued = {r[0] for r in db.execute('SELECT segment_id FROM projection_queue')}
                changed = queued & preferred
                if not changed:
                    changed = {r[0] for r in db.execute('SELECT p.segment_id FROM projection_queue p LEFT JOIN session_metadata m '
                        'ON m.segment_id=p.segment_id ORDER BY m.last_active DESC,p.segment_id LIMIT 16')}
                if not changed:
                    return
                related = store.related_segments(db, changed)
                project_segments(store, db, related)
                db.executemany('DELETE FROM projection_queue WHERE segment_id=?', [(sid,) for sid in related])
                db.execute("INSERT OR REPLACE INTO settings VALUES('data_revision',?)", (json.dumps(store.setting("data_revision", 0) + 1),))
            from .cooperative import checkpoint
            batches += 1
            if max_batches is not None and batches >= max_batches:
                return
            if self.cancel and self.cancel.is_set():
                return
            checkpoint(store)

    def read(self, source, path, failures):
        store, report, cancel = self.store, self.report, self.cancel
        rebuild, automatic = self.rebuild, self.automatic
        provider_adapter = adapter(source.get('provider', 'codex'))
        parser_version = failures.parser_version
        stat, parser = None, None
        try:
            stat = path.stat()
            if failures.skip(path, stat, automatic and not rebuild):
                report["skipped_errors"] += 1
                with store.connect() as db:
                    db.execute('DELETE FROM index_pending WHERE source_id=? AND path=?', (source['id'], str(path)))
                return
            cached = self.checkpoint(source["id"], path)
            current = cached and cached["parser_version"] == parser_version
            # A stable incomplete final line cannot become complete
            # until the file changes. Avoid re-packing its entire
            # checkpoint on every fallback scan while it is idle.
            if (current and not rebuild and str(path) not in failures.failed
                    and cached["size"] == stat.st_size and cached["mtime"] == stat.st_mtime_ns):
                with store.connect() as db:
                    verified = db.execute('SELECT 1 FROM file_coverage WHERE source_id=? AND path=?',
                                          (source['id'], str(path))).fetchone()
                    if not verified:
                        saved = unpack(cached['state'])
                        gaps = saved.get('parse_errors', 0)
                        reason = 'parse_gap' if gaps or (not saved.get('fact') and stat.st_size) else 'incomplete_tail' if cached['offset'] < stat.st_size else None
                        file_checked(db, source['id'], path, issues=max(gaps, int(bool(reason))), reason=reason,
                                     bound=event_time_bound(path, stat.st_size) if reason else None)
                    else:
                        db.execute("DELETE FROM index_pending WHERE source_id=? AND path=?", (source["id"], str(path)))
                return
            state = None
            if current and not rebuild:
                with store.connect() as db:
                    saved=db.execute('SELECT state FROM files WHERE source_id=? AND path=?',(source['id'],str(path))).fetchone()
                state=unpack(saved[0]) if saved else None
            if state and (state.get("version") != parser_version or stat.st_size < cached["offset"] or anchor(path, cached["offset"]) != cached["anchor"] or (stat.st_size == cached["size"] and stat.st_mtime_ns != cached["mtime"])):
                state = None
            from .providers.antigravity import read_metadata
            metadata = read_metadata(store.directory, path) if provider_adapter.provider == 'antigravity' else None
            parser = provider_adapter.parser(state, path, source["kind"], metadata=metadata)
            start_offset = parser.state["offset"]
            evidence = parser.state.get('event_time_evidence', {'valid': start_offset == 0, 'latest': None})
            with path.open("rb") as stream:
                stream.seek(start_offset)
                while stream.tell() < stat.st_size and (not cancel or not cancel.is_set()):
                    line = stream.readline(stat.st_size - stream.tell())
                    if not line or not line.endswith(b"\n"):
                        break
                    parser.consume(line, stream.tell())
                    if evidence['valid']:
                        try:
                            item = json.loads(line)
                            at = timestamp(item.get('timestamp')) if isinstance(item, dict) else None
                            if at is None:
                                evidence['valid'] = False
                            else:
                                evidence['latest'] = max(evidence['latest'] or at.timestamp(), at.timestamp())
                        except (ValueError, TypeError, UnicodeError):
                            evidence['valid'] = False
                    if parser.state.get("ordinal", 0) % 256 == 0:
                        yield
            if provider_adapter.provider == 'antigravity' and (path.stat().st_size != stat.st_size or path.stat().st_mtime_ns != stat.st_mtime_ns):
                raise ValueError('Public transcript changed while reading; retrying on the next refresh')
            if cancel and cancel.is_set():
                return
            offset = parser.state["offset"]
            parser.state['event_time_evidence'] = evidence
            fact = parser.fact()
            with store.lock, store.connect() as db:
                if provider_adapter.provider == 'claude_code':
                    from .claude_recovery_store import clear_issue
                    clear_issue(db, source['id'], path)
                db.execute("INSERT OR REPLACE INTO files(source_id,path,offset,mtime,size,anchor,state,parser_version) VALUES(?,?,?,?,?,?,?,?)", (source["id"], str(path), offset, stat.st_mtime_ns, stat.st_size, anchor(path, offset), pack(parser.checkpoint()), parser_version))
                if fact:
                    fact = portable_fact(fact)
                    store.put_candidate(db, source["id"], fact, parser_version, path)
                    if store.choose_canonical(db, fact["segment_id"]):
                        db.execute("INSERT OR IGNORE INTO projection_queue VALUES(?)", (fact["segment_id"],))
            report["bytes_read"] += offset - start_offset
            report["changed_files"] += 1
            failures.clear(path)
            self.flush([fact['segment_id']] if fact else ())
            with store.lock, store.connect() as db:
                gaps = parser.state.get('parse_errors', 0)
                tail = offset < stat.st_size
                reason = 'parse_gap' if gaps or (not fact and stat.st_size) else 'incomplete_tail' if tail else None
                file_checked(db, source['id'], path, issues=max(gaps, int(bool(reason))), reason=reason,
                             bound=event_time_bound(path, stat.st_size) if reason else None)
                db.execute('INSERT OR REPLACE INTO file_time_evidence VALUES(?,?,?,?,?)',
                           (source['id'], str(path), stat.st_size, stat.st_mtime_ns,
                            evidence['latest'] if evidence['valid'] and not tail else None))
            latest = path.stat()
            if latest.st_size != stat.st_size or latest.st_mtime_ns != stat.st_mtime_ns:
                live = getattr(store, 'live_paths', None)
                if live:
                    live.requeue([(source['id'], str(path))])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            report["errors"] += 1
            failures.record(path, stat, exc, parser.state.get("offset") if parser else None)
            with store.lock, store.connect() as db:
                file_checked(db, source["id"], path, issues=1, reason="file_error",
                             bound=event_time_bound(path, stat.st_size if stat else None))
            from .providers.claude_identity import IdentityError
            if isinstance(exc, IdentityError):
                from .claude_recovery_store import issue
                with store.lock, store.connect() as db:
                    previous = db.execute('SELECT state FROM files WHERE source_id=? AND path=?', (source['id'], str(path))).fetchone()
                    accepted = unpack(previous[0]).get('fact') if previous else None
                    segment = accepted.get('segment_id') if accepted else None
                    issue(db, source['id'], path, segment, exc.reason)
                    if segment and store.choose_canonical(db, segment):
                        db.execute('INSERT OR IGNORE INTO projection_queue VALUES(?)', (segment,))
            return

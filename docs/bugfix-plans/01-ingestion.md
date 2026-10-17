# Repair duplicate session handling and parser isolation

Own B1 and B6. Read README.md in this directory first.

## Owned files

src/codex_insights/storage.py, ingestion.py, parser.py, index_failures.py, a small new ingestion helper if justified, and new tests/test_duplicate_file_history.py and tests/test_malformed_session_isolation.py. Do not edit projection.py, transfers.py, service.py, shared tests, or accounting/token_reconciliation.py while other owners work. Report any necessary changes in those files to the integration owner through your result file.

## Reproduce

B1: use the existing synthetic log/token helpers. In one registered source folder, a-long.jsonl contains log() + token(100) + token(300, 5, last=200). z-short.jsonl is its prefix log() + token(100). Expected accepted total is 330; current code reports 110 and stays wrong on an unchanged refresh. put_candidate currently replaces the row keyed by source_id and segment_id before canonical selection can compare the files.

B6: a-malformed.jsonl contains session_meta with git set to a nonempty string instead of a mapping. z-valid.jsonl contains a valid 110-token session. Current refresh raises AttributeError, skips the valid file, and records no file failure.

## Implementation steps

1. Add failing regression cases for both issues.
2. Preserve sufficient physical-file provenance or verify candidate prefix relationships before replacing a source candidate. A later shorter prefix must not displace a fuller accepted history. A divergent copy must retain accepted history and expose a diagnostic instead of silently winning. Choose a bounded, maintainable representation that preserves source IDs, source filters, canonical selection, and snapshot compatibility.
3. Cover either filename ordering, exact copies, append updates, restart, unchanged refresh, and divergent copies. Avoid relying on filesystem traversal order.
4. Handle existing affected indexes. Their longer file may be checkpointed and skipped on ordinary refresh. Implement an idempotent migration/reparse trigger owned by ingestion if needed and document the behavior for offline sources. Do not silently require a user to delete the index.
5. Validate nested parser payload shapes and normalize malformed values into handled parse/file errors. Keep unexpected payloads isolated per file, retain that file's prior accepted facts, record safe diagnostics, and continue scanning healthy files. Automatic retries should honor unchanged-failure suppression; manual refresh should retry.
6. Add tests for malformed git, subagent/thread_spawn, settings/token-info structures where applicable; distinguish omitted optional data from invalid data. Do not hide unrelated database or programming errors with a broad outer catch.
7. Run the new tests plus relevant existing engine, index failure, backfill, and structured-change tests.

## Acceptance and handoff

Both numeric reproductions must pass. Transfers must remain compatible and must never expose private file paths. Record any remaining projection/transfer migration integration requirements explicitly. Write docs/bugfix-plans/status/ingestion.json with changed files, tests, outcomes for B1/B6, and integration notes.


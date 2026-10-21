# Copy conflicts and recovery (0.1.5)

Update Windows and the Intel Mac exporter together. Windows 0.1.5 imports transfer v1–v6; older dashboards cannot import v6. The Mac must export again to supply history alternatives omitted by an older snapshot.

## Recover an existing warning

Open the updated exporter with its existing data directory. It backs up the SQLite database to `insights.before-copy-review.sqlite3` before upgrading, recovers available alternatives from checkpoints, and reparses accessible logs once. Do not forget sources or delete the index to clear the warning.

Proven duplicates and extensions resolve automatically, including JSON differences limited to whitespace or object-key order. Copies with changed timestamps, ancestry, record order or counters require review. Equal totals alone do not establish equivalence.

Choose **Sources → Review conflicts**. Each entry shows the session ID, sources, local file locations where known, record counts, first/last activity and recorded token counters. These counters describe a version; they are not combined or reconciled totals. The accepted version alone contributes accounting. **Keep accepted** and **Use this version** save a persistent choice; **Undo selection** restores review. All sanitized alternatives remain stored. New incompatible activity reopens review; a verified extension of the selected history remains selected.

**Awaiting verification** means an older warning lacks sufficient evidence to classify it. Reconnect its source and refresh, or explicitly choose retained history. Removing a divergent file does not prove that its excluded activity was redundant, so removal alone does not clear review.

Accounting overlaps between already stored legacy and transcript formats have a separate review entry. Choosing a format affects usage accounting only; retired archive collection stays disabled.

## Portable evidence

Transfer v6 keeps one envelope per session segment in `facts.jsonl`. Each envelope has `accepted`, `alternatives`, `state`, `selection`, `awaiting_verification`, and `accounting_selection`. Facts remain allowlisted, with additional ordered `record_hash` and `record_proofs` fields. Choices contain a selected variant fingerprint and the sanitized facts reviewed at that time. Original physical byte proofs and history boundaries stay attached to each version.

Only enabled local folder/bridge observations and local decisions are exported. Imported facts and exporter decisions are never recirculated. Snapshot replacement remains atomic and revision-based. Paths, conversation text, commands and credentials are excluded, including alternatives and reviewed evidence. The receiver recomputes conflict state from evidence; unresolved export warnings remain visible there. An unresolved export includes retained alternatives, but accepted totals can exclude their unique activity.

## Local API

- `history_conflicts` returns review groups with ID, evidence revision, state, reason, selected status, and transcript-free version summaries.
- `resolve_history_conflict` queues an accounting update with `{id, revision, selected}` or `{id, revision, undo: true}`. Changed evidence rejects the action with an instruction to reopen review. Choices, canonical selection, dependent projections and dashboard revision update in one transaction.

The same code serves the Windows dashboard, Intel Mac exporter and headless exports. Schema recovery is idempotent; interrupted scans resume from per-file checkpoints. Offline and unreadable sources retain their accepted histories.

## Build the Intel Mac exporter

Use an Intel Mac with macOS 12 or later, x86_64 Python 3.11+, and Node installed. Extract the 0.1.5 source archive, open Terminal in its folder, and run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mac-build]'
npm ci --prefix frontend
bash scripts/build_mac.sh
```

The build runs backend/frontend checks, verifies the bundled helper, signs the final bundle locally, extracts the ZIP, and runs native exporter and packaged transfer/review smoke tests. It writes the validated ZIP and SHA-256 file to `release/`. An Intel build and native launch cannot be validated from the Windows development machine.

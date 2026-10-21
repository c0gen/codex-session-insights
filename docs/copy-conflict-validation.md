# Copy-conflict implementation validation

Version: 0.1.5. Development host: Windows x64.

- Full repository check: 524 Python tests passed; all existing frontend data checks plus history review rendering/escaping passed; dashboard and widget production builds passed.
- Final targeted history suite after the remaining selection/backup adjustments: 22 tests passed. Covers normalized copies, real disagreements, durable choices, source enable/disable, cancellation, transactional rollback, migration backups and recovery, unavailable evidence, v1–v5 compatibility, v6 alternatives/decisions, snapshot replacement, format overlap, privacy, and physical history boundaries.
- Browser regression: Mac exporter presentation passed banner opening, Use this version, Keep accepted, Undo selection, reopening saved review, narrow layout and zero page errors. Existing persistent export-warning UI regression also passed. Reviewed the generated screenshot.
- Isolated Windows package built with the bundled bridge. Packaged bridge smoke passed. Packaged v6 cost export/import, normalized JSON copies, retained alternatives, authenticated review API selection, and exclusion of imported-only facts from re-export all passed.
- Windows release archive CRC, executable/bridge contents and frontend asset references verified; SHA-256 supplied beside the ZIP. No installation or replacement of the user's index was performed.

The Intel Mac packaging script includes the same tests and packaged review smoke. Native Intel macOS build/launch/signature validation remains to be run on an Intel Mac. The user's actual 11 conflicts require the updated exporter to inspect their existing Mac index; this Windows run used isolated synthetic histories only.

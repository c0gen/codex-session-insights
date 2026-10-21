# Claude recovery validation — 0.1.6

Development host: Windows x64. No installation or migration of the user's live index was performed.

- Final repository check: **559 Python tests passed** in 206.23 seconds. All frontend data checks, TypeScript checking, and dashboard/widget production builds passed.
- The recovery regression suite covers flat/nested/workflow logs, metadata-only copied agents, parent-scoped filenames, contradictory and mixed identities, pre-review and v6 indexes, rejected checkpoints, saved choices, unavailable/disabled sources, cancellation/restart, staging evidence surviving file loss, publication rollback, large catalogs, pricing/filter retention, and counters above the signed 32-bit limit.
- Import regressions cover v5 replacement by a corrected v6 export, idempotent imports, receiver-side choices between separate agents, backup failure before replacement, and rollback of snapshot replacement if recovery fails. Identity repair and accounting publication occur inside the replacement transaction.
- Browser regression passed the recovery summary, multi-billion-token formatting, persistent review selections, undo, narrow layout, and disabled selections for unverified agent identity, with no page errors. The generated review screenshot was visually inspected. Browser startup required an isolated run outside the desktop sandbox because Edge's process pipe was unavailable inside it.
- The isolated Windows 0.1.6 package and bridge built successfully. Packaged bridge smoke passed. Packaged v6 Claude pricing export/import, normalized copies, retained alternatives, authenticated review API, and exclusion of imported-only facts from re-export passed. A seeded old workflow-agent collision was automatically backed up, recovered to all 230 expected tokens, audited through the packaged read-only command, and exported/imported without changing that total. The packaged local API smoke required execution outside the sandbox for loopback communication.
- Windows release archive CRC, app/bridge presence, frontend asset references and SHA-256 were verified. The source archive includes the same new recovery smoke in the Intel Mac build pipeline.
- Read-only diagnostics were verified against committed WAL data without modifying the original database or sidecars and without constructing Engine/Store or creating a startup log. An audit attempt against the user's running Windows index detected concurrent changes and refused to publish a report, as intended.

## Still required on the Intel Mac

Build/sign/extract/native-launch validation and the actual before/after conflict audit require the Intel Mac. They were not performed on this Windows host. The latest saved Mac snapshot on this PC is v5 and omits rejected alternatives; it cannot establish how much of the reported billion-plus conflicting tokens is recoverable.

Follow [the recovery guide](claude-identity-recovery.md) against the Mac's existing data directory, retain both diagnostic reports, and account for every remaining conflict by cause. Re-export with the same exporter ID and import the higher revision into Windows. Do not treat the synthetic 230-token case or the raw sum of conflicting version counters as a measurement of the user's recovered usage.

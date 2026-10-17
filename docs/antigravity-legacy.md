# Retired Antigravity encrypted archives

Encrypted archive collection and its diagnostics are disabled. The former importer depended on extracting an archive key from the installed reader. It is no longer offered as a supported integration.

Existing indexed facts, original archives, and imported sanitized snapshots are retained. Refresh does not discover archives, unlock a Windows profile, extract keys, or decrypt files. Existing archive sources display **Collection disabled** while their accepted usage remains available. Portable legacy provenance and nullable component validation remain supported; v1, v2 and v3 imports continue to work.

For new usage, choose **Antigravity (public transcripts)** in Sources and select the application's `brain` directory. Enable the documented passive hooks for project/model metadata and supported edit results. For remaining allowance, install the official Antigravity CLI, sign in there, and enable **Check Antigravity allowance** in Settings. See [provider integrations](provider-integrations.md).

To verify retained history after building the frontend, run from the app directory:

```powershell
.venv/Scripts/python.exe scripts/legacy_fixture.py .local-data/retained-legacy-qa
$env:PLAYWRIGHT_CHANNEL = 'msedge'
node scripts/qa_legacy.mjs .local-data/retained-legacy-qa
```

The fixture seeds synthetic, previously accepted facts directly into an isolated index and verifies that refresh preserves both usage and the original placeholder archive. It does not enable collection, unlock a profile, or decrypt an archive. The browser check covers disabled collection, public transcript setup, provider filters, missing counters, the widget, summary-image data, and saved-report privacy.

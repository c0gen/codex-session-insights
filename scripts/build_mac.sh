#!/bin/bash
# Run on an Intel Mac with an editable .[dev,mac-build] installation and Node.
set -euo pipefail
project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"
python_program="${PYTHON:-$project_root/.venv/bin/python}"
"$python_program" scripts/check_sqlite_runtime.py
"$python_program" -c 'import platform,sys; assert sys.platform == "darwin" and platform.machine() == "x86_64", "Build requires macOS and an x86_64 Python runtime"'
mkdir -p .local-data release
build_root="$(mktemp -d "$project_root/.local-data/mac-build.XXXXXX")"
(cd frontend && npm run build)
"$python_program" -m pytest -q --basetemp "$build_root/pytest"
for check in qa_filter_state_unit qa_token_activity_data qa_metric_interface_data qa_account_identity qa_dashboard_data qa_widget_data qa_export_feedback qa_history_review_data; do
    node "scripts/$check.mjs"
done
app_version="$("$python_program" -c 'from codex_insights import __version__; print(__version__)')"
MACOSX_DEPLOYMENT_TARGET=12.0 "$python_program" setup_mac.py py2app --dist-dir "$build_root/dist" --bdist-base "$build_root/build"
app="$build_root/dist/Codex Insights Exporter.app"
for executable in "$app/Contents/MacOS/Codex Insights Exporter" "$app/Contents/MacOS/bridge_entry"; do
    test -x "$executable"
    lipo "$executable" -verify_arch x86_64
done
"$python_program" scripts/finalize_mac.py "$app"
"$python_program" scripts/check_sqlite_runtime.py "$app/Contents/MacOS/Codex Insights Exporter"
# Seal the final bundle locally; this needs no Apple account or certificate.
# py2app's copied launchers and libraries must remain valid after extraction.
codesign --force --deep --sign - "$app"
archive_name="CodexInsightsExporter-$app_version-macos-x86_64.zip"
ditto -c -k --sequesterRsrc --keepParent "$app" "$build_root/$archive_name"
mkdir "$build_root/extracted café app"
ditto -x -k "$build_root/$archive_name" "$build_root/extracted café app"
extracted="$build_root/extracted café app/Codex Insights Exporter.app"
codesign --verify --deep --verbose=2 "$extracted"
otool -L "$extracted/Contents/MacOS/bridge_entry"
"$python_program" scripts/smoke_bridge.py "$extracted/Contents/MacOS/bridge_entry"
"$python_program" scripts/smoke_exporter.py "$extracted/Contents/MacOS/Codex Insights Exporter" --native-exporter
cp "$build_root/$archive_name" "release/$archive_name"
(cd release && shasum -a 256 "$archive_name" > "$archive_name.sha256")
printf 'Validated Intel exporter: %s\n' "$project_root/release/$archive_name"

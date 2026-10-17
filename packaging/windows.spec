from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root=Path(SPECPATH).parent
a=Analysis([str(root/'packaging/windows_entry.py')],pathex=[str(root/'src')],
    binaries=[],datas=[(str(root/'frontend/dist'),'ui'),(str(root/'src/codex_insights/assets'),'codex_insights/assets'),(str(root/'LICENSE'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.'),(str(Path(sys.base_prefix)/'LICENSE.txt'),'licenses/python')]+collect_data_files('webview')+collect_data_files('tzdata')+copy_metadata('pywebview',recursive=True)+copy_metadata('watchdog')+copy_metadata('tzlocal',recursive=True)+copy_metadata('cryptography',recursive=True),
    hiddenimports=collect_submodules('webview')+['watchdog.observers.winapi','tzlocal','cryptography.hazmat.primitives.ciphers.aead'],
    excludes=['pytest','tkinter','PyQt5','PyQt6','PySide2','PySide6','webview.platforms.cef'],
    noarchive=False)
a.datas += [("codex_insights/providers/legacy/reader_schema.json", str(root/'src/codex_insights/providers/legacy/reader_schema.json'), 'DATA')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='CodexSessionInsights',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'src/codex_insights/assets/insights.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='CodexSessionInsights')

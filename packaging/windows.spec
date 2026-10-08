from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root=Path(SPECPATH).parent
a=Analysis([str(root/'packaging/windows_entry.py')],pathex=[str(root/'src')],
    binaries=[],datas=[(str(root/'frontend/dist'),'ui'),(str(root/'LICENSE'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.'),(str(Path(sys.base_prefix)/'LICENSE.txt'),'licenses/python')]+collect_data_files('webview')+collect_data_files('tzdata')+copy_metadata('pywebview',recursive=True)+copy_metadata('watchdog')+copy_metadata('tzlocal',recursive=True),
    hiddenimports=collect_submodules('webview')+['watchdog.observers.winapi','tzlocal'],
    excludes=['pytest','tkinter','PyQt5','PyQt6','PySide2','PySide6','webview.platforms.cef'],
    noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='CodexSessionInsights',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='CodexSessionInsights')

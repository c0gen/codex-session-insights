from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis([str(root / 'packaging/bridge_entry.py')], pathex=[str(root / 'src')],
             binaries=[], datas=[], hiddenimports=[],
             excludes=['webview', 'watchdog', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='CodexInsightsBridge',
          console=True, debug=False, strip=False, upx=False)

"""Run with Python.org x86_64 Python: python setup_mac.py py2app."""
from setuptools import setup
import os
from pathlib import Path

# py2app rejects install_requires. Keep this bundle setup separate from the
# root pyproject.toml; dependencies have already been installed by pip.
root=Path(__file__).resolve().parent
os.chdir(root/'packaging')

setup(name='Codex Insights Exporter',app=[{'script':'mac_entry.py','dest_base':'Codex Insights Exporter'}],options={'py2app':{
    'packages':['codex_insights','webview','watchdog','tzdata','tzlocal'],
    'resources':[str(root/'frontend/dist'),str(root/'LICENSE'),str(root/'THIRD_PARTY_NOTICES.md')],
    'dist_dir':str(root/'dist'),'bdist_base':str(root/'build/mac'),
    'excludes':['pytest','tkinter','PyInstaller','setuptools','wheel','pip','test','webview.__pyinstaller',
        'webview.platforms.android','webview.platforms.qt','webview.platforms.gtk','webview.platforms.winforms',
        'webview.platforms.edgechromium','webview.platforms.mshtml','webview.platforms.cef'],
    'arch':'x86_64','argv_emulation':False,
    'plist':{'CFBundleName':'Codex Insights Exporter','CFBundleDisplayName':'Codex Insights Exporter',
        'CFBundleIdentifier':'io.github.c0gen.codex-insights-exporter','CFBundleShortVersionString':'0.1.0',
        'LSMinimumSystemVersion':'12.0','NSHighResolutionCapable':True},
}})

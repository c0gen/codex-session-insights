"""Run with Python.org x86_64 Python: python setup_mac.py py2app."""
from setuptools import setup

setup(name='Codex Insights Exporter',app=[{'script':'packaging/mac_entry.py','dest_base':'Codex Insights Exporter'}],options={'py2app':{
    'packages':['codex_insights','webview','watchdog','tzdata','tzlocal'],
    'resources':['frontend/dist','LICENSE','THIRD_PARTY_NOTICES.md'],
    'excludes':['pytest','tkinter'],
    'arch':'x86_64','argv_emulation':False,
    'plist':{'CFBundleName':'Codex Insights Exporter','CFBundleDisplayName':'Codex Insights Exporter',
        'CFBundleIdentifier':'io.github.c0gen.codex-insights-exporter','CFBundleShortVersionString':'0.1.0',
        'LSMinimumSystemVersion':'12.0','NSHighResolutionCapable':True},
}},setup_requires=['py2app'])

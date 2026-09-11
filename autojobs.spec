# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

selenium_datas, selenium_bins, selenium_hidden = collect_all('selenium')
app_assets = [
    ('assets/logo-autojobs.png', 'assets'),
    ('assets/favicon-autojobs.ico', 'assets'),
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=selenium_bins,
    datas=selenium_datas + app_assets,
    hiddenimports=selenium_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Keep build/test-only packages out of the desktop executable even though
    # pytest is installed in the build venv for pre-build validation.
    excludes=['pytest', '_pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='autojobs',
    icon='assets/favicon-autojobs.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

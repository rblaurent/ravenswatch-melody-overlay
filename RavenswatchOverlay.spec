# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the standalone melody overlay.
# Build via `python build.py` (it generates build/app_icon.ico first).
# Set RAVENSWATCH_DEBUG_EXE=1 to also build a console/no-UAC debug exe.

import os

a = Analysis(
    ['overlay_app.py'],
    pathex=[],
    binaries=[],
    datas=[('icons', 'icons')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # numpy is an optional Pillow extra we don't use; excluding it ~halves the exe
    excludes=['numpy'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='RavenswatchOverlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='build/app_icon.ico',
    uac_admin=True,  # memory reading needs admin on most setups
)

if os.environ.get('RAVENSWATCH_DEBUG_EXE') == '1':
    exe_debug = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='RavenswatchOverlay-debug',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='build/app_icon.ico',
        uac_admin=False,
    )

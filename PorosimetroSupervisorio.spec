# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
app_name = "PorosimetroSupervisorio_v2_0_0"

a = Analysis(
    [str(root / "app.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "ui" / "styles.qss"), "ui"),
        (str(root / "ui" / "icons"), "ui/icons"),
        (str(root / "assets" / "branding"), "assets/branding"),
        (str(root / "config" / "default_config.json"), "config"),
        (str(root / "config" / "flow_meter.example.json"), "config"),
    ],
    hiddenimports=["openpyxl", "reportlab", "pyqtgraph"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(root / "assets" / "branding" / "ism_app_icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)

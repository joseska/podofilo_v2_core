# -*- mode: python ; coding: utf-8 -*-
# PodofiloV2 (CORE PUBLICO - open core, sin extension OVE).
#
# Diferencias respecto al spec de podofilo_dev (build con extension OVE):
#   - Sin hiddenimports de la extension: playwright, greenlet, pypac, lxml,
#     keyring (y sin los imports src.extensions.ove.*).
#   - Sin el datas del driver de Playwright (solo necesario para la extension).
#   - VERSION.txt si se empaqueta: main._read_version_label() lo lee del
#     bundle (el updater del core funciona igual que en dev).
#   - httpx SI se activa en hiddenimports: lo necesita src/core/updater.py.
#
# Ver docs/SYNC.md para la politica de sincronizacion dev -> core.

from pathlib import Path
import os

BASE_DIR = Path.cwd()
SRC_DIR = BASE_DIR / "src"


def _collect_datas():
    datas = []
    
    def add_path(relative_path, target):
        src = BASE_DIR / relative_path
        if src.exists():
            datas.append((str(src), target))
    
    # Recursos distribuidos con la app
    add_path("resources", "resources")

    # VERSION.txt: fuente unica de la version. Se empaqueta en la raiz del
    # bundle para que main._read_version_label() lo encuentre bajo _MEIPASS.
    add_path("VERSION.txt", ".")

    return datas


hidden_imports = [
    # PDF
    "fitz",
    "pymupdf",
    # UI
    "tkinterdnd2",
    "PIL._tkinter_finder",
    # HTTP (updater del core)
    "httpx",
    "httpx._transports",
    "httpcore",
    "h11",
    "anyio",
    "sniffio",
    # AMF
    # "pyamf",
    # "pyamf",
    # Proxy
    # "pypac",
    # "pypac.resolver",
    # XML
    # "lxml",
    # "lxml.etree",
    # Credenciales
    # "keyring",
    # "keyring.backends",
    # "keyring.backends.Windows",
    # Otros
    "certifi",
    "idna",
    "charset_normalizer",
]

a = Analysis(
    ['main.py'],
    pathex=[str(BASE_DIR), str(SRC_DIR)],
    binaries=[],
    datas=_collect_datas(),
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PodofiloV2',
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
    icon=str(BASE_DIR / "resources" / "podofilo.ico") if (BASE_DIR / "resources" / "podofilo.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PodofiloV2',
)


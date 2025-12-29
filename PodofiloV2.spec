# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os

BASE_DIR = Path.cwd()
SRC_DIR = BASE_DIR / "src"

# Obtener ruta del driver de Playwright
# # Obtener ruta del driver de Playwright
# def get_playwright_driver_path():
#     try:
#         import playwright
#         pw_path = Path(playwright.__file__).parent / "driver"
#         if pw_path.exists():
#             return str(pw_path)
#     except:
#         pass
#     return None

def _collect_datas():
    datas = []
    
    def add_path(relative_path, target):
        src = BASE_DIR / relative_path
        if src.exists():
            datas.append((str(src), target))
    
    # Recursos distribuidos con la app
    add_path("resources", "resources")

    
    # # Driver de Playwright (CRITICO para que funcione)
    # pw_driver = get_playwright_driver_path()
    # if pw_driver:
    #     datas.append((pw_driver, "playwright/driver"))
    
    return datas


hidden_imports = [
    # PDF
    "fitz",
    "pymupdf",
    # UI
    "tkinterdnd2",
    "PIL._tkinter_finder",
    # Playwright y async
    # "playwright",
    # "playwright.async_api",
    # "playwright.sync_api",
    # "playwright._impl",
    # "playwright._impl._driver",
    # "playwright._impl._browser_type",
    # "playwright._impl._connection",
    # "playwright._impl._transport",
    # "greenlet",
    # HTTP
    # "httpx",
    # "httpx._transports",
    # "httpcore",
    # "h11",
    # "anyio",
    # "sniffio",
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


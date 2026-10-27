# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

a = Analysis(
    ['src/cli.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('config.toml', '.'),
    ],
    hiddenimports=[
        'src',
        # Top-level packages are enough for PyInstaller to follow the imports —
        # it walks the package and pulls in submodules automatically.
        # (Only list submodules that PyInstaller's bytecode analysis misses,
        # e.g. dynamically-imported or stdlib-optional pieces.)
        'cryptography',
        'keyring',
        'qrcode',
        'playwright',
        'psutil',
        'portalocker',
        'prometheus_client',
        'fastapi',
        'uvicorn',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan.on',
        'multipart',
        'jinja2',
        'pydantic',
        'httpx',
        'aiohttp',
        'colorlog',
        'lxml',
        'bs4',
        'tomli_w',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.PngImagePlugin',
        'PIL.ImageWin',
        'keyring.backends.Windows',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='hoyo-code-monitor',
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
    icon='assets/icon.ico' if Path('assets/icon.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='hoyo-code-monitor',
)
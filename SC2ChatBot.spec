# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for a portable folder (simulated + OCR backends).
# Build:  pyinstaller SC2ChatBot.spec
# Output: dist/SC2ChatBot/

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('config/config.example.yaml', 'config'),
        ('config/config.yaml', 'config'),
    ],
    hiddenimports=[
        'src',
        'src.bot',
        'src.paths',
        'src.config_loader',
        'src.logger',
        'src.models',
        'src.names',
        'src.game_requests',
        'src.gemini_client',
        'src.personality',
        'src.triggers',
        'src.memory',
        'src.anti_spam',
        'src.commands',
        'src.decision_engine',
        'src.chat',
        'src.chat.base',
        'src.chat.simulated',
        'src.chat.sc2_stub',
        'google.generativeai',
        'yaml',
        'pydantic',
        'dotenv',
        'rich',
        'pyautogui',
        'pygetwindow',
        'mss',
        'PIL',
        'pytesseract',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SC2ChatBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SC2ChatBot',
)

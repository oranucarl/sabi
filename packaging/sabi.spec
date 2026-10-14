# PyInstaller spec for SAbi.app. Build with: scripts/build_app.sh
# ruff: noqa
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent
VERSION = "0.1.0"

datas = collect_data_files("sabi", includes=["data/*.json"])
binaries = []
hiddenimports = ["sabi.__main__"]
for pkg in ("faster_whisper", "ctranslate2", "edge_tts", "jwt", "cryptography"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Bundle the speech model so the app works offline from the first launch.
whisper_dir = os.environ.get("SABI_WHISPER_DIR")
if whisper_dir:
    datas += [(str(Path(whisper_dir) / f), "whisper-model") for f in os.listdir(whisper_dir)]

a = Analysis(
    [str(ROOT / "packaging" / "sabi_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "PyQt6.QtWebEngineCore", "PyQt6.QtQuick", "PyQt6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SAbi",
    console=False,
    target_arch="arm64",
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SAbi")
app = BUNDLE(
    coll,
    name="SAbi.app",
    icon=str(ROOT / "build" / "SAbi.icns"),
    bundle_identifier="com.oranucarl.sabi",
    version=VERSION,
    info_plist={
        "CFBundleDisplayName": "SAbi",
        "CFBundleName": "SAbi",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "14.0",
        "LSUIElement": True,  # menu-bar app, no Dock icon
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "SAbi listens while you hold Control+Option so you can ask questions out loud.",
        "NSScreenCaptureUsageDescription": "SAbi looks at your screen so it can explain and point at what you are studying.",
        "NSHumanReadableCopyright": "MIT License",
    },
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for MarkAssist (onedir).

Bundles the heavy AI stack (torch, transformers, ultralytics, PaddleOCR) plus
PySide6. This spec lives in packaging/; the app source (main.py + the app
package) is one level up, so paths are resolved relative to the project root.
Build from the project root:  python -m PyInstaller packaging/MarkAssist.spec
The writable data/ tree (DB, AI models, uploads) is NOT bundled - copy it next
to the built executable (the app resolves its data root next to the exe when
frozen; see app/database/db.py)."""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# The project root is one directory above this spec (packaging/).
_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)  # so collect_submodules('app') can import app

datas, binaries, hiddenimports = [], [], []

# Heavy third-party packages that need their submodules, data files and native
# libraries collected wholesale. Missing ones are skipped rather than fatal.
for pkg in [
    "torch", "torchvision", "transformers", "tokenizers", "safetensors",
    "huggingface_hub", "ultralytics", "cv2", "fitz", "pymupdf",
    "sklearn", "scipy", "sentencepiece", "regex", "PIL",
    "paddleocr", "paddle", "paddlex",
    # PaddleOCR pipeline runtime deps (code + data). Several are pulled in
    # transitively, but imagesize was missing, so collect them explicitly.
    "shapely", "pyclipper", "imagesize", "pypdfium2", "bidi",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # noqa: BLE001 - a missing optional pkg must not stop the spec
        print(f"[MarkAssist.spec] skipping {pkg}: {exc}")

# CRITICAL for PaddleOCR: paddlex checks each dependency with
# importlib.metadata.version(), which reads .dist-info METADATA. PyInstaller
# does not bundle that metadata by default, so paddlex wrongly decides the
# dependency is missing and raises "A dependency error occurred during pipeline
# creation" when the OCR engine is constructed. Bundle the metadata for every
# distribution paddlex may version-check (distribution names, not import names);
# not-installed extras are skipped.
for _dist in [
    "paddlepaddle", "paddleocr", "paddlex",
    "shapely", "pyclipper", "imagesize", "pypdfium2", "python-bidi",
    "opencv-contrib-python", "tokenizers", "safetensors", "regex",
    "numpy", "pillow", "PyYAML", "requests", "packaging", "typing-extensions",
    "pandas", "pydantic", "ruamel.yaml", "ujson", "prettytable", "colorlog",
    "chardet", "filelock", "huggingface-hub", "py-cpuinfo", "einops",
    "Jinja2", "scikit-learn", "scipy", "decord", "GPUtil", "ftfy",
]:
    try:
        datas += copy_metadata(_dist)
    except Exception as exc:  # noqa: BLE001 - a not-installed extra is fine
        print(f"[MarkAssist.spec] no metadata for {_dist}: {exc}")

# The whole application package, including the worker entry points that the
# frozen build relaunches itself into (main.py's --run-worker dispatch).
hiddenimports += collect_submodules("app")

block_cipher = None

a = Analysis(
    [os.path.join(_ROOT, "main.py")],
    pathex=[_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "pytest", "_pytest"],
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
    name="MarkAssist",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, "MarkAssist.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MarkAssist",
)

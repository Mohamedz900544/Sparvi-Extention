# -*- mode: python ; coding: utf-8 -*-

import tempfile
from pathlib import Path

from PIL import Image
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VSVersionInfo,
    VarFileInfo,
    VarStruct,
)


project_dir = Path(globals().get("SPECPATH", ".")).resolve()
icon_png_path = project_dir / "icon.png"
temp_icon_path = Path(tempfile.gettempdir()) / "sparvi-desktop-pointer-build-icon.ico"
icon_arg = []


def sparvi_version_info(app_name):
    exe_name = f"{app_name}.exe"
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=(1, 0, 0, 0),
            prodvers=(1, 0, 0, 0),
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Sparvi Lab"),
                        StringStruct("FileDescription", app_name),
                        StringStruct("FileVersion", "1.0.0.0"),
                        StringStruct("InternalName", app_name),
                        StringStruct("LegalCopyright", "Copyright (c) 2026 Sparvi Lab"),
                        StringStruct("OriginalFilename", exe_name),
                        StringStruct("ProductName", app_name),
                        StringStruct("ProductVersion", "1.0.0.0"),
                    ],
                )
            ]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

if icon_png_path.exists():
    with Image.open(icon_png_path).convert("RGBA") as image:
        alpha_bbox = image.getchannel("A").getbbox()
        if alpha_bbox:
            image = image.crop(alpha_bbox)

            # Tighten transparent margins so Windows does not show the artwork
            # floating inside a visibly square icon slot.
            side = max(image.size)
            padding = max(2, int(side * 0.06))
            canvas_side = side + (padding * 2)
            canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
            canvas.alpha_composite(
                image,
                ((canvas_side - image.width) // 2, (canvas_side - image.height) // 2)
            )
            image = canvas

        # Windows desktop view looks best when the ICO actually contains a
        # real 256x256 frame. Upscale the source before saving so Pillow
        # embeds that size instead of stopping at 128x128.
        minimum_master_size = 512
        if min(image.size) < minimum_master_size:
            scale = minimum_master_size / float(min(image.size))
            image = image.resize(
                (int(round(image.width * scale)), int(round(image.height * scale))),
                Image.LANCZOS
            )

        image.save(
            temp_icon_path,
            format="ICO",
            sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (96, 96), (128, 128), (256, 256)]
        )
    icon_arg = [str(temp_icon_path)]


a = Analysis(
    ['client_app.py'],
    pathex=[],
    binaries=[],
    datas=[('logo.png', '.'), ('icon.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

pointer_exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Sparvi Desktop Pointer',
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
    icon=icon_arg,
    version=sparvi_version_info('Sparvi Desktop Pointer'),
)

student_exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Sparvi Desktop Student',
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
    icon=icon_arg,
    version=sparvi_version_info('Sparvi Desktop Student'),
)

teacher_exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Sparvi Desktop Teacher',
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
    icon=icon_arg,
    version=sparvi_version_info('Sparvi Desktop Teacher'),
)

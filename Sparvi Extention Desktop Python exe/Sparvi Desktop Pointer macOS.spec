# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_dir = Path(globals().get("SPECPATH", ".")).resolve()
icon_icns_path = project_dir / "icon.icns"
icon_arg = str(icon_icns_path) if icon_icns_path.exists() else None


a = Analysis(
    ["client_app.py"],
    pathex=[],
    binaries=[],
    datas=[("logo.png", "."), ("icon.png", ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)


def sparvi_app(app_name, bundle_identifier):
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=app_name,
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
    )

    return BUNDLE(
        exe,
        name=f"{app_name}.app",
        icon=icon_arg,
        bundle_identifier=bundle_identifier,
        info_plist={
            "CFBundleDisplayName": app_name,
            "CFBundleName": app_name,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHumanReadableCopyright": "Copyright (c) 2026 Sparvi Lab",
            "NSAppleEventsUsageDescription": "Sparvi uses desktop permissions to support live teaching pointer features.",
        },
    )


pointer_app = sparvi_app("Sparvi Desktop Pointer", "com.sparvilab.desktoppointer")
student_app = sparvi_app("Sparvi Desktop Student", "com.sparvilab.desktopstudent")
teacher_app = sparvi_app("Sparvi Desktop Teacher", "com.sparvilab.desktopteacher")

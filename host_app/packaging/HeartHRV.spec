# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（三平台通用）。

Windows: 产出 dist/HeartHRV/ 文件夹版（Inno 再封成安装包）
macOS:   产出 dist/HeartHRV.app
Linux:   产出 dist/HeartHRV/ 文件夹版

在 host_app 目录执行:  pyinstaller packaging/HeartHRV.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

HERE = Path(SPECPATH)  # packaging 目录
ROOT = HERE.parent     # host_app 目录

icon = str(HERE / "app_icon.ico") if sys.platform == "win32" else None

datas = [
    (str(HERE / "app_icon.ico"), "."),   # 运行时窗口图标（随exe携带）
    (str(HERE / "app_icon.png"), "."),
]

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "bleak.backends.winrt",
        "bleak.backends.corebluetooth",
        "bleak.backends.bluez",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HeartHRV",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # 关闭UPX压缩：减少杀软误报
    console=False,             # 窗口程序，无控制台
    icon=icon,
    version=str(HERE / "version_info.txt") if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="HeartHRV",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="HeartHRV.app",
        icon=str(HERE / "app_icon.png"),
        bundle_identifier="top.hearthrv.app",
        info_plist={
            "CFBundleDisplayName": "心电HRV采集分析",
            "CFBundleShortVersionString": "1.0.0",
            "NSBluetoothAlwaysUsageDescription": "连接心电采集设备",
        },
    )

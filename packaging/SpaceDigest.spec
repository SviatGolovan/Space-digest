# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller packaging/SpaceDigest.spec --noconfirm   (из корня проекта)
# Windows → dist/SpaceDigest/SpaceDigest.exe  (дальше Inno Setup делает установщик)
# macOS   → dist/Space Digest.app              (дальше build_macos.sh делает .dmg)
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)
from spacedigest import APP_NAME, VERSION  # noqa: E402

datas = [
    (os.path.join(ROOT, "spacedigest", "templates"), "spacedigest/templates"),
    (os.path.join(ROOT, "spacedigest", "static"), "spacedigest/static"),
    (os.path.join(ROOT, "spacedigest", "core", "migrations"), "spacedigest/core/migrations"),
    (os.path.join(ROOT, "spacedigest", "prompts"), "spacedigest/prompts"),
]
datas += collect_data_files("fastembed")
datas += collect_data_files("telethon")
for pkg in ("trafilatura", "justext", "courlan", "htmldate"):   # полный текст статей: настройки и стоп-слова
    datas += collect_data_files(pkg)

hiddenimports = []
hiddenimports += collect_submodules("telethon")
hiddenimports += collect_submodules("fastembed")
hiddenimports += collect_submodules("deep_translator")
hiddenimports += collect_submodules("spacedigest")          # ядро 4.0 подключается лениво
hiddenimports += ["feedparser", "bs4", "htmldate"]          # страницы новостей без RSS и даты статей
hiddenimports += collect_submodules("trafilatura") + collect_submodules("justext")
hiddenimports += ["sklearn.feature_extraction.text", "sklearn.utils._typedefs",
                  "sklearn.utils._heap", "sklearn.utils._sorting", "sklearn.utils._vector_sentinel",
                  "sklearn.neighbors._partition_nodes"]
if sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa", "objc", "AppKit", "Foundation", "PyObjCTools.AppHelper"]
elif sys.platform == "win32":
    hiddenimports += ["webview.platforms.edgechromium", "webview.platforms.winforms", "clr"]

excludes = ["torch", "tensorflow", "sentence_transformers", "transformers", "matplotlib",
            "IPython", "jupyter", "notebook", "pytest", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"]

icon_win = os.path.join(SPECPATH, "icons", "icon.ico")
icon_mac = os.path.join(SPECPATH, "icons", "icon.icns")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SpaceDigest",
    console=False,                      # без чёрного окна терминала
    icon=icon_win if sys.platform == "win32" else icon_mac,
    upx=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SpaceDigest", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon_mac,
        bundle_identifier="com.spacedigest.app",
        version=VERSION,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.news",
            # интерфейс открывается с локального сервера 127.0.0.1
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    )

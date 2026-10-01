"""
すぐサーチ（SuguSearch）— インストール配置と settings / version の場所
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_VERSION = "1.0.0"
GITHUB_REPO = "rittyapp/SuguSearch"
INSTALL_DIR_NAME = "SuguSearch"
# 旧アプリ（Everysearch）の設定を初回だけ引き継ぐ
LEGACY_INSTALL_DIR_NAME = "Everysearch"


def runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def local_app_install_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / INSTALL_DIR_NAME


def detect_install_root() -> Path | None:
    """
    setup 済みレイアウト（…/SuguSearch/current/SuguSearch.exe）ならその親。
    """
    rd = runtime_dir()
    if rd.name.lower() == "current":
        parent = rd.parent
        if parent.name.lower() == INSTALL_DIR_NAME.lower() or (parent / "data").exists():
            return parent
        # LocalAppData\SuguSearch\current
        if parent == local_app_install_root():
            return parent
        return parent
    # EXE が LocalAppData\SuguSearch\ 直下に置かれた場合
    lar = local_app_install_root()
    try:
        if rd.resolve() == lar.resolve() or rd.resolve() == (lar / "current").resolve():
            return lar
    except OSError:
        pass
    return None


def legacy_settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / LEGACY_INSTALL_DIR_NAME / "data" / "settings.json"


def ensure_install_dirs(root: Path | None = None) -> Path:
    root = root or local_app_install_root()
    for name in ("current", "previous", "staging", "data"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def settings_path() -> Path:
    inst = detect_install_root()
    if inst is not None:
        ensure_install_dirs(inst)
        return inst / "data" / "settings.json"
    # 開発時: src/ または EXE 隣
    return runtime_dir() / "settings.json"


def read_version() -> str:
    """version.txt（EXE 隣 or current）→ なければ APP_VERSION。"""
    candidates = [
        runtime_dir() / "version.txt",
        local_app_install_root() / "current" / "version.txt",
    ]
    for p in candidates:
        try:
            if p.is_file():
                v = p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
                if v:
                    return v
        except OSError:
            continue
    return APP_VERSION


def write_version_file(path: Path, version: str | None = None) -> None:
    path.write_text((version or APP_VERSION).strip() + "\n", encoding="utf-8")

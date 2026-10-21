"""
すぐサーチ（SuguSearch）— GitHub Releases 確認と差し替え準備
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app_paths import (
    APP_VERSION,
    GITHUB_REPO,
    detect_install_root,
    ensure_install_dirs,
    local_app_install_root,
    read_version,
    write_version_file,
)


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    name: str
    body: str
    asset_name: str
    asset_url: str
    html_url: str


def _parse_version(text: str) -> tuple[int, ...]:
    t = (text or "").strip().lstrip("vV")
    parts = re.findall(r"\d+", t)
    if not parts:
        return (0,)
    return tuple(int(x) for x in parts)


def version_is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _github_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"SuguSearch-Updater/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    tok = (token or "").strip() or os.environ.get("GITHUB_TOKEN") or os.environ.get(
        "GH_TOKEN"
    ) or ""
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def fetch_latest_release(
    repo: str = GITHUB_REPO,
    timeout: float = 20.0,
    token: str | None = None,
) -> ReleaseInfo:
    """
    最新 Release を取得。私有リポジトリは token（または環境変数 GITHUB_TOKEN / GH_TOKEN）が必要。
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers=_github_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                "公開されている更新情報（Release）が見つかりません。"
                "ネットワーク、または配布元の Release 設定を確認してください。"
            ) from e
        raise

    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")
    assets = data.get("assets") or []
    asset_name = ""
    asset_url = ""
    # Prefer SuguSearch.exe, then zip containing the name
    for a in assets:
        name = str(a.get("name") or "")
        low = name.lower()
        if low == "sugusearch.exe" or (
            low.startswith("sugusearch") and low.endswith(".exe")
        ):
            asset_name = name
            asset_url = str(a.get("browser_download_url") or "")
            break
    if not asset_url:
        for a in assets:
            name = str(a.get("name") or "")
            if name.lower().endswith(".zip") and "sugusearch" in name.lower():
                asset_name = name
                asset_url = str(a.get("browser_download_url") or "")
                break
    if not asset_url and assets:
        a = assets[0]
        asset_name = str(a.get("name") or "")
        asset_url = str(a.get("browser_download_url") or "")

    if not asset_url:
        raise RuntimeError(
            "最新 Release にダウンロード用 asset（SuguSearch.exe 等）がありません。"
        )

    return ReleaseInfo(
        tag=tag,
        version=version or tag,
        name=str(data.get("name") or tag),
        body=str(data.get("body") or ""),
        asset_name=asset_name,
        asset_url=asset_url,
        html_url=str(data.get("html_url") or f"https://github.com/{repo}/releases"),
    )


def download_file(
    url: str,
    dest: Path,
    timeout: float = 120.0,
    token: str | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=_github_headers(token))
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def prepare_staging_exe(asset_path: Path, staging_dir: Path) -> Path:
    """zip なら展開して SuguSearch.exe を探し、staging/SuguSearch.exe に置く。"""
    staging_dir.mkdir(parents=True, exist_ok=True)
    target = staging_dir / "SuguSearch.exe"
    if asset_path.suffix.lower() == ".exe":
        # 1.0.3 までは asset 名が SuguSearch.exe だと「同じファイルへのコピー」になり
        # SameFileError で更新が必ず失敗していた。同じなら何もしない。
        if asset_path.resolve() != target.resolve():
            shutil.copy2(asset_path, target)
        return target

    if asset_path.suffix.lower() == ".zip":
        import zipfile

        extract_to = staging_dir / "_extract"
        if extract_to.exists():
            shutil.rmtree(extract_to, ignore_errors=True)
        extract_to.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(asset_path, "r") as zf:
            zf.extractall(extract_to)
        found = None
        for p in extract_to.rglob("SuguSearch.exe"):
            found = p
            break
        if found is None:
            raise RuntimeError("zip 内に SuguSearch.exe が見つかりません")
        shutil.copy2(found, target)
        return target

    raise RuntimeError(f"未対応の asset: {asset_path.name}")


def _update_log(install_root: Path, msg: str) -> None:
    """更新の経過を data\\update.log に追記（失敗しても止めない）。"""
    try:
        import time

        log = install_root / "data" / "update.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def apply_update_in_place(release: ReleaseInfo, token: str | None = None) -> Path:
    """
    ダウンロードして current\\SuguSearch.exe をその場で差し替える。戻り値は新しい EXE。

    Windows では実行中の EXE でも「名前の変更（移動）」はできる（上書き・削除はできない）。
    そこで、動いている自分の EXE を previous へ移動してから新しい EXE を current に置く。
    1.0.5 までは「差し替え用 bat を起動してアプリを閉じる」方式だったが、実機で bat が
    始まらないことがあったため廃止した（このやり方は 2026-10-21 に実機で確認済み）。
    差し替えが済んでいれば、新しい版の起動に失敗してもショートカットからは新しい版が開く。
    """
    install_root = detect_install_root()
    if install_root is None or not getattr(sys, "frozen", False):
        raise RuntimeError(
            "セットアップ済みのアプリでのみ更新できます（配布の setup.bat で入れてください）"
        )
    ensure_install_dirs(install_root)
    staging = install_root / "staging"
    current = install_root / "current"
    previous = install_root / "previous"
    for p in staging.glob("*"):
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass

    _update_log(install_root, f"start {read_version()} -> {release.version} ({release.asset_name})")
    tmp = staging / f"download_{release.asset_name}"
    download_file(release.asset_url, tmp, token=token)
    new_exe = prepare_staging_exe(tmp, staging)
    _update_log(install_root, f"downloaded {new_exe.stat().st_size} bytes")

    cur = current / "SuguSearch.exe"
    prev = previous / "SuguSearch.exe"
    # previous の古い EXE を片付ける（使用中なら別名に逃がす）
    if prev.exists():
        try:
            prev.unlink()
        except OSError:
            import time

            os.replace(prev, previous / f"SuguSearch.{int(time.time())}.old")
    # 動いている EXE を previous へ（名前の変更なので実行中でもできる）
    if cur.exists():
        os.replace(cur, prev)
    try:
        shutil.copy2(new_exe, cur)
    except Exception:
        # 置けなかったら元に戻す
        if prev.exists() and not cur.exists():
            os.replace(prev, cur)
        _update_log(install_root, "copy failed, restored previous")
        raise
    cur_ver = current / "version.txt"
    if cur_ver.exists():
        os.replace(cur_ver, previous / "version.txt")
    write_version_file(cur_ver, release.version)
    _update_log(install_root, f"replaced current with {release.version}")
    return cur


def launch_new_version(exe: Path) -> bool:
    """差し替えた新しい EXE を起動する（アプリから切り離して）。"""
    import subprocess

    try:
        flags = 0
        if sys.platform == "win32":
            flags = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
        subprocess.Popen(
            [str(exe)], cwd=str(exe.parent), creationflags=flags, close_fds=True
        )
        root = detect_install_root()
        if root is not None:
            _update_log(root, f"launched {exe}")
        return True
    except Exception as e:
        root = detect_install_root()
        if root is not None:
            _update_log(root, f"launch failed: {e!r}")
        return False

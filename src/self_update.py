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


def write_update_runner(
    install_root: Path,
    *,
    new_version: str,
    wait_pid: int,
) -> Path:
    """
    本体終了後に current↔previous を差し替え、新 EXE を起動する bat を書く。
    経過は data\\update_runner.log に残す（差し替えが進まないときの調査用）。
    """
    ensure_install_dirs(install_root)
    runner = install_root / "update_runner.bat"
    staging_exe = install_root / "staging" / "SuguSearch.exe"
    log = install_root / "data" / "update_runner.log"
    # CP932-safe: ASCII only in bat body（パスに日本語が入る場合も cp932 で書く）
    lines = [
        "@echo off",
        "chcp 932 >nul",
        "setlocal",
        f'cd /d "{install_root}"',
        f'set "LOG={log}"',
        f'echo [%date% %time%] start {new_version} wait pid {wait_pid}>> "%LOG%"',
        f'powershell -NoProfile -Command "try {{ Wait-Process -Id {wait_pid} -Timeout 60 -ErrorAction SilentlyContinue }} catch {{}}"',
        "ping -n 2 127.0.0.1 >nul",
        f'if not exist "{staging_exe}" (',
        '  echo [%date% %time%] staging exe missing>> "%LOG%"',
        "  goto launch",
        ")",
        "if exist previous\\SuguSearch.exe.bak del /f /q previous\\SuguSearch.exe.bak",
        "if exist previous\\SuguSearch.exe move /y previous\\SuguSearch.exe previous\\SuguSearch.exe.bak >nul",
        "set /a TRY=0",
        ":mv",
        "if not exist current\\SuguSearch.exe goto moved",
        "move /y current\\SuguSearch.exe previous\\SuguSearch.exe >nul 2>&1",
        "if not exist current\\SuguSearch.exe goto moved",
        "set /a TRY+=1",
        "if %TRY% GEQ 15 goto locked",
        "ping -n 2 127.0.0.1 >nul",
        "goto mv",
        ":locked",
        'echo [%date% %time%] current exe is still in use, update skipped>> "%LOG%"',
        "if exist previous\\SuguSearch.exe.bak move /y previous\\SuguSearch.exe.bak previous\\SuguSearch.exe >nul",
        "goto launch",
        ":moved",
        "if exist current\\version.txt move /y current\\version.txt previous\\version.txt >nul",
        f'copy /y "{staging_exe}" "current\\SuguSearch.exe" >nul',
        "if errorlevel 1 (",
        '  echo [%date% %time%] copy failed, restoring previous>> "%LOG%"',
        "  copy /y previous\\SuguSearch.exe current\\SuguSearch.exe >nul",
        "  if exist previous\\version.txt copy /y previous\\version.txt current\\version.txt >nul",
        "  goto launch",
        ")",
        f"echo {new_version}> current\\version.txt",
        f'echo [%date% %time%] updated to {new_version}>> "%LOG%"',
        ":launch",
        'start "" "current\\SuguSearch.exe"',
        "exit /b 0",
    ]
    text = "\r\n".join(lines) + "\r\n"
    # Write as CP932 for cmd
    try:
        runner.write_bytes(text.encode("cp932", errors="replace"))
    except Exception:
        runner.write_text(text, encoding="utf-8")
    return runner


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def launch_detached(runner: Path, cwd: Path) -> str:
    """
    差し替え bat をアプリから完全に切り離して起動する。
    普通に子プロセスとして起動すると、アプリ（PyInstaller の EXE）の終了と一緒に
    止められることがあり、1.0.4 までは差し替えが一度も実行されていなかった。
    1) WMI（Win32_Process.Create）で起動 … 親がアプリではなくなる
    2) だめならジョブから抜けて（CREATE_BREAKAWAY_FROM_JOB）起動
    3) それもだめなら従来どおり
    戻り値: 使った方法（ログ・表示用）
    """
    import subprocess

    comspec = os.environ.get("COMSPEC", "cmd.exe")
    if sys.platform != "win32":
        subprocess.Popen([comspec, "/c", str(runner)], cwd=str(cwd), close_fds=True)
        return "popen"

    create_no_window = 0x08000000
    detached = 0x00000008
    new_group = 0x00000200
    breakaway = 0x01000000
    cmdline = f'"{comspec}" /c "{runner}"'
    ps = (
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{CommandLine={_ps_quote(cmdline)}; CurrentDirectory={_ps_quote(cwd)}}}; "
        "exit [int]$r.ReturnValue"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            creationflags=create_no_window,
            timeout=30,
            capture_output=True,
        )
        if res.returncode == 0:
            return "wmi"
    except Exception:
        pass
    try:
        subprocess.Popen(
            [comspec, "/c", str(runner)],
            cwd=str(cwd),
            creationflags=detached | new_group | breakaway,
            close_fds=True,
        )
        return "breakaway"
    except OSError:
        pass
    subprocess.Popen(
        [comspec, "/c", str(runner)],
        cwd=str(cwd),
        creationflags=detached | new_group,
        close_fds=True,
    )
    return "popen"


def apply_update_and_restart(
    release: ReleaseInfo,
    token: str | None = None,
) -> str:
    """
    DL→staging→runner 起動→呼び出し元は終了すること。
    戻り値: ユーザー向けメッセージ（成功準備完了）
    """
    install_root = detect_install_root() or local_app_install_root()
    ensure_install_dirs(install_root)
    staging = install_root / "staging"
    # clear staging lightly
    for p in staging.glob("*"):
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass

    # ダウンロード先は展開後の SuguSearch.exe と名前がぶつからないようにする
    tmp = staging / f"download_{release.asset_name}"
    download_file(release.asset_url, tmp, token=token)
    prepare_staging_exe(tmp, staging)
    write_version_file(staging / "version.txt", release.version)

    # Ensure current exists (first update from odd layout)
    current = install_root / "current"
    current.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        cur_exe = Path(sys.executable).resolve()
        dest = current / "SuguSearch.exe"
        if cur_exe != dest and not dest.is_file():
            try:
                shutil.copy2(cur_exe, dest)
            except OSError:
                pass
        if not (current / "version.txt").is_file():
            write_version_file(current / "version.txt", read_version())

    runner = write_update_runner(
        install_root, new_version=release.version, wait_pid=os.getpid()
    )
    launch_detached(runner, install_root)
    return f"版 {release.version} のダウンロード準備ができました。"

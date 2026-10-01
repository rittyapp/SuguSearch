"""
Everything 検索補助ツール
- / _ / 半角スペース / 全角スペース のゆらぎを吸収して Everything HTTP サーバーへ検索を依頼する
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _fix_tcl_tk_paths() -> None:
    """
    複数バージョンの Python が混在すると、環境変数 TCL_LIBRARY / TK_LIBRARY が
    別バージョンを指したままになり、tkinter の初期化に失敗することがある。
    実行中の Python 配下の tcl/tk を優先する。
    """
    base = Path(sys.prefix)
    tcl = base / "tcl" / "tcl8.6"
    tk_dir = base / "tcl" / "tk8.6"
    if tcl.is_dir():
        os.environ["TCL_LIBRARY"] = str(tcl)
    if tk_dir.is_dir():
        os.environ["TK_LIBRARY"] = str(tk_dir)


_fix_tcl_tk_paths()

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

# =========================
# 設定・パス
# =========================
from app_paths import (  # noqa: E402
    APP_VERSION,
    detect_install_root,
    ensure_install_dirs,
    legacy_settings_path,
    local_app_install_root,
    read_version,
    resource_dir as _resource_dir_impl,
    runtime_dir as _runtime_dir_impl,
    settings_path as _settings_path_impl,
    write_version_file,
)


def _runtime_dir() -> Path:
    return _runtime_dir_impl()


def _resource_dir() -> Path:
    return _resource_dir_impl()


APP_DIR = _runtime_dir()
RESOURCE_DIR = _resource_dir()
SETTINGS_PATH = _settings_path_impl()
ICON_PATH = RESOURCE_DIR / "sugusearch.ico"
if not ICON_PATH.is_file():
    for _alt in (
        APP_DIR / "sugusearch.ico",
        APP_DIR.parent / "assets" / "sugusearch.ico",
        Path(__file__).resolve().parents[1] / "assets" / "sugusearch.ico",
    ):
        if _alt.is_file():
            ICON_PATH = _alt
            break

DEFAULT_SETTINGS = {
    "host": "127.0.0.1",
    "port": 8888,
    "user": "",
    "password": "",
    # 私有 GitHub の Releases 取得用（DPAPI 暗号化保存）
    "github_token": "",
    # 初期は空（全体検索）。特定フォルダはユーザーが指定／履歴から選択
    "search_folder": "",
    "folder_history": [],
    # 接続設定の履歴（host + port）。フォーカス時に選べる
    "connection_history": [],
    "filters": [],  # 空なら default_filter_definitions() を使う
    # 検索画面チップの明暗（id -> true=明るい/表示側）
    "chip_state": {},
}

EVERYTHING_DOWNLOAD_URL = "https://www.voidtools.com/"

# Everything から最初に取る件数（新しい順で取得）
MAX_RESULTS = 500
# フィルタ後の件数がこの値以下なら全件表示。超える場合はこの件数まで。
DISPLAY_LIMIT = 200
# フィルタ後がこの件数以下 かつ 未取得分がある → 確認なしで広めに再取得
REFETCH_IF_FILTERED_LE = 100
# 再取得時の安全上限（これ以上は切る）
MAX_RESULTS_HARD_CAP = 20000
FOLDER_HISTORY_MAX = 20
CONNECTION_HISTORY_MAX = 20
# 入力ごとのライブ検索（デバウンス ms）
LIVE_SEARCH_DEBOUNCE_MS = 280

_FILETIME_EPOCH_DIFF = 116444736000000000

# ---------- デザイン ----------
UI = {
    "bg": "#F3F5F9",
    "surface": "#FFFFFF",
    "surface_2": "#F8FAFC",
    "border": "#E2E8F0",
    "text": "#0F172A",
    "text_muted": "#64748B",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_text": "#FFFFFF",
    "secondary": "#EEF2FF",
    "secondary_text": "#3730A3",
    "select": "#BFDBFE",
    "heading": "#F1F5F9",
    "accent_line": "#DBEAFE",
}

COLOR_FOLDER = "#FEF9C3"
COLOR_DWG = "#DBEAFE"
COLOR_DXF = "#E5E7EB"
COLOR_PDF = "#FECACA"
COLOR_EXCEL = "#BBF7D0"
COLOR_OTHER = "#FFFFFF"
COLOR_DUP = "#E9D5FF"
COLOR_OLD = "#FED7AA"
COLOR_SYS = "#A5F3FC"

# 非表示（オフ）時のチップ色
FILTER_OFF_BG = "#94A3B8"
FILTER_OFF_FG = "#F8FAFC"

# フィルタ kind:
#   folder / extension / other … 種類（結果の分類とチップ）
#   path_keyword … パス・名前キーワード（暗い＝該当を除外）
#   builtin_dedupe … 同名は最新のみ（暗い＝重複排除）
def default_filter_definitions() -> list[dict]:
    """出荷時のフィルタ定義（設定リセットでもこれを使う）。"""
    return [
        {
            "id": "type_folder",
            "kind": "folder",
            "label": "フォルダ",
            "color": COLOR_FOLDER,
            "show_chip": True,
            "default_on": True,
            "order": 10,
        },
        {
            "id": "type_dwg",
            "kind": "extension",
            "label": "DWG",
            "color": COLOR_DWG,
            "extensions": [".dwg"],
            "show_chip": True,
            "default_on": True,
            "order": 20,
        },
        {
            "id": "type_dxf",
            "kind": "extension",
            "label": "DXF",
            "color": COLOR_DXF,
            "extensions": [".dxf"],
            "show_chip": True,
            "default_on": True,
            "order": 30,
        },
        {
            "id": "type_pdf",
            "kind": "extension",
            "label": "PDF",
            "color": COLOR_PDF,
            "extensions": [".pdf"],
            "show_chip": True,
            "default_on": True,
            "order": 40,
        },
        {
            "id": "type_excel",
            "kind": "extension",
            "label": "Excel",
            "color": COLOR_EXCEL,
            "extensions": [".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".xltm"],
            "show_chip": True,
            "default_on": True,
            "order": 50,
        },
        {
            "id": "type_other",
            "kind": "other",
            "label": "その他",
            "color": COLOR_OTHER,
            "show_chip": True,
            "default_on": True,
            "order": 60,
            "locked": True,  # 削除不可
        },
        {
            "id": "path_old",
            "kind": "path_keyword",
            "label": "旧・OLD",
            "color": COLOR_OLD,
            "keywords": ["旧", "old"],
            "match_in": ["fullpath", "path", "name"],
            "case_insensitive": True,
            "show_chip": True,
            "default_on": True,
            "order": 100,
        },
        {
            "id": "path_sys",
            "kind": "path_keyword",
            "label": "システム履歴",
            "color": COLOR_SYS,
            "keywords": [
                "$RECYCLE.BIN",
                "RECYCLE.BIN",
                "RECYCLER",
                "FileHistory",
            ],
            "match_in": ["fullpath", "path"],
            "case_insensitive": True,
            "show_chip": True,
            "default_on": True,
            "order": 110,
        },
        {
            "id": "builtin_dedupe",
            "kind": "builtin_dedupe",
            "label": "重複",
            "color": COLOR_DUP,
            "show_chip": True,
            "default_on": True,
            "order": 200,
            "locked": True,
        },
    ]


def _normalize_extensions(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        s = str(e).strip().lower()
        if not s:
            continue
        if not s.startswith("."):
            s = "." + s
        if s not in out:
            out.append(s)
    return out


def _normalize_keywords(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = []
    for k in raw:
        s = str(k).strip()
        if s and s not in out:
            out.append(s)
    return out


def normalize_filter_definitions(raw) -> list[dict]:
    """ユーザ設定または既定を正規化したフィルタ定義リスト。"""
    if not isinstance(raw, list) or not raw:
        return default_filter_definitions()

    defaults_by_id = {f["id"]: f for f in default_filter_definitions()}
    result = []
    seen = set()

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in {
            "folder",
            "extension",
            "other",
            "path_keyword",
            "builtin_dedupe",
        }:
            continue
        fid = str(item.get("id") or "").strip() or f"filter_{i}"
        if fid in seen:
            continue
        seen.add(fid)
        base = defaults_by_id.get(fid, {})
        entry = {
            "id": fid,
            "kind": kind,
            "label": str(item.get("label") or base.get("label") or fid)[:40],
            "color": str(item.get("color") or base.get("color") or "#E2E8F0"),
            "show_chip": bool(item.get("show_chip", base.get("show_chip", True))),
            "default_on": bool(item.get("default_on", base.get("default_on", True))),
            "order": int(item.get("order", base.get("order", 100 + i * 10))),
            "locked": bool(item.get("locked", base.get("locked", False))),
        }
        if kind == "extension":
            entry["extensions"] = _normalize_extensions(
                item.get("extensions", base.get("extensions", []))
            )
        if kind == "path_keyword":
            entry["keywords"] = _normalize_keywords(
                item.get("keywords", base.get("keywords", []))
            )
            mi = item.get("match_in", base.get("match_in", ["fullpath", "path", "name"]))
            if not isinstance(mi, list):
                mi = ["fullpath", "path", "name"]
            entry["match_in"] = [
                x for x in mi if x in ("fullpath", "path", "name")
            ] or ["fullpath"]
            entry["case_insensitive"] = bool(
                item.get("case_insensitive", base.get("case_insensitive", True))
            )
        # other / folder / dedupe に locked 既定
        if kind in ("other", "builtin_dedupe") and fid in defaults_by_id:
            entry["locked"] = True
        result.append(entry)

    # 必須: other と dedupe が無ければ補完
    ids = {f["id"] for f in result}
    for must in default_filter_definitions():
        if must["id"] not in ids and must["kind"] in ("other", "builtin_dedupe"):
            result.append(dict(must))
        if must["kind"] == "folder" and not any(f["kind"] == "folder" for f in result):
            result.append(dict(must))

    result.sort(key=lambda f: (int(f.get("order", 0)), f.get("label", "")))
    return result


def classify_with_filters(item_type: str, name: str, filters: list[dict]) -> str:
    """フィルタ定義に基づき結果の tag（フィルタ id）を返す。"""
    if (item_type or "").lower() == "folder":
        for f in filters:
            if f.get("kind") == "folder":
                return f["id"]
        return "type_folder"

    ext = Path(name or "").suffix.lower()
    for f in filters:
        if f.get("kind") != "extension":
            continue
        if ext in f.get("extensions", []):
            return f["id"]

    for f in filters:
        if f.get("kind") == "other":
            return f["id"]
    return "type_other"


def path_keyword_matches(row: dict, filt: dict) -> bool:
    """path_keyword フィルタに行が該当するか。"""
    keywords = filt.get("keywords") or []
    if not keywords:
        return False
    fields = filt.get("match_in") or ["fullpath", "path", "name"]
    parts = []
    for field in fields:
        parts.append(str(row.get(field) or ""))
    text = "\n".join(parts)
    ci = bool(filt.get("case_insensitive", True))
    hay = text.lower() if ci else text
    for kw in keywords:
        needle = kw.lower() if ci else kw
        if needle and needle in hay:
            return True
    return False

# PowerShell 程度の読みやすさを意識した大きめフォント
FONT_UI = ("Yu Gothic UI", 13)
FONT_UI_BOLD = ("Yu Gothic UI", 13, "bold")
FONT_TITLE = ("Yu Gothic UI", 18, "bold")
FONT_SMALL = ("Yu Gothic UI", 12)
FONT_MONO = ("Consolas", 12)
FONT_ENTRY = ("Yu Gothic UI", 13)
FONT_TREE = ("Yu Gothic UI", 13)
FONT_TREE_HEAD = ("Yu Gothic UI", 13, "bold")


# =========================
# パスワードの暗号化（Windows DPAPI = crypt32.dll）
# =========================
# 保存形式: "enc:v1:<base64>"。同じ PC の同じ Windows ユーザーだけが復号できる。
# 別 PC / 別ユーザーで開いた場合は復号できないので空にして再入力してもらう。
_ENC_PREFIX = "enc:v1:"


def _dpapi_transform(data: bytes, protect: bool) -> bytes:
    """CryptProtectData / CryptUnprotectData を呼ぶ（Windows 専用）。"""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = DATA_BLOB()

    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(
        ctypes.byref(blob_in),
        None,  # 説明文（使わない）
        None,  # 追加エントロピー（使わない）
        None,
        None,  # プロンプトなし
        0,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def encrypt_secret(text: str) -> str:
    """保存用に暗号化する。暗号化できない環境では平文のまま返す。"""
    if not text or text.startswith(_ENC_PREFIX) or sys.platform != "win32":
        return text
    try:
        blob = _dpapi_transform(text.encode("utf-8"), protect=True)
    except (OSError, ValueError):
        return text
    return _ENC_PREFIX + base64.b64encode(blob).decode("ascii")


def decrypt_secret(text: str) -> str:
    """読み込み時に復号する。復号できないときは空（別 PC / 別ユーザー）。"""
    if not text:
        return ""
    if not text.startswith(_ENC_PREFIX):
        return text  # 旧バージョンが書いた平文
    if sys.platform != "win32":
        return ""
    try:
        blob = base64.b64decode(text[len(_ENC_PREFIX) :].encode("ascii"))
        return _dpapi_transform(blob, protect=False).decode("utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return ""


# =========================
# 設定ファイル
# =========================
def normalize_folder_history(raw) -> list[str]:
    """履歴を引用符付きパスのリストに正規化する（新しい順・重複なし）。"""
    if not isinstance(raw, list):
        return []
    seen = set()
    result = []
    for item in raw:
        q = quote_folder_path(str(item) if item is not None else "")
        if not q:
            continue
        key = strip_folder_quotes(q).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(q)
        if len(result) >= FOLDER_HISTORY_MAX:
            break
    return result


def normalize_connection_history(raw) -> list[dict]:
    """接続履歴を [{host, port}, ...] に正規化（新しい順・host:port 重複なし）。"""
    if not isinstance(raw, list):
        return []
    seen = set()
    result = []
    for item in raw:
        host = ""
        port = 8888
        if isinstance(item, dict):
            host = str(item.get("host") or "").strip()
            try:
                port = int(item.get("port", 8888))
            except (TypeError, ValueError):
                port = 8888
        elif isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            if text.count(":") == 1:
                # host:port（IPv4 / ホスト名想定。IPv6 は非対応）
                left, right = text.rsplit(":", 1)
                host = left.strip()
                try:
                    port = int(right.strip())
                except ValueError:
                    host = text
                    port = 8888
            else:
                host = text
        if not host:
            continue
        if not (1 <= port <= 65535):
            port = 8888
        key = f"{host.lower()}:{port}"
        if key in seen:
            continue
        seen.add(key)
        result.append({"host": host, "port": port})
        if len(result) >= CONNECTION_HISTORY_MAX:
            break
    return result


def format_connection_history_label(item: dict) -> str:
    return f"{item.get('host', '')}:{item.get('port', 8888)}"


def normalize_chip_state(raw, filters: list[dict]) -> dict:
    """チップ明暗を id->bool に正規化。未設定は default_on。"""
    saved = raw if isinstance(raw, dict) else {}
    state = {}
    for f in filters:
        fid = f["id"]
        if fid in saved:
            state[fid] = bool(saved[fid])
        else:
            state[fid] = bool(f.get("default_on", True))
    return state


def _migrate_settings_to_data_dir() -> None:
    """旧 EXE 隣の settings.json を LocalAppData\\SuguSearch\\data へ一度コピー。"""
    try:
        if SETTINGS_PATH.is_file():
            return
        inst = detect_install_root() or local_app_install_root()
        if SETTINGS_PATH.parent != (inst / "data"):
            return
        for legacy in (
            APP_DIR / "settings.json",
            local_app_install_root() / "current" / "settings.json",
            Path(__file__).resolve().parent / "settings.json",
            legacy_settings_path(),  # 旧 Everysearch の設定を引き継ぐ
        ):
            if legacy.is_file() and legacy.resolve() != SETTINGS_PATH.resolve():
                SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
                SETTINGS_PATH.write_bytes(legacy.read_bytes())
                return
    except OSError:
        pass


def load_settings() -> dict:
    _migrate_settings_to_data_dir()
    data = dict(DEFAULT_SETTINGS)
    data["folder_history"] = list(DEFAULT_SETTINGS["folder_history"])
    data["connection_history"] = list(DEFAULT_SETTINGS["connection_history"])
    data["filters"] = []
    data["chip_state"] = {}
    if SETTINGS_PATH.is_file():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k in DEFAULT_SETTINGS:
                    if k in loaded:
                        data[k] = loaded[k]
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    # パスワード／GitHub トークンは暗号化して保存（旧平文も読める）
    data["password"] = decrypt_secret(str(data.get("password") or ""))
    data["github_token"] = decrypt_secret(str(data.get("github_token") or ""))
    # 既定フォルダに引用符が無い場合は付ける
    data["search_folder"] = quote_folder_path(data.get("search_folder", "") or "")
    data["folder_history"] = normalize_folder_history(data.get("folder_history", []))
    data["connection_history"] = normalize_connection_history(
        data.get("connection_history", [])
    )
    data["filters"] = normalize_filter_definitions(data.get("filters"))
    data["chip_state"] = normalize_chip_state(data.get("chip_state"), data["filters"])
    # 現在の対象フォルダが履歴に無ければ先頭へ（空は追加しない）
    current = data["search_folder"]
    if current:
        data["folder_history"] = normalize_folder_history(
            [current] + data["folder_history"]
        )
    try:
        data["port"] = int(data.get("port", 8888))
    except (TypeError, ValueError):
        data["port"] = 8888
    # 現在の接続先も履歴先頭へ
    data["connection_history"] = normalize_connection_history(
        [{"host": str(data.get("host") or "127.0.0.1"), "port": data["port"]}]
        + data["connection_history"]
    )
    return data


def save_settings(settings: dict) -> None:
    filters = normalize_filter_definitions(settings.get("filters"))
    payload = {
        "host": str(settings.get("host", "127.0.0.1")).strip() or "127.0.0.1",
        "port": int(settings.get("port", 8888)),
        "user": str(settings.get("user", "")),
        "password": encrypt_secret(str(settings.get("password", ""))),
        "github_token": encrypt_secret(str(settings.get("github_token", ""))),
        "search_folder": quote_folder_path(settings.get("search_folder", "")),
        "folder_history": normalize_folder_history(settings.get("folder_history", [])),
        "connection_history": normalize_connection_history(
            settings.get("connection_history", [])
        ),
        "filters": filters,
        "chip_state": normalize_chip_state(settings.get("chip_state"), filters),
    }
    SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def strip_folder_quotes(folder: str) -> str:
    """前後の " または ' を外したパスを返す。"""
    f = (folder or "").strip()
    if len(f) >= 2 and f[0] == f[-1] and f[0] in "\"'":
        return f[1:-1].strip()
    return f


def quote_folder_path(folder: str) -> str:
    """
    表示・保存用に "パス" 形式にする。
    空欄はそのまま（全体検索）。
    """
    f = strip_folder_quotes(folder)
    if not f:
        return ""
    return f'"{f}"'


# =========================
# 検索語変換
# =========================
_FULLWIDTH_SPACE = "\u3000"
# 重複キー用: - / _ / 半角・全角スペースを同一視（検索のスペース緩和とは別）
_FLEX_SEPARATORS = frozenset(("-", "_", " ", _FULLWIDTH_SPACE))
# - / _ は「区切り1文字」（半角・全角スペースも1文字として許容）
_FLEX_SEPARATOR_CLASS = r"[-_\x20\x{3000}]"
# 検索入力のスペースは「間に任意」（ヒットが増えてよい）
_LOOSE_GAP = ".*?"


def to_flexible_regex(text: str) -> str:
    """
    入力中のゆらぎを正規表現へ変換する。

    - `-` / `_` … 区切り1文字として同一視（[-_\\x20\\x{3000}]）
    - 半角・全角スペース … 間に任意の文字列を許容（.*?）
      連続スペースは1つの間にまとめる

    先頭固定（^）は付けない（途中一致）。

    例:
      REV757_0200     -> REV757[-_…]0200
      空　スタッカー  -> 空.*?スタッカー  （空トレイアンスタッカー 等）
      AB010 54        -> AB010.*?54       （AB010-85-054 等）
    """
    parts = []
    i = 0
    s = text.strip()
    while i < len(s):
        ch = s[i]
        if ch in (" ", _FULLWIDTH_SPACE):
            while i < len(s) and s[i] in (" ", _FULLWIDTH_SPACE):
                i += 1
            parts.append(_LOOSE_GAP)
            continue
        if ch in "-_":
            parts.append(_FLEX_SEPARATOR_CLASS)
        else:
            parts.append(re.escape(ch))
        i += 1
    return "".join(parts)


def normalize_name_for_dedup(filename: str) -> str:
    """
    重複判定用キー。
    ファイル名の - / _ / 半角・全角スペースを同一視し、拡張子は大小無視。
    """
    name = filename or ""
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    parts = []
    for ch in stem:
        if ch in _FLEX_SEPARATORS:
            parts.append("\x00")
        else:
            parts.append(ch.lower())
    # 連続する区切りは1つにまとめる
    norm_stem = re.sub(r"\x00+", "\x00", "".join(parts)).strip("\x00")
    return f"{norm_stem}{ext}"


def path_depth(fullpath: str) -> int:
    """パスの深さ（区切りの数）。浅いほど小さい。"""
    p = (fullpath or "").replace("/", "\\").strip("\\")
    if not p:
        return 0
    return p.count("\\")


def pick_better_duplicate(a: dict, b: dict) -> dict:
    """
    同名ファイルのうち残す方を選ぶ。
    1. 更新日時が新しい
    2. パスが浅い
    3. フルパスが短い
    4. フルパスの辞書順が先
    """
    da = a.get("date_raw", -1.0)
    db = b.get("date_raw", -1.0)
    if da != db:
        return a if da > db else b

    pa = a.get("path_depth", 10**9)
    pb = b.get("path_depth", 10**9)
    if pa != pb:
        return a if pa < pb else b

    fa = a.get("fullpath") or ""
    fb = b.get("fullpath") or ""
    if len(fa) != len(fb):
        return a if len(fa) < len(fb) else b
    return a if fa <= fb else b


def dedupe_files_keep_newest(rows: list) -> list:
    """
    ファイルのみ、あいまい正規化した name+ext で重複排除。
    フォルダはそのまま残す。
    """
    folders = []
    files = []
    for r in rows:
        if (r.get("type") or "").lower() == "folder":
            folders.append(r)
        else:
            files.append(r)

    best: dict[str, dict] = {}
    for r in files:
        key = r.get("dedup_key") or normalize_name_for_dedup(r.get("name") or "")
        if key not in best:
            best[key] = r
        else:
            best[key] = pick_better_duplicate(best[key], r)

    # フォルダを先に、ファイルは元の相対順に近いよう fullpath で安定ソートは後段の sort に任せる
    return folders + list(best.values())


# =========================
# クリップボードへのファイルコピー
# =========================
def copy_files_to_clipboard(paths: list[str]) -> int:
    """
    選択ファイル/フォルダをクリップボードへ（CF_HDROP）。
    エクスプローラーで「貼り付け」するとコピーされる。
    戻り値: コピーした件数。
    """
    if sys.platform != "win32":
        raise OSError("Windows 専用です")
    if not paths:
        raise ValueError("パスがありません")

    import ctypes
    from ctypes import wintypes
    import struct
    import win32clipboard
    import win32con

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    GMEM_MOVEABLE = 0x0002
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    normed = []
    for p in paths:
        p = (p or "").strip()
        if not p:
            continue
        is_unc = p.startswith("\\\\") or p.startswith("//")
        if not is_unc:
            p_norm = os.path.normpath(p)
            if os.path.exists(p_norm):
                p = p_norm
            elif os.path.exists(p):
                p = os.path.normpath(p)
            else:
                # 見つからなくてもパスは載せる（ネットワーク遅延対策）
                p = p_norm
        else:
            p = p.replace("/", "\\")
        if p not in normed:
            normed.append(p)

    if not normed:
        raise FileNotFoundError("コピーするパスがありません")

    # CF_HDROP データ
    path_bytes = ("\0".join(normed) + "\0\0").encode("utf-16-le")
    header = struct.pack("<IIIii", 20, 0, 0, 0, 1)  # DROPFILES, fWide=1
    raw = header + path_bytes
    hdrop = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
    if not hdrop:
        raise OSError("GlobalAlloc failed")
    ptr = kernel32.GlobalLock(hdrop)
    ctypes.memmove(ptr, raw, len(raw))
    kernel32.GlobalUnlock(hdrop)

    # Preferred DropEffect = COPY (1)
    drop_effect = struct.pack("<I", 1)  # DROPEFFECT_COPY
    heffect = kernel32.GlobalAlloc(GMEM_MOVEABLE, 4)
    if not heffect:
        raise OSError("GlobalAlloc failed (drop effect)")
    ptr_e = kernel32.GlobalLock(heffect)
    ctypes.memmove(ptr_e, drop_effect, 4)
    kernel32.GlobalUnlock(heffect)

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        # SetClipboardData が所有権を持つ（解放しない）
        win32clipboard.SetClipboardData(win32con.CF_HDROP, int(hdrop))
        fmt_effect = win32clipboard.RegisterClipboardFormat("Preferred DropEffect")
        win32clipboard.SetClipboardData(fmt_effect, int(heffect))
    finally:
        win32clipboard.CloseClipboard()

    return len(normed)


# =========================
# 表示用ヘルパー
# =========================
def format_size(size_value) -> str:
    if size_value in (None, "", "-"):
        return ""
    try:
        size = int(size_value)
    except (TypeError, ValueError):
        return ""
    if size < 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def filetime_to_datetime(filetime_value):
    if filetime_value in (None, "", "0", 0):
        return None
    try:
        ft = int(filetime_value)
    except (TypeError, ValueError):
        return None
    if ft <= 0:
        return None
    try:
        seconds = (ft - _FILETIME_EPOCH_DIFF) / 10_000_000
        return dt.datetime.fromtimestamp(seconds)
    except (OSError, OverflowError, ValueError):
        return None


def format_datetime(filetime_value) -> str:
    d = filetime_to_datetime(filetime_value)
    if not d:
        return ""
    return d.strftime("%Y-%m-%d %H:%M")


def type_display_label(tag: str, name: str, filters: list[dict] | None = None) -> str:
    """一覧「種類」列の表示名。"""
    if filters:
        for f in filters:
            if f.get("id") == tag:
                if f.get("kind") == "other":
                    ext = Path(name or "").suffix.lower()
                    return ext.lstrip(".").upper() if ext else f.get("label", "その他")
                return f.get("label") or tag
    # フォールバック
    if tag in ("type_folder", "folder"):
        return "フォルダ"
    ext = Path(name or "").suffix.lower()
    return ext.lstrip(".").upper() if ext else "その他"


# =========================
# Everything HTTP 問い合わせ
# =========================
def search_everything(
    query_regex: str,
    search_folder: str = "",
    host: str = "127.0.0.1",
    port: int = 8888,
    user: str = "",
    password: str = "",
    count: int | None = None,
    item_type: str | None = None,
):
    """
    Everything HTTP サーバーへ問い合わせる（JSON）。
    path: で配下に限定し、regex: で -/_ ゆらぎを吸収する。
    item_type: "folder" のとき folder: を付与（フォルダのみ）。
    count 未指定時は MAX_RESULTS。
    """
    folder = strip_folder_quotes(search_folder)
    parts = []
    # フォルダのみモード（フィルタ「フォルダ」だけ ON のとき）
    if item_type == "folder":
        parts.append("folder:")
    elif item_type == "file":
        parts.append("file:")
    if folder:
        parts.append(f'path:"{folder}"')
    parts.append(f"regex:{query_regex}")
    search_query = " ".join(parts)

    fetch_count = MAX_RESULTS if count is None else max(1, int(count))
    params = {
        "search": search_query,
        "json": 1,
        "count": fetch_count,
        "path_column": 1,
        "size_column": 1,
        "date_modified_column": 1,
        # 取得分を新しい順にしておく（フィルタ後の上位表示の質向上）
        "sort": "date_modified",
        "ascending": 0,
    }

    url = f"http://{host}:{int(port)}/?{urlencode(params)}"
    req = Request(url)

    if user or password:
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", f"Basic {token}")

    # 件数が多いときはタイムアウトを延ばす
    timeout = 15 if fetch_count <= MAX_RESULTS else min(180, 20 + fetch_count // 200)
    with urlopen(req, timeout=timeout) as res:
        data = res.read().decode("utf-8", errors="replace")
        return json.loads(data)


def parse_results(data, filters: list[dict] | None = None):
    filters = filters or default_filter_definitions()
    results = []

    # 種類ソート用の順序
    type_order = {
        f["id"]: i
        for i, f in enumerate(
            sorted(
                [x for x in filters if x["kind"] in ("folder", "extension", "other")],
                key=lambda x: x.get("order", 0),
            )
        )
    }

    for item in data.get("results", []):
        path = item.get("path", "") or ""
        name = item.get("name", "") or ""
        item_type = item.get("type", "") or ""

        if path and name:
            fullpath = os.path.join(path, name)
        elif name:
            fullpath = name
        else:
            continue

        size_raw = item.get("size", "")
        date_raw = item.get("date_modified", "")
        date_dt = filetime_to_datetime(date_raw)
        tag = classify_with_filters(item_type, name, filters)
        label = type_display_label(tag, name, filters)

        try:
            size_num = int(size_raw) if size_raw not in (None, "") else -1
        except (TypeError, ValueError):
            size_num = -1

        is_folder = (item_type or "").lower() == "folder"
        results.append(
            {
                "fullpath": fullpath,
                "name": name,
                "path": path,
                "type": item_type,
                "tag": tag,
                "type_text": label,
                "type_sort": (
                    type_order.get(tag, 99),
                    label.lower(),
                    name.lower(),
                ),
                "name_sort": name.lower(),
                "size_raw": size_num,
                "size_text": format_size(size_raw) if not is_folder else "",
                "date_raw": date_dt.timestamp() if date_dt else -1.0,
                "date_text": format_datetime(date_raw),
                "path_depth": path_depth(fullpath),
                "dedup_key": "" if is_folder else normalize_name_for_dedup(name),
            }
        )

    return results


# =========================
# UI部品
# =========================
class TypeFilterChip(tk.Frame):
    """
    種類の表示/非表示を切り替えるチップ。
    オン: 本来の色 / オフ: ダークアウトして一覧から除外
    """

    def __init__(
        self,
        master,
        text: str,
        tag: str,
        active_bg: str,
        command=None,
        **kwargs,
    ):
        super().__init__(master, bg=UI["surface"], **kwargs)
        self.tag = tag
        self.active_bg = active_bg
        self.command = command
        self.enabled = True

        self.label = tk.Label(
            self,
            text=text,
            bg=active_bg,
            fg=UI["text"],
            font=FONT_SMALL,
            padx=10,
            pady=4,
            cursor="hand2",
        )
        self.label.pack()
        self.configure(highlightbackground=UI["border"], highlightthickness=1)

        for w in (self, self.label):
            w.bind("<Button-1>", self._on_click)

        self._refresh_look()

    def _on_click(self, _event=None):
        self.set_enabled(not self.enabled)
        if self.command:
            self.command(self.tag, self.enabled)

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        self._refresh_look()

    def _refresh_look(self):
        if self.enabled:
            self.label.configure(bg=self.active_bg, fg=UI["text"])
            self.configure(highlightbackground=UI["border"], highlightthickness=1)
        else:
            # ダークアウト（非表示）
            self.label.configure(bg=FILTER_OFF_BG, fg=FILTER_OFF_FG)
            self.configure(highlightbackground="#64748B", highlightthickness=1)


class ModernButton(tk.Label):
    def __init__(
        self,
        master,
        text: str,
        command=None,
        variant: str = "secondary",
        **kwargs,
    ):
        self.command = command
        self._enabled = True
        colors = self._palette(variant)
        super().__init__(
            master,
            text=text,
            bg=colors["bg"],
            fg=colors["fg"],
            font=FONT_UI_BOLD if variant == "primary" else FONT_UI,
            padx=16,
            pady=9,
            cursor="hand2",
            **kwargs,
        )
        self._colors = colors
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    @staticmethod
    def _palette(variant: str):
        if variant == "primary":
            return {
                "bg": UI["primary"],
                "fg": UI["primary_text"],
                "hover": UI["primary_hover"],
            }
        if variant == "ghost":
            return {
                "bg": UI["surface"],
                "fg": UI["text"],
                "hover": UI["surface_2"],
            }
        return {
            "bg": UI["secondary"],
            "fg": UI["secondary_text"],
            "hover": "#E0E7FF",
        }

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self.configure(
            bg=self._colors["bg"] if self._enabled else UI["border"],
            fg=self._colors["fg"] if self._enabled else UI["text_muted"],
            cursor="hand2" if self._enabled else "arrow",
        )

    def _on_enter(self, _e=None):
        if self._enabled:
            self.configure(bg=self._colors["hover"])

    def _on_leave(self, _e=None):
        if self._enabled:
            self.configure(bg=self._colors["bg"])

    def _on_click(self, _e=None):
        if self._enabled and self.command:
            self.command()


# =========================
# GUI
# =========================
class EverythingSearchApp:
    SORT_KEYS = {
        "path": "fullpath",
        "name": "name_sort",
        "type": "type_sort",
        "size": "size_raw",
        "date": "date_raw",
    }
    SORT_LABELS = {
        "path": "場所",
        "name": "名前",
        "type": "種類",
        "size": "サイズ",
        "date": "更新日時",
    }
    SORT_DEFAULT_ASC = {
        "path": True,
        "name": True,
        "type": True,
        "size": False,
        "date": False,  # 日時は新しい順が初期
    }

    def __init__(self, root):
        self.root = root
        self.root.title(f"すぐサーチ  {read_version()}")
        self.root.geometry("1240x780")
        # 下部ボタン＋検索欄が隠れない程度の最小サイズ
        self.root.minsize(960, 520)
        self.root.configure(bg=UI["bg"])

        self.settings = load_settings()
        self._setup_styles()

        self.all_results = []
        self.display_results = []
        self.total_results = 0
        # 初期表示: 更新日時の新しい順
        self.sort_column = "date"
        self.sort_ascending = False
        # フィルタ定義とチップ明暗（settings から復元）
        self.filter_defs = normalize_filter_definitions(self.settings.get("filters"))
        self.chip_state = normalize_chip_state(
            self.settings.get("chip_state"), self.filter_defs
        )
        self.filter_chips = {}  # id -> TypeFilterChip
        self.filter_chip_host = None  # チップを置く Frame
        self.filter_stats = {}
        self.folder_history_open = False
        self.connection_history_open = False
        # 直前の検索条件（フィルタ後の自動再取得用）
        self._last_regex = ""
        self._last_folder = ""
        self._refetch_done_for_search = False
        # 現在 all_results を取ったときの item_type（None / "folder"）
        self._results_item_type: str | None = None
        # 非同期検索（世代番号で古い応答を破棄）
        self._search_gen = 0
        self._search_busy = False
        # ライブ検索用デバウンス
        self._live_after_id = None
        # フィルタ設定 UI 用
        self._filter_editor_id = None
        self._filter_list_ids = []

        self.create_widgets()
        # 終了時にチップ状態を保存
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.entry.focus_set()

    # ----- connection helpers -----
    def _conn(self):
        return {
            "host": self.settings.get("host", "127.0.0.1"),
            "port": int(self.settings.get("port", 8888)),
            "user": self.settings.get("user", ""),
            "password": self.settings.get("password", ""),
        }

    def _setup_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TNotebook", background=UI["bg"], borderwidth=0)
        style.configure(
            "App.TNotebook.Tab",
            font=FONT_UI_BOLD,
            padding=(18, 10),
            background=UI["surface_2"],
            foreground=UI["text_muted"],
        )
        style.map(
            "App.TNotebook.Tab",
            background=[("selected", UI["surface"])],
            foreground=[("selected", UI["text"])],
        )

        style.configure(
            "Search.TEntry",
            fieldbackground="#FFFFFF",
            foreground=UI["text"],
            insertcolor=UI["text"],
            bordercolor=UI["border"],
            lightcolor=UI["primary"],
            darkcolor=UI["border"],
            padding=10,
            font=FONT_ENTRY,
        )
        style.map(
            "Search.TEntry",
            fieldbackground=[("focus", "#FFFFFF")],
            bordercolor=[("focus", UI["primary"])],
        )

        style.configure(
            "Settings.TEntry",
            fieldbackground="#FFFFFF",
            foreground=UI["text"],
            insertcolor=UI["text"],
            bordercolor=UI["border"],
            lightcolor=UI["primary"],
            darkcolor=UI["border"],
            padding=10,
            font=FONT_ENTRY,
        )

        style.configure(
            "Results.Treeview",
            background=UI["surface"],
            fieldbackground=UI["surface"],
            foreground=UI["text"],
            rowheight=36,
            borderwidth=0,
            font=FONT_TREE,
        )
        style.configure(
            "Results.Treeview.Heading",
            background=UI["heading"],
            foreground=UI["text"],
            relief="flat",
            borderwidth=0,
            font=FONT_TREE_HEAD,
            padding=10,
        )
        style.map(
            "Results.Treeview",
            background=[("selected", UI["select"])],
            foreground=[("selected", UI["text"])],
        )
        style.map(
            "Results.Treeview.Heading",
            background=[("active", UI["accent_line"])],
        )

        style.configure(
            "Modern.Vertical.TScrollbar",
            background=UI["border"],
            troughcolor=UI["surface_2"],
            bordercolor=UI["surface_2"],
            arrowcolor=UI["text_muted"],
            relief="flat",
        )
        style.configure(
            "Modern.Horizontal.TScrollbar",
            background=UI["border"],
            troughcolor=UI["surface_2"],
            bordercolor=UI["surface_2"],
            arrowcolor=UI["text_muted"],
            relief="flat",
        )

    def _card_shell(self, parent, **pack_kwargs) -> tk.Frame:
        outer = tk.Frame(parent, bg=UI["bg"])
        outer.pack(**pack_kwargs)
        shell = tk.Frame(
            outer,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        shell.pack(fill="both", expand=True)
        card = tk.Frame(shell, bg=UI["surface"])
        card.pack(fill="both", expand=True, padx=16, pady=14)
        return card

    def create_widgets(self):
        # ヘッダ（タイトルのみ）
        header = tk.Frame(self.root, bg=UI["bg"])
        header.pack(fill="x", padx=20, pady=(16, 6))
        tk.Label(
            header,
            text="すぐサーチ",
            bg=UI["bg"],
            fg=UI["text"],
            font=FONT_TITLE,
        ).pack(side="left")

        # タブ
        self.notebook = ttk.Notebook(self.root, style="App.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.search_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.settings_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.filter_settings_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.help_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.update_tab = tk.Frame(self.notebook, bg=UI["bg"])
        self.notebook.add(self.search_tab, text="  検索  ")
        self.notebook.add(self.settings_tab, text="  接続設定  ")
        self.notebook.add(self.filter_settings_tab, text="  フィルタ設定  ")
        self.notebook.add(self.update_tab, text="  更新  ")
        self.notebook.add(self.help_tab, text="  使い方  ")

        self._build_search_tab()
        self._build_settings_tab()
        self._build_filter_settings_tab()
        self._build_update_tab()
        self._build_help_tab()

    def _build_search_tab(self):
        parent = self.search_tab

        # 先にフッターを bottom 固定 → ウィンドウを縮めてもボタンが隠れない
        footer_outer = tk.Frame(parent, bg=UI["bg"])
        footer_outer.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        footer_shell = tk.Frame(
            footer_outer,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        footer_shell.pack(fill="x")
        footer = tk.Frame(footer_shell, bg=UI["surface"])
        footer.pack(fill="x", padx=16, pady=12)

        top_footer = tk.Frame(footer, bg=UI["surface"])
        top_footer.pack(fill="x")

        legend = tk.Frame(top_footer, bg=UI["surface"])
        legend.pack(side="left", fill="x", expand=True)
        # 「フィルタ」ラベル: クリックで全ON ⇔ 全OFF
        self.filter_all_on_btn = tk.Label(
            legend,
            text="フィルタ",
            bg=UI["surface"],
            fg=UI["primary"],
            font=FONT_UI_BOLD,
            cursor="hand2",
            padx=4,
            pady=2,
        )
        self.filter_all_on_btn.pack(side="left", padx=(0, 8))
        self.filter_all_on_btn.bind(
            "<Button-1>", lambda _e: self.toggle_all_filters()
        )
        self.filter_all_on_btn.bind(
            "<Enter>",
            lambda _e: self.filter_all_on_btn.configure(fg=UI["primary_hover"]),
        )
        self.filter_all_on_btn.bind(
            "<Leave>",
            lambda _e: self.filter_all_on_btn.configure(fg=UI["primary"]),
        )
        self.filter_chip_host = tk.Frame(legend, bg=UI["surface"])
        self.filter_chip_host.pack(side="left", fill="x", expand=True)
        self.rebuild_filter_chips()

        actions = tk.Frame(top_footer, bg=UI["surface"])
        actions.pack(side="right")
        ModernButton(
            actions,
            text="選択ファイルを開く",
            command=self.open_selected,
            variant="primary",
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            actions, text="選択フォルダを開く", command=self.open_selected_folder
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            actions, text="ファイルコピー", command=self.copy_selected_files
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            actions, text="パスのコピー", command=self.copy_selected_path, variant="ghost"
        ).pack(side="left")

        self.regex_var = tk.StringVar(value="変換後正規表現:  —")
        tk.Label(
            footer,
            textvariable=self.regex_var,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_MONO,
            anchor="w",
        ).pack(fill="x", pady=(10, 0))

        # 検索カード（上部）
        search_card = self._card_shell(parent, side="top", fill="x", padx=8, pady=(8, 6))

        row1 = tk.Frame(search_card, bg=UI["surface"])
        row1.pack(fill="x")
        tk.Label(
            row1,
            text="検索",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_UI,
            width=10,
            anchor="w",
        ).pack(side="left")
        self.keyword_var = tk.StringVar()
        self.entry = ttk.Entry(
            row1, textvariable=self.keyword_var, style="Search.TEntry"
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        # Enter = 即時検索 / 通常入力 = デバウンス付きライブ検索
        self.entry.bind("<Return>", lambda _e: self.on_search())
        self.entry.bind("<KeyRelease>", self._on_keyword_key_release)
        self.entry.bind("<<Paste>>", self._on_keyword_paste)
        # 検索文字クリア（フォルダ欄の × と同じ見た目）
        ModernButton(
            row1, text="×", command=self.clear_search_keyword, variant="ghost"
        ).pack(side="left", padx=(0, 6))
        ModernButton(
            row1, text="検索", command=self.on_search, variant="primary"
        ).pack(side="left")

        row2 = tk.Frame(search_card, bg=UI["surface"])
        row2.pack(fill="x", pady=(12, 0))
        tk.Label(
            row2,
            text="対象フォルダ",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_UI,
            width=10,
            anchor="w",
        ).pack(side="left")
        self.folder_var = tk.StringVar(
            value=quote_folder_path(self.settings.get("search_folder", ""))
        )
        self.folder_entry = ttk.Entry(
            row2, textvariable=self.folder_var, style="Search.TEntry"
        )
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.folder_entry.bind("<FocusIn>", self._on_folder_entry_focus)
        self.folder_entry.bind("<Button-1>", self._on_folder_entry_click)
        self.folder_entry.bind("<Down>", self._on_folder_entry_down)
        self.folder_entry.bind("<Escape>", lambda _e: self.hide_folder_history())

        # 履歴閉時: 入力クリア / 履歴開時: 一覧を閉じる
        self.folder_clear_btn = ModernButton(
            row2, text="×", command=self.on_folder_clear_or_close, variant="ghost"
        )
        self.folder_clear_btn.pack(side="left", padx=(0, 6))
        ModernButton(
            row2, text="フォルダ選択…", command=self.browse_folder
        ).pack(side="left")

        # 履歴ドロップダウン（対象フォルダの下に表示）
        self.history_panel = tk.Frame(
            search_card,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        # pack は表示時のみ
        self.history_list_frame = tk.Frame(self.history_panel, bg=UI["surface"])
        self.history_list_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.history_empty_label = tk.Label(
            self.history_list_frame,
            text="履歴はまだありません",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        )

        # 件数
        self.info_var = tk.StringVar(value="型番・図番を入力して検索してください")
        info_bar = tk.Frame(parent, bg=UI["bg"])
        info_bar.pack(side="top", fill="x", padx=16, pady=(0, 4))
        tk.Label(
            info_bar,
            textvariable=self.info_var,
            bg=UI["bg"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x")

        # 結果テーブル（残り領域を占有。縮小時はここだけが縮む）
        result_outer = tk.Frame(parent, bg=UI["bg"])
        result_outer.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 6))
        result_card = tk.Frame(
            result_outer,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        result_card.pack(fill="both", expand=True)
        table_wrap = tk.Frame(result_card, bg=UI["surface"])
        table_wrap.pack(fill="both", expand=True, padx=1, pady=1)

        columns = ("type", "name", "path", "size", "date")
        self.tree = ttk.Treeview(
            table_wrap,
            columns=columns,
            show="headings",
            selectmode="extended",  # Ctrl/Shift 複数選択
            style="Results.Treeview",
        )
        self.tree.heading("type", text="種類", command=lambda: self.toggle_sort("type"))
        self.tree.heading("name", text="名前", command=lambda: self.toggle_sort("name"))
        self.tree.heading("path", text="場所", command=lambda: self.toggle_sort("path"))
        self.tree.heading("size", text="サイズ", command=lambda: self.toggle_sort("size"))
        self.tree.heading(
            "date", text="更新日時", command=lambda: self.toggle_sort("date")
        )

        self.tree.column("type", width=90, anchor="center", stretch=False, minwidth=80)
        self.tree.column("name", width=300, anchor="w", stretch=True, minwidth=180)
        self.tree.column("path", width=420, anchor="w", stretch=True, minwidth=200)
        self.tree.column("size", width=100, anchor="e", stretch=False, minwidth=80)
        self.tree.column("date", width=150, anchor="center", stretch=False, minwidth=120)

        self.configure_tree_tags()

        yscroll = ttk.Scrollbar(
            table_wrap,
            orient="vertical",
            command=self.tree.yview,
            style="Modern.Vertical.TScrollbar",
        )
        xscroll = ttk.Scrollbar(
            table_wrap,
            orient="horizontal",
            command=self.tree.xview,
            style="Modern.Horizontal.TScrollbar",
        )
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        self.tree.bind("<Double-Button-1>", self.open_selected)
        self.tree.bind("<Return>", self.open_selected)
        # Ctrl / Shift の複数選択を自前で処理する
        self.tree.bind("<ButtonPress-1>", self._on_tree_b1_down)
        # 右クリック → コンテキストメニュー
        self.tree.bind("<ButtonPress-3>", self._on_tree_b3_down)
        self.tree.bind("<ButtonRelease-3>", self._on_tree_b3_up)

        self._update_heading_labels()

    def _build_settings_tab(self):
        parent = self.settings_tab
        card = self._card_shell(parent, fill="both", expand=True, padx=8, pady=8)

        tk.Label(
            card,
            text="Everything HTTP サーバー接続",
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        tk.Label(
            card,
            text="Everything が別 PC で動いている場合は、そのホスト名または IP を指定してください。"
            "ホスト／ポート欄をクリックすると接続履歴から選べます。",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 16))

        form = tk.Frame(card, bg=UI["surface"])
        form.pack(fill="x")

        self.host_var = tk.StringVar(value=str(self.settings.get("host", "127.0.0.1")))
        self.port_var = tk.StringVar(value=str(self.settings.get("port", 8888)))
        self.user_var = tk.StringVar(value=str(self.settings.get("user", "")))
        self.password_var = tk.StringVar(value=str(self.settings.get("password", "")))

        fields = [
            ("ホスト / IP", self.host_var, False, "host"),
            ("ポート", self.port_var, False, "port"),
            ("ユーザー名（任意）", self.user_var, False, None),
            ("パスワード（任意）", self.password_var, True, None),
        ]
        self.host_entry = None
        self.port_entry = None
        for label, var, is_password, hist_key in fields:
            row = tk.Frame(form, bg=UI["surface"])
            row.pack(fill="x", pady=(0, 12))
            tk.Label(
                row,
                text=label,
                bg=UI["surface"],
                fg=UI["text_muted"],
                font=FONT_UI,
                width=18,
                anchor="w",
            ).pack(side="left")
            entry = ttk.Entry(
                row,
                textvariable=var,
                style="Settings.TEntry",
                show="●" if is_password else "",
            )
            entry.pack(side="left", fill="x", expand=True)
            if hist_key == "host":
                self.host_entry = entry
            elif hist_key == "port":
                self.port_entry = entry
            if hist_key:
                entry.bind("<FocusIn>", self._on_connection_entry_focus)
                entry.bind("<Button-1>", self._on_connection_entry_click)
                entry.bind("<Down>", self._on_connection_entry_down)
                entry.bind("<Escape>", lambda _e: self.hide_connection_history())

        # 接続履歴（ホスト／ポートフォーカス時に表示）
        self.connection_history_panel = tk.Frame(
            card,
            bg=UI["surface"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        self.connection_history_list_frame = tk.Frame(
            self.connection_history_panel, bg=UI["surface"]
        )
        self.connection_history_list_frame.pack(
            fill="both", expand=True, padx=4, pady=4
        )

        self.settings_btn_row = tk.Frame(card, bg=UI["surface"])
        self.settings_btn_row.pack(fill="x", pady=(8, 0))
        ModernButton(
            self.settings_btn_row,
            text="設定を保存",
            command=self.save_connection_settings,
            variant="primary",
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            self.settings_btn_row, text="接続テスト", command=self.test_connection
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            self.settings_btn_row,
            text="自身に接続",
            command=self.connect_to_self_and_test,
            variant="ghost",
        ).pack(side="left")

        self.settings_status_var = tk.StringVar(
            value=f"現在: {self.settings.get('host')}:{self.settings.get('port')}"
        )
        tk.Label(
            card,
            textvariable=self.settings_status_var,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            wraplength=900,
            justify="left",
        ).pack(fill="x", pady=(16, 0))

        tip = (
            "ヒント:\n"
            "・Everything → ツール → オプション → HTTP サーバー を有効にする\n"
            "・「自身に接続」でこのPCのIPを入れ、接続テストまで行います\n"
            "・ホスト／ポート欄をクリックすると、以前使った接続先を選べます\n"
            "・他 PC から使う場合は、ファイアウォールでポートを許可する\n"
            "・アプリの更新は「更新」タブから行えます\n"
            "・接続設定はこのPCだけに保存されます（他の人の設定とは別）"
        )
        tk.Label(
            card,
            text=tip,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(20, 0))

    def _build_filter_settings_tab(self):
        parent = self.filter_settings_tab
        card = self._card_shell(parent, fill="both", expand=True, padx=8, pady=8)

        tk.Label(
            card,
            text="フィルタ設定",
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        tk.Label(
            card,
            text="検索画面のチップ・色・拡張子・パス条件を編集します。保存すると settings.json に記録されます。",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            wraplength=900,
            justify="left",
        ).pack(fill="x", pady=(0, 10))

        body = tk.Frame(card, bg=UI["surface"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=300)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # 左: 一覧
        left = tk.Frame(body, bg=UI["surface"])
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
        tk.Label(
            left, text="フィルタ一覧", bg=UI["surface"], fg=UI["text"], font=FONT_UI
        ).pack(anchor="w")
        list_wrap = tk.Frame(left, bg=UI["surface"])
        list_wrap.pack(fill="both", expand=True, pady=(4, 6))
        self.filter_listbox = tk.Listbox(
            list_wrap,
            font=FONT_SMALL,
            width=36,
            height=18,
            activestyle="dotbox",
            selectmode="browse",
            exportselection=False,
        )
        list_scroll = ttk.Scrollbar(
            list_wrap, orient="vertical", command=self.filter_listbox.yview
        )
        self.filter_listbox.configure(yscrollcommand=list_scroll.set)
        self.filter_listbox.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        self.filter_listbox.bind("<<ListboxSelect>>", self._on_filter_list_select)

        list_btns = tk.Frame(left, bg=UI["surface"])
        list_btns.pack(fill="x")
        ModernButton(list_btns, text="↑", command=lambda: self._move_filter(-1)).pack(
            side="left", padx=(0, 4)
        )
        ModernButton(list_btns, text="↓", command=lambda: self._move_filter(1)).pack(
            side="left", padx=(0, 8)
        )
        ModernButton(
            list_btns, text="追加(拡張子)", command=lambda: self._add_filter("extension")
        ).pack(side="left", padx=(0, 4))
        ModernButton(
            list_btns, text="追加(条件)", command=lambda: self._add_filter("path_keyword")
        ).pack(side="left")

        list_btns2 = tk.Frame(left, bg=UI["surface"])
        list_btns2.pack(fill="x", pady=(6, 0))
        ModernButton(
            list_btns2, text="削除", command=self._delete_selected_filter, variant="ghost"
        ).pack(side="left")

        # 右: 詳細（grid でラベル列と入力列を分離 — pack だと重なる）
        right_outer = tk.Frame(body, bg=UI["surface"])
        right_outer.grid(row=0, column=1, sticky="nsew")
        right_outer.columnconfigure(0, weight=1)
        right_outer.rowconfigure(0, weight=1)

        right_canvas = tk.Canvas(right_outer, bg=UI["surface"], highlightthickness=0)
        right_scroll = ttk.Scrollbar(
            right_outer, orient="vertical", command=right_canvas.yview
        )
        right_canvas.configure(yscrollcommand=right_scroll.set)
        right_scroll.grid(row=0, column=1, sticky="ns")
        right_canvas.grid(row=0, column=0, sticky="nsew")

        right = tk.Frame(right_canvas, bg=UI["surface"])
        right_window = right_canvas.create_window((0, 0), window=right, anchor="nw")

        def _on_right_configure(_e=None):
            right_canvas.configure(scrollregion=right_canvas.bbox("all"))
            # キャンバス幅にフォームを合わせる
            right_canvas.itemconfigure(right_window, width=max(right_canvas.winfo_width(), 1))

        right.bind("<Configure>", _on_right_configure)
        right_canvas.bind("<Configure>", _on_right_configure)

        self.fe_id_var = tk.StringVar()
        self.fe_kind_var = tk.StringVar()
        self.fe_label_var = tk.StringVar()
        self.fe_color_var = tk.StringVar()
        self.fe_order_var = tk.StringVar()
        self.fe_show_chip_var = tk.BooleanVar(value=True)
        self.fe_default_on_var = tk.BooleanVar(value=True)
        self.fe_ext_var = tk.StringVar()
        self.fe_keywords_var = tk.StringVar()
        self.fe_match_full_var = tk.BooleanVar(value=True)
        self.fe_match_path_var = tk.BooleanVar(value=True)
        self.fe_match_name_var = tk.BooleanVar(value=True)
        self.fe_case_var = tk.BooleanVar(value=True)

        form = tk.Frame(right, bg=UI["surface"])
        form.pack(fill="x", anchor="n")
        form.columnconfigure(0, minsize=120, weight=0)
        form.columnconfigure(1, weight=1)

        def _grid_label(row: int, text: str):
            tk.Label(
                form,
                text=text,
                bg=UI["surface"],
                fg=UI["text_muted"],
                font=FONT_SMALL,
                anchor="w",
            ).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)

        def _grid_field(row: int, widget, sticky="ew"):
            widget.grid(row=row, column=1, sticky=sticky, pady=6)

        row = 0
        _grid_label(row, "ID")
        _grid_field(
            row,
            tk.Label(
                form,
                textvariable=self.fe_id_var,
                bg=UI["surface"],
                fg=UI["text"],
                font=FONT_MONO,
                anchor="w",
            ),
            sticky="w",
        )
        row += 1
        _grid_label(row, "種類")
        _grid_field(
            row,
            tk.Label(
                form,
                textvariable=self.fe_kind_var,
                bg=UI["surface"],
                fg=UI["text"],
                font=FONT_UI,
                anchor="w",
            ),
            sticky="w",
        )
        row += 1
        _grid_label(row, "表示名")
        _grid_field(
            row, ttk.Entry(form, textvariable=self.fe_label_var, style="Settings.TEntry")
        )
        row += 1
        _grid_label(row, "色 (#RRGGBB)")
        color_fr = tk.Frame(form, bg=UI["surface"])
        ttk.Entry(
            color_fr, textvariable=self.fe_color_var, style="Settings.TEntry", width=14
        ).pack(side="left")
        self.fe_color_preview = tk.Label(
            color_fr, text="    ", bg="#E2E8F0", width=4, relief="solid", borderwidth=1
        )
        self.fe_color_preview.pack(side="left", padx=(8, 0))
        _grid_field(row, color_fr, sticky="w")
        row += 1
        _grid_label(row, "並び (数)")
        _grid_field(
            row,
            ttk.Entry(
                form, textvariable=self.fe_order_var, style="Settings.TEntry", width=10
            ),
            sticky="w",
        )
        row += 1
        _grid_label(row, "オプション")
        opt_fr = tk.Frame(form, bg=UI["surface"])
        tk.Checkbutton(
            opt_fr,
            text="検索画面にチップを表示",
            variable=self.fe_show_chip_var,
            bg=UI["surface"],
            font=FONT_SMALL,
            activebackground=UI["surface"],
        ).pack(anchor="w")
        tk.Checkbutton(
            opt_fr,
            text="初期は明るい(表示側)",
            variable=self.fe_default_on_var,
            bg=UI["surface"],
            font=FONT_SMALL,
            activebackground=UI["surface"],
        ).pack(anchor="w")
        _grid_field(row, opt_fr, sticky="w")

        # 拡張子ブロック
        self.fe_ext_frame = tk.Frame(right, bg=UI["surface"])
        self.fe_ext_frame.pack(fill="x", anchor="n", pady=(12, 0))
        self.fe_ext_frame.columnconfigure(1, weight=1)
        tk.Label(
            self.fe_ext_frame,
            text="拡張子",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).grid(row=0, column=0, sticky="nw", padx=(0, 12), pady=4)
        ttk.Entry(
            self.fe_ext_frame, textvariable=self.fe_ext_var, style="Settings.TEntry"
        ).grid(row=0, column=1, sticky="ew", pady=4)
        tk.Label(
            self.fe_ext_frame,
            text="カンマ区切り 例: .dwg, .dxf",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).grid(row=1, column=1, sticky="ew")

        # キーワードブロック
        self.fe_kw_frame = tk.Frame(right, bg=UI["surface"])
        self.fe_kw_frame.pack(fill="x", anchor="n", pady=(12, 0))
        self.fe_kw_frame.columnconfigure(1, weight=1)
        tk.Label(
            self.fe_kw_frame,
            text="キーワード",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).grid(row=0, column=0, sticky="nw", padx=(0, 12), pady=4)
        ttk.Entry(
            self.fe_kw_frame, textvariable=self.fe_keywords_var, style="Settings.TEntry"
        ).grid(row=0, column=1, sticky="ew", pady=4)
        tk.Label(
            self.fe_kw_frame,
            text="カンマ区切り。パス等に含まれれば該当（暗いチップで除外）",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            wraplength=520,
            justify="left",
        ).grid(row=1, column=1, sticky="ew")
        tk.Label(
            self.fe_kw_frame,
            text="照合先",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).grid(row=2, column=0, sticky="nw", padx=(0, 12), pady=4)
        match_fr = tk.Frame(self.fe_kw_frame, bg=UI["surface"])
        for text, var in (
            ("フルパス", self.fe_match_full_var),
            ("場所", self.fe_match_path_var),
            ("名前", self.fe_match_name_var),
        ):
            tk.Checkbutton(
                match_fr,
                text=text,
                variable=var,
                bg=UI["surface"],
                font=FONT_SMALL,
                activebackground=UI["surface"],
            ).pack(side="left", padx=(0, 10))
        match_fr.grid(row=2, column=1, sticky="w", pady=4)
        tk.Label(
            self.fe_kw_frame,
            text="",
            bg=UI["surface"],
        ).grid(row=3, column=0)
        tk.Checkbutton(
            self.fe_kw_frame,
            text="大小文字を無視",
            variable=self.fe_case_var,
            bg=UI["surface"],
            font=FONT_SMALL,
            activebackground=UI["surface"],
        ).grid(row=3, column=1, sticky="w", pady=4)

        self.fe_note_var = tk.StringVar(value="")
        tk.Label(
            right,
            textvariable=self.fe_note_var,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(fill="x", pady=(12, 0), anchor="n")

        bottom = tk.Frame(card, bg=UI["surface"])
        bottom.pack(fill="x", pady=(12, 0))
        ModernButton(
            bottom, text="この項目を反映", command=self._apply_filter_editor_fields
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            bottom, text="設定を保存", command=self.save_filter_settings, variant="primary"
        ).pack(side="left", padx=(0, 8))
        ModernButton(
            bottom, text="既定に戻す", command=self.reset_filters_to_default, variant="ghost"
        ).pack(side="left")

        self._refresh_filter_listbox()
        if self._filter_list_ids:
            self.filter_listbox.selection_set(0)
            self._load_filter_into_editor(self._filter_list_ids[0])

    def _kind_label(self, kind: str) -> str:
        return {
            "folder": "フォルダ種類",
            "extension": "拡張子",
            "other": "その他（残り）",
            "path_keyword": "パス条件",
            "builtin_dedupe": "重複（ビルトイン）",
        }.get(kind, kind)

    def _refresh_filter_listbox(self):
        self.filter_listbox.delete(0, tk.END)
        self._filter_list_ids = []
        for f in sorted(self.filter_defs, key=lambda x: x.get("order", 0)):
            chip = "表示" if f.get("show_chip", True) else "非表示"
            self.filter_listbox.insert(
                tk.END, f"{f.get('order', 0):3d}  {f.get('label', '')}  [{self._kind_label(f['kind'])}]  チップ{chip}"
            )
            self._filter_list_ids.append(f["id"])

    def _on_filter_list_select(self, _event=None):
        sel = self.filter_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._filter_list_ids):
            # 編集中の内容を捨てて切り替え（反映ボタンで確定する運用）
            self._load_filter_into_editor(self._filter_list_ids[idx])

    def _load_filter_into_editor(self, fid: str):
        filt = next((f for f in self.filter_defs if f["id"] == fid), None)
        if not filt:
            return
        self._filter_editor_id = fid
        self.fe_id_var.set(filt["id"])
        self.fe_kind_var.set(self._kind_label(filt["kind"]))
        self.fe_label_var.set(filt.get("label", ""))
        self.fe_color_var.set(filt.get("color", "#E2E8F0"))
        self.fe_order_var.set(str(filt.get("order", 0)))
        self.fe_show_chip_var.set(bool(filt.get("show_chip", True)))
        self.fe_default_on_var.set(bool(filt.get("default_on", True)))
        try:
            self.fe_color_preview.configure(bg=filt.get("color", "#E2E8F0"))
        except tk.TclError:
            pass

        kind = filt["kind"]
        if kind == "extension":
            self.fe_ext_frame.pack(fill="x", anchor="n", pady=(12, 0))
            self.fe_ext_var.set(", ".join(filt.get("extensions") or []))
            self.fe_note_var.set("拡張子グループ。該当しないファイルは「その他」になります。")
        else:
            self.fe_ext_frame.pack_forget()

        if kind == "path_keyword":
            self.fe_kw_frame.pack(fill="x", anchor="n", pady=(12, 0))
            self.fe_keywords_var.set(", ".join(filt.get("keywords") or []))
            mi = set(filt.get("match_in") or [])
            self.fe_match_full_var.set("fullpath" in mi)
            self.fe_match_path_var.set("path" in mi)
            self.fe_match_name_var.set("name" in mi)
            self.fe_case_var.set(bool(filt.get("case_insensitive", True)))
            self.fe_note_var.set(
                "チップが暗いとき、キーワードに当てはまる結果を除外します。"
            )
        else:
            self.fe_kw_frame.pack_forget()

        if kind == "builtin_dedupe":
            self.fe_note_var.set(
                "ビルトイン: 暗い＝あいまい同名は最新1件のみ。判定ロジックは変更できません。"
            )
        elif kind == "folder":
            self.fe_note_var.set("フォルダ種別の表示切替です。")
        elif kind == "other":
            self.fe_note_var.set(
                "どの拡張子グループにも入らないファイル用。削除できません。"
            )

    def _apply_filter_editor_fields(self):
        fid = self._filter_editor_id
        if not fid:
            return
        filt = next((f for f in self.filter_defs if f["id"] == fid), None)
        if not filt:
            return
        label = self.fe_label_var.get().strip() or filt["id"]
        color = self.fe_color_var.get().strip() or "#E2E8F0"
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            messagebox.showerror("入力エラー", "色は #RRGGBB 形式で指定してください。")
            return
        try:
            order = int(self.fe_order_var.get().strip())
        except ValueError:
            messagebox.showerror("入力エラー", "並びは整数で指定してください。")
            return

        filt["label"] = label
        filt["color"] = color
        filt["order"] = order
        filt["show_chip"] = bool(self.fe_show_chip_var.get())
        filt["default_on"] = bool(self.fe_default_on_var.get())

        if filt["kind"] == "extension":
            raw = self.fe_ext_var.get().replace("、", ",").split(",")
            filt["extensions"] = _normalize_extensions(raw)
            if not filt["extensions"]:
                messagebox.showwarning("入力不足", "拡張子を1つ以上指定してください。")
                return
        if filt["kind"] == "path_keyword":
            raw = self.fe_keywords_var.get().replace("、", ",").split(",")
            filt["keywords"] = _normalize_keywords(raw)
            match_in = []
            if self.fe_match_full_var.get():
                match_in.append("fullpath")
            if self.fe_match_path_var.get():
                match_in.append("path")
            if self.fe_match_name_var.get():
                match_in.append("name")
            if not match_in:
                messagebox.showwarning("入力不足", "照合先を1つ以上選んでください。")
                return
            filt["match_in"] = match_in
            filt["case_insensitive"] = bool(self.fe_case_var.get())
            if not filt["keywords"]:
                messagebox.showwarning("入力不足", "キーワードを1つ以上指定してください。")
                return

        try:
            self.fe_color_preview.configure(bg=color)
        except tk.TclError:
            pass
        self.filter_defs = normalize_filter_definitions(self.filter_defs)
        # 選択維持
        self._refresh_filter_listbox()
        if fid in self._filter_list_ids:
            self.filter_listbox.selection_set(self._filter_list_ids.index(fid))
        self.info_var.set(f"フィルタ「{label}」を編集内容に反映しました（保存は別ボタン）")

    def _add_filter(self, kind: str):
        import time

        fid = f"{kind}_{int(time.time() * 1000) % 1000000}"
        max_order = max((f.get("order", 0) for f in self.filter_defs), default=100)
        if kind == "extension":
            item = {
                "id": fid,
                "kind": "extension",
                "label": "新規拡張子",
                "color": "#E0E7FF",
                "extensions": [".txt"],
                "show_chip": True,
                "default_on": True,
                "order": max_order + 10,
            }
        else:
            item = {
                "id": fid,
                "kind": "path_keyword",
                "label": "新規条件",
                "color": "#FDE68A",
                "keywords": ["keyword"],
                "match_in": ["fullpath", "path", "name"],
                "case_insensitive": True,
                "show_chip": True,
                "default_on": True,
                "order": max_order + 10,
            }
        self.filter_defs.append(item)
        self.filter_defs = normalize_filter_definitions(self.filter_defs)
        self.chip_state[fid] = True
        self._refresh_filter_listbox()
        if fid in self._filter_list_ids:
            idx = self._filter_list_ids.index(fid)
            self.filter_listbox.selection_clear(0, tk.END)
            self.filter_listbox.selection_set(idx)
            self.filter_listbox.see(idx)
            self._load_filter_into_editor(fid)

    def _delete_selected_filter(self):
        sel = self.filter_listbox.curselection()
        if not sel:
            return
        fid = self._filter_list_ids[sel[0]]
        filt = next((f for f in self.filter_defs if f["id"] == fid), None)
        if not filt:
            return
        if filt.get("locked") or filt.get("kind") in ("other", "builtin_dedupe", "folder"):
            if filt.get("kind") in ("other", "builtin_dedupe"):
                messagebox.showinfo("削除不可", "このフィルタは削除できません。")
                return
            if filt.get("kind") == "folder":
                messagebox.showinfo(
                    "削除不可", "フォルダ種類フィルタは削除できません（非表示にはできます）。"
                )
                return
        if not messagebox.askyesno("確認", f"「{filt.get('label')}」を削除しますか？"):
            return
        self.filter_defs = [f for f in self.filter_defs if f["id"] != fid]
        self.filter_defs = normalize_filter_definitions(self.filter_defs)
        self.chip_state.pop(fid, None)
        self._refresh_filter_listbox()
        if self._filter_list_ids:
            self.filter_listbox.selection_set(0)
            self._load_filter_into_editor(self._filter_list_ids[0])
        else:
            self._filter_editor_id = None

    def _move_filter(self, delta: int):
        sel = self.filter_listbox.curselection()
        if not sel:
            return
        # 並びは order で制御。選択の order と隣の order を入れ替え
        ordered = sorted(self.filter_defs, key=lambda x: x.get("order", 0))
        ids = [f["id"] for f in ordered]
        fid = self._filter_list_ids[sel[0]]
        if fid not in ids:
            return
        i = ids.index(fid)
        j = i + delta
        if j < 0 or j >= len(ordered):
            return
        ordered[i]["order"], ordered[j]["order"] = ordered[j]["order"], ordered[i]["order"]
        # order が同値だと不安定なので再採番
        for n, f in enumerate(sorted(self.filter_defs, key=lambda x: x.get("order", 0))):
            f["order"] = (n + 1) * 10
        self.filter_defs = normalize_filter_definitions(self.filter_defs)
        self._refresh_filter_listbox()
        if fid in self._filter_list_ids:
            ni = self._filter_list_ids.index(fid)
            self.filter_listbox.selection_set(ni)
            self._load_filter_into_editor(fid)

    def save_filter_settings(self):
        # 編集中フィールドがあれば先に反映
        if self._filter_editor_id:
            self._apply_filter_editor_fields()
        self.filter_defs = normalize_filter_definitions(self.filter_defs)
        self.settings["filters"] = self.filter_defs
        # チップ状態: 新規は default_on、既存 id は維持
        new_state = {}
        for f in self.filter_defs:
            fid = f["id"]
            if fid in self.chip_state:
                new_state[fid] = self.chip_state[fid]
            else:
                new_state[fid] = bool(f.get("default_on", True))
        self.chip_state = new_state
        self.settings["chip_state"] = dict(self.chip_state)
        try:
            save_settings(self.settings)
        except OSError as e:
            messagebox.showerror("保存失敗", f"settings.json を保存できません。\n{e}")
            return
        self.rebuild_filter_chips()
        # 既存結果を新しい分類で付け直す
        if self.all_results:
            # tag を付け直すために再 parse はできないので、classify を再実行
            for r in self.all_results:
                r["tag"] = classify_with_filters(r.get("type"), r.get("name"), self.filter_defs)
                r["type_text"] = type_display_label(r["tag"], r.get("name"), self.filter_defs)
            self.apply_sort_and_display()
        messagebox.showinfo("保存完了", "フィルタ設定を保存しました。")
        self._refresh_filter_listbox()

    def reset_filters_to_default(self):
        if not messagebox.askyesno(
            "確認", "フィルタ設定を出荷時の既定に戻しますか？\n（保存するまでファイルには書き込まれません）"
        ):
            return
        self.filter_defs = default_filter_definitions()
        self.chip_state = {
            f["id"]: bool(f.get("default_on", True)) for f in self.filter_defs
        }
        self.rebuild_filter_chips()
        self._refresh_filter_listbox()
        if self._filter_list_ids:
            self.filter_listbox.selection_set(0)
            self._load_filter_into_editor(self._filter_list_ids[0])
        if self.all_results:
            for r in self.all_results:
                r["tag"] = classify_with_filters(r.get("type"), r.get("name"), self.filter_defs)
                r["type_text"] = type_display_label(r["tag"], r.get("name"), self.filter_defs)
            self.apply_sort_and_display()

    def _build_update_tab(self):
        parent = self.update_tab
        card = self._card_shell(parent, fill="both", expand=True, padx=8, pady=8)

        tk.Label(
            card,
            text="アプリの更新",
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        tk.Label(
            card,
            text=(
                "新しい版があるか確認し、このPCへ取り込めます。"
                "更新後も、いつも使っているショートカットから起動できます。"
            ),
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            justify="left",
            wraplength=900,
        ).pack(fill="x", pady=(0, 12))

        self.update_local_ver_var = tk.StringVar(value=f"このPCの版: {read_version()}")
        self.update_remote_ver_var = tk.StringVar(value="ダウンロード可能な版: （未確認）")
        self.update_status_var = tk.StringVar(value="")
        self._pending_release = None

        tk.Label(
            card,
            textvariable=self.update_local_ver_var,
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            card,
            textvariable=self.update_remote_ver_var,
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI,
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        inst = detect_install_root()
        if inst is not None:
            layout = "このPC: セットアップ済み（自動更新が使えます）"
        else:
            layout = (
                "このPC: まだセットアップされていません。"
                "配布されたセットアップを一度実行してからお使いください。"
            )
        tk.Label(
            card,
            text=layout,
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
            wraplength=900,
            justify="left",
        ).pack(fill="x", pady=(8, 8))

        btn_row = tk.Frame(card, bg=UI["surface"])
        btn_row.pack(fill="x", pady=(4, 8))
        ModernButton(
            btn_row, text="更新を確認", command=self.check_for_updates, variant="primary"
        ).pack(side="left", padx=(0, 8))
        self.update_apply_btn = ModernButton(
            btn_row, text="ダウンロードして更新", command=self.apply_pending_update
        )
        self.update_apply_btn.pack(side="left", padx=(0, 8))
        self.update_apply_btn.set_enabled(False)

        tk.Label(
            card,
            textvariable=self.update_status_var,
            bg=UI["surface"],
            fg=UI["primary"],
            font=FONT_SMALL,
            anchor="w",
            wraplength=900,
            justify="left",
        ).pack(fill="x", pady=(8, 4))

        tk.Label(
            card,
            text="更新内容",
            bg=UI["surface"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x", pady=(8, 0))
        notes_fr = tk.Frame(
            card,
            bg=UI["surface_2"],
            highlightbackground=UI["border"],
            highlightthickness=1,
        )
        notes_fr.pack(fill="both", expand=True, pady=(4, 0))
        self.update_notes_text = tk.Text(
            notes_fr,
            height=12,
            bg=UI["surface_2"],
            fg=UI["text"],
            font=FONT_SMALL,
            relief="flat",
            wrap="word",
            state="disabled",
        )
        self.update_notes_text.pack(fill="both", expand=True, padx=8, pady=8)

        # 起動直後に裏で確認（失敗しても黙ってよい）
        self.root.after(800, lambda: self.check_for_updates(silent=True))

    def check_for_updates(self, silent: bool = False):
        self.update_local_ver_var.set(f"このPCの版: {read_version()}")
        self.update_status_var.set("確認中…")
        self.update_apply_btn.set_enabled(False)
        self._pending_release = None

        def worker():
            err = None
            info = None
            try:
                from self_update import fetch_latest_release, version_is_newer

                # 利用者は配布元を意識しない。公開のダウンロード先を参照（トークン不要）
                info = fetch_latest_release()
            except Exception as e:
                err = e

            def done():
                if err:
                    msg = (
                        "いま更新情報を確認できませんでした。\n"
                        "ネット接続を確認し、しばらくしてからもう一度お試しください。"
                    )
                    self.update_remote_ver_var.set("ダウンロード可能な版: （確認できません）")
                    self.update_status_var.set(msg if not silent else "")
                    if not silent:
                        messagebox.showwarning("更新", msg)
                    return
                assert info is not None
                local = read_version()
                self.update_remote_ver_var.set(
                    f"ダウンロード可能な版: {info.version}"
                )
                self._set_update_notes(info.body or "（特に記載なし）")
                if version_is_newer(info.version, local):
                    self._pending_release = info
                    self.update_apply_btn.set_enabled(True)
                    self.update_status_var.set(
                        "新しい版があります。「ダウンロードして更新」を押してください。"
                    )
                    if not silent:
                        if messagebox.askyesno(
                            "更新版があります",
                            f"新しい版 {info.version} があります（いまの版 {local}）。\n\n"
                            "ダウンロードして更新しますか？\n"
                            "（あとで「更新」タブからも実行できます）",
                        ):
                            self.apply_pending_update()
                else:
                    self.update_status_var.set("最新の版を使っています。" if not silent else "")
                    if not silent:
                        messagebox.showinfo("更新", f"最新の版です（{local}）。")

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _set_update_notes(self, text: str):
        self.update_notes_text.configure(state="normal")
        self.update_notes_text.delete("1.0", "end")
        self.update_notes_text.insert("1.0", text)
        self.update_notes_text.configure(state="disabled")

    def apply_pending_update(self):
        rel = self._pending_release
        if rel is None:
            messagebox.showinfo("更新", "先に「更新を確認」を押してください。")
            return
        if detect_install_root() is None:
            if not messagebox.askyesno(
                "セットアップが必要",
                "このPCにはまだインストール配置がありません。\n\n"
                "配布されたセットアップを実行してから更新するのが安全です。\n"
                "このままこのPC用フォルダへ入れて更新を試みますか？",
            ):
                return
            ensure_install_dirs(local_app_install_root())

        self.update_status_var.set("ダウンロード中…")
        self.update_apply_btn.set_enabled(False)

        def worker():
            err = None
            msg = ""
            try:
                from self_update import apply_update_and_restart

                msg = apply_update_and_restart(rel)
            except Exception as e:
                err = e

            def done():
                if err:
                    self.update_status_var.set(
                        "ダウンロードまたは更新の準備に失敗しました。ネット接続を確認してください。"
                    )
                    self.update_apply_btn.set_enabled(True)
                    messagebox.showerror(
                        "更新",
                        "更新できませんでした。\n"
                        "ネット接続を確認し、もう一度お試しください。",
                    )
                    return
                self.update_status_var.set(msg)
                messagebox.showinfo(
                    "更新",
                    "ダウンロードが終わりました。\n\n"
                    "OK を押すとアプリを一度終了し、新しい版に切り替わります。\n"
                    "いつも使っているショートカットから起動できます。",
                )
                self.root.destroy()

            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _build_help_tab(self):
        parent = self.help_tab
        card = self._card_shell(parent, fill="both", expand=True, padx=8, pady=8)

        tk.Label(
            card,
            text="すぐサーチの使い方",
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        usage = (
            "【このアプリでできること】\n"
            "・型番・図番の検索で、- と _、半角スペースと全角スペースの違いを気にせず検索できます\n"
            "・例: 「694 1056」→ REV694-1056 など（スペースは間を飛ばして広く検索）\n"
            "・例: 「空　スタッカー」→ 空トレイアンスタッカー などにもヒット\n"
            "・例: 「AB010 54」→ AB010-85-054 などにもヒット\n"
            "・例: 「REV757_0200」→ REV757-0200（- と _ は区切り1文字として同一視）\n"
            "・検索欄は入力するだけで候補が更新されます（検索ボタン不要）\n"
            "・結果の複数選択: Ctrl+クリックで追加、Shift+クリックで範囲\n"
            "・右クリック → 「ファイルコピー」「パスのコピー」（複数選択対応）\n"
            "  （ファイルコピー後、エクスプローラーで Ctrl+V で貼り付け）\n"
            "・下の「ファイルコピー」「パスのコピー」ボタンでも同じ操作ができます\n"
            "\n"
            "【準備（初回のみ）】\n"
            "1. Everything をインストールして起動する（下のリンクから入手）\n"
            "2. Everything → ツール → オプション → HTTP サーバー を有効にする\n"
            "   （ポートは通常 8888）\n"
            "3. ブラウザで http://127.0.0.1:8888/ が開けば OK\n"
            "\n"
            "【検索の手順】\n"
            "1. 「検索」タブで型番・図番を入力する\n"
            "2. 対象フォルダは空欄のままで全体検索、必要ならパスを指定\n"
            "   （\"\\\\サーバー\\共有\\フォルダ\" のようにダブルクォート付き推奨）\n"
            "3. 検索ボタンまたは Enter で実行\n"
            "4. 結果を選んで「選択ファイルを開く」またはダブルクリック\n"
            "\n"
            "【便利な操作】\n"
            "・列ヘッダをクリック → 並び替え（種類 / 名前 / 場所 / サイズ / 日時）\n"
            "・下の各チップをクリック → 種類・重複・条件の表示切替（終了後も保持）\n"
            "  （暗い＝除外 / 重複は最新1件のみ。詳細は「フィルタ設定」タブ）\n"
            "・「フィルタ」の文字をクリック → すべて ON ⇔ すべて OFF を切替\n"
            "・対象フォルダ入力欄 → 履歴から過去のフォルダを選択\n"
            "・接続設定タブ → Everything が別 PC のときのホスト/ポート\n"
            "・フィルタ設定タブ → 拡張子・色・条件・チップ表示の編集\n"
        )
        tk.Label(
            card,
            text=usage,
            bg=UI["surface"],
            fg=UI["text"],
            font=FONT_SMALL,
            anchor="nw",
            justify="left",
        ).pack(fill="both", expand=True, pady=(0, 12))

        link_box = tk.Frame(card, bg=UI["surface_2"], highlightbackground=UI["border"], highlightthickness=1)
        link_box.pack(fill="x", pady=(4, 0))
        inner = tk.Frame(link_box, bg=UI["surface_2"])
        inner.pack(fill="x", padx=12, pady=12)

        tk.Label(
            inner,
            text="Everything のダウンロード",
            bg=UI["surface_2"],
            fg=UI["text"],
            font=FONT_UI_BOLD,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            text="公式サイト（voidtools）から最新版を入手できます。",
            bg=UI["surface_2"],
            fg=UI["text_muted"],
            font=FONT_SMALL,
            anchor="w",
        ).pack(fill="x", pady=(4, 8))

        link_row = tk.Frame(inner, bg=UI["surface_2"])
        link_row.pack(fill="x")
        link_label = tk.Label(
            link_row,
            text=EVERYTHING_DOWNLOAD_URL,
            bg=UI["surface_2"],
            fg=UI["primary"],
            font=FONT_UI,
            cursor="hand2",
            anchor="w",
        )
        link_label.pack(side="left", fill="x", expand=True)
        link_label.bind("<Button-1>", lambda _e: self.open_everything_download())
        ModernButton(
            link_row,
            text="サイトを開く",
            command=self.open_everything_download,
            variant="primary",
        ).pack(side="right")

    def open_everything_download(self):
        try:
            webbrowser.open(EVERYTHING_DOWNLOAD_URL)
        except Exception as e:
            messagebox.showerror(
                "開けませんでした",
                f"ブラウザを開けませんでした。\n{EVERYTHING_DOWNLOAD_URL}\n\n{e}",
            )

    # ----- folder history -----
    def get_folder_history(self) -> list[str]:
        return normalize_folder_history(self.settings.get("folder_history", []))

    def set_folder_history(self, history: list[str], persist: bool = True):
        self.settings["folder_history"] = normalize_folder_history(history)
        if persist:
            try:
                save_settings(self.settings)
            except OSError:
                pass

    def add_folder_to_history(self, folder: str, persist: bool = True):
        """使ったフォルダを履歴の先頭へ（空は追加しない）。"""
        q = quote_folder_path(folder)
        if not q:
            return
        history = [q] + [
            h
            for h in self.get_folder_history()
            if strip_folder_quotes(h).lower() != strip_folder_quotes(q).lower()
        ]
        self.set_folder_history(history, persist=persist)
        if self.folder_history_open:
            self._rebuild_history_list()

    def _on_folder_entry_focus(self, _event=None):
        # フォーカス時に履歴を開く
        self.root.after(50, self.show_folder_history)

    def _on_folder_entry_click(self, _event=None):
        self.root.after(10, self.show_folder_history)

    def _on_folder_entry_down(self, _event=None):
        self.show_folder_history()
        return "break"

    def show_folder_history(self):
        if self.folder_history_open:
            self._rebuild_history_list()
            return
        self.folder_history_open = True
        self.history_panel.pack(fill="x", pady=(8, 0))
        self._rebuild_history_list()
        self._update_folder_clear_btn_look()

    def hide_folder_history(self):
        if not self.folder_history_open:
            return
        self.folder_history_open = False
        self.history_panel.pack_forget()
        self._update_folder_clear_btn_look()

    def _update_folder_clear_btn_look(self):
        # 見た目は同じ ×。ツールチップ代わりに title 相当の状態は info で補足しない
        pass

    def _rebuild_history_list(self):
        for child in self.history_list_frame.winfo_children():
            child.destroy()

        history = self.get_folder_history()
        if not history:
            tk.Label(
                self.history_list_frame,
                text="履歴はまだありません（検索やフォルダ選択で追加されます）",
                bg=UI["surface"],
                fg=UI["text_muted"],
                font=FONT_SMALL,
                anchor="w",
            ).pack(fill="x", padx=6, pady=6)
            return

        # スクロール可能な領域
        canvas = tk.Canvas(
            self.history_list_frame,
            bg=UI["surface"],
            highlightthickness=0,
            height=min(220, 36 * min(len(history), 6) + 8),
        )
        scrollbar = ttk.Scrollbar(
            self.history_list_frame,
            orient="vertical",
            command=canvas.yview,
            style="Modern.Vertical.TScrollbar",
        )
        inner = tk.Frame(canvas, bg=UI["surface"])
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        if len(history) > 6:
            scrollbar.pack(side="right", fill="y")

        def _on_canvas_configure(event, wid=window_id):
            canvas.itemconfigure(wid, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        for path in history:
            row = tk.Frame(inner, bg=UI["surface"])
            row.pack(fill="x", pady=1)

            path_btn = tk.Label(
                row,
                text=path,
                bg=UI["surface"],
                fg=UI["text"],
                font=FONT_SMALL,
                anchor="w",
                cursor="hand2",
                padx=8,
                pady=6,
            )
            path_btn.pack(side="left", fill="x", expand=True)

            del_btn = tk.Label(
                row,
                text=" × ",
                bg=UI["surface"],
                fg="#B91C1C",
                font=FONT_UI_BOLD,
                cursor="hand2",
                padx=6,
                pady=4,
            )
            del_btn.pack(side="right")

            def _hover_in(e, w=path_btn, r=row, d=del_btn):
                w.configure(bg=UI["accent_line"])
                r.configure(bg=UI["accent_line"])
                d.configure(bg=UI["accent_line"])

            def _hover_out(e, w=path_btn, r=row, d=del_btn):
                w.configure(bg=UI["surface"])
                r.configure(bg=UI["surface"])
                d.configure(bg=UI["surface"])

            def _select(e, p=path):
                self.select_folder_history(p)

            def _delete(e, p=path):
                self.delete_folder_history(p)
                return "break"

            for w in (path_btn, row):
                w.bind("<Enter>", _hover_in)
                w.bind("<Leave>", _hover_out)
                w.bind("<Button-1>", _select)
            del_btn.bind("<Enter>", _hover_in)
            del_btn.bind("<Leave>", _hover_out)
            del_btn.bind("<Button-1>", _delete)

    def select_folder_history(self, path: str):
        self.folder_var.set(quote_folder_path(path))
        self.add_folder_to_history(path)
        self.hide_folder_history()
        self.folder_entry.focus_set()
        # 検索欄に文字を打ったときと同じようにその場で検索し直す
        self._run_live_search()

    def delete_folder_history(self, path: str):
        key = strip_folder_quotes(path).lower()
        history = [
            h
            for h in self.get_folder_history()
            if strip_folder_quotes(h).lower() != key
        ]
        self.set_folder_history(history)
        # 削除したパスが入力中と同じならクリアはしない（ユーザーが意図した入力を守る）
        self._rebuild_history_list()

    def on_folder_clear_or_close(self):
        """
        履歴リスト表示中 → リストを閉じる
        リスト非表示 → 対象フォルダを空にして全体検索用にする
        """
        if self.folder_history_open:
            self.hide_folder_history()
            return
        self.folder_var.set("")
        self.settings["search_folder"] = ""
        try:
            save_settings(self.settings)
        except OSError:
            pass
        self.info_var.set("対象フォルダをクリアしました（空欄＝全体検索）")
        # 全体検索としてその場で検索し直す
        self._run_live_search()

    # ----- folder browse -----
    def browse_folder(self):
        self.hide_folder_history()
        initial = strip_folder_quotes(self.folder_var.get())
        # filedialog は UNC を初期ディレクトリにできない場合がある
        kwargs = {"title": "検索対象フォルダを選択"}
        if initial and Path(initial).exists():
            kwargs["initialdir"] = initial
        chosen = filedialog.askdirectory(**kwargs)
        if chosen:
            # Windows パス区切りをそのまま / から \ に
            chosen = os.path.normpath(chosen)
            quoted = quote_folder_path(chosen)
            self.folder_var.set(quoted)
            self.add_folder_to_history(quoted)
            # 選び直したらその場で検索し直す
            self._run_live_search()

    # ----- connection history -----
    def get_connection_history(self) -> list[dict]:
        return normalize_connection_history(self.settings.get("connection_history", []))

    def set_connection_history(self, history: list, persist: bool = True):
        self.settings["connection_history"] = normalize_connection_history(history)
        if persist:
            try:
                save_settings(self.settings)
            except OSError:
                pass

    def add_connection_to_history(self, host: str, port: int, persist: bool = True):
        """使った接続先を履歴の先頭へ。"""
        host = (host or "").strip() or "127.0.0.1"
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 8888
        if not (1 <= port <= 65535):
            port = 8888
        entry = {"host": host, "port": port}
        key = f"{host.lower()}:{port}"
        history = [entry] + [
            h
            for h in self.get_connection_history()
            if f"{str(h.get('host', '')).lower()}:{h.get('port')}" != key
        ]
        self.set_connection_history(history, persist=persist)
        if self.connection_history_open:
            self._rebuild_connection_history_list()

    def _on_connection_entry_focus(self, _event=None):
        self.root.after(50, self.show_connection_history)

    def _on_connection_entry_click(self, _event=None):
        self.root.after(10, self.show_connection_history)

    def _on_connection_entry_down(self, _event=None):
        self.show_connection_history()
        return "break"

    def show_connection_history(self):
        if self.connection_history_open:
            self._rebuild_connection_history_list()
            return
        self.connection_history_open = True
        # ボタン行の直前（フォーム直後）に差し込む
        self.connection_history_panel.pack(
            fill="x", pady=(0, 8), before=self.settings_btn_row
        )
        self._rebuild_connection_history_list()

    def hide_connection_history(self):
        if not self.connection_history_open:
            return
        self.connection_history_open = False
        self.connection_history_panel.pack_forget()

    def _rebuild_connection_history_list(self):
        for child in self.connection_history_list_frame.winfo_children():
            child.destroy()

        history = self.get_connection_history()
        if not history:
            tk.Label(
                self.connection_history_list_frame,
                text="履歴はまだありません（保存や接続テストで追加されます）",
                bg=UI["surface"],
                fg=UI["text_muted"],
                font=FONT_SMALL,
                anchor="w",
            ).pack(fill="x", padx=6, pady=6)
            return

        canvas = tk.Canvas(
            self.connection_history_list_frame,
            bg=UI["surface"],
            highlightthickness=0,
            height=min(180, 36 * min(len(history), 5) + 8),
        )
        scrollbar = ttk.Scrollbar(
            self.connection_history_list_frame,
            orient="vertical",
            command=canvas.yview,
            style="Modern.Vertical.TScrollbar",
        )
        inner = tk.Frame(canvas, bg=UI["surface"])
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        if len(history) > 5:
            scrollbar.pack(side="right", fill="y")

        def _on_canvas_configure(event, wid=window_id):
            canvas.itemconfigure(wid, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        for item in history:
            label = format_connection_history_label(item)
            row = tk.Frame(inner, bg=UI["surface"])
            row.pack(fill="x", pady=1)

            path_btn = tk.Label(
                row,
                text=label,
                bg=UI["surface"],
                fg=UI["text"],
                font=FONT_SMALL,
                anchor="w",
                cursor="hand2",
                padx=8,
                pady=6,
            )
            path_btn.pack(side="left", fill="x", expand=True)

            del_btn = tk.Label(
                row,
                text=" × ",
                bg=UI["surface"],
                fg="#B91C1C",
                font=FONT_UI_BOLD,
                cursor="hand2",
                padx=6,
                pady=4,
            )
            del_btn.pack(side="right")

            def _hover_in(e, w=path_btn, r=row, d=del_btn):
                w.configure(bg=UI["accent_line"])
                r.configure(bg=UI["accent_line"])
                d.configure(bg=UI["accent_line"])

            def _hover_out(e, w=path_btn, r=row, d=del_btn):
                w.configure(bg=UI["surface"])
                r.configure(bg=UI["surface"])
                d.configure(bg=UI["surface"])

            def _select(e, it=item):
                self.select_connection_history(it)

            def _delete(e, it=item):
                self.delete_connection_history(it)
                return "break"

            for w in (path_btn, row):
                w.bind("<Enter>", _hover_in)
                w.bind("<Leave>", _hover_out)
                w.bind("<Button-1>", _select)
            del_btn.bind("<Enter>", _hover_in)
            del_btn.bind("<Leave>", _hover_out)
            del_btn.bind("<Button-1>", _delete)

    def select_connection_history(self, item: dict):
        host = str(item.get("host") or "127.0.0.1")
        try:
            port = int(item.get("port", 8888))
        except (TypeError, ValueError):
            port = 8888
        self.host_var.set(host)
        self.port_var.set(str(port))
        self.add_connection_to_history(host, port)
        self.hide_connection_history()
        if self.host_entry is not None:
            self.host_entry.focus_set()
        self.settings_status_var.set(f"履歴から選択: {host}:{port}")

    def delete_connection_history(self, item: dict):
        key = f"{str(item.get('host', '')).lower()}:{item.get('port')}"
        history = [
            h
            for h in self.get_connection_history()
            if f"{str(h.get('host', '')).lower()}:{h.get('port')}" != key
        ]
        self.set_connection_history(history)
        self._rebuild_connection_history_list()

    # ----- settings actions -----
    def save_connection_settings(self):
        host = self.host_var.get().strip() or "127.0.0.1"
        port_text = self.port_var.get().strip()
        try:
            port = int(port_text)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("入力エラー", "ポートは 1〜65535 の数値で指定してください。")
            return

        self.settings["host"] = host
        self.settings["port"] = port
        self.settings["user"] = self.user_var.get()
        self.settings["password"] = self.password_var.get()
        self.settings["search_folder"] = quote_folder_path(self.folder_var.get())
        # 現在のフォルダも履歴へ
        if self.settings["search_folder"]:
            self.add_folder_to_history(self.settings["search_folder"], persist=False)
        self.add_connection_to_history(host, port, persist=False)
        self.hide_connection_history()

        try:
            save_settings(self.settings)
        except OSError as e:
            messagebox.showerror("保存失敗", f"設定ファイルを保存できませんでした。\n{e}")
            return

        self.settings_status_var.set(f"保存しました: {host}:{port}")
        messagebox.showinfo("保存完了", f"接続設定を保存しました。\n{host}:{port}")

    @staticmethod
    def _detect_own_ipv4() -> tuple[str, list[str]]:
        """
        このPCの IPv4 を推定。
        戻り値: (優先して使うIP, 見つかった候補一覧)
        ループバック以外の LAN IP を優先。無ければ 127.0.0.1。
        """
        import socket

        candidates: list[str] = []
        # 外部へ繋がない UDP で、出ていく NIC のアドレスを知る
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    candidates.append(ip)
            finally:
                s.close()
        except OSError:
            pass
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip and ip not in candidates and not ip.startswith("127."):
                    candidates.append(ip)
        except OSError:
            pass
        if not candidates:
            return "127.0.0.1", ["127.0.0.1"]
        return candidates[0], candidates

    def connect_to_self_and_test(self):
        """ホストにこのPCのIPを入れ、そのまま接続テストする。"""
        primary, all_ips = self._detect_own_ipv4()
        self.host_var.set(primary)
        if not (self.port_var.get() or "").strip():
            self.port_var.set("8888")
        self.settings_status_var.set(
            f"自身のIPを設定: {primary}"
            + (f"（他候補: {', '.join(all_ips[1:])}）" if len(all_ips) > 1 else "")
            + " — 接続テスト中…"
        )
        self.root.update_idletasks()
        self.test_connection(extra_note=f"このPCのIP {primary} でテストしました。")

    def test_connection(self, extra_note: str = ""):
        host = self.host_var.get().strip() or "127.0.0.1"
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("入力エラー", "ポートは数値で指定してください。")
            return
        user = self.user_var.get()
        password = self.password_var.get()
        try:
            data = search_everything(
                query_regex="^$",
                search_folder="",
                host=host,
                port=port,
                user=user,
                password=password,
            )
            # 空に近い regex でも応答があれば接続OK
            total = data.get("totalResults", 0)
            self.add_connection_to_history(host, port)
            self.settings_status_var.set(
                f"接続成功: {host}:{port}（応答あり / total={total}）"
            )
            msg = f"Everything に接続できました。\n{host}:{port}"
            if extra_note:
                msg += f"\n\n{extra_note}"
            messagebox.showinfo("接続成功", msg)
        except Exception as e:
            self.settings_status_var.set(f"接続失敗: {host}:{port}")
            msg = f"接続できませんでした。\n{host}:{port}\n\n{e}"
            if extra_note:
                msg += f"\n\n{extra_note}"
            msg += (
                "\n\nEverything の HTTP サーバーが有効か、"
                "ポート番号が合っているか確認してください。"
            )
            messagebox.showerror("接続失敗", msg)

    # ----- search / sort -----
    def _cancel_live_debounce(self):
        if self._live_after_id is not None:
            try:
                self.root.after_cancel(self._live_after_id)
            except (tk.TclError, ValueError):
                pass
            self._live_after_id = None

    def _on_keyword_key_release(self, event=None):
        """1文字ごとのライブ検索（修飾キーのみは無視）。"""
        if event is not None:
            # 確定操作は on_search 側
            if event.keysym in (
                "Return",
                "KP_Enter",
                "Tab",
                "Escape",
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
                "Alt_L",
                "Alt_R",
            ):
                return
        self._schedule_live_search()

    def _on_keyword_paste(self, _event=None):
        # 貼り付け後に文字列が反映されてから検索
        self.root.after(30, self._schedule_live_search)

    def _schedule_live_search(self):
        """連打時はまとめて1回だけ検索（デバウンス）。"""
        self._cancel_live_debounce()
        self._live_after_id = self.root.after(
            LIVE_SEARCH_DEBOUNCE_MS, self._run_live_search
        )

    def _run_live_search(self):
        """検索ボタンなしで候補を更新する。"""
        self._live_after_id = None
        keyword = self.keyword_var.get().strip()
        if not keyword:
            # 空欄 → 結果クリア（進行中の検索も無効化）
            self._search_gen += 1
            self._search_busy = False
            self._last_regex = ""
            self.all_results = []
            self.display_results = []
            self.total_results = 0
            self.filtered_count = 0
            self._clear_tree()
            self.regex_var.set("変換後正規表現:  —")
            self.info_var.set("検索文字列を入力すると候補が表示されます")
            return

        folder_now = quote_folder_path(self.folder_var.get())
        # フォルダ欄は正規化だけ（履歴はライブでは増やさない）
        if self.folder_var.get().strip() != folder_now:
            self.folder_var.set(folder_now)

        regex = to_flexible_regex(keyword)
        item_type = self._desired_item_type()
        # 同じ条件なら打ち直さない
        if (
            regex == self._last_regex
            and folder_now == self._last_folder
            and item_type == self._results_item_type
            and self.all_results
            and not self._search_busy
        ):
            return

        self.regex_var.set(f"変換後正規表現:  {regex}")
        self._last_regex = regex
        self._last_folder = folder_now
        self._refetch_done_for_search = False

        self._start_search_job(
            regex=regex,
            folder=folder_now,
            count=MAX_RESULTS,
            item_type=item_type,
            allow_refetch_after=True,
            clear_list=False,  # 入力中は前の一覧を残し、完了後に差し替え
            status_text="検索中…",
        )

    def clear_search_keyword(self):
        """検索文字列をクリアする。"""
        self._cancel_live_debounce()
        self.keyword_var.set("")
        self.entry.focus_set()
        self._run_live_search()  # 結果もクリア

    def on_search(self):
        """Enter / 検索ボタン: 即時検索（履歴も更新）。"""
        self._cancel_live_debounce()
        keyword = self.keyword_var.get().strip()
        if not keyword:
            self._run_live_search()
            return

        # 表示フォルダは常に引用符付きに正規化（空は空のまま＝全体検索）
        folder_now = quote_folder_path(self.folder_var.get())
        self.folder_var.set(folder_now)
        self.hide_folder_history()

        regex = to_flexible_regex(keyword)
        self.regex_var.set(f"変換後正規表現:  {regex}")

        self._last_regex = regex
        self._last_folder = folder_now
        self._refetch_done_for_search = False

        # 直近のフォルダを設定・履歴に残す（明示検索時のみ）
        self.settings["search_folder"] = folder_now
        if folder_now:
            self.add_folder_to_history(folder_now)
        else:
            try:
                save_settings(self.settings)
            except OSError:
                pass

        self._start_search_job(
            regex=regex,
            folder=folder_now,
            count=MAX_RESULTS,
            item_type=self._desired_item_type(),
            allow_refetch_after=True,
            clear_list=True,
            status_text="しばらくお待ちください…",
        )

    def toggle_sort(self, column: str):
        if self.sort_column == column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = self.SORT_DEFAULT_ASC.get(column, True)
        self._update_heading_labels()
        if self.all_results:
            self.apply_sort_and_display()

    def _update_heading_labels(self):
        labels = {
            "type": "種類",
            "name": "名前",
            "path": "場所",
            "size": "サイズ",
            "date": "更新日時",
        }
        arrow = " ↑" if self.sort_ascending else " ↓"
        active = {
            "type": self.sort_column == "type",
            "name": self.sort_column == "name",
            "path": self.sort_column == "path",
            "size": self.sort_column == "size",
            "date": self.sort_column == "date",
        }
        for col, base in labels.items():
            self.tree.heading(col, text=base + (arrow if active[col] else ""))

    def configure_tree_tags(self):
        """種類タグの行色をフィルタ定義から設定。"""
        if not hasattr(self, "tree"):
            return
        for f in self.filter_defs:
            if f.get("kind") in ("folder", "extension", "other"):
                try:
                    self.tree.tag_configure(f["id"], background=f.get("color", "#FFFFFF"))
                except tk.TclError:
                    pass

    def _chip_is_on(self, filt: dict) -> bool:
        """
        チップが明るい側か。
        バー非表示のフィルタは常に ON（除外しない）として扱う。
        """
        if not filt.get("show_chip", True):
            return True
        return bool(self.chip_state.get(filt["id"], filt.get("default_on", True)))

    def rebuild_filter_chips(self):
        """検索タブ下のフィルタチップを定義どおり再生成。"""
        if self.filter_chip_host is None:
            return
        for w in self.filter_chip_host.winfo_children():
            w.destroy()
        self.filter_chips = {}
        for f in sorted(self.filter_defs, key=lambda x: x.get("order", 0)):
            if not f.get("show_chip", True):
                continue
            chip = TypeFilterChip(
                self.filter_chip_host,
                text=f.get("label", f["id"]),
                tag=f["id"],
                active_bg=f.get("color", "#E2E8F0"),
                command=self.on_filter_chip_toggle,
            )
            # セッション状態を反映
            chip.set_enabled(self._chip_is_on(f))
            chip.pack(side="left", padx=(0, 6))
            self.filter_chips[f["id"]] = chip
        self.configure_tree_tags()

    def on_filter_chip_toggle(self, tag: str, enabled: bool):
        self.chip_state[tag] = enabled
        self._persist_chip_state()
        self._on_filter_mode_changed()

    def _visible_filter_ids(self) -> list[str]:
        return [
            f["id"]
            for f in self.filter_defs
            if f.get("show_chip", True)
        ]

    def _all_visible_filters_on(self) -> bool:
        ids = self._visible_filter_ids()
        if not ids:
            return True
        return all(self.chip_state.get(fid, True) for fid in ids)

    def toggle_all_filters(self):
        """「フィルタ」ラベル押下: すべて ON なら全 OFF、それ以外は全 ON。"""
        turn_on = not self._all_visible_filters_on()
        for fid in self._visible_filter_ids():
            self.chip_state[fid] = turn_on
        for fid, chip in self.filter_chips.items():
            chip.set_enabled(turn_on)
            self.chip_state[fid] = turn_on
        self._persist_chip_state()
        if turn_on:
            self.info_var.set("フィルタをすべて ON（表示側）にしました")
        else:
            self.info_var.set("フィルタをすべて OFF（非表示側）にしました")
        self._on_filter_mode_changed()

    def force_all_filters_on(self):
        """互換: 表示中チップをすべて ON にする。"""
        for fid in self._visible_filter_ids():
            self.chip_state[fid] = True
        for fid, chip in self.filter_chips.items():
            chip.set_enabled(True)
            self.chip_state[fid] = True
        self._persist_chip_state()
        self.info_var.set("フィルタをすべて ON（表示側）にしました")
        self._on_filter_mode_changed()

    def _is_folder_only_mode(self) -> bool:
        """
        種類フィルタのうち「フォルダ」だけが ON で、
        拡張子・その他がすべて OFF のとき True。
        """
        type_filts = [
            f
            for f in self.filter_defs
            if f.get("kind") in ("folder", "extension", "other")
        ]
        folder_filts = [f for f in type_filts if f.get("kind") == "folder"]
        non_folder = [f for f in type_filts if f.get("kind") != "folder"]
        if not folder_filts:
            return False
        if not any(self._chip_is_on(f) for f in folder_filts):
            return False
        if any(self._chip_is_on(f) for f in non_folder):
            return False
        return True

    def _desired_item_type(self) -> str | None:
        """Everything に渡す item_type（folder のみモード時は folder:）。"""
        if self._is_folder_only_mode():
            return "folder"
        return None

    def _on_filter_mode_changed(self):
        """
        チップ変更時: フォルダのみ ⇔ 通常 の切替なら再検索、
        同じモードならクライアント側フィルタのみ。
        """
        if not self._last_regex:
            self._update_info_label()
            return

        desired = self._desired_item_type()
        if desired != self._results_item_type:
            # モードが変わった → バックグラウンドで取り直し（UI は止めない）
            self._refetch_done_for_search = False
            self._start_search_job(
                regex=self._last_regex,
                folder=self._last_folder,
                count=MAX_RESULTS,
                item_type=desired,
                allow_refetch_after=True,
                clear_list=False,
                status_text="しばらくお待ちください…",
            )
            return

        if self.all_results:
            self.apply_sort_and_display(allow_refetch=True)
        else:
            self._update_info_label()

    def _start_search_job(
        self,
        regex: str,
        folder: str,
        count: int,
        item_type: str | None,
        allow_refetch_after: bool,
        clear_list: bool,
        status_text: str,
    ):
        """
        バックグラウンドで Everything 検索。UI スレッドは止めない。
        古い応答は世代番号で捨てる。
        """
        self._search_gen += 1
        gen = self._search_gen
        self._search_busy = True
        self.info_var.set(status_text)
        if clear_list:
            self._clear_tree()
            self.all_results = []
            self.display_results = []
            self.total_results = 0
        self.root.update_idletasks()

        conn = self._conn()

        def worker():
            err = None
            data = None
            try:
                data = search_everything(
                    regex,
                    folder,
                    host=conn["host"],
                    port=conn["port"],
                    user=conn["user"],
                    password=conn["password"],
                    count=count,
                    item_type=item_type,
                )
            except Exception as e:
                err = e

            def on_done():
                if gen != self._search_gen:
                    return  # より新しい検索が走っている
                self._search_busy = False
                if err is not None:
                    self.info_var.set("検索に失敗しました（条件を変えて再試行できます）")
                    # 誤操作防止のためダイアログは出さず、操作は継続可能
                    return
                try:
                    self.all_results = parse_results(data, self.filter_defs)
                    self.total_results = int(
                        data.get("totalResults", len(self.all_results))
                    )
                    self._results_item_type = item_type
                    self.apply_sort_and_display(allow_refetch=allow_refetch_after)
                except Exception as e:
                    self.info_var.set(f"結果の処理に失敗しました: {e}")

            try:
                self.root.after(0, on_done)
            except tk.TclError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _persist_chip_state(self):
        """チップ明暗を settings.json に保存。"""
        self.settings["chip_state"] = dict(self.chip_state)
        self.settings["filters"] = self.filter_defs
        try:
            save_settings(self.settings)
        except OSError:
            pass

    def on_close(self):
        """ウィンドウ終了時に状態を保存して閉じる。"""
        self._persist_chip_state()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _apply_filters(self, rows: list) -> list:
        """
        適用順:
          1. 種類（folder / extension / other）
          2. path_keyword（order 順）
          3. builtin_dedupe
        """
        stats: dict[str, int] = {}
        current = list(rows)

        # 1) 種類
        type_ids = {
            f["id"]
            for f in self.filter_defs
            if f.get("kind") in ("folder", "extension", "other")
        }
        after_type = []
        type_hidden = 0
        for r in current:
            tag = r.get("tag")
            # 該当フィルタ定義
            filt = next((f for f in self.filter_defs if f["id"] == tag), None)
            if filt is None:
                # 不明タグは other 扱い
                other = next(
                    (f for f in self.filter_defs if f.get("kind") == "other"), None
                )
                if other and not self._chip_is_on(other):
                    type_hidden += 1
                    continue
                after_type.append(r)
                continue
            if self._chip_is_on(filt):
                after_type.append(r)
            else:
                type_hidden += 1
        if type_hidden:
            stats["種類"] = type_hidden
        current = after_type

        # 2) path_keyword
        for filt in sorted(
            [f for f in self.filter_defs if f.get("kind") == "path_keyword"],
            key=lambda x: x.get("order", 0),
        ):
            if self._chip_is_on(filt):
                continue  # 明るい＝該当も表示 → 除外しない
            kept = []
            removed = 0
            for r in current:
                if path_keyword_matches(r, filt):
                    removed += 1
                else:
                    kept.append(r)
            if removed:
                stats[filt.get("label") or filt["id"]] = removed
            current = kept

        # 3) 重複
        dedupe = next(
            (f for f in self.filter_defs if f.get("kind") == "builtin_dedupe"), None
        )
        if dedupe and not self._chip_is_on(dedupe):
            before = len(current)
            current = dedupe_files_keep_newest(current)
            removed = before - len(current)
            if removed:
                stats[dedupe.get("label") or "重複"] = removed

        self.filter_stats = stats
        return current

    def _needs_full_refetch(self, filtered_count: int) -> bool:
        """
        フィルタ後が少なく、かつ Everything 側に未取得分があるとき再取得する。
        確認ダイアログは出さない。
        """
        if self._refetch_done_for_search:
            return False
        if not self._last_regex:
            return False
        if filtered_count > REFETCH_IF_FILTERED_LE:
            return False
        if self.total_results <= len(self.all_results):
            return False
        return True

    def _schedule_refetch_all_async(self):
        """
        フィルタ後が少ないときの広め再取得を非同期で行う。
        UI は止めず、メッセージのみ出す（内部事情は出さない）。
        """
        target = min(int(self.total_results), MAX_RESULTS_HARD_CAP)
        if target <= len(self.all_results):
            self._refetch_done_for_search = True
            return

        self._refetch_done_for_search = True  # 二重起動防止（失敗時も再試行しない）
        item_type = self._desired_item_type()
        self._start_search_job(
            regex=self._last_regex,
            folder=self._last_folder,
            count=target,
            item_type=item_type,
            allow_refetch_after=False,
            clear_list=False,
            status_text="しばらくお待ちください…",
        )

    def apply_sort_and_display(self, allow_refetch: bool = True):
        key = self.SORT_KEYS.get(self.sort_column, "fullpath")
        reverse = not self.sort_ascending

        filtered = self._apply_filters(self.all_results)

        # フィルタ後が少なく未取得がある → 確認なしで非同期再取得
        if allow_refetch and self._needs_full_refetch(len(filtered)):
            self._schedule_refetch_all_async()
            # いったん取得済みだけで表示し、完了後に一覧が差し替わる
            # （操作は止めない）

        sorted_results = sorted(
            filtered,
            key=lambda r: (r.get(key, ""), r.get("fullpath", "")),
            reverse=reverse,
        )

        # フィルタ後が DISPLAY_LIMIT 以下なら全件表示
        self.filtered_count = len(sorted_results)
        if self.filtered_count <= DISPLAY_LIMIT:
            self.display_results = sorted_results
        else:
            self.display_results = sorted_results[:DISPLAY_LIMIT]
        self._populate_tree(self.display_results)
        note = ""
        if self._search_busy:
            note = ""
        self._update_info_label(extra_note=note)
        if allow_refetch and self._search_busy:
            # 再取得中は件数バーを待ち表示に（内部理由は書かない）
            self.info_var.set("しばらくお待ちください…")

    def _clear_tree(self):
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

    def _populate_tree(self, results):
        self._clear_tree()
        for row in results:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row["type_text"],
                    row["name"],
                    row["path"],
                    row["size_text"],
                    row["date_text"],
                ),
                tags=(row["tag"],),
            )

    def _update_info_label(self, extra_note: str = ""):
        shown = len(self.display_results)
        fetched = len(self.all_results)
        total = self.total_results
        direction = "昇順" if self.sort_ascending else "降順"
        col = self.SORT_LABELS.get(self.sort_column, self.sort_column)
        stats = getattr(self, "filter_stats", {}) or {}

        if total > fetched:
            base = f"{total} 件中 {fetched} 件取得"
        else:
            base = f"{total} 件ヒット"

        parts = [base, f"{col}{direction}"]
        if extra_note:
            parts.append(extra_note)
        for label, n in stats.items():
            if n:
                parts.append(f"{label}で {n} 件除外")

        filtered_count = getattr(self, "filtered_count", shown)
        if filtered_count <= DISPLAY_LIMIT and shown == filtered_count:
            if shown:
                parts.append(f"フィルタ後 {shown} 件を全件表示")
            else:
                parts.append("フィルタ後 0 件")
        elif shown < filtered_count:
            parts.append(f"フィルタ後 {filtered_count} 件中 上位 {shown} 件を表示")
        elif shown:
            parts.append(f"{shown} 件表示")

        # 種類がすべて OFF か
        type_filts = [
            f
            for f in self.filter_defs
            if f.get("kind") in ("folder", "extension", "other")
        ]
        if type_filts and not any(self._chip_is_on(f) for f in type_filts):
            parts.append("すべての種類が非表示")
        self.info_var.set("  ·  ".join(parts))

    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("未選択", "項目を選択してください。")
            return None
        idx = self.tree.index(sel[0])
        if idx < 0 or idx >= len(self.display_results):
            return None
        return self.display_results[idx]

    def get_selected_path(self):
        row = self._selected_row()
        if not row:
            return None
        return row["fullpath"]

    @staticmethod
    def _nearest_existing_folder(path: str) -> str | None:
        """path の親をさかのぼり、実在する最も近いフォルダを返す（なければ None）。"""
        cur = os.path.dirname(os.path.normpath(path or ""))
        while cur:
            try:
                if os.path.isdir(cur):
                    return cur
            except OSError:
                pass
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        return None

    def _open_stale_fallback(self, path: str, what: str):
        """
        索引にはあるが実体が見つからない場合の案内。
        接続先 PC の Everything がネットワーク共有を索引していると、
        改名・移動・削除が反映されず古い名前が残ることがある。
        """
        folder = self._nearest_existing_folder(path)
        msg = (
            f"{what}が見つかりませんでした。\n"
            "索引が古い可能性があります（改名・移動・削除された可能性）。\n\n"
            f"{path}"
        )
        if folder:
            messagebox.showwarning(
                "見つかりません", msg + f"\n\n親フォルダを開きます:\n{folder}"
            )
            try:
                os.startfile(folder)
            except Exception as e:
                messagebox.showerror(
                    "フォルダオープン失敗", f"フォルダを開けませんでした。\n{e}"
                )
        else:
            messagebox.showwarning(
                "見つかりません", msg + "\n\n親フォルダも見つかりませんでした。"
            )

    def open_selected(self, _event=None):
        path = self.get_selected_path()
        if not path:
            return
        try:
            os.startfile(path)
        except FileNotFoundError:
            self._open_stale_fallback(path, "ファイル")
        except Exception as e:
            messagebox.showerror("オープン失敗", f"ファイルを開けませんでした。\n{e}")

    def open_selected_folder(self):
        row = self._selected_row()
        if not row:
            return
        path = row["fullpath"]
        folder = path if row["type"] == "folder" else os.path.dirname(path)
        try:
            os.startfile(folder)
        except FileNotFoundError:
            self._open_stale_fallback(folder, "フォルダ")
        except Exception as e:
            messagebox.showerror(
                "フォルダオープン失敗", f"フォルダを開けませんでした。\n{e}"
            )

    def copy_selected_path(self):
        """選択パスをテキストとしてコピー（複数は改行区切り）。"""
        paths = self._get_selected_paths()
        if not paths:
            messagebox.showinfo("未選択", "項目を選択してください。")
            return
        text = "\n".join(paths)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        if len(paths) == 1:
            self.info_var.set(f"パスをコピーしました: {paths[0]}")
        else:
            self.info_var.set(f"{len(paths)} 件のパスをコピーしました")

    def copy_selected_files(self):
        """
        選択ファイル/フォルダをクリップボードへ（複数選択対応）。
        エクスプローラーで Ctrl+V（貼り付け）するとコピーされる。
        """
        paths = self._get_selected_paths()
        if not paths:
            messagebox.showinfo("未選択", "項目を選択してください。")
            return
        try:
            n = copy_files_to_clipboard(paths)
            if n == 1:
                self.info_var.set(
                    "ファイルをコピーしました（エクスプローラーで貼り付けできます）"
                )
            else:
                self.info_var.set(
                    f"{n} 件をファイルコピーしました（エクスプローラーで貼り付けできます）"
                )
        except Exception as e:
            messagebox.showerror(
                "ファイルコピー失敗", f"ファイルをコピーできませんでした。\n{e}"
            )

    def _get_selected_paths(self) -> list[str]:
        """現在選択中の行のフルパス一覧。"""
        paths = []
        for iid in self.tree.selection():
            try:
                idx = self.tree.index(iid)
                if 0 <= idx < len(self.display_results):
                    paths.append(self.display_results[idx]["fullpath"])
            except (ValueError, IndexError, KeyError):
                continue
        return paths

    def _select_row_for_click(self, event, *, multi_aware: bool = True) -> str | None:
        """
        クリック位置の行を選択する。
        multi_aware 時: Ctrl=トグル追加, Shift=範囲, 既選択上の普通クリック=複数維持（ドラッグ用）
        戻り値: クリックした行のパス（なければ None）
        """
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return None

        ctrl = bool(event.state & 0x0004)  # Control
        shift = bool(event.state & 0x0001)  # Shift
        items = list(self.tree.get_children(""))

        if multi_aware and ctrl:
            if row_id in self.tree.selection():
                self.tree.selection_remove(row_id)
            else:
                self.tree.selection_add(row_id)
            self.tree.focus(row_id)
        elif multi_aware and shift:
            anchor = self.tree.focus()
            if not anchor and self.tree.selection():
                anchor = self.tree.selection()[0]
            if anchor and anchor in items and row_id in items:
                i1, i2 = items.index(anchor), items.index(row_id)
                if i1 > i2:
                    i1, i2 = i2, i1
                self.tree.selection_set(items[i1 : i2 + 1])
            else:
                self.tree.selection_set(row_id)
            self.tree.focus(row_id)
        else:
            # 既に複数選択中で、その中をクリック → 選択を維持（ドラッグ用）
            if (
                multi_aware
                and row_id in self.tree.selection()
                and len(self.tree.selection()) > 1
            ):
                self.tree.focus(row_id)
            else:
                self.tree.selection_set(row_id)
                self.tree.focus(row_id)

        try:
            idx = self.tree.index(row_id)
            if 0 <= idx < len(self.display_results):
                return self.display_results[idx]["fullpath"]
        except (ValueError, IndexError, KeyError):
            pass
        return None

    def _on_tree_b1_down(self, event):
        self._select_row_for_click(event, multi_aware=True)

    def _on_tree_b3_down(self, event):
        """右クリック: 未選択行なら単一選択。既選択内なら複数選択を維持。"""
        row_id = self.tree.identify_row(event.y)
        if row_id and row_id not in self.tree.selection():
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)

    def _on_tree_b3_up(self, event):
        paths = self._get_selected_paths()
        if not paths:
            return
        self._show_selection_context_menu(event, paths)

    def _show_selection_context_menu(self, event, paths: list[str]):
        """右クリックメニュー（複数選択対応・ファイルコピー／パスのコピー）。"""
        if not paths:
            return
        n = len(paths)
        menu = tk.Menu(self.root, tearoff=0, font=FONT_UI)
        menu.add_command(
            label="ファイルコピー" if n == 1 else f"ファイルコピー（{n} 件）",
            command=self.copy_selected_files,
        )
        menu.add_command(
            label="パスのコピー" if n == 1 else f"パスのコピー（{n} 件）",
            command=self.copy_selected_path,
        )
        menu.add_separator()
        menu.add_command(label="開く", command=self.open_selected)
        menu.add_command(label="フォルダを開く", command=self.open_selected_folder)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


def main():
    root = tk.Tk()
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    # ウィンドウ／タスクバー用アイコン
    if ICON_PATH.is_file():
        try:
            root.iconbitmap(default=str(ICON_PATH))
        except Exception:
            try:
                root.iconbitmap(str(ICON_PATH))
            except Exception:
                pass
    EverythingSearchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

# 仕組みとソース構成

実装は主に [`src/sugusearch.py`](../src/sugusearch.py)（約 4,800 行）。版数・配置先は `src/app_paths.py`、自己更新は `src/self_update.py`。
外部依存は標準ライブラリ + `pywin32`（コピー機能のみ）。ネットワークは `urllib` だけ。

操作方法は [usage.md](usage.md)、これからの話は [roadmap.md](roadmap.md)。

---

## 1. 全体像

```
入力文字列
  └ to_flexible_regex()      -/_ とスペースのゆらぎを正規表現へ
      └ search_everything()  http://host:port/ に GET（別スレッド）
          │  （暗いチップの条件は build_everything_filter_terms() で検索式に含める）
          └ parse_results()  表示用の dict に整形
              └ _apply_filters()        種類 → パス条件 → 重複（手元の最終チェック）
                  └ apply_sort_and_display()  ソートして上位 500 件を表示
```

Everything 本体は改造せず、**検索語を整形して HTTP API に渡すだけ**。

---

## 2. 検索語の変換（`to_flexible_regex`）

先頭固定（`^`）を付けないので途中一致。

| 入力中の文字 | 変換後 | 意図 |
|--------------|--------|------|
| `-` / `_` | `[-_\x20\x{3000}]` | 区切り 1 文字として同一視 |
| 半角・全角スペース（連続は 1 つに集約） | `.*?` | 間に何が入ってもよい |
| その他 | `re.escape` した 1 文字 | そのまま |

```
REV757_0200     → REV757[-_\x20\x{3000}]0200
空　スタッカー   → 空.*?スタッカー
AB010 54        → AB010.*?54
```

`\x{3000}` は Everything（PCRE 系）の記法で、Python の `re` とは互換ではない。**Everything に渡すためだけ**の文字列。

## 3. Everything への問い合わせ（`search_everything`）

検索式:

```
[folder: | file:]  [path:"対象フォルダ"]  [チップ由来の除外条件]  regex:<変換後>
```

`regex:` は必ず最後に置く。チップ由来の除外条件は §5 を参照。

| パラメータ | 値 |
|-----------|----|
| `json` | `1` |
| `count` | 既定 500／再取得時は段階的に増やす（最大 20000） |
| `path_column` / `size_column` / `date_modified_column` | `1` |
| `sort` / `ascending` | `date_modified` / `0`（新しい順で取得） |

- 認証: `user` か `password` があれば HTTP Basic ヘッダを付与
- タイムアウト: 500 件以下は 15 秒、それ以上は `min(180, 20 + count // 200)` 秒
- 検索はワーカースレッドで実行。応答は**世代番号**（`_search_gen`）で管理し、古い応答は破棄。UI 更新は必ず `root.after(0, ...)` 経由

## 3.5 接続確認と LAN 探索

- `probe_everything(host, port, user, password, timeout)` … `regex:^$` を `count=1` で問い合わせ、`ok`（JSON に `totalResults`）／`auth`（401・403）／`not_everything`（JSON でない等）／`down`（接続できない・タイムアウト）を返す。例外は投げない
- `scan_lan_for_everything(prefixes, ports, …)` … 各 `/24` の 1〜254 × ポートに TCP 接続（0.4 秒・64 並列）を試し、つながった相手にだけ `probe_everything` を送る。254 × 3 ポートで数秒
- 探索範囲は `lan_scan_prefixes(自 PC の IPv4)`（127.x と 169.254.x は除外）。VPN の先など別ネットワークは対象外

## 4. 結果の整形（`parse_results`）

各行に持たせる主なキー:

| キー | 内容 |
|------|------|
| `tag` / `type_text` | フィルタ定義から決まる種類 ID と表示名 |
| `size_raw` / `date_raw` | ソート用の数値（日時は FILETIME → UNIX 時刻） |
| `path_depth` | `\` の数（重複判定の優先度に使用） |
| `dedup_key` | あいまい正規化した名前（フォルダは空） |

種類の判定順は **フォルダ → 拡張子フィルタ（定義順）→ その他**。

---

## 5. フィルタ（`build_everything_filter_terms` / `_apply_filters`）

チップが **明るい = 除外しない / 暗い = 抑制**。

### サーバー側で絞る（1.0.2〜）

以前は「新しい順 500 件」を取ってから手元で絞っていたため、暗くしたチップの側（例: 大分 NAS）が 500 件を占めると、残したい側（例: 本社 NAS）が 1 件も届かないことがあった。
1.0.2 から、暗いチップの条件を Everything の検索式に含め、**絞り込んだ後の 500 件**を受け取る。

| チップ | 検索式に足す条件 |
|--------|------------------|
| パス条件（照合先にフルパスを含む）を暗く | `!nocase:path:"キーワード"`（大小文字を区別する設定なら `case:`） |
| パス条件（照合先が名前だけ）を暗く | `!nocase:nopath:"キーワード"` |
| 拡張子を暗く（その他は明るい） | `!ext:dwg;dxf` |
| フォルダを暗く（その他は明るい） | `file:` |
| その他を暗く | `<folder:\|ext:明るい拡張子;…>`（フォルダも暗ければ `ext:…` だけ） |

- 照合先が「場所」だけの条件、`"` `*` `?` を含むキーワードは Everything で正確に表せないので送らない（手元だけで判定）
- チップを切り替えて検索式が変わったら、Everything に取り直す（反映に少し時間がかかる）
- 手元のフィルタも従来どおり必ず掛ける（下記）。サーバー側で落とし切れなかった分の最終チェック

### 手元のフィルタ（`_apply_filters`）

適用順は固定。

1. **種類**（`folder` / `extension` / `other`）… 暗い種類を除外
2. **パス条件**（`path_keyword`、`order` の小さい順）… 暗いときだけキーワード該当行を除外
3. **重複**（`builtin_dedupe`）… 暗いときだけ同名を 1 件に集約

除外件数は手元で除外した分だけがフィルタごとに集計され、件数バーに `<表示名>で N 件除外` と出る（サーバー側で除外した分は総数に反映済み）。

### 重複判定

- キーは **ファイル名のみ**（場所は見ない）。拡張子は小文字化、それ以外は `-` `_` 半角・全角スペースを同一視し、連続する区切りを 1 つに畳む
  - `A-B.dwg` / `A_B.dwg` / `A B.dwg` は同名扱い
- フォルダは対象外（そのまま残る）
- 残す 1 件の順位: **更新日時が新しい → パスが浅い → フルパスが短い → 辞書順が先**

### フォルダのみモード

種類チップのうちフォルダだけが明るいとき（`_is_folder_only_mode`）、Everything に `folder:` を付けて取り直す。通常モードに戻すと `folder:` なしで再取得。切り替えは非同期で UI は止まらない。

## 6. 件数の制御

| 定数 | 値 | 役割 |
|------|----|------|
| `MAX_RESULTS` | 500 | 通常検索での取得件数 |
| `DISPLAY_LIMIT` | 500 | フィルタ後がこれ以下なら全件表示、超えたらこの件数まで |
| `REFETCH_IF_FILTERED_LE` | 499 | フィルタ後がこれ以下なら追加取得の対象（主に「重複」で減った分） |
| `REFETCH_GROWTH` | 4 | 追加取得で取得済みの何倍まで広げるか |
| `MAX_RESULTS_HARD_CAP` | 20000 | 追加取得の上限 |
| `INFO_WARN_FG` | `#DC2626` | 件数バーを警告表示するときの色（太字） |
| `FILTER_CHIPS_PER_ROW` | 10 | チップ 1 行あたりの個数（超えたら折り返し） |
| `FOLDER_HISTORY_MAX` | 20 | 対象フォルダ履歴の保持数 |
| `LIVE_SEARCH_DEBOUNCE_MS` | 280 | ライブ検索のデバウンス |

追加取得（`_needs_full_refetch` → `_schedule_refetch_all_async`）は、フィルタ後が `DISPLAY_LIMIT` 未満 **かつ** 総数が取得済みより多いときに発動。確認ダイアログを出さず `min(総数, 20000, max(取得済み×4, 2000))` 件で非同期に取り直し、完了後に一覧を差し替える。**1 検索につき 1 回だけ**（失敗しても再試行しない）。

### 件数バーの警告表示

総数が取得済みより多い（取り切れていない）か、フィルタ後が表示件数より多い（打ち切り）ときは、件数バーを **赤い太字**（文字の大きさは同じ）にする。`info_var` の書き込みを `trace_add` で拾い、`_info_warn_next` が立っているときだけ警告色にするので、ほかのメッセージは通常色に戻る。

## 7. ファイルのコピー（`copy_files_to_clipboard`）

- `CF_HDROP`（`DROPFILES` + UTF-16LE のパス列）と `Preferred DropEffect = DROPEFFECT_COPY` をクリップボードへ置く → エクスプローラーで Ctrl+V すると実体がコピーされる
- UNC パスは `/` を `\` に直すだけで存在確認はしない（ネットワーク遅延対策）
- 依存: `pywin32`（`win32clipboard` / `win32con`）

---

## 8. settings.json

セットアップ済み（`%LOCALAPPDATA%\SuguSearch\` に配置）なら `%LOCALAPPDATA%\SuguSearch\data\settings.json`。それ以外はアプリ（EXE またはスクリプト）と**同じフォルダ**（`app_paths.settings_path()`）。スクリプト版は `src\settings.json`。**両者は共有されない。**
無ければ既定値で起動し、保存操作で作られる。壊れた JSON は読み飛ばして既定値になる（起動は失敗しない）。Git 管理外。雛形は [settings.example.json](settings.example.json)。

| キー | 型 | 既定 | 内容 |
|------|----|------|------|
| `host` / `port` | 文字列 / 数値 | `127.0.0.1` / `8888` | Everything HTTP サーバー（ポートは 1〜65535） |
| `connection_history` | 配列 | `[]` | 接続履歴 `{host, port, last_ok}`（新しい順・最大 20 件）。`last_ok` は最後に接続できた日時 `YYYY-MM-DD HH:MM` |
| `user` | 文字列 | `""` | Basic 認証のユーザー名（平文） |
| `password` | 文字列 | `""` | Basic 認証のパスワード。**`enc:v1:<base64>` 形式で暗号化保存**（下記） |
| `search_folder` | 文字列 | `""` | 最後に使った対象フォルダ。`"パス"` 形式に正規化。空＝全体検索 |
| `folder_history` | 配列 | `[]` | 対象フォルダ履歴（新しい順・重複なし・最大 20 件） |
| `filters` | 配列 | `[]` | フィルタ定義。空なら出荷時の既定 |
| `chip_state` | オブジェクト | `{}` | フィルタ ID → `true`（明るい）／`false`（暗い） |

未知のキーは保存時に捨てられる。JSON なのでパスの `\` は `\\` と書く。

### filters の要素

```json
{ "id": "type_dwg", "kind": "extension", "label": "DWG",
  "color": "#DBEAFE", "extensions": [".dwg"],
  "show_chip": true, "default_on": true, "order": 20 }
```

| フィールド | 対象 kind | 内容 |
|-----------|-----------|------|
| `id` | 全部 | 一意。`chip_state` のキー。同じ ID が複数あると最初の 1 件だけ採用 |
| `kind` | — | `folder` / `extension` / `other` / `path_keyword` / `builtin_dedupe`。それ以外は無視 |
| `label` / `color` / `order` | 全部 | 表示名（40 文字まで）／`#RRGGBB`／小さいほど左・先 |
| `show_chip` | 全部 | `false` でチップを出さず、常に「除外しない」側で動く |
| `default_on` | 全部 | 画面の「初期表示」。`chip_state` に無いときの初期値で、「フィルタ」文字クリックの循環で戻る状態 |
| `locked` | 全部 | `true` は削除不可（`type_other` と `builtin_dedupe` は常に `true`） |
| `extensions` | `extension` | 小文字化され、`.` が無ければ補われる |
| `keywords` / `match_in` / `case_insensitive` | `path_keyword` | 部分一致する文字列／`fullpath` `path` `name`／既定 `true` |

読み込み時（`normalize_filter_definitions`）に、`other` / `builtin_dedupe` / `folder` が無ければ既定から補われ、`order` → `label` で並べ替えられる。

### 出荷時のフィルタ

| id | kind | 表示名 | 対象 | order |
|----|------|--------|------|-------|
| `type_folder` | folder | フォルダ | フォルダ | 10 |
| `type_dwg` | extension | DWG | `.dwg` | 20 |
| `type_dxf` | extension | DXF | `.dxf` | 30 |
| `type_pdf` | extension | PDF | `.pdf` | 40 |
| `type_excel` | extension | Excel | `.xls .xlsx .xlsm .xlsb .xlt .xltx .xltm` | 50 |
| `type_other` | other | その他 | 上記以外（削除不可） | 60 |
| `path_old` | path_keyword | 旧・OLD | `旧`, `old`（フルパス / 場所 / 名前） | 100 |
| `path_sys` | path_keyword | システム履歴 | `$RECYCLE.BIN`, `RECYCLE.BIN`, `RECYCLER`, `FileHistory`（フルパス / 場所） | 110 |
| `builtin_dedupe` | builtin_dedupe | 重複 | 同名ファイル（削除不可） | 200 |

### 保存されるタイミング

**接続して保存**（つながらなかった場合は「保存する」を選んだときだけ）/ フィルタ設定の保存 / **チップをクリックした瞬間** / Enter・検索ボタンでの検索（対象フォルダと履歴）/ 履歴の追加・削除 / **ウィンドウを閉じたとき**。

### パスワードの暗号化

Windows の DPAPI（`crypt32.dll` の `CryptProtectData` / `CryptUnprotectData`）を `ctypes` で直接呼んでいる（pywin32 は不要）。

- 保存時: `encrypt_secret()` が `enc:v1:<base64>` に変換。空文字はそのまま
- 読込時: `decrypt_secret()` が復号。`enc:v1:` が付いていない値は**旧バージョンの平文**としてそのまま読む（次回保存時に暗号化される）
- **復号できるのは暗号化した PC の、同じ Windows ユーザーだけ。** Dropbox 経由で別 PC / 別ユーザーが開いた場合は空になるので、接続設定タブで一度入れ直す（入れ直せばその PC 用に暗号化される）
- Windows 以外や DPAPI 呼び出しに失敗した環境では平文のまま保存される（機能は止めない）

---

## 9. ソース構成

| パス | 役割 |
|------|------|
| `README.MD` | ルートに置く唯一のファイル。概要・起動・ビルド手順 |
| `src/sugusearch.py` | 本体（GUI・検索・フィルタ・設定すべて） |
| `script/build_exe2.bat` | **ユーザーが実行するのはこれだけ。** アイコン生成 → PyInstaller → `dist` へ README コピー |
| `script/build_icon.py` | Pillow でアイコン PNG 11 サイズ + `assets/sugusearch.ico` を生成 |
| `script/起動.bat` | Python で直接起動する開発用ランチャ |
| `assets/sugusearch.ico` / `assets/icons/` | `build_icon.py` の生成物（Git 管理対象） |
| `doc/` | ドキュメント一式 |
| `tools/Everything-1.4.1.1032.x86/` | Everything 本体のポータブル版（ビルドには不要・Git 管理外） |
| `dist/` | ビルド生成物（`SuguSearch.exe` / `README.MD` / EXE 版の `settings.json`） |
| `build/` | PyInstaller の作業フォルダと自動生成 spec（`--workpath` / `--specpath` で集約） |

### モジュール内の区分

行番号はすぐずれるので、関数名で検索する。上から次の順に並んでいる。

| 区分 | 主な要素 |
|------|----------|
| 環境・定数 | `_fix_tcl_tk_paths` / `_runtime_dir` / `_resource_dir` / 件数・接続・LAN 探索の定数 / 配色 |
| フィルタ定義 | `default_filter_definitions` / `normalize_filter_definitions` / `classify_with_filters` / `path_keyword_matches` / `build_everything_filter_terms` |
| パスワードの暗号化 | `_dpapi_transform` / `encrypt_secret` / `decrypt_secret` |
| 設定 I/O | `load_settings` / `save_settings` / `normalize_connection_history` / `quote_folder_path` |
| 検索語とデータ加工 | `to_flexible_regex` / `normalize_name_for_dedup` / `dedupe_files_keep_newest` |
| Win32 連携 | `copy_files_to_clipboard` |
| 表示用ヘルパー | `format_size` / `format_datetime` / `type_display_label` |
| Everything アクセス | `probe_everything` / `probe_status_text` / `lan_scan_prefixes` / `scan_lan_for_everything` / `search_everything` / `parse_results` |
| UI 部品 | `TypeFilterChip` / `ModernButton` |
| `EverythingSearchApp` | タブ構築・検索・フィルタ・履歴・接続・結果操作 |
| エントリポイント | `main()` |

### `EverythingSearchApp` の要所

| メソッド | 内容 |
|----------|------|
| `create_widgets` / `_build_*_tab` | ヘッダ + 5 タブ（検索 / 接続設定 / フィルタ設定 / 更新 / 使い方） |
| `_run_live_search` / `on_search` | ライブ検索（280 ms デバウンス、履歴は増やさない）／即時検索（履歴を更新） |
| `_start_search_job` | スレッドで検索し、世代番号で古い応答を破棄 |
| `_on_filter_mode_changed` | フォルダのみモードやチップ由来の検索式が変わったら再検索、同じなら手元のフィルタのみ |
| `rebuild_filter_chips` / `_layout_footer` | チップを 10 個ごとに折り返して配置。2 行以上、または横に入りきらないときはボタンを上の行へ |
| `connect_and_save` | 接続確認（別スレッド）→ つながれば保存。つながらなければ理由を出して保存するか確認 |
| `_probe_connection_history_async` | 接続履歴を開いたとき各接続先を並列で確認（2 秒、30 秒キャッシュ） |
| `_check_failover_async` | 検索で接続できないとき履歴の他の接続先を確認し、件数バーで案内（自動では切り替えない） |
| `open_lan_scan_dialog` | 自 PC の /24 を（入力中のポート・8888・80）で探し、見つかった接続先を一覧表示 |
| `_apply_filters` / `apply_sort_and_display` | 絞り込み → ソート → 上位 `DISPLAY_LIMIT` 件を表示 |
| `_update_info_label` | 件数バーの文言生成。取り切れていない／打ち切りなら赤太字 |
| `toggle_sort` / `_update_heading_labels` | ソート切り替えと ↑↓ 表示（「名前」＝ファイル名、「場所」＝フルパス） |
| `copy_selected_files` / `_select_row_for_click` | ファイルコピーと Ctrl / Shift の複数選択処理 |
| `_persist_chip_state` | チップ明暗の保存（チップ操作時と終了時） |

### 実装メモ

- **`_fix_tcl_tk_paths`**: 複数バージョンの Python 混在で `TCL_LIBRARY` / `TK_LIBRARY` がずれる問題への対処。`import tkinter` より前に実行する必要があるためモジュール冒頭で呼んでいる
- **`_runtime_dir` と `_resource_dir`**: 設定は EXE の隣（書き込み可）、同梱リソースは `sys._MEIPASS`（onefile の展開先）と使い分け
- **エラー表示**: 検索失敗はダイアログを出さず件数バーの文言のみ（誤操作防止、赤太字）。保存やコピーの失敗はダイアログ
- **画面の文言**: 製品名（Everything）は出さず「サーバー」「検索サーバー」と書く。例外は使い方タブのダウンロード先（`EVERYTHING_DOWNLOAD_URL`）だけ
- **初期ウィンドウ**: 1280×960（画面に収まらなければ縮める）。接続履歴を開いても下部が隠れない高さ

---

## 10. これまでに入れた機能

| 機能 | 詳細 |
|------|------|
| `-` / `_` のゆらぎ吸収 | §2 |
| スペースの緩い検索（`-`/`_` とは別扱い） | §2。重複キーは連動しない（§5） |
| あいまい重複判定 | §5 |
| フィルタ設定タブ（拡張子・色・条件・並び・チップ表示） | §8 |
| チップ明暗の永続化・「フィルタ」文字クリックで 初期表示 → 全 ON → 全 OFF の循環（1.0.8） | §8 保存タイミング |
| 初期の並び＝更新日時の新しい順 | §9 `toggle_sort` |
| ライブ検索（280 ms デバウンス） | §9 `_run_live_search` |
| 対象フォルダを選び直したときもその場で再検索（履歴選択 / フォルダ選択… / × でクリア） | §9 `select_folder_history` / `browse_folder` / `on_folder_clear_or_close` |
| 件数の自動再取得 | §6 |
| フォルダのみモード | §5 |
| 複数選択 + エクスプローラーへのコピー | §7 |
| チップ条件をサーバー側で絞る（1.0.2） | §5 |
| 対象フォルダ欄の手入力・貼り付けで再検索（1.0.2） | §9 |
| 取得・表示 500 件、打ち切り時は件数バー赤太字（1.0.2） | §6 |
| 接続して保存・接続履歴の状態表示・LAN 探索・接続失敗時の案内（1.0.2） | §9 |
| チップの折り返し・初期ウィンドウ拡大・画面文言から製品名を除去（1.0.3） | §9 |
| パスワードの暗号化保存（DPAPI） | §8 |
| 「名前」列をファイル名で並べ替え（以前はフルパス基準だった） | §9 `toggle_sort` |

### 削除したもの（2026-07-27）

呼ばれていなかったコード約 350 行を削除した。復元が必要なら Git 履歴（`b9b3018` 以前）から取れる。
ドラッグ＆ドロップで分かっているノウハウは [development-guide.md](development-guide.md) の「7. ドラッグ＆ドロップ」に残してある。

| 削除した対象 | 経緯 |
|------|------|
| `_make_hdrop_hglobal` / `_FileDropDataObject` / `_FileDropSource` / `_init_drag_com_interfaces` / `do_files_drag_drop` | OLE ドラッグ＆ドロップ。環境により `DoDragDrop` が不安定で無効化されたまま残っていた。**機能自体は今後もほしいので、作り直す前提でいったん白紙に戻した** |
| `show_shell_context_menu` / `_show_fallback_context_menu` | エクスプローラー相当のシェルメニュー。UNC 等で挙動差があり複数選択も扱いづらいため、独自メニューに置き換え済みだった |
| `is_old_related` / `is_system_history` | 旧・OLD／システム履歴の判定。絞り込みは `path_keyword_matches` に一本化済みだった |

これに伴い PyInstaller の `--hidden-import` から `pythoncom` / `win32com.shell.shell` / `win32com.shell.shellcon` を外した（EXE は 15.9 MB → 12.1 MB）。`win32timezone` は pywin32 の取りこぼし対策として残している。

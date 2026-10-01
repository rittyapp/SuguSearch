# すぐサーチ

型番・図番の検索で、`-` と `_`、半角・全角スペースの違いを意識せずに Everything を使える補助ツールです。

## できること

- **`-` / `_`** … 区切り 1 文字として同一視（`REV757_0200` → `REV757-0200`）
- **半角・全角スペース** … 間に任意の文字を許容（`AB010 54` → `AB010-85-054`、`空　スタッカー` → `空トレイアンスタッカー`）
- ファイル名の途中一致（`694 1056` → `REV694-1056`）
- 入力するだけで結果が更新される（ライブ検索）
- **フィルタ** … 種類・**重複**・**旧・OLD**・**システム履歴** の表示切替
- 複数選択 → **コピー** でエクスプローラーへ貼り付け（Ctrl+V）
- サイズ・更新日時の表示、列ヘッダでのソート（初期は更新日時の新しい順）
- 対象フォルダの指定と履歴、Everything が別 PC のときの接続先設定

## 必要なもの

| 項目 | 内容 |
|------|------|
| OS | Windows |
| Everything | インストール済みで、**HTTP サーバーが有効**であること |
| Python | EXE 版は不要（ソースから動かす場合は 3.9 以上・`tkinter`） |

### Everything 側の設定

1. Everything を起動する
2. **ツール → オプション → HTTP サーバー** を有効にする（既定ポートは `8888`）
3. ブラウザで `http://127.0.0.1:8888/` が開けば準備完了
4. 他 PC から使う場合は、ファイアウォールでそのポートを許可する

**同じ Wi‑Fi / LAN の他 PC から接続するとき**の注意（サーバー側・クライアント側の両方）は  
[doc/lan-wifi-connection.md](doc/lan-wifi-connection.md) を参照。

Everything 本体: https://www.voidtools.com/

## 起動・セットアップ（どの Windows でも）

### 利用者向け

1. 配布された **`SuguSearch-Setup-<版>.zip`** を展開し、中の **`setup.bat`** をダブルクリック（デスクトップに「すぐサーチ」が付く）。`files` フォルダの中は触らなくてよい
2. デスクトップの「すぐサーチ」から起動
3. 新しい版があるときはアプリ内 **「更新」タブ** →「更新を確認」→「ダウンロードして更新」

旧 Everysearch を使っていた場合、接続先などの設定はセットアップ時に自動で引き継がれます。すぐサーチが起動できたら、Everysearch のショートカットと `%LocalAppData%\Everysearch` を削除してください。

利用者は GitHub やトークンを意識する必要はありません。

### 開発者向け

1. **ビルド**: `script\build_exe2.bat` → `dist\SuguSearch.exe` と配布用 `dist\SuguSearch-Setup-<版>.zip`（`setup.bat` と `files\`{exe, setup.ps1}）
2. **セットアップ試験**: `script\setup.bat` → `%LocalAppData%\SuguSearch\`
3. **リリース**: `script\release.bat`（ビルド → push → 公開 Release に exe と zip を添付。更新タブは exe を見に行く）
4. 版数は `src\app_paths.py` の `APP_VERSION` と `version.txt` を揃える（配布物に version.txt は不要）
5. **開発起動**: `script\起動.bat` または `py src\sugusearch.py`

## かんたんな使い方

1. **検索** 欄に型番・図番を入力（例: `REV757_0200`）。入力するだけで結果が出ます
2. **対象フォルダ** は空欄なら全体検索。`"\\サーバー\共有\フォルダ"` のように指定もできます（履歴あり）
3. 結果をダブルクリックで開く／**ファイルコピー** でエクスプローラーへ貼り付け／**パスのコピー**（複数選択可）
4. 画面下の **フィルタ** チップで種類・重複・旧・OLD の表示を切り替え
   - 明るい＝表示、暗い＝抑制。「フィルタ」の文字を押すと全部明るく戻ります

詳しい操作は [doc/usage.md](doc/usage.md)。

## 再ビルド

**`script\build_exe2.bat` をダブルクリック**します（ルートを整理したので、bat は `script` フォルダの中です）。
出来上がるのはこれまでどおり `dist\SuguSearch.exe` です。

| 手順 | 内容 |
|------|------|
| 0 | 起動中の `SuguSearch.exe` を終了（上書きできるように） |
| 1/3 | `script\build_icon.py` で `assets\icons\*.png` と `assets\sugusearch.ico` を生成 |
| 2/3 | PyInstaller（`--onefile --windowed`）で `dist\SuguSearch.exe` を作成 |
| 3/3 | `README.MD` を `dist\` へコピー |

必要パッケージ:

```bat
py -3 -m pip install pyinstaller pillow pywin32
```

- `pywin32` はコピー機能に必要（`--hidden-import` だけでは足りず、本体の導入が要る）
- PyInstaller の作業ファイルと自動生成される `すぐサーチ.spec` は `build\` にまとめています（ビルドの入力ではありません）
- EXE は単体で配布できます。設定は EXE と同じフォルダの `settings.json` に作られるので、書き込みできる場所に置いてください

## ドキュメント

| 文書 | 内容 |
|------|------|
| [doc/usage.md](doc/usage.md) | 使い方の詳細（画面・操作・トラブル対応） |
| [doc/architecture.md](doc/architecture.md) | 仕組み・`settings.json` 仕様・ソース構成・実装済み機能 |
| [doc/roadmap.md](doc/roadmap.md) | 決めてほしいこと・実装候補 |
| [doc/development-guide.md](doc/development-guide.md) | 開発の進め方（汎用ガイド） |

## ファイル構成

ルートに置くファイルはこの README だけにしてあります。

```
すぐサーチ/
  README.MD                      … この説明
  script/
    build_exe2.bat               … EXE ビルド（ユーザーが実行するのはこれだけ）
    build_icon.py                … 多サイズ アイコン生成
    起動.bat                     … Python から起動（開発用）
  src/
    sugusearch.py     … 本体ソース
    settings.json                … Python 実行時の設定（自動生成）
  assets/                        … sugusearch.ico と icons/（build_icon.py の生成物）
  doc/                           … ドキュメント一式
  dist/
    SuguSearch.exe              … 配布用 EXE
    README.MD                    … ビルド時にコピー
    settings.json                … EXE 版の設定（自動生成）
  build/                         … PyInstaller の作業フォルダ（自動生成）
  tools/                         … Everything 本体のポータブル版など
```

## うまく動かないとき

| 症状 | 確認すること |
|------|--------------|
| 検索に失敗する | Everything が起動しているか、HTTP サーバーが有効か、ホスト・ポートが合っているか（接続設定タブの **接続テスト**） |
| 0 件になる | 対象フォルダのパスが正しいか。空欄で全体検索して比較。種類チップが全部暗くなっていないか |
| 期待する型番が出ない | 画面下の「変換後正規表現」を確認。`旧・OLD` や `重複` で除外されていないか |
| 画面が開かない | Python の `tkinter` が使えるか（`py -3 -c "import tkinter"`） |
| ビルドが失敗する | `pyinstaller` / `pillow` の導入、ウイルス対策ソフトによる EXE 生成のブロック |

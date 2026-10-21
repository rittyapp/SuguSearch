# すぐサーチ（SuguSearch）— Claude 用プロジェクト指示

共通原則は `ai-instructions/common/operating-principles.md`、Windows の作法は `ai-instructions/common/windows-app.md` を正とする。ここにはこのプロジェクト固有の事実だけ書く。

## 現状（2026-10-01）

- 旧 **Everysearch を「すぐサーチ」に改名**して本リポジトリ `rittyapp/SuguSearch`（公開）で 1.0.0 から開始。
- 旧 Everysearch リポジトリは 1.3.2 で終了。旧すぐサーチ（別実装）は `oldfile/`（git 管理外）。
- 名前の使い分け: 画面・ショートカット・Release 名は「すぐサーチ」、EXE は `SuguSearch.exe`、配置は `%LOCALAPPDATA%\SuguSearch\`（日本語の EXE 名は更新 bat が ASCII 前提なので使わない）。
- 自己更新あり（`src/self_update.py`）。差し替えは `update_runner.bat`（インストール先直下）が行い、経過を `data\update_runner.log` に残す。更新の失敗は `data\update_error.log`。参照先は `rittyapp/SuguSearch` の Releases、asset は `SuguSearch-<版>.exe` と `SuguSearch-Setup-<版>.zip`（exe を `SuguSearch.exe` という名前で添付すると 1.0.3 以前の更新処理が SameFileError で失敗するので、必ず版付きの名前にする。`release.ps1` がそうしている）。
- 旧 Everysearch の設定は初回だけ引き継ぐ（`app_paths.legacy_settings_path()`、`setup.ps1`）。
- ロードマップは `doc/roadmap.md`。

## バージョン番号のルール

- 形式は `メジャー.マイナー.パッチ`（例 `1.0.0`）。比較は数値（`self_update._parse_version`）なので `1.0.10 > 1.0.9` で正しく動く。
- **main に変更を入れるたびにパッチ（最下位）を +1** する。`.py` を変更したとき（コミット前でも）も同様に +1 する（1 回の作業で 1 回）。`1.0.0 → 1.0.1 → … → 1.0.9 → 1.0.10 → …`
- パッチは**最大 2 桁**。3 桁（100 以上）にはしない。
- **パッチが 90 を超える版（91 以降）にするときは、上げる前にユーザーに確認を促す**（マイナーを上げて `1.1.0` にするか等をユーザーが決める）。勝手にマイナー/メジャーを上げない。
- 上げる箇所は下の「リリース手順」1 の 3 か所。

## リリース手順

1. `version.txt`、`src/app_paths.py` の `APP_VERSION`、`script/build_exe2.bat` のフォールバック版数を揃えて上げる
2. コミットメッセージを `script/release-msg.txt`、リリースノートを `script/release-notes.md` に置く
3. Windows で `script\release.bat` を実行（ビルド → commit → push → Release 作成 → asset 添付。リポジトリが無ければ作る）
4. ログは `%TEMP%\sugusearch-release.log`（終了時に `script\release.log` へコピー。Dropbox がロックするため直接書かない）
5. PowerShell 5.1 で `Get-Content -Raw` の結果を JSON に入れない（NoteProperty が混ざり 422 になる）。`[IO.File]::ReadAllText` を使う

## 注意

- リポジトリは**公開**。社内 IP・ユーザー名・パスワードを書かない。
- `.bat` は CP932 + CRLF、`.ps1` は UTF-8 BOM 付き。
- Everything の結果パスは「接続先 PC から見たパス」。ネットワーク共有の索引は古いことがある（開けない場合は親フォルダを開く実装済み）。

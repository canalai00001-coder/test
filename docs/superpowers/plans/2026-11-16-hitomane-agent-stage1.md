# ヒトマネ入稿ツール 第1段階（土台・ログイン情報・画面調査）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ヒトマネ管理画面の作りと取り出し CSV の形を、ユーザーのパソコンから調べて保存する「画面調査」コマンドを、`hitomane_agent` パッケージの土台と一緒に作る。

**Architecture:** `qmate_agent` を変えずに、同じリポジトリに `hitomane_agent/` を新しく作る。設定の読み方（`config.py`）とログイン情報の読み方（`accounts.py`）は `qmate_agent` と同じ形にそろえる（統合しやすくするため）。画面調査は Playwright でログインし、各画面の HTML・スクリーンショット・リンク一覧を `output/画面調査_<日時>/` に保存する。ボタンは見分け方が分からないので、文字（「募集管理」「ファイルを取込む」など）で探し、見つからなくても止めずに、見つかったところまで保存する。

**Tech Stack:** Python 3.10+、Playwright（sync API）、gspread（ログイン情報シートを読む）、unittest、標準ライブラリの http.server（テスト用のにせの管理画面）。

**Spec:** `docs/superpowers/specs/2026-11-16-hitomane-agent-design.md`

入稿（段階2）と取り下げ（段階3）は、画面調査の結果（セレクター・CSV の形）が分かってから別の計画にする。

## Global Constraints

- 読むスプレッドシートは【AI用】ヒトマネ 求人原稿自動生成（`1sDLw8aMXmkQi9Uy4fhQMf3g4GqKhh7fd8TJEIWe1DzA`）だけ。原本は読まない・書かない。
- 管理画面の URL：`https://kanri.hitomgr.jp/m66w/`。
- ログイン情報：通勤用スプレッドシート（`1nPk9AG7wePhszTO4bcN8Rs_gFNJKjlj0YAFanz9ggK4`）の「Q-mateログイン情報」シートの、会社名「ヒトマネ」の行。スプレッドシートがリンク共有（anyone / domain）のあいだはパスワードを使わずに止める。
- 画面調査では、取り込み・取り下げ・掲載状態の変更をしない。押してよいのは、ログイン、画面の移動、ダイアログを開く・閉じる、検索、（`--sample` を付けたときだけ）1件の「ファイル取出予約」とそのダウンロード。
- `qmate_agent/` の中身は変えない。
- 文章（画面の表示・README・コメント）は日本語で、AI らしい言い回しを避ける。

## Review Focus

- 管理画面がこのパソコンからも 403 を返す（社外ネットワーク）：「管理画面を開けませんでした（403）。社内のネットワークから実行してください」と出して止め、そこまでの記録を保存する。→ Task 3 のテストに入れる。
- ログインに失敗する（ID・パスワード違い）：ログイン後もログイン画面のままなら「ログインできませんでした」と出して止め、その画面の HTML と写真を保存する。→ Task 3。
- 「募集管理」などの文字が見つからない：止めずにその画面だけ「見つかりませんでした」と記録し、残りの画面の調査を続ける。→ Task 3。
- `--sample` の取り出しが時間内に完了しない：待った時間と予約一覧の画面を保存して止める（取り出し予約はそのまま残る旨を出す）。→ Task 4。
- ログイン情報シートに「ヒトマネ」の行がない：「Q-mateログイン情報シートに『ヒトマネ』の行を足してください」と出して止める。→ Task 2。

---

### Task 1: パッケージの土台と設定

**Files:**
- Create: `hitomane_agent/hitomane_agent/__init__.py`（空）
- Create: `hitomane_agent/hitomane_agent/config.py`（`qmate_agent/qmate_agent/config.py` と同じ中身。`ROOT` は `hitomane_agent/`）
- Create: `hitomane_agent/config/settings.json`
- Create: `hitomane_agent/requirements.txt`（`qmate_agent/requirements.txt` と同じ）
- Create: `hitomane_agent/.gitignore`（`output/` `state/` `config/*.local.json` `service_account*.json` `__pycache__/`）
- Test: `hitomane_agent/tests/test_config.py`

**Interfaces:**
- Produces: `config.ROOT: Path`、`config.CONFIG_DIR`、`config.OUTPUT_DIR`、`config.STATE_DIR`、`config.load(name: str) -> dict`（`<stem>.local.json` を重ねる）。
- Produces: `settings.json` のキー：`spreadsheet_id`（AI 用）、`output_sheet_prefix`（`"ヒトマネ出力_"`）、`service_account_file`（`"service_account.json"`）、`login_spreadsheet_id`（通勤用）、`accounts_sheet`（`"Q-mateログイン情報"`）、`login_company`（`"ヒトマネ"`）、`hitomane.base_url`（`"https://kanri.hitomgr.jp/m66w/"`）、`hitomane.timeout_ms`（60000）、`hitomane.poll_interval_ms`（5000）、`hitomane.export_poll_times`（360）、`csv`（`{"encoding": "utf-8", "newline": "\r\n"}`。調査後に直す）。

- [ ] **Step 1: Write the failing test** — `test_local_overrides_settings`：一時フォルダの `settings.json` に `{"hitomane": {"base_url": "a", "timeout_ms": 1}}`、`settings.local.json` に `{"hitomane": {"base_url": "b"}}` を置き、`config.load("settings.json")["hitomane"] == {"base_url": "b", "timeout_ms": 1}`。`test_settings_has_required_keys`：本物の `settings.json` に上のキーがすべてあり、`spreadsheet_id == "1sDLw8aMXmkQi9Uy4fhQMf3g4GqKhh7fd8TJEIWe1DzA"`。
- [ ] **Step 2: Run** `cd hitomane_agent && python -m unittest tests.test_config -v` → FAIL（モジュールがない）。
- [ ] **Step 3: Implement** 上の Files を作る。
- [ ] **Step 4: Run** 同じコマンド → PASS。
- [ ] **Step 5: Commit** `git add hitomane_agent && git commit -m "ヒトマネ入稿ツールの土台（設定の読み込み）を足す"`

### Task 2: ログイン情報の読み込み

**Files:**
- Create: `hitomane_agent/hitomane_agent/accounts.py`
- Test: `hitomane_agent/tests/test_accounts.py`

**Interfaces:**
- Consumes: `config.load`。
- Produces: `parse_sheet(values: list[list]) -> dict[str, dict]`（`qmate_agent.accounts.parse_sheet` と同じ見出しの読み方。ただし URL 欄は空欄可で、co の番号は読まない。値は `{"login_id", "password", "url"}`）。
- Produces: `login_info(settings: dict, book=None) -> dict`（`{"login_id", "password", "url"}`。`url` が空なら `settings["hitomane"]["base_url"]`。`book` はテスト用に渡せる gspread Spreadsheet 互換のもの。渡さなければ `login_spreadsheet_id` をサービスアカウントで開く）。共有が anyone / domain なら `RuntimeError("…制限付き…")`、行がなければ `RuntimeError("Q-mateログイン情報シートに『ヒトマネ』の行を足してください")`、パスワードが空なら `RuntimeError("…パスワードが空欄…")`。

- [ ] **Step 1: Write the failing tests** — にせの book（`worksheet(name).get_all_values()` と `list_permissions()` を持つ）で：`test_reads_hitomane_row`（見出し「会社名・ログインID・パスワード・CSV取込画面のURL（またはco=の番号）」、行「ヒトマネ / Minami / pw / 」→ `login_info` が `{"login_id": "Minami", "password": "pw", "url": "https://kanri.hitomgr.jp/m66w/"}`）、`test_link_shared_is_refused`（permissions に `{"type": "anyone"}` → 「制限付き」を含む RuntimeError）、`test_missing_row`（「ヒトマネ」の行なし →「『ヒトマネ』の行を足して」を含む RuntimeError）、`test_blank_password`。
- [ ] **Step 2: Run** `python -m unittest tests.test_accounts -v` → FAIL。
- [ ] **Step 3: Implement** `accounts.py`（gspread は関数の中で import。`gspread.service_account(filename=ROOT/service_account_file)` で開く）。
- [ ] **Step 4: Run** → PASS。
- [ ] **Step 5: Commit** `git commit -m "ヒトマネのログイン情報をログイン情報シートから読む"`

### Task 3: 画面調査（ログインと各画面の保存）

**Files:**
- Create: `hitomane_agent/hitomane_agent/survey.py`
- Create: `hitomane_agent/hitomane_agent/__main__.py`（サブコマンド `survey`）
- Test: `hitomane_agent/tests/test_survey.py`（`http.server` のにせの管理画面）

**Interfaces:**
- Consumes: `accounts.login_info`、`config.OUTPUT_DIR`。
- Produces: `run_survey(info: dict, out_dir: Path, headed: bool = False, sample: str = "", log=print) -> dict`。戻り値 `{"steps": [{"name": str, "ok": bool, "url": str, "note": str}], "dir": str}`。各段階で `out_dir/<番号>_<名前>.html`・`.png`・`_links.txt`（「文字 → href」1行1つ）を保存し、最後に `out_dir/調査結果.txt`（段階ごとの ok・url・note）を書く。
- 段階（名前は固定）：`01_ログイン画面`、`02_トップ`（ログイン後）、`03_ファイル取込ダイアログ`（トップで「ファイルを取込む」を押してダイアログを開いた状態。保存後に「閉じる」を押す。取込予約は押さない）、`04_募集管理`（「募集管理」を押した画面）、`05_予約一覧`（トップか募集管理のリンクのうち文字に「予約」を含むもの。無ければ note に「見つかりませんでした」）。
- ログイン：最初の `input[type=password]` にパスワード、その前にある最初の text / email の input に ID、`button[type=submit], input[type=submit]` か文字「ログイン」のボタンを押す。ログイン後もパスワード欄が残っていれば「ログインできませんでした」で止める。最初の応答が 403 なら「管理画面を開けませんでした（403）。社内のネットワークから実行してください」で止める。
- `__main__.py survey [--headed] [--sample 募集番号]`：`login_info` → `run_survey`（out_dir は `OUTPUT_DIR / f"画面調査_{%Y%m%d_%H%M}"`）。最後に「output\画面調査_… フォルダをまとめて送ってください」と出す。パスワードはどこにも保存・表示しない。

- [ ] **Step 1: Write the failing tests** — にせの管理画面（`/m66w/` がログインフォーム、POST で `/m66w/top` へ、トップに「募集管理」リンク・「ファイルを取込む」ボタン（押すと `#import_dialog` が表示され「閉じる」ボタンあり）・「予約一覧」リンク）で：`test_survey_saves_each_screen`（5段階すべて ok、各 `.html` と `.png` があり、`調査結果.txt` に5行、どのファイルにもパスワード文字列が含まれない）、`test_wrong_password_stops`（02 以降なし、01 の ok が False で note「ログインできませんでした」）、`test_forbidden_stops`（`/m66w/` が 403 → note「403」、例外を投げずに戻る）、`test_missing_link_continues`（トップに「予約」のリンクなし → 05 の ok が False で note「見つかりませんでした」、01〜04 は ok）、`test_import_is_not_reserved`（にせの画面で「ファイル取込予約」が押されたら記録するようにし、押されていないこと）。
- [ ] **Step 2: Run** `PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium python -m unittest tests.test_survey -v` → FAIL。
- [ ] **Step 3: Implement** `survey.py` と `__main__.py`。
- [ ] **Step 4: Run** → PASS。
- [ ] **Step 5: Commit** `git commit -m "ヒトマネ管理画面の画面調査コマンドを足す"`

### Task 4: 1件だけの取り出し（`--sample`）

**Files:**
- Modify: `hitomane_agent/hitomane_agent/survey.py`
- Test: `hitomane_agent/tests/test_survey.py`

**Interfaces:**
- Produces: `run_survey(..., sample="CB93208")` のとき、04 のあとに段階 `06_取り出し予約`（募集管理のフリーワードに `sample` を入れて「検索」→ 結果の画面を保存 →「ファイル取出予約」を押す → 開いた画面を保存）と `07_取り出しファイル`（「最新を表示する」を押しながら、`poll_interval_ms` ごとに最大 `export_poll_times` 回、いちばん上の行のステータスが「完了」になるのを待ち、詳細の `.csv` リンクをダウンロードして `out_dir/取り出し見本.csv` に保存。中身はそのまま）を足す。完了しなければ 07 の note に「○分待っても完了しませんでした（予約はヒトマネに残っています）」。検索結果が1件でなければ 06 で止める（note に件数）。

- [ ] **Step 1: Write the failing tests** — にせの画面に募集管理の検索（フリーワード欄・「検索」ボタン・「全N件」）、「ファイル取出予約」（押すと予約一覧へ。2回目の「最新を表示する」で「完了」と `.csv` リンクが出る）を足して：`test_sample_export_downloads_csv`（`取り出し見本.csv` が保存され中身がにせの CSV と同じ）、`test_sample_not_unique_stops`（検索結果「全3件」→ 06 の ok False、note に「3件」、取出予約は押されていない）、`test_sample_export_timeout`（ずっと「待機中」、`export_poll_times=2` → 07 の note に「完了しませんでした」）。
- [ ] **Step 2: Run** → FAIL。
- [ ] **Step 3: Implement**。
- [ ] **Step 4: Run** → PASS。
- [ ] **Step 5: Commit** `git commit -m "画面調査で1件だけ取り出して CSV の見本を保存する"`

### Task 5: 実行用のファイルと説明

**Files:**
- Create: `hitomane_agent/survey.bat`（`..\qmate_agent\.venv` があればそれを使い、なければ `hitomane_agent\.venv` を作って `pip install -r requirements.txt`・`playwright install chromium`。`python -m hitomane_agent survey %*` を実行して `pause`）
- Create: `hitomane_agent/README.md`（置き場所、service_account.json は qmate_agent と同じものを置くこと、ログイン情報シートに「ヒトマネ」の行を足すこと、`survey.bat` と `survey.bat --sample 募集番号` の使い方、結果フォルダの送り方。今後の段階（入稿・取り下げ）の予定）
- Test: なし（全テストを流して確認）

- [ ] **Step 1: Write** 上の2ファイル。
- [ ] **Step 2: Run** `cd hitomane_agent && PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium python -m unittest discover -s tests -v` → すべて PASS。`cd ../qmate_agent && python -m unittest discover -s tests -q` → OK（qmate_agent に影響なし）。
- [ ] **Step 3: Commit and push** `git commit -m "ヒトマネの画面調査の実行ファイルと説明を足す" && git push -u origin claude/relaxed-clarke-nk8kc9`

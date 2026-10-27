# Q-mate 求人投稿エージェント

Google スプレッドシートの求人データを読み、内容をチェックしてから Q-mate の管理画面に入力するツールです。
投稿するのは、人が承認した行だけです。

## 流れ

```
スプレッドシート
   │
   ▼
① check   ルールチェック（必須・数値・選択肢・年齢の逆転・最低賃金・県と住所の不一致・重複）
          ＋ Claude による内容チェック（項目同士の食い違い、誤字、不適切な表現、情報の抜け）
          → output/report.html と、シートの「AIチェック」「チェック内容」列に結果を書く
   │
   ▼
② 人が確認  レポートを見て、投稿してよい行の「承認」列に OK と入れる
   │
   ▼
③ post    承認済みの行だけ Q-mate に入力
          → 入力した値を画面から読み戻して元データと1項目ずつ照合
          → 全部一致したときだけ保存（初期設定は下書き保存）
          → スクリーンショットを output/screens/ に残し、シートの「投稿状況」列に結果を書く
```

次の行は post で自動的に外れます。

- check をしていない行
- check のあとでシートの内容が書き換えられた行（承認後の書き換えを防ぐため）
- 判定が NG の行
- 同じ内容ですでに投稿した行

## セットアップ

```bash
cd qmate_agent
pip install -r requirements.txt
playwright install chromium
export ANTHROPIC_API_KEY=...   # AIチェック用
```

### スプレッドシートの準備

1. Google Cloud でサービスアカウントを作り、JSON キーを `service_account.json` として置く
2. スプレッドシートを、そのサービスアカウントのメールアドレスに「編集者」で共有する
3. `config/sheet.json` の `spreadsheet_id` と `worksheet` を書き換える
4. シートに次の列を用意する（列名は `config/sheet.json` で変更可）
   - `承認`（人が OK を入れる）
   - `AIチェック` `チェック内容` `投稿状況`（ツールが書き込む。なくても動く）

求人データの列名と、各項目のチェック内容は `config/fields.json` で設定します。
`column` をシートの見出しに合わせてください。

### Q-mate 画面の設定

`config/qmate_form.json` に、ログインページや求人作成ページの URL、各入力欄のセレクタを書きます。
今入っているセレクタは仮のものなので、実際の画面に合わせて書き換えが必要です。

#### セレクタの調べ方

```bash
playwright codegen https://（Q-mateのログインURL）
```

ブラウザが開くので、ログインして求人作成画面で各欄をクリック・入力すると、右側に
`page.fill("input[name='title']", ...)` のようなコードが出ます。この `input[name='title']` の部分を
`qmate_form.json` の `selector` に写します。

`action` は入力欄の種類に合わせます。

| action | 対象 |
|---|---|
| fill | テキスト入力、テキストエリア |
| select | プルダウン（シートの値と同じ表示名の選択肢を選ぶ） |
| check | チェックボックス（`value_map` で「あり→true」のように対応付ける） |
| radio | ラジオボタン（シートの値と同じ value のものを選ぶ） |

数値欄に `"format": "int"` を付けると、「1,600円」を「1600」にして入力します。

#### ログイン

2段階認証がある場合は、手でログインしてセッションを保存します。

```bash
python -m qmate_agent login
```

ID とパスワードだけで入れる場合は、環境変数 `QMATE_ID` `QMATE_PASSWORD` を設定しておけば自動でログインします。

## 使い方

```bash
# チェック
python -m qmate_agent check

# 入力と照合だけ試す（保存しない）。最初はブラウザを表示して動きを確認する
python -m qmate_agent post --dry-run --headed

# 本番（qmate_form.json の submit_mode が draft なら下書き保存、publish なら公開）
python -m qmate_agent post
```

CSV で試すときは `--csv sample/jobs_sample.csv` を付けます（シートへの書き戻しはしません）。
AI を使わずルールだけで見るときは `check --no-ai` です。ただし AI チェックなしの承認は、
`post --allow-no-ai` を付けない限り投稿対象になりません。

## 運用上の注意

- 最初のうちは `submit_mode` を `draft` のままにして、下書きを Q-mate 上で目視してから公開するのがおすすめです。
  照合で一致していても、画面上の見え方まではチェックしていません。
- 最低賃金は `config/fields.json` の `min_wage_by_prefecture` に都道府県ごとに入れてください。
  毎年10月ごろに改定されるので、その都度更新が必要です。未設定の県は `min_wage_default` で判定します。
- 性別の指定や年齢制限がある行には注意を出します。法令上載せられるかの最終判断は人がしてください。
  性別の列は Q-mate には入力しない設定にしています。
- Q-mate の利用規約で自動操作が認められているかは、事前に確認してください。
- 画面のデザインが変わるとセレクタが合わなくなり、その行は「操作中にエラー」で止まります。
  その場合は codegen で調べ直して `qmate_form.json` を直します。

## テスト

```bash
python -m unittest discover -s tests -t .
```

`tests/mock_qmate_form.html` という仮の入力画面を使って、入力・照合・保存の流れを確かめています。
本物の Q-mate には接続しません。

## ファイル

| ファイル | 内容 |
|---|---|
| `qmate_agent/sheet.py` | スプレッドシート / CSV の読み込みと書き戻し |
| `qmate_agent/validate.py` | ルールチェック |
| `qmate_agent/ai_review.py` | Claude による内容チェック |
| `qmate_agent/poster.py` | Q-mate 画面への入力と照合（Playwright） |
| `qmate_agent/report.py` | 確認用レポート |
| `qmate_agent/__main__.py` | コマンド（check / post / login） |
| `state/` | チェック時のデータのハッシュと投稿履歴（自動作成） |
| `output/` | レポートとスクリーンショット（自動作成） |

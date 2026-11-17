# ヒトマネ用 GAS（写し）

【AI用】ヒトマネ 求人原稿自動生成 のスプレッドシートに付いている Apps Script を、2026-11-17 に `clasp clone` で取り出した写しです。
スクリプト ID：`1vfEfYrDHk0VLdkqrTmvc40zX4zX0wyvGkcyqL60rJOtzNA6IB0aVh0NC`

- `コード.js`：メニュー「ヒトマネ自動生成」の①〜⑥（③予約リストを一括実行・⑤検品シートを作成 など）
- `appsscript.json`：プロジェクトの設定

ツールの原稿の生成（`hitomane_agent/generator.py`）は、この `コード.js` の③の新FMT の部分（hmBuildContentBank_・hmGenerateBatchNewFmt_・
hmBuildRowNewFmt_ など）を Python に移したものです。⑤検品の項目は、ツールのチェック（`checks.py`）に入っています。

ここにあるのは見るための写しです。GAS を直すときは Apps Script のエディタで直し、直したらもう一度取り出してここを置き換えてください。

```
cd （空のフォルダ）
npx -y @google/clasp@2.4.2 login
npx -y @google/clasp@2.4.2 clone 1vfEfYrDHk0VLdkqrTmvc40zX4zX0wyvGkcyqL60rJOtzNA6IB0aVh0NC
```

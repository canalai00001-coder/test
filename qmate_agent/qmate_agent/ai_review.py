"""Claude による原稿の中身のチェック。

ルールでは拾えない「職種名と仕事内容のズレ」「タイトルと本文の食い違い」
「キーワードが原稿の内容と合っていない」「誤字」などを見てもらう。
AI は指摘だけを返し、シートを書き換えることはしない。
"""
import json

import anthropic

from .checks import Issue

MODEL = "claude-opus-5-5"

# AI に渡す列。応募フォームの設定や他媒体用の列は渡さない。
REVIEW_COLUMNS = [
    "雇用形態", "職種名", "求人ボックス用職種名", "職種カテゴリー(大分類)", "職種カテゴリー(中分類)",
    "勤務地：都道府県", "勤務地：市区町村", "仕事内容", "応募資格・条件", "年齢制限の有無", "性別制限",
    "給与形態", "給与_下限", "給与_上限", "基本給", "給与例", "勤務形態", "勤務時間",
    "給与形態に応じた労働時間（日給・週給・月給・年俸のみ）", "休日休暇", "待遇・福利厚生",
    "受動喫煙対策", "キャッチコピー", "選考フロー", "キーワードリスト（複数選択可）", "メモ",
]

SYSTEM = """あなたは人材紹介会社で、求人媒体 Q-mate に入稿する求人原稿を最終チェックする担当者です。
原稿は GAS でテンプレートから自動生成されたもので、1件ずつ渡します。入稿前に次の点を見てください。

- 項目同士の食い違い（職種名・求人ボックス用職種名・仕事内容・カテゴリーが同じ仕事を指しているか、
  勤務時間の夜勤の有無とタイトルや待遇の書き方、給与例と給与の範囲、休日の日数の書き方など）
- キーワードリストに、原稿の内容と合わない語が入っていないか（例：夜勤ありの原稿に「日勤のみ」系、
  寮の記載がないのに「寮・社宅あり」など）。無駄クリックの原因になるため運用で削っています
- テンプレートの差し込み漏れ（{ } や ○○ が残っている、別の勤務地や別職種の文が混ざっている）
- 誤字脱字、文のつながりがおかしい箇所
- 求人広告として問題のある表現（差別的表現、根拠のない誇大表現、性別や年齢を限定する書き方）

運用ルール:
- 求人ボックス用職種名には休日や待遇など原稿の中身を入れる方針です（無駄クリック対策）
- 応募資格・勤務時間・休日・キャッチコピー・待遇と、重め/軽め以外の仕事内容では絵文字を使わず飾り紐にしています
- 年間休日は120日表記です

ルールで判定済みの指摘も渡すので、同じ内容は繰り返さないでください。
問題がなければ issues は空にしてください。言い回しの好みのような細かい指摘は不要です。
severity は、掲載すると誤った情報になるもの・法令上問題があるものを error、
直したほうがよいものを warning、参考程度を info にしてください。
column には上の列名をそのまま入れ、どれにも当てはまらなければ "全体" としてください。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                    "column": {"type": "string"},
                    "message": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["severity", "column", "message", "suggestion"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["issues", "summary"],
    "additionalProperties": False,
}


class AIReviewer:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def review(self, row: dict, rule_issues: list[Issue]) -> tuple[list[Issue], str]:
        data = {c: row[c] for c in REVIEW_COLUMNS if row.get(c, "").strip()}
        prompt = (
            "## 原稿\n" + json.dumps(data, ensure_ascii=False, indent=2) +
            "\n\n## ルールで判定済みの指摘\n" +
            (json.dumps([i.to_dict() for i in rule_issues], ensure_ascii=False, indent=2)
             if rule_issues else "なし")
        )
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return [Issue("error", "全体", "AIチェックが実行できませんでした（refusal）。人の目で確認してください", "ai")], ""
        if response.stop_reason == "max_tokens":
            return [Issue("error", "全体", "AIチェックの出力が途中で切れました。再実行してください", "ai")], ""
        text = next(b.text for b in response.content if b.type == "text")
        result = json.loads(text)
        issues = [Issue(i["severity"], i["column"], i["message"], "ai", i.get("suggestion", ""))
                  for i in result["issues"]]
        return issues, result.get("summary", "")

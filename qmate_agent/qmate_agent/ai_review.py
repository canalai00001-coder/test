"""Claude による内容チェック。

ルールでは拾えない「仕事内容と職種名が合っていない」「誤字」「求職者が読んで
意味が通らない」「数字と文章の食い違い」などを見てもらう。
AI は指摘だけを返し、値を勝手に直すことはしない。直すのは人。
"""
import json

import anthropic

from .validate import Issue

MODEL = "claude-opus-5-5"

SYSTEM = """あなたは人材派遣会社で求人原稿をチェックする担当者です。
これから Q-mate に掲載する求人1件分のデータを渡します。掲載前の最終確認として、
次の観点で問題を探してください。

- 項目同士の食い違い（職種名と仕事内容、給与と月収例、勤務時間とシフト、住所と最寄り駅など）
- 誤字脱字、表記ゆれ、全角半角の混在で読みにくい箇所
- 求職者が読んで意味が取れない、または誤解しそうな書き方
- 求人広告として不適切な表現（差別的表現、根拠のない誇大表現、性別や年齢を限定する書き方）
- 応募判断に必要なのに抜けている情報

ルールで判定済みの指摘も渡します。同じ内容を繰り返す必要はありません。
問題がなければ issues は空にしてください。細かすぎる好みの指摘はしないでください。
severity は、掲載すると誤った情報になるもの・法令上問題があるものを error、
直したほうがよいものを warning、参考程度を info にしてください。
field にはデータのキー名（job_no, title など）を入れ、どれにも当てはまらなければ "general" にしてください。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                    "field": {"type": "string"},
                    "message": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["severity", "field", "message", "suggestion"],
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

    def review(self, job: dict, labels: dict, rule_issues: list[Issue]) -> tuple[list[Issue], str]:
        data = {k: {"項目名": labels.get(k, k), "値": v} for k, v in job.items()}
        prompt = (
            "## 求人データ\n" + json.dumps(data, ensure_ascii=False, indent=2) +
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
            return [Issue("error", "general", "AIチェックが実行できませんでした（refusal）。人の目で確認してください", "ai")], ""
        if response.stop_reason == "max_tokens":
            return [Issue("error", "general", "AIチェックの出力が途中で切れました。再実行してください", "ai")], ""
        text = next(b.text for b in response.content if b.type == "text")
        result = json.loads(text)
        issues = [Issue(i["severity"], i["field"], i["message"], "ai", i.get("suggestion", ""))
                  for i in result["issues"]]
        return issues, result.get("summary", "")

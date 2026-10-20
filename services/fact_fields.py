"""
fact_fields.py：事実のテーブルごとに「画面で修正できる項目」を決めておくファイルです。

更新管理画面の修正フォームは、この一覧（FIELD_SPECS）を見て入力欄を自動で並べます。
新しい事実のテーブルを追加したときは、ここにも項目を追加します。

項目の書き方：(列名, 画面に出す名前, 入力の種類, 選択肢)
  入力の種類：text（1行）/ textarea（複数行）/ date（YYYY-MM-DD）/ int（整数）/ select（選択肢から選ぶ）/ company（企業を選ぶ）
選択肢は、データベースのルール（CHECK）と同じ値にしています（テストで一致を確かめています）。
"""

import re
from datetime import date

DISCLOSURES = ["公開", "非公開", "未確認"]

FIELD_SPECS = {
    "medical_facts": [
        ("content", "内容", "textarea", None),
    ],
    "safety_info": [
        ("content", "内容", "textarea", None),
    ],
    "product_companies": [
        ("company_id", "企業", "company", None),
    ],
    "approvals": [
        ("approval_type", "承認の種類", "select", ["初回承認", "効能・効果追加", "用法・用量追加・変更", "剤形追加", "その他"]),
        ("approval_date", "承認年月日", "date", None),
        ("approval_number", "承認番号", "text", None),
        ("content", "承認内容の説明", "textarea", None),
    ],
    "reexaminations": [
        ("content", "説明", "textarea", None),
        ("disclosure", "再審査期間の公開状況", "select", DISCLOSURES),
        ("period_years", "再審査期間（年）", "int", None),
        ("start_date", "再審査期間の開始日", "date", None),
        ("end_date", "再審査期間の終了日", "date", None),
    ],
    "patents": [
        ("patent_number", "特許番号", "text", None),
        ("country", "国・地域", "text", None),
        ("patent_kind", "特許の種類", "select", ["物質", "用途", "製剤", "製法", "その他", "不明"]),
        ("title", "発明の名称", "text", None),
        ("disclosure", "満了日の公開状況", "select", DISCLOSURES),
        ("expiry_date", "特許の存続期間満了日", "date", None),
        ("extended_expiry_date", "延長登録後の満了日", "date", None),
    ],
    "licenses": [
        ("partner_company_id", "相手先の企業", "company", None),
        ("role", "相手先の役割", "select", ["導入元", "導出先", "提携先"]),
        ("license_type", "契約の種類", "select", ["導入", "導出", "共同開発", "共同販売", "販売提携", "その他"]),
        ("territory", "対象地域", "text", None),
        ("content", "契約内容の説明", "textarea", None),
        ("disclosure", "契約期間の公開状況", "select", DISCLOSURES),
        ("contract_start", "契約開始日", "date", None),
        ("contract_end", "契約終了日", "date", None),
        ("disclosed_fiscal_year", "開示年度", "text", None),
    ],
    "pms_studies": [
        ("study_type", "調査・試験の種類", "select", ["一般使用成績調査", "特定使用成績調査", "使用成績比較調査",
                                                 "製造販売後データベース調査", "製造販売後臨床試験", "その他"]),
        ("title", "調査名", "text", None),
        ("all_case", "全例調査か", "select", ["全例調査", "全例調査ではない", "未確認"]),
        ("approval_condition", "承認条件か", "select", ["承認条件", "承認条件ではない", "未確認"]),
        ("progress", "実施状況", "select", ["計画中", "実施中", "終了", "結果公表済み", "未確認"]),
        ("target_cases", "目標症例数", "text", None),
        ("disclosure", "実施期間の公開状況", "select", DISCLOSURES),
        ("start_date", "実施期間の開始日", "date", None),
        ("end_date", "実施期間の終了日", "date", None),
        ("registration_no", "登録番号（jRCT など）", "text", None),
    ],
}

# 公開状況（disclosure）が「公開」のときだけ入力できる列
DISCLOSED_COLUMNS = {
    "reexaminations": ["period_years", "start_date", "end_date"],
    "patents": ["expiry_date", "extended_expiry_date"],
    "licenses": ["contract_start", "contract_end"],
    "pms_studies": ["start_date", "end_date"],
}


def parse_value(kind, label, raw):
    """
    入力欄の文字を、データベースに入れる値に直します。空欄は None です。
    形が正しくないときは、日本語の説明つきで ValueError を出します。
    """
    if raw is None:
        return None
    if kind in ("select", "company"):
        return raw  # 選択肢から選んだ値は、そのまま使う
    text = str(raw).strip()
    if not text:
        return None
    if kind == "date":
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                raise ValueError
            date.fromisoformat(text)
        except ValueError:
            raise ValueError(f"「{label}」は YYYY-MM-DD の形の正しい日付にしてください（例：2025-11-01）。") from None
    if kind == "int":
        if not text.isdigit() or int(text) <= 0:
            raise ValueError(f"「{label}」は1以上の整数にしてください。")
        return int(text)
    return text


def check_combination(table, values):
    """
    項目どうしの組み合わせを確かめ、問題があれば日本語の説明のリストを返します。
    （データベースのルールでも防いでいますが、先にわかりやすい言葉で知らせるため）
    """
    errors = []
    columns = DISCLOSED_COLUMNS.get(table)
    if columns:
        filled = [c for c in columns if values.get(c) is not None]
        if values.get("disclosure") != "公開" and filled:
            errors.append(f"公開状況が「{values.get('disclosure')}」のときは、日付・期間を空欄にしてください（推測で埋めないため）。")
        if values.get("disclosure") == "公開" and not filled:
            errors.append("公開状況が「公開」のときは、日付（または期間）を1つ以上入力してください。")
    for start, end in (("start_date", "end_date"), ("contract_start", "contract_end"),
                       ("expiry_date", "extended_expiry_date")):
        if values.get(start) and values.get(end) and values[end] <= values[start]:
            errors.append("終了日（延長後の満了日）は、開始日（もとの満了日）より後の日付にしてください。")
    return errors

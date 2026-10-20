"""
diff.py：変更前と変更後の「差分」（どこがどう変わったか）を作る処理です。

- diff_records()：2つのデータを比べて、違う項目だけを一覧にする
- parse_json()  ：更新履歴に保存した JSON の文字を、辞書に戻す

内容を修正する前の確認画面と、更新履歴の表示で使います。
"""

import json

# 列名の日本語名（差分の表で使う）
COLUMN_LABELS = {
    "id": "ID",
    "content": "内容",
    "status": "確認状態",
    "verified_by": "確認者",
    "verified_at": "確認日時",
    "source_version_id": "出典の版",
    "source_location": "該当箇所",
    "entry_method": "入力方法",
    "is_current": "今の情報か",
    "superseded_by": "置き換え先ID",
    "product_id": "製品",
    "disease_id": "疾患",
    "indication_id": "適応症",
    "company_id": "企業",
    "role": "役割",
    "fact_type": "種類",
    "subcategory": "細かい区分",
    "category": "区分",
    "document_id": "文書",
    "version_label": "版",
    "revised_on": "改訂年月",
    "retrieved_on": "入手日",
    "confirmed_on": "確認日",
    "source_url": "原文URL",
    "description": "内容",
    "detection_method": "検出方法",
    "detected_at": "検出日時",
    "new_version_id": "新しい版",
    "resolved_by": "対応者",
    "resolved_at": "対応日時",
    "created_at": "登録日時",
    # ---- 承認・再審査・特許・ライセンス・PMS（Step 9 で追加）----
    "approval_type": "承認の種類",
    "approval_date": "承認年月日",
    "approval_number": "承認番号",
    "disclosure": "公開状況",
    "period_years": "再審査期間（年）",
    "start_date": "開始日",
    "end_date": "終了日",
    "patent_number": "特許番号",
    "country": "国・地域",
    "patent_kind": "特許の種類",
    "title": "名称",
    "expiry_date": "特許の存続期間満了日",
    "extended_expiry_date": "延長登録後の満了日",
    "partner_company_id": "相手先の企業",
    "license_type": "契約の種類",
    "territory": "対象地域",
    "contract_start": "契約開始日",
    "contract_end": "契約終了日",
    "disclosed_fiscal_year": "開示年度",
    "study_type": "調査・試験の種類",
    "all_case": "全例調査か",
    "approval_condition": "承認条件か",
    "progress": "実施状況",
    "target_cases": "目標症例数",
    "registration_no": "登録番号",
    # ---- 製品・疾患・文書など（CSVインポートの履歴で使う）----
    "brand_name": "販売名",
    "generic_name": "一般名",
    "official_url": "公式製品URL",
    "last_checked_on": "最終確認日",
    "name_ja": "名前（日本語）",
    "name_en": "名前（英語）",
    "doc_type": "文書種別",
    "publisher": "発行元",
    "external_id": "識別番号",
}

# 差分を見るときに比べなくてよい列（自動で決まる値）
_IGNORED = ("id", "created_at")


def diff_records(before, after, conn=None):
    """
    変更前（before）と変更後（after）の辞書を比べ、違う項目だけを
    [{"項目": …, "変更前": …, "変更後": …}, ...] の形で返します。
    新しく追加したデータ（before が None）のときは、すべての項目を「変更後」に並べます。
    conn を渡すと、ID（出典の版・製品など）を名前に直して表示します。
    """
    before = before or {}
    after = after or {}
    rows = []
    for column in list(dict.fromkeys([*before, *after])):  # 列の順番を保ったまま重複をなくす
        if column in _IGNORED:
            continue
        old, new = before.get(column), after.get(column)
        if old == new:
            continue
        rows.append({
            "項目": COLUMN_LABELS.get(column, column),
            "変更前": display_value(conn, column, old) if column in before else "（なし）",
            "変更後": display_value(conn, column, new),
        })
    return rows


def display_value(conn, column, value):
    """値を、人が読みやすい文字に直します（IDは名前に、1/0 ははい/いいえに）。"""
    if value is None or value == "":
        return "（空欄）"
    if column == "is_current":
        return "今の情報" if value else "過去の情報"
    if conn is not None:
        lookups = {
            "source_version_id": "SELECT d.title || ' ／ ' || v.version_label FROM document_versions v "
                                 "JOIN documents d ON d.id = v.document_id WHERE v.id = ?",
            "new_version_id": "SELECT d.title || ' ／ ' || v.version_label FROM document_versions v "
                              "JOIN documents d ON d.id = v.document_id WHERE v.id = ?",
            "document_id": "SELECT title FROM documents WHERE id = ?",
            "product_id": "SELECT brand_name FROM products WHERE id = ?",
            "disease_id": "SELECT name_ja FROM diseases WHERE id = ?",
            "company_id": "SELECT name_ja FROM companies WHERE id = ?",
            "partner_company_id": "SELECT name_ja FROM companies WHERE id = ?",
            "indication_id": "SELECT p.brand_name || ' × ' || d.name_ja FROM indications i "
                             "JOIN products p ON p.id = i.product_id JOIN diseases d ON d.id = i.disease_id "
                             "WHERE i.id = ?",
        }
        if column in lookups:
            row = conn.execute(lookups[column], (value,)).fetchone()
            if row:
                return f"{row[0]}（ID {value}）"
    return str(value)


def parse_json(text):
    """更新履歴に保存した JSON の文字を辞書に戻します。空なら None を返します。"""
    return json.loads(text) if text else None

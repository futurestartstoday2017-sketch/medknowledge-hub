"""
comparison.py：競合製品比較のための表を作る処理です。

- build_comparison()：疾患（適応症）を選んで、その疾患に適応のある製品の情報を集める
- comparison_table()：製品を横に並べた比較表を作る
- sources_table()   ：比較表の各値の出典と確認日の一覧を作る

この処理は情報を並べるだけで、製品の優劣を判定したり、値で並べ替えたりはしません。
並び順は「対象企業の製品 → 競合製品」（それぞれ販売名の順）で固定です。
"""

import pandas as pd

from components.display import STATUS_ICONS, disclosed_value, status_label
from db.queries import get_disease_products, get_product_companies, get_product_facts, get_product_regulatory
from services.timeline import effective_expiry, first_approval, latest_patent, product_reexam

# 比較表に並べる項目（この順で上から表示する）
COMPARISON_ITEMS = [
    "効能・効果", "製造販売元", "販売元", "薬効分類", "作用機序", "投与経路", "剤形", "用法・用量",
    # ---- 承認・再審査・特許・PMS（Step 9 で追加）----
    "初回承認年月日", "再審査期間の終了日", "特許満了日（最も遅いもの）", "全例調査",
]


def build_comparison(conn, disease_id, product_ids=None):
    """
    疾患に適応のある製品について、比較に使う情報を集めます。
    product_ids を渡すと、その製品だけにしぼります。
    戻り値：[{"product": {販売名などの辞書}, "items": {項目名: [事実のリスト]}}, ...]
    """
    entries = []
    for entry in get_disease_products(conn, disease_id):
        if product_ids is not None and entry["product_id"] not in product_ids:
            continue
        items = {name: [] for name in COMPARISON_ITEMS}
        items["効能・効果"] = entry["facts"]  # この疾患に対する効能・効果の文言
        for fact in get_product_companies(conn, entry["product_id"]):
            items[fact["role"]].append(fact)
        for fact in get_product_facts(conn, entry["product_id"]):
            if fact["fact_type"] in items:
                items[fact["fact_type"]].append(fact)
        items.update(_regulatory_items(get_product_regulatory(conn, entry["product_id"])))
        product = {k: entry[k] for k in ("product_id", "brand_name", "generic_name", "category")}
        entries.append({"product": product, "items": items})
    return entries


def comparison_table(entries, verified_only=False):
    """
    製品を横（列）、項目を縦（行）に並べた比較表を作ります。
    verified_only=True のときは、「原文確認済み」の情報だけを表に出します。
    """
    columns = {}
    for entry in entries:
        product = entry["product"]
        column = {"区分": product["category"], "一般名": product["generic_name"] or "—"}
        for item in COMPARISON_ITEMS:
            column[item] = _cell_text(entry["items"][item], verified_only)
        columns[product["brand_name"]] = column
    table = pd.DataFrame(columns, index=["区分", "一般名"] + COMPARISON_ITEMS)
    table.index.name = "項目"
    return table


def sources_table(entries, verified_only=False):
    """比較表に出した各値の、出典（文書名・版・該当箇所）と確認日の一覧を作ります。"""
    rows = []
    for entry in entries:
        for item in COMPARISON_ITEMS:
            for fact in _visible(entry["items"][item], verified_only):
                rows.append({
                    "製品": entry["product"]["brand_name"],
                    "項目": item,
                    "確認状態": status_label(fact["status"]),
                    "内容": fact["content"],
                    "出典文書": fact["doc_title"],
                    "版": fact["version_label"],
                    "改訂年月": fact["revised_on"] or "記載なし",
                    "該当箇所": fact["source_location"],
                    "確認日": fact["verified_at"][:10] if fact["status"] == "原文確認済み" else "未確認",
                    "原文URL": fact["source_url"],
                })
    return pd.DataFrame(rows, columns=["製品", "項目", "確認状態", "内容", "出典文書", "版", "改訂年月",
                                       "該当箇所", "確認日", "原文URL"])


def _regulatory_items(regulatory):
    """
    承認・再審査・特許・PMS から、比較表の4つの行に出す値を作ります。
    事実の辞書をコピーし、表に出す文字を content に入れ直して返します（出典・確認状態はそのまま）。
    """
    def shown(fact, text):
        return {**fact, "content": text}

    items = {}
    approval = first_approval(regulatory["approvals"])
    items["初回承認年月日"] = [shown(approval, approval["approval_date"])] if approval else []

    reexam = product_reexam(regulatory["reexaminations"])
    items["再審査期間の終了日"] = (
        [shown(reexam, disclosed_value(reexam["disclosure"], reexam["end_date"]))] if reexam else [])

    patent = latest_patent(regulatory["patents"])
    if patent:
        extended = "（延長登録後）" if patent["extended_expiry_date"] else ""
        items["特許満了日（最も遅いもの）"] = [shown(patent, f"{effective_expiry(patent)}{extended}")]
    else:
        # 公開の満了日がない場合は、特許ごとの公開状況（🔒 非公開 / ❔ 未確認）を出す
        items["特許満了日（最も遅いもの）"] = [shown(p, disclosed_value(p["disclosure"], None))
                                       for p in regulatory["patents"]]

    # 全例調査：PMS ごとに「全例調査か」と調査名を出す（登録がなければ「未登録」）
    items["全例調査"] = [shown(p, f"{p['all_case']}（{p['title']}）") for p in regulatory["pms_studies"]]
    return items


def _visible(facts, verified_only):
    """表に出してよい事実だけを返します。"""
    return [f for f in facts if f["status"] == "原文確認済み"] if verified_only else facts


def _cell_text(facts, verified_only):
    """比較表の1マス分の文字を作ります（確認状態の印 + 内容）。"""
    if not facts:
        return "未登録"
    shown = _visible(facts, verified_only)
    if not shown:
        return "（原文確認済みの情報がないため非表示）"
    return " ／ ".join(f"{STATUS_ICONS[f['status']]} {f['content']}" for f in shown)

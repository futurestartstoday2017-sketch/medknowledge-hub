"""
quality.py：データの品質をチェックし、問題のある箇所を一覧にする処理です。

DBの制約だけでは防げない「つじつまの合わない状態」を見つけます。
見つけた問題は自動では直さず、人が確認して対応します。

- find_quality_problems()：問題の一覧を返す（問題がなければ空のリスト）
"""

from db.database import FACT_TABLES

# 事実のテーブルの日本語名（画面やメッセージ用）
TABLE_LABELS = {
    "product_companies": "製造販売元・販売元",
    "medical_facts": "医学的情報",
    "safety_info": "安全性情報",
}

# 「出典の文書が、その情報の対象（製品・疾患）とつながっているか」を確かめるSQLの条件
# f は事実のテーブル、v は出典の版を表します
_SOURCE_LINKED = {
    "product_companies": "EXISTS (SELECT 1 FROM document_links l "
                         "WHERE l.document_id = v.document_id AND l.product_id = f.product_id)",
    "safety_info": "EXISTS (SELECT 1 FROM document_links l "
                   "WHERE l.document_id = v.document_id AND l.product_id = f.product_id)",
    # 医学的情報は、対象が製品・疾患・適応症のどれかなので、それぞれの場合を確かめる
    "medical_facts": """(
        (f.product_id IS NOT NULL AND EXISTS (SELECT 1 FROM document_links l
            WHERE l.document_id = v.document_id AND l.product_id = f.product_id))
        OR (f.disease_id IS NOT NULL AND EXISTS (SELECT 1 FROM document_links l
            WHERE l.document_id = v.document_id AND l.disease_id = f.disease_id))
        OR (f.indication_id IS NOT NULL AND EXISTS (SELECT 1 FROM document_links l
            JOIN indications i ON i.id = f.indication_id
            WHERE l.document_id = v.document_id
              AND (l.product_id = i.product_id OR l.disease_id = i.disease_id)))
    )""",
}


def find_quality_problems(conn):
    """
    品質の問題を探して、次の形の辞書のリストで返します。
    {"kind": 問題の種類, "table": テーブル名, "record_id": 行のID, "message": 説明}
    """
    problems = []

    for table in FACT_TABLES:
        label = TABLE_LABELS[table]

        # ① 出典の文書が、情報の対象（製品・疾患）とつながっていない
        rows = conn.execute(f"""
            SELECT f.id FROM {table} f
            JOIN document_versions v ON v.id = f.source_version_id
            WHERE f.is_current = 1 AND NOT {_SOURCE_LINKED[table]}
        """)
        for row in rows:
            problems.append({
                "kind": "出典の対象不一致",
                "table": table,
                "record_id": row["id"],
                "message": f"{label}（ID {row['id']}）の出典文書が、対象の製品・疾患とつながっていません",
            })

        # ② 「原文確認済み」なのに、出典が最新版ではない（改訂後に確認していない）
        rows = conn.execute(f"""
            SELECT f.id FROM {table} f
            JOIN document_versions v ON v.id = f.source_version_id
            WHERE f.is_current = 1 AND f.status = '原文確認済み' AND v.is_current = 0
        """)
        for row in rows:
            problems.append({
                "kind": "旧版を出典にした確認済み情報",
                "table": table,
                "record_id": row["id"],
                "message": f"{label}（ID {row['id']}）は、出典の文書が改訂されています。再確認が必要です",
            })

    # ③ 版が登録されているのに、最新版が1つもない文書
    rows = conn.execute("""
        SELECT d.id, d.title FROM documents d
        WHERE EXISTS (SELECT 1 FROM document_versions v WHERE v.document_id = d.id)
          AND NOT EXISTS (SELECT 1 FROM document_versions v WHERE v.document_id = d.id AND v.is_current = 1)
    """)
    for row in rows:
        problems.append({
            "kind": "最新版のない文書",
            "table": "documents",
            "record_id": row["id"],
            "message": f"文書「{row['title']}」（ID {row['id']}）に最新版が設定されていません",
        })

    return problems

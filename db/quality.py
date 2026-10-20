"""
quality.py：データの品質をチェックし、問題のある箇所を一覧にする処理です。

DBの制約だけでは防げない「つじつまの合わない状態」を見つけます。
見つけた問題は自動では直さず、人が確認して対応します。

- find_quality_problems()：問題の一覧を返す（問題がなければ空のリスト）
"""

from db.database import FACT_TABLES, TABLE_LABELS

# 「出典の文書が、その情報の対象（製品・疾患）とつながっているか」を確かめるSQLの条件
# f は事実のテーブル、v は出典の版を表します
# ここに書いていないテーブル（安全性情報・承認・特許など、対象が製品のもの）は _PRODUCT_LINKED で確かめます
_PRODUCT_LINKED = ("EXISTS (SELECT 1 FROM document_links l "
                   "WHERE l.document_id = v.document_id AND l.product_id = f.product_id)")
_SOURCE_LINKED = {
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
    # 登録番号の出典は、その登録番号の登録ページ（文書種別「臨床試験登録」で、識別番号が登録番号と同じ）
    "trial_registrations": """EXISTS (SELECT 1 FROM documents d2
        WHERE d2.id = v.document_id AND d2.doc_type = '臨床試験登録' AND d2.external_id = f.registration_no)""",
    # 試験の内容の出典は、その試験のどれかの登録番号の登録ページ
    "trial_details": """EXISTS (SELECT 1 FROM documents d2
        JOIN trial_registrations r ON r.registration_no = d2.external_id AND r.is_current = 1
        WHERE d2.id = v.document_id AND d2.doc_type = '臨床試験登録' AND r.trial_id = f.trial_id)""",
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
            WHERE f.is_current = 1 AND NOT {_SOURCE_LINKED.get(table, _PRODUCT_LINKED)}
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

    problems += _trial_problems(conn)
    return problems


def _trial_problems(conn):
    """臨床試験に特有の問題（内容や登録番号のない試験、同一試験の可能性）を探します。"""
    problems = []

    # ④ 今の内容、または登録番号が1つもない試験
    for column, table, message in (
        ("内容", "trial_details", "の内容（タイトルなど）が登録されていません"),
        ("登録番号", "trial_registrations", "に登録番号が1つもありません"),
    ):
        rows = conn.execute(f"""
            SELECT t.id FROM trials t
            WHERE NOT EXISTS (SELECT 1 FROM {table} x WHERE x.trial_id = t.id AND x.is_current = 1)
        """)
        for row in rows:
            problems.append({
                "kind": f"{column}のない試験", "table": "trials", "record_id": row["id"],
                "message": f"試験 TR-{row['id']:04d} {message}",
            })

    # ⑤ 同一試験の可能性：登録ページに書かれた「他の登録番号」が、別の試験の登録番号になっている
    #   （自動ではまとめない。人が登録ページを見比べて、同じ試験なら1つにまとめる）
    registrations = conn.execute(
        "SELECT trial_id, registration_no, secondary_ids FROM trial_registrations WHERE is_current = 1").fetchall()
    owner = {r["registration_no"]: r["trial_id"] for r in registrations}
    reported = set()
    for r in registrations:
        for other_no in (r["secondary_ids"] or "").split(";"):
            other_no = other_no.strip()
            other_trial = owner.get(other_no)
            pair = tuple(sorted((r["trial_id"], other_trial or 0)))
            if other_trial and other_trial != r["trial_id"] and pair not in reported:
                reported.add(pair)
                problems.append({
                    "kind": "同一試験の可能性", "table": "trials", "record_id": r["trial_id"],
                    "message": (f"TR-{r['trial_id']:04d} の登録番号 {r['registration_no']} の登録ページに、"
                                f"TR-{other_trial:04d} の登録番号 {other_no} が書かれています。同じ試験かもしれません"),
                })
    return problems

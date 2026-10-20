"""
queries.py：画面に表示するためのデータを、データベースから取り出す処理をまとめたファイルです。

画面（pages/ のファイル）からは SQL を直接書かずに、このファイルの関数を呼び出します。
事実（医学的情報など）は、必ず「今の情報」（is_current = 1）だけを、出典と一緒に取り出します。
"""

import pandas as pd

from db.database import FACT_TABLES

# 一覧表で、確認状態を文字の前に付ける印（SQLの中で使う）
_STATUS_ICON_SQL = """
    CASE {col} WHEN '原文確認済み' THEN '✅ ' WHEN '再確認要' THEN '🔁 ' ELSE '⚠️ ' END
"""

# 事実と一緒に取り出す「出典」の列（f = 事実のテーブル、v = 文書の版、d = 文書）
_SOURCE_COLUMNS = """
    d.id AS doc_id, d.title AS doc_title, d.doc_type, v.version_label, v.revised_on,
    v.source_url, v.is_current AS version_is_current
"""


# ---------------------------------------------------------------------
# ホーム
# ---------------------------------------------------------------------

def get_home_counts(conn):
    """ホーム画面に表示する件数をまとめて返します。"""
    def count(sql):
        return conn.execute(sql).fetchone()[0]

    # 確認待ち：今の情報のうち「未確認」と「再確認要」のもの（事実のテーブルすべての合計）
    unverified = sum(
        count(f"SELECT COUNT(*) FROM {t} WHERE is_current = 1 AND status = '未確認'") for t in FACT_TABLES
    )
    recheck = sum(
        count(f"SELECT COUNT(*) FROM {t} WHERE is_current = 1 AND status = '再確認要'") for t in FACT_TABLES
    )

    return {
        "products": count("SELECT COUNT(*) FROM products"),
        "diseases": count("SELECT COUNT(*) FROM diseases"),
        "documents": count("SELECT COUNT(*) FROM documents"),
        "unverified": unverified,
        "recheck": recheck,
        # 名前に「（架空）」が付いた企業の数（架空のサンプルデータが入っているかの目印）
        "sample_companies": count("SELECT COUNT(*) FROM companies WHERE name_ja LIKE '%（架空）%'"),
    }


# ---------------------------------------------------------------------
# 製品
# ---------------------------------------------------------------------

def list_products(conn):
    """製品一覧を表（pandas の DataFrame）で返します。確認状態の印付きです。"""
    icon = _STATUS_ICON_SQL.format(col="pc.status")
    fact_icon = _STATUS_ICON_SQL.format(col="f.status")
    sql = f"""
        SELECT
            p.id,
            p.brand_name   AS 販売名,
            p.generic_name AS 一般名,
            p.category     AS 区分,
            (SELECT group_concat({icon} || c.name_ja, '、')
               FROM product_companies pc JOIN companies c ON c.id = pc.company_id
              WHERE pc.product_id = p.id AND pc.role = '製造販売元' AND pc.is_current = 1) AS 製造販売元,
            (SELECT group_concat({icon} || c.name_ja, '、')
               FROM product_companies pc JOIN companies c ON c.id = pc.company_id
              WHERE pc.product_id = p.id AND pc.role = '販売元' AND pc.is_current = 1) AS 販売元,
            (SELECT group_concat({fact_icon} || f.content, '、')
               FROM medical_facts f
              WHERE f.product_id = p.id AND f.fact_type = '薬効分類' AND f.is_current = 1) AS 薬効分類,
            (SELECT group_concat(d.name_ja, '、')
               FROM indications i JOIN diseases d ON d.id = i.disease_id
              WHERE i.product_id = p.id) AS 適応疾患
        FROM products p
        ORDER BY CASE p.category WHEN '対象企業' THEN 0 ELSE 1 END, p.brand_name
    """
    return pd.read_sql_query(sql, conn)


def get_product(conn, product_id):
    """製品の基本情報を1件、辞書で返します。"""
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def get_product_companies(conn, product_id):
    """製品の製造販売元・販売元を、出典付きで返します（content 列に企業名が入ります）。"""
    return fetch_facts(
        conn, "product_companies", "f.product_id = ?", (product_id,),
        extra_columns="c.name_ja AS content",
        extra_join="JOIN companies c ON c.id = f.company_id",
        order="CASE f.role WHEN '製造販売元' THEN 0 ELSE 1 END, f.id",
    )


def get_product_facts(conn, product_id):
    """製品が対象の医学的情報（薬効分類・作用機序など）を、出典付きで返します。"""
    return fetch_facts(conn, "medical_facts", "f.product_id = ?", (product_id,))


def get_product_indications(conn, product_id):
    """製品の適応症（疾患）と、それぞれの効能・効果の文言（出典付き）を返します。"""
    indications = conn.execute("""
        SELECT i.id, d.id AS disease_id, d.name_ja AS disease_name
        FROM indications i JOIN diseases d ON d.id = i.disease_id
        WHERE i.product_id = ? ORDER BY d.name_ja
    """, (product_id,)).fetchall()
    return [
        {**dict(i), "facts": fetch_facts(conn, "medical_facts", "f.indication_id = ?", (i["id"],))}
        for i in indications
    ]


def get_safety_info(conn, product_id):
    """製品の安全性情報を、出典付きで返します。"""
    return fetch_facts(conn, "safety_info", "f.product_id = ?", (product_id,))


# ---------------------------------------------------------------------
# 疾患
# ---------------------------------------------------------------------

def list_diseases(conn):
    """疾患一覧を表（DataFrame）で返します。"""
    sql = """
        SELECT
            d.id,
            d.name_ja AS 疾患名,
            d.name_en AS 英語名,
            (SELECT group_concat(p.brand_name, '、') FROM indications i JOIN products p ON p.id = i.product_id
              WHERE i.disease_id = d.id AND p.category = '対象企業') AS 対象企業の製品,
            (SELECT group_concat(p.brand_name, '、') FROM indications i JOIN products p ON p.id = i.product_id
              WHERE i.disease_id = d.id AND p.category = '競合') AS 競合製品
        FROM diseases d
        ORDER BY d.name_ja
    """
    return pd.read_sql_query(sql, conn)


def get_disease(conn, disease_id):
    """疾患の基本情報を1件、辞書で返します。"""
    row = conn.execute("SELECT * FROM diseases WHERE id = ?", (disease_id,)).fetchone()
    return dict(row) if row else None


def get_disease_facts(conn, disease_id):
    """疾患が対象の医学的情報（疾患概要・診断・治療など）を、出典付きで返します。"""
    return fetch_facts(conn, "medical_facts", "f.disease_id = ?", (disease_id,))


def get_disease_products(conn, disease_id):
    """疾患に適応のある製品と、それぞれの効能・効果の文言（出典付き）を返します。"""
    products = conn.execute("""
        SELECT i.id, p.id AS product_id, p.brand_name, p.generic_name, p.category
        FROM indications i JOIN products p ON p.id = i.product_id
        WHERE i.disease_id = ?
        ORDER BY CASE p.category WHEN '対象企業' THEN 0 ELSE 1 END, p.brand_name
    """, (disease_id,)).fetchall()
    return [
        {**dict(p), "facts": fetch_facts(conn, "medical_facts", "f.indication_id = ?", (p["id"],))}
        for p in products
    ]


# ---------------------------------------------------------------------
# 文書・学習メモ（製品・疾患の共通）
# ---------------------------------------------------------------------

def get_documents(conn, product_id=None, disease_id=None):
    """
    製品または疾患にひも付いた文書と、その版の一覧を返します。
    文書ごとに {"id", "doc_type", "title", "publisher", "versions": DataFrame} の辞書になります。
    """
    column, value = ("product_id", product_id) if product_id else ("disease_id", disease_id)
    documents = conn.execute(f"""
        SELECT d.* FROM documents d JOIN document_links l ON l.document_id = d.id
        WHERE l.{column} = ? ORDER BY d.doc_type, d.title
    """, (value,)).fetchall()

    result = []
    for doc in documents:
        versions = pd.read_sql_query("""
            SELECT
                version_label AS 版,
                CASE is_current WHEN 1 THEN '最新版' ELSE '過去の版' END AS 区分,
                coalesce(revised_on, '記載なし') AS 改訂年月,
                retrieved_on AS 入手日,
                coalesce(confirmed_on, '—') AS 確認日,
                CASE status WHEN '原文確認済み' THEN '✅ ' WHEN '再確認要' THEN '🔁 ' ELSE '⚠️ ' END
                    || status AS 確認状態,
                source_url AS 原文URL
            FROM document_versions WHERE document_id = ?
            ORDER BY is_current DESC, revised_on DESC
        """, conn, params=(doc["id"],))
        result.append({**dict(doc), "versions": versions})
    return result


def get_notes(conn, product_id=None, disease_id=None):
    """製品または疾患の学習メモ・考察を返します（事実ではないデータです）。"""
    column, value = ("product_id", product_id) if product_id else ("disease_id", disease_id)
    rows = conn.execute(
        f"SELECT * FROM notes WHERE {column} = ? ORDER BY note_type, updated_at DESC", (value,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------
# 補助関数
# ---------------------------------------------------------------------

def fetch_facts(conn, table, where, params, extra_columns=None, extra_join="", order="f.id"):
    """
    事実のテーブルから「今の情報」を、出典（文書名・版・URL）と一緒に取り出し、辞書のリストで返します。
    where・order などはこのファイルの中で決めた文字だけを渡します（利用者の入力は params で渡す）。
    """
    columns = f"f.*, {_SOURCE_COLUMNS}" + (f", {extra_columns}" if extra_columns else "")
    rows = conn.execute(f"""
        SELECT {columns}
        FROM {table} f
        JOIN document_versions v ON v.id = f.source_version_id
        JOIN documents d ON d.id = v.document_id
        {extra_join}
        WHERE f.is_current = 1 AND {where}
        ORDER BY {order}
    """, params).fetchall()
    return [dict(r) for r in rows]

"""
queries.py：画面に表示するためのデータを、データベースから取り出す処理をまとめたファイルです。

画面（pages/ のファイル）からは SQL を直接書かずに、このファイルの関数を呼び出します。
事実（医学的情報など）は、必ず「今の情報」（is_current = 1）だけを、出典と一緒に取り出します。
"""

import pandas as pd

from db.database import FACT_TABLES, TABLE_LABELS

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
# 確認・更新管理
# ---------------------------------------------------------------------

# 事実のテーブルごとに、「対象（製品名・疾患名）」「項目」「内容」を取り出すための追加のSQL
FACT_SUBJECTS = {
    "medical_facts": dict(
        extra_columns="""
            coalesce(sp.brand_name, sd.name_ja, ip.brand_name || ' × ' || idis.name_ja) AS subject,
            f.fact_type AS item
        """,
        extra_join="""
            LEFT JOIN products sp    ON sp.id = f.product_id
            LEFT JOIN diseases sd    ON sd.id = f.disease_id
            LEFT JOIN indications si ON si.id = f.indication_id
            LEFT JOIN products ip    ON ip.id = si.product_id
            LEFT JOIN diseases idis  ON idis.id = si.disease_id
        """,
    ),
    "safety_info": dict(
        extra_columns="sp.brand_name AS subject, f.category AS item",
        extra_join="JOIN products sp ON sp.id = f.product_id",
    ),
    "product_companies": dict(
        extra_columns="sp.brand_name AS subject, f.role AS item, c.name_ja AS content",
        extra_join="JOIN products sp ON sp.id = f.product_id JOIN companies c ON c.id = f.company_id",
    ),
    # ---- 承認・再審査・特許・ライセンス・PMS（対象は製品。適応症が指定されていれば疾患名も付ける）----
    "approvals": dict(
        extra_columns="""
            sp.brand_name || coalesce(' × ' || idis.name_ja, '') AS subject,
            '承認（' || f.approval_type || '）' AS item
        """,
        extra_join="""
            JOIN products sp ON sp.id = f.product_id
            LEFT JOIN indications si ON si.id = f.indication_id
            LEFT JOIN diseases idis ON idis.id = si.disease_id
        """,
    ),
    "reexaminations": dict(
        extra_columns="sp.brand_name || coalesce(' × ' || idis.name_ja, '') AS subject, '再審査期間' AS item",
        extra_join="""
            JOIN products sp ON sp.id = f.product_id
            LEFT JOIN indications si ON si.id = f.indication_id
            LEFT JOIN diseases idis ON idis.id = si.disease_id
        """,
    ),
    "patents": dict(
        extra_columns="""
            sp.brand_name AS subject, '特許（' || f.patent_kind || '）' AS item,
            f.patent_number || '（' || f.country || '）' || coalesce(' ' || f.title, '') AS content
        """,
        extra_join="JOIN products sp ON sp.id = f.product_id",
    ),
    "licenses": dict(
        extra_columns="sp.brand_name AS subject, f.role || '：' || pc.name_ja AS item",
        extra_join="JOIN products sp ON sp.id = f.product_id JOIN companies pc ON pc.id = f.partner_company_id",
    ),
    "pms_studies": dict(
        extra_columns="""
            sp.brand_name || coalesce(' × ' || idis.name_ja, '') AS subject,
            'PMS（' || f.study_type || '）' AS item, f.title AS content
        """,
        extra_join="""
            JOIN products sp ON sp.id = f.product_id
            LEFT JOIN indications si ON si.id = f.indication_id
            LEFT JOIN diseases idis ON idis.id = si.disease_id
        """,
    ),
    # ---- 臨床試験（Step 10）。対象は「研究ID（TR-0001 の形）」----
    "trial_details": dict(
        extra_columns="'TR-' || printf('%04d', f.trial_id) AS subject, '試験の内容（' || f.phase || '）' AS item, "
                      "f.title AS content",
        extra_join="",
    ),
    "trial_registrations": dict(
        extra_columns="'TR-' || printf('%04d', f.trial_id) AS subject, '登録番号（' || f.registry || '）' AS item, "
                      "f.registration_no AS content",
        extra_join="",
    ),
}


REGULATORY_TABLES = ["approvals", "reexaminations", "patents", "licenses", "pms_studies"]


def get_product_regulatory(conn, product_id):
    """
    製品の承認・再審査・特許・ライセンス・PMS を、出典付きで返します。
    {"approvals": [...], "reexaminations": [...], ...} の形で、承認は承認年月日の順に並べます。
    """
    result = {t: fetch_facts(conn, t, "f.product_id = ?", (product_id,), **FACT_SUBJECTS[t])
              for t in REGULATORY_TABLES}
    result["approvals"].sort(key=lambda a: a["approval_date"])
    return result


def list_review_facts(conn, statuses):
    """
    指定した確認状態の「今の情報」を、すべての事実のテーブルから集めて返します。
    1件ごとに table（テーブル名）と table_label（日本語名）が付いた辞書のリストです。
    再確認要 → 未確認 → 原文確認済み の順に並べます。
    """
    if not statuses:
        return []
    placeholders = ", ".join("?" * len(statuses))
    facts = []
    for table in FACT_TABLES:
        for fact in fetch_facts(conn, table, f"f.status IN ({placeholders})", list(statuses),
                                **FACT_SUBJECTS[table]):
            facts.append({**fact, "table": table, "table_label": TABLE_LABELS[table]})
    order = {"再確認要": 0, "未確認": 1, "原文確認済み": 2}
    return sorted(facts, key=lambda f: (order[f["status"]], f["table_label"], f["subject"], f["id"]))


def get_fact_detail(conn, table, fact_id):
    """事実を1件、出典・対象・項目つきで返します（今の情報だけ）。"""
    rows = fetch_facts(conn, table, "f.id = ?", (fact_id,), **FACT_SUBJECTS[table])
    return {**rows[0], "table": table, "table_label": TABLE_LABELS[table]} if rows else None


def get_version_choices(conn, fact):
    """
    事実の出典として選べる「文書の版」の一覧を返します：[(版のID, 表示名), ...]
    対象の製品・疾患にひも付いた文書の版と、今の出典の版を並べます。
    """
    product_ids, disease_ids = set(), set()
    if fact.get("product_id"):
        product_ids.add(fact["product_id"])
    if fact.get("disease_id"):
        disease_ids.add(fact["disease_id"])
    if fact.get("indication_id"):
        row = conn.execute("SELECT product_id, disease_id FROM indications WHERE id = ?",
                           (fact["indication_id"],)).fetchone()
        product_ids.add(row["product_id"])
        disease_ids.add(row["disease_id"])

    p_marks = ", ".join("?" * len(product_ids)) or "NULL"
    d_marks = ", ".join("?" * len(disease_ids)) or "NULL"
    rows = conn.execute(f"""
        SELECT v.id, d.title, v.version_label, v.is_current
        FROM document_versions v JOIN documents d ON d.id = v.document_id
        WHERE v.id = ? OR d.id IN (
            SELECT document_id FROM document_links
            WHERE product_id IN ({p_marks}) OR disease_id IN ({d_marks}))
        ORDER BY d.title, v.is_current DESC, v.revised_on DESC
    """, [fact["source_version_id"], *product_ids, *disease_ids]).fetchall()
    return [(r["id"], f"{r['title']} ／ {r['version_label']}" + ("" if r["is_current"] else "（過去の版）"))
            for r in rows]


def list_companies(conn):
    """企業の一覧を返します：[(企業ID, 企業名), ...]"""
    return [(r["id"], r["name_ja"]) for r in conn.execute("SELECT id, name_ja FROM companies ORDER BY name_ja")]


def list_all_documents(conn):
    """すべての文書を返します：[(文書ID, 表示名), ...]"""
    rows = conn.execute("SELECT id, doc_type, title FROM documents ORDER BY doc_type, title")
    return [(r["id"], f"{r['title']}（{r['doc_type']}）") for r in rows]


def list_all_versions(conn):
    """すべての文書の版を、表（DataFrame）で返します。"""
    return pd.read_sql_query("""
        SELECT v.id AS 版ID, d.title AS 文書, v.version_label AS 版,
               CASE v.is_current WHEN 1 THEN '最新版' ELSE '過去の版' END AS 区分,
               coalesce(v.revised_on, '記載なし') AS 改訂年月, v.retrieved_on AS 入手日,
               coalesce(v.confirmed_on, '—') AS 確認日,
               CASE v.status WHEN '原文確認済み' THEN '✅ ' WHEN '再確認要' THEN '🔁 ' ELSE '⚠️ ' END
                   || v.status AS 確認状態,
               v.source_url AS 原文URL
        FROM document_versions v JOIN documents d ON d.id = v.document_id
        ORDER BY d.title, v.is_current DESC, v.revised_on DESC
    """, conn)


def list_candidates(conn):
    """変更候補の一覧を、表（DataFrame）で返します。未対応・確認中を上に並べます。"""
    return pd.read_sql_query("""
        SELECT c.id AS 候補ID, c.status AS 対応状況, d.title AS 文書, c.description AS 内容,
               c.detected_at AS 検出日時, c.detection_method AS 検出方法,
               coalesce(v.version_label, '—') AS 新しい版,
               coalesce(c.resolved_by, '—') AS 対応者, coalesce(c.resolved_at, '—') AS 対応日時
        FROM change_candidates c
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN document_versions v ON v.id = c.new_version_id
        ORDER BY CASE c.status WHEN '未対応' THEN 0 WHEN '確認中' THEN 1 ELSE 2 END, c.detected_at DESC
    """, conn)


def list_change_log(conn, table=None, limit=200):
    """更新履歴を新しい順に、表（DataFrame）で返します。table を渡すとそのテーブルだけにしぼります。"""
    where, params = ("WHERE table_name = ?", [table]) if table else ("", [])
    log = pd.read_sql_query(f"""
        SELECT id AS 履歴ID, changed_at AS 日時, changed_by AS 確認者, action AS 操作,
               table_name AS 対象, record_id AS 対象ID, reason AS 理由
        FROM change_log {where}
        ORDER BY id DESC LIMIT {int(limit)}
    """, conn, params=params)
    log["対象"] = log["対象"].map(lambda t: TABLE_LABELS.get(t, t))
    return log


def get_change_log_entry(conn, log_id):
    """更新履歴を1件、辞書で返します。"""
    row = conn.execute("SELECT * FROM change_log WHERE id = ?", (log_id,)).fetchone()
    return dict(row) if row else None


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

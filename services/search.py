"""
search.py：横断検索（1つのキーワードで、製品・疾患・文書・医学的情報をまとめて探す）の処理です。

- search_all()：キーワードで検索し、種類ごとの結果をまとめて返す

キーワードを空白で区切ると、「すべての語を含むもの」だけを探します（AND検索）。
事実（医学的情報・安全性情報）は「今の情報」だけを、出典と一緒に返します。
"""

from db.queries import fetch_facts

# 1つの種類あたりに表示する最大件数（多すぎると画面が見にくくなるため）
LIMIT = 50


def search_all(conn, keyword):
    """
    キーワードで横断検索し、次の形の辞書を返します。
    {"products": [...], "diseases": [...], "documents": [...], "facts": [...], "safety": [...]}
    """
    terms = keyword.split()  # 空白（全角・半角）で区切る
    if not terms:
        return {"products": [], "diseases": [], "documents": [], "facts": [], "safety": []}

    # ---- 製品（販売名・一般名・製造販売元/販売元の企業名）----
    where, params = _like_all(terms, [
        "p.brand_name", "p.generic_name",
        "(SELECT group_concat(c.name_ja || ' ' || coalesce(c.name_en, ''), ' ') "
        "   FROM product_companies pc JOIN companies c ON c.id = pc.company_id "
        "  WHERE pc.product_id = p.id AND pc.is_current = 1)",
    ])
    products = conn.execute(f"""
        SELECT p.id, p.brand_name, p.generic_name, p.category FROM products p
        WHERE {where} ORDER BY p.brand_name LIMIT {LIMIT}
    """, params).fetchall()

    # ---- 疾患（日本語名・英語名）----
    where, params = _like_all(terms, ["d.name_ja", "d.name_en"])
    diseases = conn.execute(f"""
        SELECT d.id, d.name_ja, d.name_en FROM diseases d
        WHERE {where} ORDER BY d.name_ja LIMIT {LIMIT}
    """, params).fetchall()

    # ---- 文書（タイトル・発行元・識別番号）と、ひも付いた製品・疾患 ----
    where, params = _like_all(terms, ["d.title", "d.publisher", "d.external_id"])
    documents = conn.execute(f"""
        SELECT d.id, d.doc_type, d.title, d.publisher,
               (SELECT l.product_id FROM document_links l WHERE l.document_id = d.id
                 AND l.product_id IS NOT NULL ORDER BY l.id LIMIT 1) AS product_id,
               (SELECT l.disease_id FROM document_links l WHERE l.document_id = d.id
                 AND l.disease_id IS NOT NULL ORDER BY l.id LIMIT 1) AS disease_id
        FROM documents d
        WHERE {where} ORDER BY d.doc_type, d.title LIMIT {LIMIT}
    """, params).fetchall()

    # ---- 医学的情報（内容）。対象が製品・疾患・適応症のどれでも、製品名・疾患名がわかるようにする ----
    where, params = _like_all(terms, ["f.content"])
    facts = fetch_facts(
        conn, "medical_facts", where, params,
        extra_columns="""
            coalesce(sp.brand_name, ip.brand_name) AS subject_product,
            coalesce(sp.id, ip.id)                 AS subject_product_id,
            coalesce(sd.name_ja, idis.name_ja)     AS subject_disease,
            coalesce(sd.id, idis.id)               AS subject_disease_id
        """,
        extra_join="""
            LEFT JOIN products sp     ON sp.id = f.product_id
            LEFT JOIN diseases sd     ON sd.id = f.disease_id
            LEFT JOIN indications si  ON si.id = f.indication_id
            LEFT JOIN products ip     ON ip.id = si.product_id
            LEFT JOIN diseases idis   ON idis.id = si.disease_id
        """,
        order=f"f.id LIMIT {LIMIT}",
    )

    # ---- 安全性情報（内容）----
    where, params = _like_all(terms, ["f.content"])
    safety = fetch_facts(
        conn, "safety_info", where, params,
        extra_columns="sp.brand_name AS subject_product, sp.id AS subject_product_id",
        extra_join="JOIN products sp ON sp.id = f.product_id",
        order=f"f.id LIMIT {LIMIT}",
    )

    return {
        "products": [dict(r) for r in products],
        "diseases": [dict(r) for r in diseases],
        "documents": [dict(r) for r in documents],
        "facts": facts,
        "safety": safety,
    }


def _like_all(terms, columns):
    """
    「すべての語が、どれかの列に含まれる」という条件のSQLと、そこに入れる値を作ります。
    例：語が2つ、列が2つなら
        (列1 LIKE ? OR 列2 LIKE ?) AND (列1 LIKE ? OR 列2 LIKE ?)
    """
    clauses, params = [], []
    for term in terms:
        pattern = f"%{_escape_like(term)}%"  # %…%：前後に何があってもよい（部分一致）
        clauses.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columns) + ")")
        params.extend([pattern] * len(columns))
    return " AND ".join(clauses), params


def _escape_like(term):
    """
    検索語に含まれる % と _ を、ふつうの文字として扱うようにします。
    （LIKE では % は「何文字でもよい」、_ は「1文字なら何でもよい」という特別な意味を持つため）
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

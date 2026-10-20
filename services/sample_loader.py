"""
sample_loader.py：data/samples/ にある架空データのCSVを、データベースに登録する処理です。

- load_sample_data()         ：架空データをすべて登録する
- load_sample_data_if_empty()：データベースが空のときだけ登録する（アプリ起動時に使う）

登録は「全部成功するか、全部なかったことにするか」の1つのトランザクションで行います。
医学的情報などの事実は db/changes.py を通して登録するので、出典・更新履歴のルールがすべて働きます。

※ CSVの内容を細かく検証して日本語でエラーを表示する本格的な機能は、Step 8 で作ります。
"""

from pathlib import Path

import pandas as pd

from db.changes import add_record, set_status, transaction
from db.database import ROOT
from services.trials import add_trial_entry

SAMPLES_DIR = ROOT / "data" / "samples"

# 更新履歴に記録する「確認者」と「理由」
CHANGED_BY = "サンプルデータ（架空）"
REASON = "架空サンプルデータの登録"


def load_sample_data_if_empty(conn, samples_dir=None):
    """製品が1件もないときだけ架空データを登録します。登録したら True を返します。"""
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
        return False
    load_sample_data(conn, samples_dir)
    return True


def load_sample_data(conn, samples_dir=None):
    """架空データをすべて登録します。途中でエラーが起きたら、すべて取り消します。"""
    folder = Path(samples_dir or SAMPLES_DIR)

    with transaction(conn):
        # ---- 基本：企業・製品・疾患・適応症 ----
        for row in _read(folder, "companies.csv"):
            conn.execute(
                "INSERT INTO companies (name_ja, name_en, is_target) VALUES (?, ?, ?)",
                (row["name_ja"], row["name_en"], int(row["is_target"])),
            )
        for row in _read(folder, "products.csv"):
            conn.execute(
                "INSERT INTO products (brand_name, generic_name, category, official_url, last_checked_on) "
                "VALUES (?, ?, ?, ?, ?)",
                (row["brand_name"], row["generic_name"], row["category"],
                 row["official_url"], row["last_checked_on"]),
            )
        for row in _read(folder, "diseases.csv"):
            conn.execute("INSERT INTO diseases (name_ja, name_en) VALUES (?, ?)",
                         (row["name_ja"], row["name_en"]))
        for row in _read(folder, "indications.csv"):
            conn.execute(
                "INSERT INTO indications (product_id, disease_id) VALUES (?, ?)",
                (_product_id(conn, row["brand_name"]), _disease_id(conn, row["disease_name"])),
            )

        # ---- 出典：文書・版・文書と製品/疾患の対応 ----
        for row in _read(folder, "documents.csv"):
            conn.execute(
                "INSERT INTO documents (doc_type, title, publisher, external_id) VALUES (?, ?, ?, ?)",
                (row["doc_type"], row["title"], row["publisher"], row["external_id"]),
            )
        # 版は CSV の上から順に登録する（古い版 → 新しい版の順に書いておく）
        for row in _read(folder, "document_versions.csv"):
            conn.execute(
                "INSERT INTO document_versions (document_id, version_label, revised_on, retrieved_on, "
                "confirmed_on, source_url, is_current, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_document_id(conn, row["document_title"]), row["version_label"], row["revised_on"],
                 row["retrieved_on"], row["confirmed_on"], row["source_url"],
                 int(row["is_current"]), row["status"]),
            )
        for row in _read(folder, "document_links.csv"):
            conn.execute(
                "INSERT INTO document_links (document_id, product_id, disease_id) VALUES (?, ?, ?)",
                (_document_id(conn, row["document_title"]),
                 _product_id(conn, row["brand_name"]) if row["brand_name"] else None,
                 _disease_id(conn, row["disease_name"]) if row["disease_name"] else None),
            )

        # ---- 事実：製造販売元・販売元、医学的情報、安全性情報 ----
        for row in _read(folder, "product_companies.csv"):
            _add_fact(conn, "product_companies", row, {
                "product_id": _product_id(conn, row["brand_name"]),
                "company_id": _company_id(conn, row["company_name"]),
                "role": row["role"],
            })
        for row in _read(folder, "medical_facts.csv"):
            _add_fact(conn, "medical_facts", row, {
                **_fact_subject(conn, row),
                "fact_type": row["fact_type"],
                "subcategory": row["subcategory"],
                "content": row["content"],
            })
        for row in _read(folder, "safety_info.csv"):
            _add_fact(conn, "safety_info", row, {
                "product_id": _product_id(conn, row["brand_name"]),
                "category": row["category"],
                "content": row["content"],
            })

        # ---- 事実：承認・再審査・特許・ライセンス・PMS（設計図バージョン2で追加）----
        for row in _read(folder, "approvals.csv"):
            _add_fact(conn, "approvals", row, {
                "product_id": _product_id(conn, row["brand_name"]),
                "indication_id": _optional_indication_id(conn, row),
                **{k: row[k] for k in ("approval_type", "approval_date", "approval_number", "content")},
            })
        for row in _read(folder, "reexaminations.csv"):
            _add_fact(conn, "reexaminations", row, {
                "product_id": _product_id(conn, row["brand_name"]),
                "indication_id": _optional_indication_id(conn, row),
                "period_years": int(row["period_years"]) if row["period_years"] else None,
                **{k: row[k] for k in ("content", "disclosure", "start_date", "end_date")},
            })
        for row in _read(folder, "patents.csv"):
            _add_fact(conn, "patents", row, {
                "product_id": _product_id(conn, row["brand_name"]),
                **{k: row[k] for k in ("patent_number", "country", "patent_kind", "title", "disclosure",
                                       "expiry_date", "extended_expiry_date")},
            })
        for row in _read(folder, "licenses.csv"):
            _add_fact(conn, "licenses", row, {
                "product_id": _product_id(conn, row["brand_name"]),
                "partner_company_id": _company_id(conn, row["partner_company"]),
                **{k: row[k] for k in ("role", "license_type", "territory", "content", "disclosure",
                                       "contract_start", "contract_end", "disclosed_fiscal_year")},
            })
        # ---- 臨床試験（設計図バージョン3で追加）。1行 = 1つの登録番号 ----
        for row in _read(folder, "trials.csv"):
            ids = add_trial_entry(conn, row, "CSV", CHANGED_BY, REASON)
            status = row["status"] or "未確認"
            if status != "未確認":
                for table, record_id in (("trial_details", ids["detail_id"]),
                                         ("trial_registrations", ids["registration_id"])):
                    if record_id:
                        set_status(conn, table, record_id, status, CHANGED_BY, "架空サンプルデータの確認状態を設定")

        for row in _read(folder, "pms_studies.csv"):
            _add_fact(conn, "pms_studies", row, {
                "product_id": _product_id(conn, row["brand_name"]),
                "indication_id": _optional_indication_id(conn, row),
                **{k: row[k] for k in ("study_type", "title", "all_case", "approval_condition", "progress",
                                       "target_cases", "disclosure", "start_date", "end_date", "registration_no")},
            })


# ---- ここから下は、このファイルの中だけで使う補助関数 ----

def _read(folder, file_name):
    """CSVを読み込み、1行ずつ辞書（列名: 値）にしたリストを返します。空欄は None になります。"""
    # dtype=str：すべて文字列として読む（「0001」が「1」に変わるのを防ぐ）
    # keep_default_na=False：「NA」などの文字を勝手に欠損値にしない
    # encoding="utf-8-sig"：Excelで保存したCSV（先頭に目印の文字が付く）も読めるようにする
    table = pd.read_csv(folder / file_name, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return [
        {column: (value.strip() or None) for column, value in row.items()}
        for row in table.to_dict(orient="records")
    ]


def _add_fact(conn, table, row, values):
    """事実を1件登録し、CSVで指定された確認状態にします。"""
    values.update({
        "source_version_id": _version_id(conn, row["document_title"], row["version_label"]),
        "source_location": row["source_location"],
        "entry_method": "CSV",
    })
    record_id = add_record(conn, table, values, CHANGED_BY, REASON)
    # 登録直後は必ず「未確認」。CSVで別の状態が指定されていれば、確認の記録として状態を変える
    status = row["status"] or "未確認"
    if status != "未確認":
        set_status(conn, table, record_id, status, CHANGED_BY, "架空サンプルデータの確認状態を設定")


def _fact_subject(conn, row):
    """医学的情報の対象（製品・疾患・適応症のどれか）のIDを、target_type 列に合わせて返します。"""
    target_type = row["target_type"]
    if target_type == "製品":
        return {"product_id": _product_id(conn, row["brand_name"])}
    if target_type == "疾患":
        return {"disease_id": _disease_id(conn, row["disease_name"])}
    if target_type == "適応症":
        indication = conn.execute(
            "SELECT id FROM indications WHERE product_id = ? AND disease_id = ?",
            (_product_id(conn, row["brand_name"]), _disease_id(conn, row["disease_name"])),
        ).fetchone()
        if indication is None:
            raise ValueError(f"適応症が見つかりません：{row['brand_name']} × {row['disease_name']}")
        return {"indication_id": indication[0]}
    raise ValueError(f"target_type は 製品 / 疾患 / 適応症 のどれかにしてください：{target_type}")


def _optional_indication_id(conn, row):
    """disease_name 列が空なら None、入っていれば「販売名 × 疾患名」の適応症のIDを返します。"""
    if not row["disease_name"]:
        return None
    return _find_id(
        conn, "SELECT id FROM indications WHERE product_id = ? AND disease_id = ?",
        (_product_id(conn, row["brand_name"]), _disease_id(conn, row["disease_name"])), "適応症",
    )


def _find_id(conn, sql, params, label):
    """名前からIDを探します。見つからなければ、何が見つからないかを日本語で知らせます。"""
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise ValueError(f"{label}が見つかりません：{' / '.join(str(p) for p in params)}")
    return row[0]


def _product_id(conn, brand_name):
    return _find_id(conn, "SELECT id FROM products WHERE brand_name = ?", (brand_name,), "製品")


def _disease_id(conn, disease_name):
    return _find_id(conn, "SELECT id FROM diseases WHERE name_ja = ?", (disease_name,), "疾患")


def _company_id(conn, company_name):
    return _find_id(conn, "SELECT id FROM companies WHERE name_ja = ?", (company_name,), "企業")


def _document_id(conn, title):
    return _find_id(conn, "SELECT id FROM documents WHERE title = ?", (title,), "文書")


def _version_id(conn, title, version_label):
    return _find_id(
        conn,
        "SELECT v.id FROM document_versions v JOIN documents d ON d.id = v.document_id "
        "WHERE d.title = ? AND v.version_label = ?",
        (title, version_label),
        "文書の版",
    )

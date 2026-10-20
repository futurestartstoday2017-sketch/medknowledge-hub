"""
test_pms_month.py：PMSの実施期間に年月（YYYY-MM）を入れられるようにした変更（設計図バージョン4）のテストです。
"""

import sqlite3

import pytest

import db.database
from db.changes import add_record, supersede_record
from db.database import SCHEMA_VERSION, get_connection, init_db
from services.csv_importer import KINDS, import_rows, read_csv, validate
from services.sample_loader import load_sample_data
from tests.test_step9_regulatory import insert, pms

PMS_HEADER = ",".join(h for h, _, _ in KINDS["pms_studies"]["columns"])
SOURCE = "サンプル製薬 決算説明資料（架空）,2024年度 決算説明資料,（架空）p.14"  # サンプリンα錠にひも付いた出典


# ---- 新しいDBのルール ----

@pytest.mark.parametrize("start, end", [
    ("2019-08", "2023-07"),        # 年月だけ
    ("2022-11-01", "2026-04-30"),  # 年月日
    ("2019-08", "2023-07-31"),     # 混在
])
def test_month_or_date_is_accepted(conn, base, start, end):
    """実施期間に YYYY-MM と YYYY-MM-DD のどちらも入れられることを確認します。"""
    insert(conn, "pms_studies", pms(base, start_date=start, end_date=end))


@pytest.mark.parametrize("start, end", [
    ("2019-13", None),         # 13月はない
    ("2019-00", None),         # 0月はない
    ("2019-8", None),          # 0埋めしていない
    ("2019年8月", None),        # 日本語の書き方
    ("2023-07", "2019-08"),    # 終了が開始より前
])
def test_wrong_month_is_rejected(conn, base, start, end):
    """形の正しくない年月や、前後が逆の期間は、DBのルールで止まることを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "pms_studies", pms(base, start_date=start, end_date=end))


def test_protection_triggers_still_work(conn, base):
    """作り直したPMSのテーブルでも、削除禁止・書き換え禁止・適応症のチェックが働くことを確認します。"""
    pms_id = insert(conn, "pms_studies", pms(base, start_date="2019-08"))
    with pytest.raises(sqlite3.IntegrityError, match="削除できません"):
        with conn:
            conn.execute("DELETE FROM pms_studies WHERE id = ?", (pms_id,))
    with pytest.raises(sqlite3.IntegrityError, match="書き換えできません"):
        with conn:
            conn.execute("UPDATE pms_studies SET title = '別名' WHERE id = ?", (pms_id,))
    with conn:
        other = conn.execute("INSERT INTO products (brand_name, category) VALUES ('別の錠', '競合')").lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="別の製品のもの"):
        insert(conn, "pms_studies", pms(base, product_id=other, indication_id=base["indication"], title="別"))


# ---- マイグレーション（バージョン3 → 4） ----

def test_migration_from_version_3_keeps_pms_data(tmp_path, monkeypatch, base):
    """
    バージョン3のDBに入っていたPMS（旧版と置き換え先のつながりを含む）が、
    IDも内容もそのままバージョン4に移り、守るためのトリガーも付いていることを確認します。
    """
    path = tmp_path / "v3.db"
    monkeypatch.setattr(db.database, "SCHEMA_VERSION", 3)
    init_db(path)
    old = get_connection(path)
    # 土台のデータ（base フィクスチャと同じもの）を v3 のDBにも作る
    with old:
        product = old.execute("INSERT INTO products (brand_name, category) VALUES ('旧PMS錠', '対象企業')").lastrowid
        document = old.execute("INSERT INTO documents (doc_type, title) VALUES ('添付文書', '旧PMS錠 添付文書')").lastrowid
        version = old.execute("INSERT INTO document_versions (document_id, version_label, retrieved_on, source_url) "
                              "VALUES (?, '第1版', '2025-05-01', 'https://example.com/old')", (document,)).lastrowid
        old.execute("INSERT INTO document_links (document_id, product_id) VALUES (?, ?)", (document, product))
    first = add_record(old, "pms_studies", {
        "product_id": product, "study_type": "一般使用成績調査", "title": "（架空）旧調査", "disclosure": "公開",
        "start_date": "2020-04-01", "source_version_id": version, "source_location": "（架空）p.1"}, "山田", "テスト")
    second = supersede_record(old, "pms_studies", first, {"progress": "終了"}, "山田", "テスト")
    before = [dict(r) for r in old.execute("SELECT * FROM pms_studies ORDER BY id")]
    old.close()

    monkeypatch.setattr(db.database, "SCHEMA_VERSION", SCHEMA_VERSION)
    init_db(path)
    new = get_connection(path)
    assert new.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION >= 4
    assert [dict(r) for r in new.execute("SELECT * FROM pms_studies ORDER BY id")] == before
    assert new.execute("SELECT superseded_by FROM pms_studies WHERE id = ?", (first,)).fetchone()[0] == second
    assert new.execute("PRAGMA foreign_key_check").fetchall() == []
    names = {r[0] for r in new.execute("SELECT name FROM sqlite_master WHERE tbl_name = 'pms_studies'")}
    assert {"pms_studies_no_delete", "pms_studies_no_edit", "pms_studies_machine_unverified",
            "pms_studies_no_revive", "pms_studies_superseded_once", "pms_studies_indication_matches",
            "ux_pms_studies"} <= names
    assert not new.execute("SELECT 1 FROM sqlite_master WHERE name = 'pms_studies_old'").fetchone()
    # 年月も入れられるようになっている
    add_record(new, "pms_studies", {
        "product_id": product, "study_type": "特定使用成績調査", "title": "（架空）年月の調査", "disclosure": "公開",
        "start_date": "2019-08", "end_date": "2023-07", "source_version_id": version,
        "source_location": "（架空）p.2"}, "山田", "テスト")
    new.close()


# ---- CSVの取り込み ----

def test_csv_with_month_period(conn):
    """PMSのCSVで、実施期間を YYYY-MM で書いて取り込めることを確認します。"""
    load_sample_data(conn)
    csv = (f"{PMS_HEADER}\nサンプリンα錠,,一般使用成績調査,（架空）年月の調査,全例調査ではない,承認条件ではない,"
           f"終了,1200例,公開,2019-08,2023-07,,{SOURCE}\n")
    table = read_csv(csv.encode("utf-8"))
    assert validate(conn, "pms_studies", table) == []
    import_rows(conn, "pms_studies", table, "山田", "年月の取り込み", entry_method="AI抽出")
    row = conn.execute("SELECT start_date, end_date FROM pms_studies WHERE title = '（架空）年月の調査'").fetchone()
    assert tuple(row) == ("2019-08", "2023-07")


def test_csv_rejects_japanese_month(conn):
    """「2019年8月」のような書き方は、取り込み前の検証で日本語の説明つきで止まることを確認します。"""
    load_sample_data(conn)
    csv = (f"{PMS_HEADER}\nサンプリンα錠,,一般使用成績調査,（架空）調査,,,,,公開,2019年8月,,,{SOURCE}\n")
    errors = validate(conn, "pms_studies", read_csv(csv.encode("utf-8")))
    assert errors and "YYYY-MM" in errors[0]

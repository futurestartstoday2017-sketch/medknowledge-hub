"""
test_step3_schema.py：Step 3（テーブル作成）の基本と、出典・確認状態・重複のルールのテストです。

pytest.raises(sqlite3.IntegrityError)：
「この処理はDBのルール違反でエラーになるはず」ということを確かめる書き方です。
"""

import sqlite3

import pytest

from db.database import FACT_TABLES, SCHEMA_VERSION, get_connection, init_db
from tests.conftest import fact_values


def insert(conn, table, values):
    """テスト用：1行を直接追加します（ルール違反のデータを入れてみるため）。"""
    columns = ", ".join(values)
    placeholders = ", ".join("?" * len(values))
    with conn:
        return conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(values.values())
        ).lastrowid


# ---- 基本 ----

def test_all_tables_are_created(conn):
    """設計どおりのテーブルがそろっているか確認します。"""
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    expected = {
        "companies", "products", "product_companies", "diseases", "indications",
        "documents", "document_versions", "document_links",
        "medical_facts", "safety_info", "notes", "change_candidates", "change_log", "app_settings",
    }
    assert expected <= tables


def test_foreign_keys_are_enabled(conn):
    """外部キーのチェックが有効になっているか確認します。"""
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_foreign_key_rejects_unknown_id(conn):
    """存在しない製品IDを使った適応症は登録できないことを確認します。"""
    disease_id = insert(conn, "diseases", {"name_ja": "架空疾患Y"})
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "indications", {"product_id": 9999, "disease_id": disease_id})


def test_init_db_can_run_twice(db_path):
    """init_db を2回実行しても、エラーにならず設計図のバージョンが保たれることを確認します。"""
    init_db(db_path)
    conn = get_connection(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


# ---- 出典の欠落 ----

@pytest.mark.parametrize("missing", ["source_version_id", "source_location"])
def test_fact_without_source_is_rejected(conn, base, missing):
    """出典の版・該当箇所がない医学的情報は登録できないことを確認します。"""
    values = fact_values(base)
    del values[missing]
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", values)


def test_fact_with_blank_location_is_rejected(conn, base):
    """該当箇所が空白だけの医学的情報は登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", fact_values(base, source_location="   "))


def test_safety_info_without_source_is_rejected(conn, base):
    """出典のない安全性情報は登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "safety_info", {
            "product_id": base["product"], "category": "禁忌", "content": "（架空）架空成分に過敏症の患者",
        })


def test_fact_must_have_exactly_one_subject(conn, base):
    """医学的情報の対象（製品・疾患・適応症）が0個や2個だと登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", fact_values(base, product_id=None))
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", fact_values(base, disease_id=base["disease"]))


# ---- 確認状態 ----

def test_new_fact_starts_unverified(conn, base):
    """何も指定しなければ「未確認」で登録されることを確認します。"""
    fact_id = insert(conn, "medical_facts", fact_values(base))
    status = conn.execute("SELECT status FROM medical_facts WHERE id = ?", (fact_id,)).fetchone()[0]
    assert status == "未確認"


def test_verified_requires_reviewer(conn, base):
    """確認者・確認日時なしで「原文確認済み」にはできないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", fact_values(base, status="原文確認済み"))


@pytest.mark.parametrize("method", ["API", "AI抽出"])
def test_machine_entries_must_start_unverified(conn, base, method):
    """API・AIで取得した情報は、確認者がいても「原文確認済み」では登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", fact_values(
            base, entry_method=method, status="原文確認済み",
            verified_by="確認者", verified_at="2025-05-01 10:00:00",
        ))


def test_unknown_status_is_rejected(conn, base):
    """決められた3つ以外の確認状態は使えないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", fact_values(base, status="たぶん正しい"))


def test_verified_document_version_requires_confirmed_date(conn, base):
    """文書の版を「原文確認済み」にするには、確認日が必要なことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "document_versions", {
            "document_id": base["document"], "version_label": "第2版", "revised_on": "2025-10",
            "retrieved_on": "2025-10-01", "source_url": "https://example.com/v2",
            "status": "原文確認済み", "is_current": 0,
        })


# ---- 重複登録 ----

def test_duplicate_brand_name_is_rejected(conn, base):
    """同じ販売名の製品は二重に登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "products", {"brand_name": "テストール錠", "category": "競合"})


def test_duplicate_indication_is_rejected(conn, base):
    """同じ製品と疾患の組み合わせは二重に登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "indications", {"product_id": base["product"], "disease_id": base["disease"]})


def test_duplicate_current_fact_is_rejected(conn, base):
    """同じ対象・種類・内容の「今の情報」は二重に登録できないことを確認します。"""
    insert(conn, "medical_facts", fact_values(base))
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", fact_values(base, source_location="別の箇所"))


def test_duplicate_disease_fact_is_rejected(conn, base):
    """疾患が対象の情報でも、重複が防がれることを確認します（空欄を含む組み合わせの確認）。"""
    values = fact_values(base, product_id=None, disease_id=base["disease"], fact_type="疾患概要")
    insert(conn, "medical_facts", values)
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "medical_facts", values)


def test_duplicate_document_external_id_is_rejected(conn):
    """同じ種類・同じ識別番号（PMIDなど）の文書は二重に登録できないことを確認します。"""
    insert(conn, "documents", {"doc_type": "論文", "title": "架空論文A", "external_id": "00000001"})
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "documents", {"doc_type": "論文", "title": "架空論文A（重複）", "external_id": "00000001"})


def test_only_one_target_company(conn, base):
    """対象企業は1社しか登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "companies", {"name_ja": "別のテスト製薬", "is_target": 1})


def test_every_fact_table_has_source_columns(conn):
    """【出典セット】を持つはずのテーブルに、必要な列がすべてあるか確認します。"""
    required = {"source_version_id", "source_location", "status", "verified_by", "verified_at",
                "entry_method", "is_current", "superseded_by"}
    for table in FACT_TABLES:
        columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert required <= columns, f"{table} に出典セットの列が足りません"

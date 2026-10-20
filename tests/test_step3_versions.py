"""
test_step3_versions.py：文書の版の管理と、版の不整合を見つける品質チェックのテストです。
"""

import sqlite3

import pytest

from db.changes import add_record, set_status
from db.quality import find_quality_problems
from tests.conftest import fact_values


def add_version(conn, document_id, label, revised_on, is_current=1):
    """テスト用：文書の版を1つ追加します。"""
    with conn:
        return conn.execute(
            "INSERT INTO document_versions (document_id, version_label, revised_on, retrieved_on, source_url, is_current) "
            "VALUES (?, ?, ?, '2025-11-01', 'https://example.com/test/new', ?)",
            (document_id, label, revised_on, is_current),
        ).lastrowid


def make_current(conn, document_id, new_version_id):
    """テスト用：新しい版を最新版にします（古い版の印を先に外す）。"""
    with conn:
        conn.execute("UPDATE document_versions SET is_current = 0 WHERE document_id = ?", (document_id,))
        conn.execute("UPDATE document_versions SET is_current = 1 WHERE id = ?", (new_version_id,))


# ---- 版のルール ----

def test_two_current_versions_are_rejected(conn, base):
    """1つの文書に最新版が2つできないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        add_version(conn, base["document"], "第2版", "2025-10", is_current=1)


def test_duplicate_version_label_is_rejected(conn, base):
    """同じ文書で同じ版表記は二重に登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        add_version(conn, base["document"], "第1版", "2025-10", is_current=0)


def test_older_version_cannot_become_current(conn, base):
    """既存の版より古い改訂年月の版を、最新版として登録できないことを確認します。"""
    with conn:
        conn.execute("UPDATE document_versions SET is_current = 0 WHERE id = ?", (base["version"],))
    with pytest.raises(sqlite3.IntegrityError):
        add_version(conn, base["document"], "第0版", "2024-01", is_current=1)


def test_old_version_can_be_recorded_as_history(conn, base):
    """古い版でも「過去の版」としてなら記録できることを確認します。"""
    add_version(conn, base["document"], "第0版", "2024-01", is_current=0)


def test_version_content_cannot_be_edited(conn, base):
    """版の改訂年月やURLは、あとから書き換えできないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("UPDATE document_versions SET revised_on = '2026-01' WHERE id = ?", (base["version"],))


def test_versions_and_documents_cannot_be_deleted(conn, base):
    """文書と版は削除できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("DELETE FROM document_versions WHERE id = ?", (base["version"],))
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (base["document"],))


def test_invalid_dates_are_rejected(conn, base):
    """日付の形が正しくない版は登録できないことを確認します（改訂年月・入手日）。"""
    with pytest.raises(sqlite3.IntegrityError):
        add_version(conn, base["document"], "第2版", "2025/10", is_current=0)
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "INSERT INTO document_versions (document_id, version_label, retrieved_on, source_url, is_current) "
                "VALUES (?, '第3版', '2025-13-01', 'https://example.com/x', 0)", (base["document"],))


# ---- 品質チェック（版の不整合の検出） ----

def test_no_problems_for_clean_data(conn, base):
    """正しいデータでは、問題が見つからないことを確認します。"""
    add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    assert find_quality_problems(conn) == []


def test_detects_verified_fact_citing_old_version(conn, base):
    """確認済みの情報の出典が改訂されたとき、「再確認が必要」として見つかることを確認します。"""
    fact_id = add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    set_status(conn, "medical_facts", fact_id, "原文確認済み", "確認者", "原文と照合")

    new_version = add_version(conn, base["document"], "第2版", "2025-10", is_current=0)
    make_current(conn, base["document"], new_version)

    kinds = [p["kind"] for p in find_quality_problems(conn)]
    assert kinds == ["旧版を出典にした確認済み情報"]


def test_detects_source_not_linked_to_product(conn, base):
    """出典の文書が、情報の対象の製品とつながっていない場合に見つかることを確認します。"""
    with conn:
        other_product = conn.execute(
            "INSERT INTO products (brand_name, category) VALUES ('ベツモノ錠', '競合')").lastrowid
    add_record(conn, "medical_facts", fact_values(base, product_id=other_product), "確認者", "テスト登録")

    problems = find_quality_problems(conn)
    assert [p["kind"] for p in problems] == ["出典の対象不一致"]


def test_indication_fact_linked_through_product_is_ok(conn, base):
    """適応症の情報は、出典が製品か疾患のどちらかとつながっていれば問題なしになることを確認します。"""
    add_record(conn, "medical_facts", fact_values(
        base, product_id=None, indication_id=base["indication"], fact_type="効能・効果",
        content="（架空）架空疾患X", source_location="4. 効能又は効果",
    ), "確認者", "テスト登録")
    assert find_quality_problems(conn) == []


def test_detects_document_without_current_version(conn, base):
    """最新版が1つもない文書が見つかることを確認します。"""
    with conn:
        conn.execute("UPDATE document_versions SET is_current = 0 WHERE id = ?", (base["version"],))
    assert [p["kind"] for p in find_quality_problems(conn)] == ["最新版のない文書"]

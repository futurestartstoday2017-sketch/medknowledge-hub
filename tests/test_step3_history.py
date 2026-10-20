"""
test_step3_history.py：旧版の保持、更新履歴、トランザクション、バックアップと復元のテストです。
"""

import json
import sqlite3

import pytest

from db.backup import backup_db, check_integrity, restore_db
from db.changes import add_record, set_status, supersede_record
from db.database import get_connection
from tests.conftest import fact_values


def log_rows(conn):
    """テスト用：更新履歴をすべて取り出します。"""
    return conn.execute("SELECT * FROM change_log ORDER BY id").fetchall()


# ---- 旧版の保持 ----

def test_fact_cannot_be_deleted(conn, base):
    """医学的情報は削除できないことを確認します。"""
    fact_id = add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("DELETE FROM medical_facts WHERE id = ?", (fact_id,))


def test_fact_content_cannot_be_overwritten(conn, base):
    """医学的情報の内容・出典を直接書き換えできないことを確認します。"""
    fact_id = add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    for column, value in [("content", "書き換え"), ("source_location", "別の箇所")]:
        with pytest.raises(sqlite3.IntegrityError):
            with conn:
                conn.execute(f"UPDATE medical_facts SET {column} = ? WHERE id = ?", (value, fact_id))


def test_supersede_keeps_old_row(conn, base):
    """内容を変えると、古い行は「過去の情報」として残り、新しい行は「未確認」から始まることを確認します。"""
    old_id = add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    set_status(conn, "medical_facts", old_id, "原文確認済み", "確認者", "原文と照合")
    new_id = supersede_record(conn, "medical_facts", old_id,
                              {"content": "架空受容体Xと架空受容体Yを遮断する（架空）"}, "確認者", "改訂を反映")

    old = conn.execute("SELECT * FROM medical_facts WHERE id = ?", (old_id,)).fetchone()
    new = conn.execute("SELECT * FROM medical_facts WHERE id = ?", (new_id,)).fetchone()
    assert old["is_current"] == 0 and old["superseded_by"] == new_id
    assert old["content"] == "架空受容体Xを遮断する（架空）"  # 古い内容がそのまま残っている
    assert new["is_current"] == 1 and new["status"] == "未確認"


def test_old_row_cannot_be_revived_or_superseded_twice(conn, base):
    """過去の情報を今の情報に戻したり、もう一度置き換えたりできないことを確認します。"""
    old_id = add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    supersede_record(conn, "medical_facts", old_id, {"content": "新しい内容（架空）"}, "確認者", "改訂を反映")

    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("UPDATE medical_facts SET is_current = 1 WHERE id = ?", (old_id,))
    with pytest.raises(ValueError):
        supersede_record(conn, "medical_facts", old_id, {"content": "さらに別の内容"}, "確認者", "二重の置き換え")


# ---- 更新履歴 ----

def test_every_change_is_logged(conn, base):
    """追加・状態変更・置き換えのすべてが、確認者・理由つきで履歴に残ることを確認します。"""
    fact_id = add_record(conn, "medical_facts", fact_values(base), "山田", "初回登録")
    set_status(conn, "medical_facts", fact_id, "原文確認済み", "山田", "原文と照合")
    supersede_record(conn, "medical_facts", fact_id, {"content": "新しい内容（架空）"}, "山田", "改訂を反映")

    rows = log_rows(conn)
    assert [r["action"] for r in rows] == ["追加", "状態変更", "置き換え"]
    assert all(r["changed_by"] == "山田" and r["changed_at"] for r in rows)

    # 置き換えの履歴には、変更前と変更後の内容が両方残っている（差分を表示できる）
    replaced = rows[2]
    assert json.loads(replaced["before_json"])["content"] == "架空受容体Xを遮断する（架空）"
    assert json.loads(replaced["after_json"])["content"] == "新しい内容（架空）"


def test_verified_status_records_reviewer(conn, base):
    """「原文確認済み」にすると、確認者と確認日時が記録されることを確認します。"""
    fact_id = add_record(conn, "medical_facts", fact_values(base), "山田", "初回登録")
    set_status(conn, "medical_facts", fact_id, "原文確認済み", "山田", "原文と照合")
    row = conn.execute("SELECT verified_by, verified_at FROM medical_facts WHERE id = ?", (fact_id,)).fetchone()
    assert row["verified_by"] == "山田" and row["verified_at"]


def test_change_log_cannot_be_edited_or_deleted(conn, base):
    """更新履歴は編集も削除もできないことを確認します。"""
    add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("UPDATE change_log SET reason = '書き換え'")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("DELETE FROM change_log")


@pytest.mark.parametrize("changed_by, reason", [("", "理由"), ("確認者", "  ")])
def test_change_requires_reviewer_and_reason(conn, base, changed_by, reason):
    """確認者や変更理由が空だと、登録そのものが取り消されることを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        add_record(conn, "medical_facts", fact_values(base), changed_by, reason)
    assert conn.execute("SELECT COUNT(*) FROM medical_facts").fetchone()[0] == 0


# ---- トランザクション ----

def test_failed_supersede_rolls_back_everything(conn, base):
    """置き換えの途中でエラーが起きたら、古い行は「今の情報」のまま残り、履歴も増えないことを確認します。"""
    old_id = add_record(conn, "medical_facts", fact_values(base), "確認者", "テスト登録")
    logs_before = len(log_rows(conn))

    # 存在しない版を出典にする → 新しい行の追加で外部キーのエラーになる
    with pytest.raises(sqlite3.IntegrityError):
        supersede_record(conn, "medical_facts", old_id, {"source_version_id": 9999}, "確認者", "失敗する変更")

    old = conn.execute("SELECT is_current, superseded_by FROM medical_facts WHERE id = ?", (old_id,)).fetchone()
    assert old["is_current"] == 1 and old["superseded_by"] is None
    assert conn.execute("SELECT COUNT(*) FROM medical_facts").fetchone()[0] == 1
    assert len(log_rows(conn)) == logs_before


def test_unknown_table_or_column_is_rejected(conn, base):
    """決められたテーブル・列以外は書き込めないことを確認します（SQLの組み立てミスを防ぐ）。"""
    with pytest.raises(ValueError):
        add_record(conn, "change_log", {"table_name": "x"}, "確認者", "理由")
    with pytest.raises(ValueError):
        add_record(conn, "medical_facts", fact_values(base, unknown_column="x"), "確認者", "理由")


# ---- バックアップと復元 ----

def test_backup_and_restore(db_path, tmp_path, base, conn):
    """バックアップを取り、データを追加したあとで復元すると、元の状態に戻ることを確認します。"""
    backup_dir = tmp_path / "backups"
    backup_file = backup_db(db_path, backup_dir)
    assert check_integrity(backup_file)

    # バックアップのあとにデータを追加する
    add_record(conn, "medical_facts", fact_values(base), "確認者", "バックアップ後の登録")
    conn.close()

    safety_copy = restore_db(backup_file, db_path, backup_dir)

    restored = get_connection(db_path)
    assert restored.execute("SELECT COUNT(*) FROM medical_facts").fetchone()[0] == 0  # 追加前に戻った
    restored.close()

    # 復元前の状態も、念のためのバックアップとして残っている
    kept = get_connection(safety_copy)
    assert kept.execute("SELECT COUNT(*) FROM medical_facts").fetchone()[0] == 1
    kept.close()


def test_restore_rejects_broken_file(db_path, tmp_path):
    """壊れたファイルからは復元しないことを確認します。"""
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a database")
    with pytest.raises(ValueError):
        restore_db(broken, db_path, tmp_path / "backups")

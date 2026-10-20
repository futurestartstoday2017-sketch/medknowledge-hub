"""
test_step9_regulatory.py：Step 9-1（承認・再審査・特許・ライセンス・PMS のテーブルとマイグレーション）のテストです。
"""

import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

import db.backup
import db.database
from db.changes import add_record, set_status, supersede_record
from db.database import FACT_TABLES, SCHEMA_VERSION, get_connection, init_db
from db.quality import find_quality_problems
from services.sample_loader import load_sample_data
from tests.test_step2 import APP

NEW_TABLES = ["approvals", "reexaminations", "patents", "licenses", "pms_studies"]


def source(base):
    """テスト用：出典（製品にひも付いた添付文書の版）の列をまとめて返します。"""
    return {"source_version_id": base["version"], "source_location": "（架空）該当箇所"}


def approval(base, **overrides):
    values = {"product_id": base["product"], "approval_type": "初回承認", "approval_date": "2020-01-15",
              "content": "（架空）初回承認", **source(base)}
    return {**values, **overrides}


def reexam(base, **overrides):
    values = {"product_id": base["product"], "content": "（架空）再審査期間", "disclosure": "公開",
              "period_years": 8, "start_date": "2020-01-15", "end_date": "2028-01-14", **source(base)}
    return {**values, **overrides}


def patent(base, **overrides):
    values = {"product_id": base["product"], "patent_number": "特許第0000009号（架空）", "patent_kind": "物質",
              "disclosure": "公開", "expiry_date": "2030-06-30", **source(base)}
    return {**values, **overrides}


def license_(base, **overrides):
    values = {"product_id": base["product"], "partner_company_id": base["company"], "role": "導入元",
              "license_type": "導入", "content": "（架空）導入契約", "disclosure": "非公開", **source(base)}
    return {**values, **overrides}


def pms(base, **overrides):
    values = {"product_id": base["product"], "study_type": "特定使用成績調査", "title": "（架空）全例調査",
              "all_case": "全例調査", "approval_condition": "承認条件", "progress": "実施中",
              "disclosure": "公開", "start_date": "2020-04-01", **source(base)}
    return {**values, **overrides}


def insert(conn, table, values):
    """テスト用：1行を直接追加します（ルール違反のデータを入れてみるため）。"""
    columns = ", ".join(values)
    with conn:
        return conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join('?' * len(values))})",
                            list(values.values())).lastrowid


# ---- マイグレーション ----

def test_new_database_is_latest_version(conn):
    """新しく作ったDBが最新の設計図のバージョンで、新しいテーブルがそろっていることを確認します。"""
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(NEW_TABLES) <= tables


def test_migration_from_version_1_keeps_data(tmp_path, monkeypatch):
    """
    バージョン1のDB（Step 3〜8 で作ったDB）を開くと、データを保ったままバージョン2になり、
    事前にバックアップが取られることを確認します。
    """
    path = tmp_path / "old.db"
    # ① バージョン1のDBを作り、架空データを入れる（Step 9 より前の状態を再現する）
    monkeypatch.setattr(db.database, "SCHEMA_VERSION", 1)
    init_db(path)
    conn = get_connection(path)
    with conn:
        conn.execute("INSERT INTO products (brand_name, category) VALUES ('旧データ錠', '競合')")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()

    # ② 最新のアプリで開く → マイグレーションが実行される
    monkeypatch.setattr(db.database, "SCHEMA_VERSION", 2)
    init_db(path)
    conn = get_connection(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert conn.execute("SELECT brand_name FROM products").fetchone()[0] == "旧データ錠"
    for table in NEW_TABLES:  # 新しいテーブルにも、削除禁止のトリガーが作られている
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                            (f"{table}_no_delete",)).fetchone(), table
    conn.close()
    assert list(db.backup.BACKUP_DIR.glob("*.db")), "マイグレーションの前にバックアップが取られていません"


def test_newer_database_is_rejected(tmp_path):
    """アプリより新しいバージョンのDBは開かないことを確認します（壊さないため）。"""
    path = tmp_path / "future.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RuntimeError, match="新しいため開けません"):
        init_db(path)


def test_all_fact_tables_have_triggers(conn):
    """すべての事実のテーブルに、削除・書き換えを禁止するトリガーがあることを確認します。"""
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    for table in FACT_TABLES:
        for suffix in ("no_delete", "no_edit", "machine_unverified", "no_revive", "superseded_once"):
            assert f"{table}_{suffix}" in triggers, f"{table}_{suffix}"


# ---- 公開状況（disclosure）のルール ----

@pytest.mark.parametrize("table, make, date_column", [
    ("reexaminations", reexam, "end_date"),
    ("patents", patent, "expiry_date"),
    ("licenses", license_, "contract_end"),
    ("pms_studies", pms, "start_date"),
])
def test_non_public_must_not_have_dates(conn, base, table, make, date_column):
    """「非公開」「未確認」なのに日付が入っている行は登録できないことを確認します（推測で埋めない）。"""
    for disclosure in ("非公開", "未確認"):
        with pytest.raises(sqlite3.IntegrityError):
            insert(conn, table, make(base, disclosure=disclosure, **{date_column: "2030-01-01"}))


@pytest.mark.parametrize("table, make, cleared", [
    ("reexaminations", reexam, {"period_years": None, "start_date": None, "end_date": None}),
    ("patents", patent, {"expiry_date": None}),
    ("licenses", license_, {"disclosure": "公開"}),
    ("pms_studies", pms, {"start_date": None}),
])
def test_public_requires_a_date(conn, base, table, make, cleared):
    """「公開」なのに日付（期間）が1つもない行は登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, table, make(base, **cleared))


@pytest.mark.parametrize("table, make", [
    ("reexaminations", lambda b: reexam(b, disclosure="非公開", period_years=None, start_date=None, end_date=None)),
    ("patents", lambda b: patent(b, disclosure="未確認", expiry_date=None)),
    ("licenses", license_),
    ("pms_studies", lambda b: pms(b, disclosure="未確認", start_date=None)),
])
def test_non_public_without_dates_is_ok(conn, base, table, make):
    """「非公開」「未確認」で日付が空欄の行は登録できることを確認します。"""
    insert(conn, table, make(base))


# ---- 日付の順序 ----

@pytest.mark.parametrize("table, values", [
    ("reexaminations", lambda b: reexam(b, start_date="2028-01-01", end_date="2020-01-01")),
    ("patents", lambda b: patent(b, expiry_date="2030-06-30", extended_expiry_date="2029-01-01")),
    ("licenses", lambda b: license_(b, disclosure="公開", contract_start="2030-01-01", contract_end="2020-01-01")),
    ("pms_studies", lambda b: pms(b, start_date="2025-01-01", end_date="2024-01-01")),
])
def test_end_must_be_after_start(conn, base, table, values):
    """終了日（延長後の満了日）が開始日（もとの満了日）より前の行は登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, table, values(base))


@pytest.mark.parametrize("bad_date", ["2020/01/15", "2020-02-30", "令和2年1月15日"])
def test_approval_date_must_be_valid(conn, base, bad_date):
    """承認年月日は、正しい形の実在する日付でなければ登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "approvals", approval(base, approval_date=bad_date))


# ---- 重複・関連付け ----

def test_only_one_first_approval_per_product(conn, base):
    """初回承認は、1つの製品につき1つしか登録できないことを確認します。"""
    insert(conn, "approvals", approval(base))
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "approvals", approval(base, approval_date="2021-01-15"))
    # 効能・効果追加は、いくつでも登録できる
    insert(conn, "approvals", approval(base, approval_type="効能・効果追加", approval_date="2022-03-01",
                                       indication_id=base["indication"], content="（架空）効能追加"))


def test_duplicate_patent_is_rejected(conn, base):
    """同じ製品に、同じ国・同じ特許番号を二重に登録できないことを確認します。"""
    insert(conn, "patents", patent(base))
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "patents", patent(base, patent_kind="用途"))
    insert(conn, "patents", patent(base, country="米国"))  # 国が違えば登録できる


@pytest.mark.parametrize("table, make", [("approvals", approval), ("reexaminations", reexam), ("pms_studies", pms)])
def test_indication_must_belong_to_same_product(conn, base, table, make):
    """別の製品の適応症を指定した行は登録できないことを確認します。"""
    with conn:
        other = conn.execute("INSERT INTO products (brand_name, category) VALUES ('ベツモノ錠', '競合')").lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="別の製品"):
        insert(conn, table, make(base, product_id=other, indication_id=base["indication"]))


def test_unknown_values_are_rejected(conn, base):
    """決められた選択肢以外の値（全例調査か、特許の種類など）は使えないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "pms_studies", pms(base, all_case="たぶん全例"))
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "patents", patent(base, patent_kind="特殊"))
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, "licenses", license_(base, role="親会社"))


# ---- 出典・旧版の保持（ほかの事実のテーブルと同じルール） ----

@pytest.mark.parametrize("table, make", [
    ("approvals", approval), ("reexaminations", reexam), ("patents", patent), ("licenses", license_), ("pms_studies", pms),
])
def test_source_required(conn, base, table, make):
    """出典の版がない行は登録できないことを確認します。"""
    values = make(base)
    del values["source_version_id"]
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, table, values)


def test_patent_expiry_is_kept_when_changed(conn, base):
    """特許の満了日を変えるときは、古い満了日が履歴として残ることを確認します。"""
    old_id = add_record(conn, "patents", patent(base), "山田", "登録")
    with pytest.raises(sqlite3.IntegrityError):  # 直接の書き換えは禁止
        with conn:
            conn.execute("UPDATE patents SET expiry_date = '2031-01-01' WHERE id = ?", (old_id,))
    new_id = supersede_record(conn, "patents", old_id, {"extended_expiry_date": "2033-06-30"}, "山田", "延長登録")
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM patents")}
    assert rows[old_id]["is_current"] == 0 and rows[old_id]["extended_expiry_date"] is None
    assert rows[new_id]["extended_expiry_date"] == "2033-06-30"


@pytest.mark.parametrize("table, make", [("approvals", approval), ("patents", patent), ("pms_studies", pms)])
def test_api_entries_start_unverified(conn, base, table, make):
    """API で取得した承認・特許・PMS の情報も、「原文確認済み」では登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        insert(conn, table, make(base, entry_method="API", status="原文確認済み",
                                 verified_by="山田", verified_at="2025-11-01 10:00:00"))


def test_quality_check_covers_new_tables(conn, base):
    """出典の文書が製品とつながっていない承認情報が、品質チェックで見つかることを確認します。"""
    with conn:
        other = conn.execute("INSERT INTO products (brand_name, category) VALUES ('ベツモノ錠', '競合')").lastrowid
    add_record(conn, "approvals", approval(base, product_id=other), "山田", "登録")
    problems = find_quality_problems(conn)
    assert [(p["kind"], p["table"]) for p in problems] == [("出典の対象不一致", "approvals")]


# ---- 架空データ ----

@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


def test_sample_regulatory_data(loaded):
    """架空データに、承認・再審査・特許・ライセンス・PMS が入り、品質の問題がないことを確認します。"""
    for table in NEW_TABLES:
        assert loaded.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
    assert find_quality_problems(loaded) == []


def test_sample_has_all_disclosure_patterns(loaded):
    """架空データに「公開」「非公開」「未確認」の3パターンがすべて含まれていることを確認します。"""
    found = set()
    for table in ("reexaminations", "patents", "licenses", "pms_studies"):
        found |= {r[0] for r in loaded.execute(f"SELECT disclosure FROM {table}")}
    assert found == {"公開", "非公開", "未確認"}


def test_sample_regulatory_data_is_fictional(loaded):
    """承認番号・特許番号・説明などに「架空」が明記されていることを確認します。"""
    checks = {
        "approvals": ["approval_number", "content"], "reexaminations": ["content"],
        "patents": ["patent_number", "title"], "licenses": ["content"], "pms_studies": ["title"],
    }
    for table, columns in checks.items():
        for column in columns:
            values = [r[0] for r in loaded.execute(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")]
            assert all("架空" in v for v in values), f"{table}.{column}"


# ---- 更新管理画面 ----

def test_update_page_lists_new_tables():
    """更新管理の確認待ち一覧に新しいテーブルの情報も出て、選ぶとその項目の修正欄が並ぶことを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/更新管理.py").run()
    kinds = set(at.dataframe[0].value["種類"])
    assert {"特許", "ライセンス", "PMS（製造販売後調査等）"} <= kinds
    patent_key = next(o for o in at.selectbox(key="review_target").options if "特許" in o)
    at.selectbox(key="review_target").select(patent_key).run()
    assert not at.exception
    labels = [t.label for t in at.text_input]
    assert any("特許の存続期間満了日" in label for label in labels), labels


def test_status_change_works_for_new_tables(loaded):
    """新しいテーブルの情報も、確認状態を変えると確認者が記録されることを確認します。"""
    patent_id = loaded.execute("SELECT id FROM patents WHERE status = '未確認' LIMIT 1").fetchone()[0]
    set_status(loaded, "patents", patent_id, "原文確認済み", "山田", "原文と照合")
    row = loaded.execute("SELECT status, verified_by FROM patents WHERE id = ?", (patent_id,)).fetchone()
    assert (row["status"], row["verified_by"]) == ("原文確認済み", "山田")

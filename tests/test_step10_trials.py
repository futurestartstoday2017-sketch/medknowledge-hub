"""
test_step10_trials.py：Step 10-1（臨床試験のテーブル・架空データ・品質チェック）のテストです。
"""

import sqlite3

import pytest

from db.changes import supersede_record
from db.quality import find_quality_problems
from services.fact_fields import check_combination, parse_value
from services.sample_loader import load_sample_data
from services.trials import add_trial_entry


def entry(**overrides):
    """テスト用：試験の1行（1つの登録番号）の標準的な値。"""
    row = {
        "same_trial_as": None, "registry": "ClinicalTrials.gov", "registration_no": "NCT-架空-9001",
        "url": "https://example.com/ctgov/9001", "last_updated": "2025-01-10", "retrieved_on": "2025-06-01",
        "secondary_ids": None, "title": "（架空）テスト試験", "conditions_text": "（架空）架空疾患X",
        "interventions_text": "（架空）テストール", "study_type": "介入研究", "phase": "第3相",
        "start_date": "2024-04", "start_date_type": "実績", "end_date": None, "end_date_type": "未確認",
        "recruitment_status": "募集中", "results_status": "結果未公開",
        "test_products": "テストール錠", "diseases": "架空疾患X",
    }
    row.update(overrides)
    return row


def count(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


# ---- 試験の登録と、重複して数えない仕組み ----

def test_one_trial_with_two_registrations(conn, base):
    """「同じ試験の登録番号」を書くと、新しい試験を作らずに登録番号だけが追加されることを確認します。"""
    first = add_trial_entry(conn, entry(registry="jRCT", registration_no="架空jRCT-9001"), "CSV", "山田", "登録")
    second = add_trial_entry(conn, entry(same_trial_as="架空jRCT-9001", registration_no="NCT-架空-9001",
                                         secondary_ids="架空jRCT-9001"), "CSV", "山田", "登録")
    assert first["trial_id"] == second["trial_id"]
    assert second["detail_id"] is None  # 内容は最初の1行だけで登録する
    assert count(conn, "SELECT COUNT(*) FROM trials") == 1
    assert count(conn, "SELECT COUNT(*) FROM trial_registrations") == 2


def test_same_registration_number_is_rejected(conn, base):
    """同じレジストリの同じ登録番号は、2つの試験に登録できないことを確認します（重複計上の防止）。"""
    add_trial_entry(conn, entry(), "CSV", "山田", "登録")
    with pytest.raises(sqlite3.IntegrityError):
        add_trial_entry(conn, entry(title="（架空）別の試験"), "CSV", "山田", "登録")
    assert count(conn, "SELECT COUNT(*) FROM trials") == 1  # 失敗した分は残らない


def test_registration_page_becomes_source(conn, base):
    """登録ページが、出典の文書（臨床試験登録）と版として登録されることを確認します。"""
    ids = add_trial_entry(conn, entry(), "CSV", "山田", "登録")
    row = conn.execute("""
        SELECT d.doc_type, d.external_id, v.version_label, v.revised_on, v.source_url
        FROM trial_details t JOIN document_versions v ON v.id = t.source_version_id
        JOIN documents d ON d.id = v.document_id WHERE t.id = ?""", (ids["detail_id"],)).fetchone()
    assert tuple(row) == ("臨床試験登録", "NCT-架空-9001", "最終更新 2025-01-10", "2025-01",
                          "https://example.com/ctgov/9001")


def test_trial_links_products_and_diseases(conn, base):
    """試験薬・対照薬・疾患の分類が登録され、履歴に残ることを確認します。"""
    with conn:
        conn.execute("INSERT INTO products (brand_name, category) VALUES ('タイショウ錠', '競合')")
    ids = add_trial_entry(conn, entry(control_products="タイショウ錠"), "CSV", "山田", "登録")
    roles = {r[0] for r in conn.execute("SELECT role FROM trial_products WHERE trial_id = ?", (ids["trial_id"],))}
    assert roles == {"試験薬", "対照薬"}
    assert count(conn, "SELECT COUNT(*) FROM change_log WHERE table_name = 'trial_products'") == 2


def test_unknown_product_rolls_back(conn, base):
    """登録されていない製品名があると、日本語のエラーになり、何も登録されないことを確認します。"""
    with pytest.raises(ValueError, match="製品「存在しない錠」が登録されていません"):
        add_trial_entry(conn, entry(test_products="存在しない錠"), "CSV", "山田", "登録")
    assert count(conn, "SELECT COUNT(*) FROM trials") == 0
    assert count(conn, "SELECT COUNT(*) FROM documents WHERE doc_type = '臨床試験登録'") == 0


def test_trial_id_is_kept_when_details_are_revised(conn, base):
    """内容を修正しても研究IDは変わらず、登録番号などのひも付けがそのまま使えることを確認します。"""
    ids = add_trial_entry(conn, entry(), "CSV", "山田", "登録")
    new_detail = supersede_record(conn, "trial_details", ids["detail_id"],
                                  {"recruitment_status": "募集終了"}, "山田", "募集状況の更新")
    row = conn.execute("SELECT trial_id, recruitment_status FROM trial_details WHERE id = ?", (new_detail,)).fetchone()
    assert tuple(row) == (ids["trial_id"], "募集終了")
    assert count(conn, "SELECT COUNT(*) FROM trial_details WHERE trial_id = ?", (ids["trial_id"],)) == 2
    assert find_quality_problems(conn) == []


# ---- 日付のルール ----

@pytest.mark.parametrize("value", ["2025-04", "2025-04-15"])
def test_month_or_full_date_is_accepted(conn, base, value):
    """日付は YYYY-MM（月まで）でも YYYY-MM-DD でも登録できることを確認します。"""
    add_trial_entry(conn, entry(start_date=value), "CSV", "山田", "登録")


@pytest.mark.parametrize("value", ["2025/04", "2025-13", "2025-04-31", "令和7年4月"])
def test_bad_dates_are_rejected(conn, base, value):
    with pytest.raises(sqlite3.IntegrityError):
        add_trial_entry(conn, entry(start_date=value), "CSV", "山田", "登録")


@pytest.mark.parametrize("value", ["2025-13", "2025-00"])
def test_revised_month_must_be_real_month(conn, base, value):
    """
    文書の版の「原文の改訂年月」に、存在しない月（13月・0月）を登録できないことを確認します。
    （バージョン1のルールで通ってしまっていたのを、Step 10 で見つけて直した不具合の再発防止）
    """
    with pytest.raises(sqlite3.IntegrityError, match="01〜12"):
        with conn:
            conn.execute("INSERT INTO document_versions (document_id, version_label, revised_on, retrieved_on, "
                         "source_url, is_current) VALUES (?, '月のテスト', ?, '2025-01-01', 'https://example.com', 0)",
                         (base["document"], value))


def test_date_type_needs_a_date(conn, base):
    """日付が空欄なのに「実績」「予定」と書いた行は登録できないことを確認します。"""
    with pytest.raises(sqlite3.IntegrityError):
        add_trial_entry(conn, entry(end_date=None, end_date_type="予定"), "CSV", "山田", "登録")


def test_end_before_start_is_rejected(conn, base):
    with pytest.raises(sqlite3.IntegrityError):
        add_trial_entry(conn, entry(start_date="2025-04", end_date="2024-12", end_date_type="実績"), "CSV", "山田", "登録")


def test_parse_month_or_date():
    """修正フォームでも、月までの日付をそのまま受け付け、日を補わないことを確認します。"""
    assert parse_value("month_or_date", "研究開始日", "2025-04") == "2025-04"
    assert parse_value("month_or_date", "研究開始日", "2025-04-15") == "2025-04-15"
    with pytest.raises(ValueError, match="YYYY-MM-DD か YYYY-MM"):
        parse_value("month_or_date", "研究開始日", "2025/04")


def test_check_combination_for_trials():
    assert check_combination("trial_details", {"start_date": "2025-04", "end_date": "2025-04"}) == []
    assert "「未確認」にしてください" in check_combination(
        "trial_details", {"start_date": None, "start_date_type": "予定"})[0]
    assert "より後の日付" in check_combination(
        "trial_details", {"start_date": "2025-04", "end_date": "2024-12"})[0]


def test_trials_cannot_be_deleted(conn, base):
    """試験そのものは削除できないことを確認します。"""
    ids = add_trial_entry(conn, entry(), "CSV", "山田", "登録")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("DELETE FROM trials WHERE id = ?", (ids["trial_id"],))


# ---- 品質チェック ----

def test_detects_possible_duplicate_trial(conn, base):
    """別々に登録した2つの試験が、登録ページの「他の登録番号」で同一の可能性ありと見つかることを確認します。"""
    add_trial_entry(conn, entry(registry="jRCT", registration_no="架空jRCT-9001"), "CSV", "山田", "登録")
    add_trial_entry(conn, entry(registration_no="NCT-架空-9001", secondary_ids="架空jRCT-9001"), "CSV", "山田", "登録")
    problems = find_quality_problems(conn)
    assert [p["kind"] for p in problems] == ["同一試験の可能性"]
    assert "TR-0001" in problems[0]["message"] and "TR-0002" in problems[0]["message"]


def test_detects_trial_without_registration(conn, base):
    """登録番号も内容もない試験が見つかることを確認します。"""
    with conn:
        conn.execute("INSERT INTO trials DEFAULT VALUES")
    kinds = sorted(p["kind"] for p in find_quality_problems(conn))
    assert kinds == ["内容のない試験", "登録番号のない試験"]


def test_detects_source_of_other_registration(conn, base):
    """登録番号の出典が、別の登録番号の登録ページになっていると見つかることを確認します。"""
    first = add_trial_entry(conn, entry(), "CSV", "山田", "登録")
    second = add_trial_entry(conn, entry(registration_no="NCT-架空-9002", url="https://example.com/x"),
                             "CSV", "山田", "登録")
    wrong_source = conn.execute("SELECT source_version_id FROM trial_registrations WHERE id = ?",
                                (first["registration_id"],)).fetchone()[0]
    supersede_record(conn, "trial_registrations", second["registration_id"],
                     {"source_version_id": wrong_source}, "山田", "誤った出典")
    assert any(p["kind"] == "出典の対象不一致" and p["table"] == "trial_registrations"
               for p in find_quality_problems(conn))


# ---- 架空データ ----

def test_sample_trials(loaded):
    """架空データで、2つのレジストリに登録された試験が1件として数えられ、品質の問題がないことを確認します。"""
    assert count(loaded, "SELECT COUNT(*) FROM trials") == 4
    assert count(loaded, "SELECT COUNT(*) FROM trial_registrations") == 5
    assert count(loaded, "SELECT COUNT(DISTINCT registry) FROM trial_registrations WHERE trial_id = 1") == 2
    assert find_quality_problems(loaded) == []


def test_sample_trials_are_fictional(loaded):
    """架空の試験の登録番号・タイトルに「架空」が明記され、URLが example.com であることを確認します。"""
    assert all("架空" in r[0] for r in loaded.execute("SELECT registration_no FROM trial_registrations"))
    assert all("架空" in r[0] for r in loaded.execute("SELECT title FROM trial_details"))
    assert all(r[0].startswith("https://example.com/") for r in loaded.execute(
        "SELECT v.source_url FROM document_versions v JOIN documents d ON d.id = v.document_id "
        "WHERE d.doc_type = '臨床試験登録'"))


def test_pms_and_trial_share_registration_number(loaded):
    """テスタミドOD錠の PMS と、製造販売後臨床試験が、同じ登録番号でつながることを確認します。"""
    pms_no = loaded.execute("SELECT registration_no FROM pms_studies WHERE registration_no IS NOT NULL").fetchone()[0]
    assert count(loaded, "SELECT COUNT(*) FROM trial_registrations WHERE registration_no = ?", (pms_no,)) == 1

"""
test_step7_updates.py：Step 7（確認・更新管理）のテストです。

更新の処理（services/updates.py）と、画面（pages/更新管理.py）の両方を確かめます。
"""

import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

import db.backup
from db.changes import set_status
from db.quality import find_quality_problems
from db.queries import get_version_choices, list_change_log, list_review_facts
from db.settings import get_setting, set_setting
from services.diff import diff_records, display_value
from services.sample_loader import load_sample_data
from services.updates import (
    add_candidate, confirm_document_version, register_document_version, revise_fact, update_candidate_status,
)
from tests.test_step2 import APP

UPDATE_PAGE = "pages/更新管理.py"
SAMPURIN_PI = 1      # サンプリンα錠 添付文書（架空）の文書ID（documents.csv の1行目）
SAMPURIN_PI_V2 = 2   # その最新版（第2版）の版ID


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


def count(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def register_v3(conn, **overrides):
    """テスト用：サンプリンα錠の添付文書に、第3版を最新版として登録します。"""
    args = dict(document_id=SAMPURIN_PI, version_label="2025年10月改訂（第3版）", revised_on="2025-10",
                retrieved_on="2025-11-01", source_url="https://example.com/sampurin/pi/v3",
                make_current=True, reviewer="山田", reason="改訂を確認")
    args.update(overrides)
    return register_document_version(conn, **args)


# ---- 新しい版の登録 ----

def test_new_version_becomes_current_and_old_is_kept(loaded):
    """新しい版を最新版にすると、古い版は「過去の版」として残ることを確認します。"""
    result = register_v3(loaded)
    rows = loaded.execute("SELECT id, is_current FROM document_versions WHERE document_id = ? ORDER BY id",
                          (SAMPURIN_PI,)).fetchall()
    assert [(r["id"], r["is_current"]) for r in rows] == [(1, 0), (SAMPURIN_PI_V2, 0), (result["version_id"], 1)]


def test_new_version_marks_verified_facts_for_recheck(loaded):
    """新しい版を登録すると、古い版を出典にした確認済み情報が「再確認要」になることを確認します。"""
    confirmed_before = count(loaded, "SELECT COUNT(*) FROM medical_facts WHERE is_current = 1 "
                                     "AND status = '原文確認済み' AND source_version_id = ?", (SAMPURIN_PI_V2,))
    result = register_v3(loaded)
    assert result["rechecked"] >= confirmed_before > 0
    assert count(loaded, "SELECT COUNT(*) FROM medical_facts WHERE is_current = 1 "
                         "AND status = '原文確認済み' AND source_version_id = ?", (SAMPURIN_PI_V2,)) == 0
    # 「改訂前の版を出典にした確認済み情報」という品質の問題が残っていない
    assert find_quality_problems(loaded) == []


def test_new_version_is_logged_with_reviewer(loaded):
    """新しい版の登録と、それに伴う状態変更が、確認者つきで履歴に残ることを確認します。"""
    register_v3(loaded)
    log = list_change_log(loaded)
    recent = log[log["確認者"] == "山田"]
    assert "文書の版" in set(recent["対象"])
    assert any("新しい版" in r for r in recent["理由"])


def test_older_version_cannot_be_current_and_nothing_changes(loaded):
    """古い改訂年月の版を最新版にしようとするとエラーになり、何も変更されないことを確認します。"""
    logs_before = count(loaded, "SELECT COUNT(*) FROM change_log")
    with pytest.raises(sqlite3.IntegrityError):
        register_v3(loaded, revised_on="2020-01")
    assert count(loaded, "SELECT is_current FROM document_versions WHERE id = ?", (SAMPURIN_PI_V2,)) == 1
    assert count(loaded, "SELECT COUNT(*) FROM change_log") == logs_before


def test_version_registration_links_candidate(loaded):
    """変更候補を指定して版を登録すると、候補に新しい版がひも付き「確認中」になることを確認します。"""
    candidate_id = add_candidate(loaded, SAMPURIN_PI, "公式サイトに改訂の掲載あり（架空）", "山田", "気づいたため")
    result = register_v3(loaded, candidate_id=candidate_id)
    row = loaded.execute("SELECT status, new_version_id FROM change_candidates WHERE id = ?",
                         (candidate_id,)).fetchone()
    assert row["status"] == "確認中" and row["new_version_id"] == result["version_id"]


def test_confirm_document_version(loaded):
    """未確認の版を「原文確認済み」にすると、確認日が記録されることを確認します。"""
    version_id = loaded.execute("SELECT id FROM document_versions WHERE status = '未確認' LIMIT 1").fetchone()[0]
    confirm_document_version(loaded, version_id, "2025-11-01", "山田", "原文を確認")
    row = loaded.execute("SELECT status, confirmed_on FROM document_versions WHERE id = ?", (version_id,)).fetchone()
    assert (row["status"], row["confirmed_on"]) == ("原文確認済み", "2025-11-01")


# ---- 変更候補 ----

def test_candidate_status_records_resolver(loaded):
    """変更候補を「見送り」にすると、対応者と日時が記録され、履歴に残ることを確認します。"""
    candidate_id = add_candidate(loaded, SAMPURIN_PI, "改訂の可能性（架空）", "山田", "気づいたため")
    update_candidate_status(loaded, candidate_id, "見送り", "佐藤", "原文を確認し、変更なし")
    row = loaded.execute("SELECT * FROM change_candidates WHERE id = ?", (candidate_id,)).fetchone()
    assert row["status"] == "見送り" and row["resolved_by"] == "佐藤" and row["resolved_at"]
    actions = [r[0] for r in loaded.execute(
        "SELECT action FROM change_log WHERE table_name = 'change_candidates' ORDER BY id")]
    assert actions == ["追加", "状態変更"]


def test_candidate_rejects_unknown_status(loaded):
    """決められた対応状況以外は使えないことを確認します。"""
    candidate_id = add_candidate(loaded, SAMPURIN_PI, "改訂の可能性（架空）", "山田", "気づいたため")
    with pytest.raises(ValueError):
        update_candidate_status(loaded, candidate_id, "たぶん大丈夫", "山田", "理由")


# ---- 内容の修正 ----

def test_revise_fact_with_verification(loaded):
    """修正と同時に「原文確認済み」にすると、新しい行が確認済みになり、古い行は残ることを確認します。"""
    old = loaded.execute("SELECT id FROM medical_facts WHERE status = '未確認' LIMIT 1").fetchone()[0]
    new_id = revise_fact(loaded, "medical_facts", old, {"content": "修正後（架空）"}, "山田", "改訂に合わせる",
                         mark_verified=True)
    new = loaded.execute("SELECT * FROM medical_facts WHERE id = ?", (new_id,)).fetchone()
    assert new["status"] == "原文確認済み" and new["verified_by"] == "山田"
    assert count(loaded, "SELECT is_current FROM medical_facts WHERE id = ?", (old,)) == 0


def test_revise_fact_failure_changes_nothing(loaded):
    """修正の途中で失敗すると、古い情報は「今の情報」のまま残ることを確認します。"""
    old = loaded.execute("SELECT id FROM medical_facts WHERE status = '未確認' LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        revise_fact(loaded, "medical_facts", old, {"source_version_id": 9999}, "山田", "失敗する修正",
                    mark_verified=True)
    assert count(loaded, "SELECT is_current FROM medical_facts WHERE id = ?", (old,)) == 1


def test_version_choices_are_related_documents(loaded):
    """出典として選べる版が、その製品にひも付いた文書の版だけであることを確認します。"""
    fact = next(f for f in list_review_facts(loaded, ["再確認要"]) if f["subject"] == "サンプリンα錠")
    titles = {label.split(" ／ ")[0] for _, label in get_version_choices(loaded, fact)}
    assert titles == {"サンプリンα錠 添付文書（架空）", "サンプリンα錠 インタビューフォーム（架空）",
                      "サンプリンα錠 RMP（架空）", "サンプル製薬 決算説明資料（架空）"}
    # 別の製品の文書（テスタミド・モックセプトの添付文書など）は選べない
    assert not any("テスタミド" in t or "モックセプト" in t for t in titles)


# ---- 差分・設定 ----

def test_diff_shows_only_changed_items(loaded):
    """差分には、変わった項目だけが日本語の項目名で出ることを確認します。"""
    before = {"id": 1, "content": "前", "source_location": "同じ", "source_version_id": 1}
    after = {"id": 2, "content": "後", "source_location": "同じ", "source_version_id": 2}
    rows = diff_records(before, after, loaded)
    assert [r["項目"] for r in rows] == ["内容", "出典の版"]
    assert "第2版" in rows[1]["変更後"]  # 版のIDが、文書名と版の表記に直されている


def test_diff_for_new_record(loaded):
    """新しく追加したデータの差分では、変更前が「（なし）」になることを確認します。"""
    rows = diff_records(None, {"content": "追加した内容"})
    assert rows == [{"項目": "内容", "変更前": "（なし）", "変更後": "追加した内容"}]
    assert display_value(None, "is_current", 0) == "過去の情報"


def test_settings_roundtrip(conn):
    """設定（前回の確認者名）を保存し、取り出せることを確認します。"""
    assert get_setting(conn, "last_reviewer", "") == ""
    set_setting(conn, "last_reviewer", "山田")
    set_setting(conn, "last_reviewer", "佐藤")
    assert get_setting(conn, "last_reviewer") == "佐藤"


# ---- 画面 ----

def open_update_page(reviewer=None):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page(UPDATE_PAGE).run()
    assert not at.exception, [e.message for e in at.exception]
    if reviewer:
        at.text_input(key="reviewer").input(reviewer).run()
    return at


def confirm_selected(at):
    """画面で選ばれている情報を「原文確認済み」にする操作をします。"""
    key = at.selectbox(key="review_target").value
    at.radio(key=f"new_status_{key}").set_value("原文確認済み")
    at.text_input(key=f"status_reason_{key}").input("原文と照合")
    at.checkbox(key=f"status_read_{key}").check()
    at.button(key="status_submit").click().run()
    return key


def test_page_requires_reviewer_name():
    """確認者名がないと変更できず、データも変わらないことを確認します。"""
    at = open_update_page()
    before = at.selectbox(key="review_target").value
    confirm_selected(at)
    assert any("確認者名を入力してください" in e.value for e in at.error)
    assert at.selectbox(key="review_target").value == before


def test_page_requires_reading_source_to_verify():
    """「原文を読んだ」のチェックなしでは「原文確認済み」にできないことを確認します。"""
    at = open_update_page("山田")
    key = at.selectbox(key="review_target").value
    at.radio(key=f"new_status_{key}").set_value("原文確認済み")
    at.text_input(key=f"status_reason_{key}").input("原文と照合")
    at.button(key="status_submit").click().run()
    assert any("チェックが必要" in e.value for e in at.error)


def test_page_status_change_makes_backup_and_log():
    """画面で確認状態を変えると、バックアップが取られ、確認者が履歴に残ることを確認します。"""
    at = open_update_page("山田")
    confirm_selected(at)
    assert not at.exception
    assert any("原文確認済み" in s.value for s in at.success)
    assert list(db.backup.BACKUP_DIR.glob("*.db")), "バックアップが作られていません"
    assert at.dataframe[-1].value.iloc[0]["確認者"] == "山田"  # 更新履歴の一番新しい行


def test_page_revision_does_not_carry_over_previous_inputs():
    """
    別の情報に切り替えたとき、前の情報の入力値が残って、意図しない変更にならないことを確認します。
    （開発中に見つかった不具合の再発防止テスト）
    """
    at = open_update_page("山田")
    confirm_selected(at)  # 確認すると一覧から外れ、別の情報が選ばれる
    # 修正フォームのある医学的情報（テスタミドOD錠の薬効分類、ID 6）に切り替える
    at.selectbox(key="review_target").set_value("medical_facts:6").run()
    key = at.selectbox(key="review_target").value
    at.text_area(key=f"revise_content_{key}").input("修正した内容（架空）")
    at.text_input(key=f"revise_reason_{key}").input("テスト修正")
    at.button(key="revise_preview").click().run()
    diff = at.table[0].value
    assert list(diff.index) == ["内容"], f"変えていない項目が差分に含まれています：{list(diff.index)}"


def test_page_revision_flow():
    """差分を確認してから反映すると、修正が反映されることを確認します。"""
    at = open_update_page("山田")
    key = at.selectbox(key="review_target").value
    at.text_area(key=f"revise_content_{key}").input("修正した内容（架空）")
    at.text_input(key=f"revise_reason_{key}").input("テスト修正")
    at.button(key="revise_preview").click().run()
    at.button(key="revise_apply").click().run()
    assert not at.exception
    assert any("修正を反映しました" in s.value for s in at.success)


def test_history_tab_has_no_edit_or_delete():
    """更新履歴のタブに、編集・削除のボタンがないことを確認します。"""
    at = open_update_page()
    labels = [b.label for b in at.button]
    assert not any("削除" in label or "編集" in label for label in labels), labels

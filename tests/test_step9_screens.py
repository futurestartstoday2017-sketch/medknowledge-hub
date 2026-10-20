"""
test_step9_screens.py：Step 9-2（製品画面・タイムライン・比較表・修正フォーム）のテストです。
"""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from components.display import disclosed_value
from db.changes import add_record, set_status
from db.errors import friendly_db_error
from services.comparison import build_comparison, comparison_table
from services.fact_fields import FIELD_SPECS, check_combination, parse_value
from services.sample_loader import load_sample_data
from services.timeline import build_timeline, years_between
from tests.test_step2 import APP

ROOT = Path(__file__).parent.parent
SAMPURIN, TESTAMID, MOCKCEPT = 1, 2, 3  # 架空データの製品ID（products.csv の順）
TODAY = date(2026, 10, 20)               # テストでは「今日」を固定する（結果が日によって変わらないように）


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


# ---- タイムライン ----

def test_timeline_milestones(loaded):
    """初回承認・再審査期間の終了・特許満了（延長後・最も遅いもの）の日付が正しく選ばれることを確認します。"""
    timeline = build_timeline(loaded, SAMPURIN, TODAY)
    dates = {m["label"]: m["date"] for m in timeline["milestones"]}
    assert dates == {"初回承認年月日": "2016-03-28", "再審査期間の終了日": "2024-03-27",
                     "特許満了日（最も遅いもの）": "2030-11-30"}  # 延長登録後の満了日を使う


def test_timeline_durations(loaded):
    """期間（約○年）と、今日時点の経過・残り・終了済みが計算されることを確認します。"""
    durations = {d["区間"]: d["期間"] for d in build_timeline(loaded, SAMPURIN, TODAY)["durations"]}
    assert durations["初回承認 → 再審査期間の終了"] == "約 8.0 年"
    assert durations["初回承認 → 特許満了（最も遅いもの）"] == "約 14.7 年"
    assert durations["今日 → 再審査期間の終了"].startswith("終了済み")
    assert durations["今日 → 特許満了（最も遅いもの）"] == "残り 約 4.1 年"


def test_timeline_warns_about_hidden_patents(loaded):
    """満了日が未確認の特許があると、「最も遅い満了日が変わる可能性」を知らせることを確認します。"""
    notes = build_timeline(loaded, SAMPURIN, TODAY)["notes"]
    assert any("特許第0000002号（架空）" in n and "変わる可能性" in n for n in notes)


def test_timeline_warns_about_unverified_values(loaded):
    """原文で確認できていない日付を使ったときは、そのことを知らせることを確認します。"""
    notes = build_timeline(loaded, TESTAMID, TODAY)["notes"]
    assert any("原文で確認できていない値を含む目安" in n for n in notes)


def test_timeline_does_not_guess_missing_dates(conn, base):
    """日付が登録されていないときは計算せず、足りない情報を知らせることを確認します（推測しない）。"""
    timeline = build_timeline(conn, base["product"], TODAY)
    assert all(m["date"] is None for m in timeline["milestones"])
    assert timeline["durations"] == []
    assert any("初回承認年月日が登録されていない" in n for n in timeline["notes"])


def test_timeline_ignores_non_public_reexam(conn, base):
    """再審査期間が「非公開」のときは、終了日を計算に使わないことを確認します。"""
    source = {"source_version_id": base["version"], "source_location": "（架空）"}
    add_record(conn, "approvals", {"product_id": base["product"], "approval_type": "初回承認",
                                   "approval_date": "2020-01-15", "content": "（架空）", **source}, "山田", "登録")
    add_record(conn, "reexaminations", {"product_id": base["product"], "content": "（架空）",
                                        "disclosure": "非公開", **source}, "山田", "登録")
    timeline = build_timeline(conn, base["product"], TODAY)
    assert timeline["milestones"][1]["date"] is None
    assert any("「非公開」のため" in n for n in timeline["notes"])


def test_years_between():
    assert round(years_between("2020-01-01", "2030-01-01"), 1) == 10.0


# ---- 比較表 ----

def test_comparison_regulatory_rows(loaded):
    """比較表に、初回承認年月日・再審査期間の終了日・特許満了日・全例調査の行が出ることを確認します。"""
    table = comparison_table(build_comparison(loaded, 1))  # 架空慢性疾患A
    assert table.loc["初回承認年月日", "サンプリンα錠"] == "✅ 2016-03-28"
    assert table.loc["特許満了日（最も遅いもの）", "サンプリンα錠"] == "✅ 2030-11-30（延長登録後）"
    assert table.loc["全例調査", "モックセプト皮下注"].startswith("✅ 全例調査（")


def test_comparison_shows_unverified_regulatory_values(loaded):
    """未確認の承認年月日などには、⚠️ の印が付くことを確認します。"""
    table = comparison_table(build_comparison(loaded, 2))  # 架空慢性疾患B
    assert table.loc["初回承認年月日", "テスタミドOD錠"].startswith("⚠️")


def test_comparison_shows_disclosure_when_no_public_patent(conn, base):
    """公開の満了日がない特許だけのときは、「❔ 未確認」などと表示されることを確認します（空欄にしない）。"""
    add_record(conn, "patents", {"product_id": base["product"], "patent_number": "特許第0000009号（架空）",
                                 "disclosure": "未確認", "source_version_id": base["version"],
                                 "source_location": "（架空）"}, "山田", "登録")
    table = comparison_table(build_comparison(conn, base["disease"]))
    assert table.loc["特許満了日（最も遅いもの）", "テストール錠"] == "⚠️ ❔ 未確認"


def test_disclosed_value():
    assert disclosed_value("公開", "2030-01-01") == "2030-01-01"
    assert disclosed_value("非公開", "2030-01-01") == "🔒 非公開"
    assert disclosed_value("未確認", None) == "❔ 未確認"
    assert disclosed_value("公開", None) == "—"


# ---- 修正フォームの項目定義 ----

def test_field_specs_cover_all_fact_tables():
    """すべての事実のテーブルに、修正できる項目の定義があることを確認します。"""
    from db.database import FACT_TABLES
    assert set(FIELD_SPECS) == set(FACT_TABLES)


def test_field_spec_options_match_database_rules():
    """選択肢の値が、データベースのルール（CHECK）に書かれている値と一致していることを確認します。"""
    # 最初の設計図と、すべてのマイグレーション（追加分）を読む
    sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8") + "".join(
        f.read_text(encoding="utf-8") for f in sorted((ROOT / "db" / "migrations").glob("*.sql")))
    for table, fields in FIELD_SPECS.items():
        for column, _, kind, options in fields:
            if kind == "select":
                for option in options:
                    assert f"'{option}'" in sql, f"{table}.{column} の選択肢「{option}」がDBのルールにありません"


def test_parse_value():
    """入力欄の文字が、正しい値に直されること・誤りが日本語で知らされることを確認します。"""
    assert parse_value("date", "承認年月日", " 2025-11-01 ") == "2025-11-01"
    assert parse_value("date", "承認年月日", "") is None
    assert parse_value("int", "再審査期間（年）", "8") == 8
    with pytest.raises(ValueError, match="正しい日付"):
        parse_value("date", "承認年月日", "2025-02-30")
    with pytest.raises(ValueError, match="1以上の整数"):
        parse_value("int", "再審査期間（年）", "八")


def test_check_combination():
    """公開状況と日付の組み合わせ、日付の順序の誤りが、日本語で知らされることを確認します。"""
    assert check_combination("patents", {"disclosure": "公開", "expiry_date": "2030-01-01"}) == []
    assert "空欄にしてください" in check_combination(
        "patents", {"disclosure": "非公開", "expiry_date": "2030-01-01"})[0]
    assert "1つ以上入力" in check_combination("licenses", {"disclosure": "公開"})[0]
    assert "より後の日付" in check_combination(
        "patents", {"disclosure": "公開", "expiry_date": "2030-01-01", "extended_expiry_date": "2029-01-01"})[0]


def test_friendly_db_error():
    assert "重複" in friendly_db_error(Exception("UNIQUE constraint failed: patents.patent_number"))
    assert "ルールに合いません" in friendly_db_error(Exception("CHECK constraint failed: x"))
    assert friendly_db_error(Exception("更新履歴は削除できません")) == "更新履歴は削除できません"


# ---- 画面 ----

def open_product_page():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/製品情報.py").run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_product_page_shows_timeline_and_tables():
    """製品画面にタイムラインと、承認・再審査・PMS・ライセンス・特許の表が出ることを確認します。"""
    at = open_product_page()
    assert [m.label for m in at.metric] == ["初回承認年月日", "再審査期間の終了日", "特許満了日（最も遅いもの）"]
    headers = [list(d.value.columns) for d in at.dataframe]
    for column in ("承認年月日", "再審査期間の終了日", "全例調査か", "契約終了日", "特許の存続期間満了日"):
        assert any(column in h for h in headers), column
    # すべての表に出典と確認状態の列がある（製品一覧の表は除く）
    for h in headers[1:]:
        assert "確認状態" in h or "改訂年月" in h


def test_product_page_shows_non_public_marks():
    """非公開・未確認の値が「🔒 非公開」「❔ 未確認」と表示されることを確認します。"""
    at = open_product_page()
    at.selectbox[0].select("テスタミドOD錠").run()
    licenses = next(d.value for d in at.dataframe if "契約終了日" in d.value.columns)
    assert licenses.iloc[0]["契約終了日"] == "🔒 非公開"


def revise_patent(at, **inputs):
    """更新管理画面で、テスタミドOD錠の特許（未確認）を選び、修正欄に値を入れて「変更内容を確認する」を押します。"""
    at.text_input(key="reviewer").input("山田").run()
    key = next(o for o in at.selectbox(key="review_target").options if "特許" in o and "テスタミド" in o)
    at.selectbox(key="review_target").select(key).run()
    target = at.selectbox(key="review_target").value
    for column, value in inputs.items():
        at.text_input(key=f"revise_{column}_{target}").input(value)
    at.text_input(key=f"revise_reason_{target}").input("延長登録を確認")
    at.button(key="revise_preview").click().run()
    return target


def test_revise_patent_with_preview_and_apply():
    """特許の延長登録後の満了日を修正すると、差分が表示され、反映できることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/更新管理.py").run()
    revise_patent(at, extended_expiry_date="2036-12-31")
    diff = at.table[0].value
    assert list(diff.index) == ["延長登録後の満了日"]
    at.button(key="revise_apply").click().run()
    assert not at.exception
    assert any("修正を反映しました" in s.value for s in at.success)


def test_revise_rejects_bad_date_in_japanese():
    """修正フォームで日付の形を間違えると、日本語で知らせ、差分の確認に進まないことを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/更新管理.py").run()
    revise_patent(at, extended_expiry_date="2036/12/31")
    assert any("YYYY-MM-DD" in e.value for e in at.error)
    assert not any("差分" in m.value for m in at.markdown), "誤りがあるのに差分の確認に進んでいます"


def test_every_fact_column_has_japanese_label(conn):
    """差分の表で、事実のテーブルのすべての列が日本語の項目名で表示されることを確認します。"""
    from db.database import FACT_TABLES
    from services.diff import COLUMN_LABELS
    for table in FACT_TABLES:
        for row in conn.execute(f"PRAGMA table_info({table})"):
            assert row["name"] in COLUMN_LABELS, f"{table}.{row['name']} の日本語名がありません"

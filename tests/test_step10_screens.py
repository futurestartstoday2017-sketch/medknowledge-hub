"""
test_step10_screens.py：Step 10-2（臨床試験の画面・CSV・AI抽出・データベースの切り替え）のテストです。
"""

import pytest
from streamlit.testing.v1 import AppTest

import db.backup
import db.database
from db.database import MODES, current_db_path, get_mode, set_mode
from services.csv_importer import KINDS, example_table, import_rows, read_csv, validate
from services.sample_loader import load_sample_data
from services.search import search_all
from tests.test_step2 import APP

TRIALS_PAGE = "pages/臨床試験.py"


def table(text):
    return read_csv(text.encode("utf-8"))


def header():
    return ",".join(h for h, _, _ in KINDS["trials"]["columns"])


def trial_line(**values):
    """テスト用：試験CSVの1行を作ります（指定しない列は空欄）。"""
    names = [n for _, n, _ in KINDS["trials"]["columns"]]
    base = {"registry": "ClinicalTrials.gov", "registration_no": "NCT-架空-0100", "url": "https://example.com/x",
            "retrieved_on": "2025-11-01", "title": "（架空）試験", "conditions_text": "（架空）疾患",
            "interventions_text": "（架空）介入", "test_products": "サンプリンα錠"}
    base.update(values)
    return ",".join(base.get(n, "") or "" for n in names)


def count(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


# ---- データベースの切り替え ----

def test_default_mode_is_sample():
    """設定がなければ、架空データ（動作確認用）のデータベースを使うことを確認します。"""
    assert get_mode() == "sample"
    assert current_db_path() == db.database.DB_PATH


def test_switch_to_real_database():
    """実データに切り替えると、別のデータベースファイルを使い、その設定が保存されることを確認します。"""
    set_mode("real")
    assert get_mode() == "real"
    assert current_db_path() == db.database.REAL_DB_PATH
    with pytest.raises(ValueError):
        set_mode("test")


def test_real_database_has_no_sample_data():
    """実データのデータベースには、架空データが読み込まれないことを確認します。"""
    set_mode("real")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["登録製品数"] == "0"
    assert any(MODES["real"] in m.value for m in at.sidebar.markdown)
    # 実データを使っている間は、架空データのデータベースには触れない（ファイルも作られない）
    assert db.database.REAL_DB_PATH.exists()
    assert not db.database.DB_PATH.exists()


def test_switching_keeps_both_databases():
    """切り替えても、もう一方のデータベースの中身は消えないことを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()  # 架空データのDBができる
    set_mode("real")
    AppTest.from_file(APP, default_timeout=30).run()       # 実データのDBができる
    set_mode("sample")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert {m.label: m.value for m in at.metric}["登録製品数"] == "3"


def test_backup_name_shows_which_database():
    """バックアップのファイル名で、どちらのデータベースの控えかがわかることを確認します。"""
    set_mode("real")
    AppTest.from_file(APP, default_timeout=30).run()
    path = db.backup.backup_db()
    assert path.name.startswith(db.database.REAL_DB_PATH.stem + "_")


def test_switch_from_data_page():
    """データ管理画面から実データに切り替えられることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/データ管理.py").run()
    at.radio(key="db_mode").set_value("real").run()
    at.button(key="db_switch").click().run()
    assert not at.exception
    assert get_mode() == "real"


@pytest.mark.parametrize("page", ["pages/製品情報.py", "pages/疾患情報.py", "pages/競合製品比較.py", TRIALS_PAGE,
                                  "pages/更新管理.py", "pages/データ管理.py"])
def test_all_pages_work_with_empty_database(page):
    """空の実データのデータベースでも、すべての画面がエラーなく表示されることを確認します。"""
    set_mode("real")
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page(page).run()
    assert not at.exception, [e.message for e in at.exception]


# ---- 臨床試験の画面 ----

def open_trials():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page(TRIALS_PAGE).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def test_trials_page_counts_each_trial_once():
    """2つのレジストリに登録された試験も、一覧では1件として数えられることを確認します。"""
    at = open_trials()
    listing = at.dataframe[0].value
    assert list(listing["研究ID"]) == ["TR-0001", "TR-0002", "TR-0003", "TR-0004"]
    assert "jRCT：架空jRCT-0001" in listing.iloc[0]["登録番号"]
    assert "ClinicalTrials.gov：NCT-架空-0001" in listing.iloc[0]["登録番号"]


def test_trials_page_filters():
    """絞り込み（スポンサー区分・製品）が効くことを確認します。"""
    at = open_trials()
    at.multiselect[4].set_value(["競合"]).run()  # スポンサー区分
    assert list(at.dataframe[0].value["研究ID"]) == ["TR-0002"]
    at.multiselect[4].set_value([]).run()
    at.multiselect[0].set_value(["モックセプト皮下注"]).run()  # 製品
    assert list(at.dataframe[0].value["研究ID"]) == ["TR-0002", "TR-0004"]


def test_trial_detail_shows_dates_with_type_and_pms():
    """詳細に、日付の「実績・予定」と、登録番号が同じ PMS が表示されることを確認します。"""
    at = open_trials()
    at.selectbox[0].select_index(2).run()  # TR-0003（製造販売後臨床試験）
    text = "\n".join(m.value for m in at.markdown)
    assert "2026-04（予定）" in text
    assert "対応する PMS（製造販売後調査等）" in [s.value for s in at.subheader]


def test_product_page_has_trials_tab():
    """製品画面の「臨床試験」タブに、その製品の試験と役割（試験薬・対照薬）が出ることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/製品情報.py").run()
    at.selectbox[0].select("モックセプト皮下注").run()
    trials = next(d.value for d in at.dataframe if "この製品の役割" in d.value.columns)
    assert dict(zip(trials["研究ID"], trials["この製品の役割"])) == {"TR-0002": "試験薬", "TR-0004": "対照薬"}


def test_pms_table_shows_matching_trial():
    """製品画面の PMS の表に、登録番号が同じ臨床試験（研究ID）が出ることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/製品情報.py").run()
    at.selectbox[0].select("テスタミドOD錠").run()
    pms = next(d.value for d in at.dataframe if "対応する臨床試験" in d.value.columns)
    assert list(pms["対応する臨床試験"]) == ["TR-0003"]


def test_go_from_product_to_trial():
    """製品画面から、選んだ試験の詳細へ移動できることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/製品情報.py").run()
    at.button(key="product_go_trial").click().run()
    assert not at.exception
    assert at.title[0].value == "🧪 臨床試験"
    assert at.header[0].value.startswith("TR-0001")


def test_disease_page_has_trials():
    """疾患画面の「臨床試験」タブに、その疾患の試験が出ることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/疾患情報.py").run()
    trials = next(d.value for d in at.dataframe if "研究ID" in d.value.columns)
    assert list(trials["研究ID"]) == ["TR-0001", "TR-0004"]


def test_home_counts_and_searches_trials(loaded):
    """横断検索で、試験のタイトルや登録番号から試験が見つかることを確認します。"""
    assert [t["trial_id"] for t in search_all(loaded, "NCT-架空-0001")["trials"]] == [1]
    assert [t["trial_id"] for t in search_all(loaded, "長期投与試験")["trials"]] == [3]


# ---- 臨床試験のCSV ----

def test_trials_csv_with_two_registries_in_one_file(loaded):
    """同じCSVの中で「同じ試験の登録番号」に上の行の番号を書くと、1つの試験にまとまることを確認します。"""
    csv = (f"{header()}\n"
           + trial_line(registry="jRCT", registration_no="架空jRCT-0100") + "\n"
           + trial_line(same_trial_as="架空jRCT-0100", registration_no="NCT-架空-0100", title="", conditions_text="",
                        interventions_text="", test_products="") + "\n")
    assert validate(loaded, "trials", table(csv)) == []
    before = count(loaded, "SELECT COUNT(*) FROM trials")
    import_rows(loaded, "trials", table(csv), "山田", "テスト")
    assert count(loaded, "SELECT COUNT(*) FROM trials") == before + 1
    assert count(loaded, "SELECT COUNT(*) FROM trial_registrations") == 7


def test_ai_created_csv_is_recorded_as_ai(loaded):
    """「AIが作成したCSV」として取り込むと、入力方法が「AI抽出」・確認状態が「未確認」になることを確認します。"""
    import_rows(loaded, "trials", example_table("trials"), "山田", "AIの調査結果", entry_method="AI抽出")
    row = loaded.execute("SELECT entry_method, status FROM trial_details ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ("AI抽出", "未確認")
    reg = loaded.execute("SELECT entry_method FROM trial_registrations ORDER BY id DESC LIMIT 1").fetchone()
    assert reg[0] == "AI抽出"


def test_ai_entry_method_for_other_kinds(loaded):
    """承認などの CSV でも、AI抽出として記録できることを確認します。"""
    import_rows(loaded, "patents", example_table("patents"), "山田", "AIの調査結果", entry_method="AI抽出")
    assert loaded.execute("SELECT entry_method FROM patents ORDER BY id DESC LIMIT 1").fetchone()[0] == "AI抽出"
    with pytest.raises(ValueError):
        import_rows(loaded, "patents", example_table("patents"), "山田", "テスト", entry_method="API")


@pytest.mark.parametrize("values, expected", [
    ({"registration_no": "NCT-架空-0001"}, "すでに登録されています"),
    ({"same_trial_as": "存在しない番号"}, "登録済みにも"),
    ({"same_trial_as": "NCT-架空-0001", "registration_no": "NCT-架空-0101"}, "内容の列は空欄"),
    ({"title": ""}, "「研究タイトル」は必須"),
    ({"phase": "第5相"}, "「開発フェーズ」は次のどれか"),
    ({"start_date": "2025/04"}, "YYYY-MM-DD か YYYY-MM"),
    ({"end_date_type": "予定"}, "「未確認」にしてください"),
    ({"test_products": "存在しない錠"}, "製品「存在しない錠」が登録されていません"),
    ({"sponsor_company": "存在しない製薬"}, "スポンサーの企業"),
    ({"registry": "EU-CTR"}, "「レジストリ」は次のどれか"),
    ({"url": "example.com"}, "http"),
])
def test_trials_csv_errors(loaded, values, expected):
    """試験CSVの誤りが日本語で知らされ、何も登録されないことを確認します。"""
    csv = table(f"{header()}\n{trial_line(**values)}\n")
    errors = validate(loaded, "trials", csv)
    assert any(expected in e for e in errors), errors
    before = count(loaded, "SELECT COUNT(*) FROM change_log")
    with pytest.raises(ValueError):
        import_rows(loaded, "trials", csv, "山田", "テスト")
    assert count(loaded, "SELECT COUNT(*) FROM change_log") == before

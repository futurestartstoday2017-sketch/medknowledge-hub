"""
test_step6_search_compare.py：Step 6（横断検索・競合製品比較）のテストです。
"""

import pytest
from streamlit.testing.v1 import AppTest

from db.changes import supersede_record
from db.queries import get_product_facts
from services.comparison import COMPARISON_ITEMS, build_comparison, comparison_table, sources_table
from services.sample_loader import load_sample_data
from services.search import search_all
from tests.test_step2 import APP

COMPARE_PAGE = "pages/競合製品比較.py"


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


def names(results, kind, column):
    return [r[column] for r in results[kind]]


# ---- 横断検索 ----

def test_search_by_brand_and_generic_name(loaded):
    """販売名・一般名で製品が見つかることを確認します。"""
    assert names(search_all(loaded, "サンプリンα"), "products", "brand_name") == ["サンプリンα錠"]
    assert names(search_all(loaded, "テスタミド"), "products", "brand_name") == ["テスタミドOD錠"]


def test_search_by_company_name(loaded):
    """企業名で、その企業が製造販売元・販売元の製品が見つかることを確認します。"""
    found = names(search_all(loaded, "モデル薬品"), "products", "brand_name")
    assert sorted(found) == ["テスタミドOD錠", "モックセプト皮下注"]


def test_search_by_disease_name_in_english(loaded):
    """疾患の英語名でも見つかることを確認します（英字の大文字・小文字は区別しない）。"""
    assert names(search_all(loaded, "chronic disease b"), "diseases", "name_ja") == ["架空慢性疾患B"]


def test_search_fact_content_with_source(loaded):
    """医学的情報の本文で見つかり、結果に出典と対象の製品名が付いていることを確認します。"""
    facts = search_all(loaded, "受容体A")["facts"]
    assert len(facts) == 1
    assert facts[0]["subject_product"] == "サンプリンα錠"
    assert facts[0]["doc_title"] == "サンプリンα錠 添付文書（架空）"


def test_search_indication_fact_shows_product_and_disease(loaded):
    """適応症の効能・効果が見つかったとき、製品名と疾患名の両方がわかることを確認します。"""
    facts = search_all(loaded, "既存治療で効果不十分")["facts"]
    assert [(f["subject_product"], f["subject_disease"]) for f in facts] == [("モックセプト皮下注", "架空慢性疾患A")]


def test_search_and_condition(loaded):
    """空白で区切った語は、すべてを含むものだけが見つかることを確認します（AND検索）。"""
    assert len(search_all(loaded, "架空感染症Z")["safety"]) == 2
    assert len(search_all(loaded, "架空感染症Z 観察")["safety"]) == 1


def test_search_special_characters_are_literal(loaded):
    """% や _ を入力しても、すべてに一致してしまわないことを確認します。"""
    for keyword in ["%", "_", "%%"]:
        results = search_all(loaded, keyword)
        assert all(len(v) == 0 for v in results.values()), keyword


def test_search_empty_keyword(loaded):
    """空白だけのキーワードでは、何も返さないことを確認します。"""
    assert all(len(v) == 0 for v in search_all(loaded, "　 ").values())


def test_search_excludes_replaced_facts(loaded):
    """置き換えられた古い情報は、検索結果に出ないことを確認します。"""
    old = next(f for f in get_product_facts(loaded, 1) if f["fact_type"] == "作用機序")
    supersede_record(loaded, "medical_facts", old["id"], {"content": "新しい作用機序（架空）"}, "確認者", "テスト")
    assert search_all(loaded, "受容体A")["facts"] == []
    assert len(search_all(loaded, "新しい作用機序")["facts"]) == 1


def test_home_search_shows_results_and_navigates():
    """ホームで検索すると結果が表示され、ボタンで製品画面に移動できることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input[0].input("モックセプト").run()
    assert not at.exception
    assert any("製品（1 件）" in e.label for e in at.expander)
    at.button(key="search_product_3").click().run()
    assert at.title[0].value == "💊 製品情報"
    assert at.header[0].value == "モックセプト皮下注"


# ---- 競合製品比較 ----

def test_comparison_order_is_fixed(loaded):
    """製品の並び順が「対象企業 → 競合」で固定されていることを確認します。"""
    entries = build_comparison(loaded, 1)  # 架空慢性疾患A
    assert [e["product"]["category"] for e in entries] == ["対象企業", "競合"]


def test_comparison_table_layout(loaded):
    """比較表が、製品を列・項目を行にした形になっていることを確認します。"""
    table = comparison_table(build_comparison(loaded, 1))
    assert list(table.columns) == ["サンプリンα錠", "モックセプト皮下注"]
    assert list(table.index) == ["区分", "一般名"] + COMPARISON_ITEMS
    assert table.loc["投与経路", "モックセプト皮下注"] == "✅ 皮下注射（架空）"


def test_comparison_shows_status_icons(loaded):
    """比較表の値に、確認状態の印が付いていることを確認します（未確認を確認済みに見せない）。"""
    table = comparison_table(build_comparison(loaded, 2))  # 架空慢性疾患B
    assert table.loc["作用機序", "テスタミドOD錠"].startswith("⚠️")
    assert table.loc["作用機序", "モックセプト皮下注"].startswith("✅")


def test_verified_only_hides_unverified(loaded):
    """「原文確認済みだけ」にすると、未確認・再確認要の値が表に出ないことを確認します。"""
    entries = build_comparison(loaded, 1)
    table = comparison_table(entries, verified_only=True)
    assert "（原文確認済みの情報がないため非表示）" == table.loc["作用機序", "サンプリンα錠"]
    assert all("⚠️" not in v and "🔁" not in v for v in table.loc[COMPARISON_ITEMS].to_numpy().ravel())
    sources = sources_table(entries, verified_only=True)
    assert set(sources["確認状態"]) == {"✅ 原文確認済み"}


def test_sources_table_has_source_and_date(loaded):
    """出典一覧に、すべての値の文書名・版・該当箇所・確認日が入っていることを確認します。"""
    sources = sources_table(build_comparison(loaded, 1))
    assert len(sources) > 0
    for column in ["出典文書", "版", "該当箇所", "確認日", "原文URL"]:
        assert sources[column].notna().all() and (sources[column] != "").all(), column
    unverified = sources[sources["確認状態"] != "✅ 原文確認済み"]
    assert (unverified["確認日"] == "未確認").all()


def test_missing_item_is_marked(loaded):
    """情報が登録されていない項目は「未登録」と表示されることを確認します（空欄にしない）。"""
    entries = build_comparison(loaded, 1)
    entries[0]["items"]["剤形"] = []
    assert comparison_table(entries).loc["剤形", "サンプリンα錠"] == "未登録"


def test_compare_page_runs():
    """比較画面が表示され、疾患を切り替えても表が表示されることを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page(COMPARE_PAGE).run()
    assert not at.exception
    assert list(at.table[0].value.columns) == ["サンプリンα錠", "モックセプト皮下注"]
    at.selectbox[0].select("架空慢性疾患B").run()
    assert list(at.table[0].value.columns) == ["テスタミドOD錠", "モックセプト皮下注"]
    assert any("優劣を判定するものではありません" in i.value for i in at.info)

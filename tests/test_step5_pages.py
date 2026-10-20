"""
test_step5_pages.py：Step 5（製品・疾患の一覧と詳細画面）のテストです。

画面のテストに加えて、「未確認の情報を確認済みとして表示しない」
「過去の情報を表示しない」といった品質のルールが画面でも守られているかを確かめます。
"""

import pytest
from streamlit.testing.v1 import AppTest

from components.display import source_text, status_label
from db.changes import set_status, supersede_record
from db.queries import get_product_facts, list_diseases, list_products
from services.sample_loader import load_sample_data
from tests.test_step2 import APP

PRODUCT_PAGE = "pages/製品情報.py"
DISEASE_PAGE = "pages/疾患情報.py"


def open_page(page):
    """アプリを起動して、指定した画面に移動した状態を返します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page(page).run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def all_text(at):
    """画面に表示されている文字（本文・小さい文字・注意書き）をまとめて1つの文字列にします。"""
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [w.value for w in at.warning] + [i.value for i in at.info]
    return "\n".join(parts)


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


# ---- 製品情報画面 ----

def test_product_page_lists_all_products():
    """製品一覧に3件が表示され、選択欄で選べることを確認します。"""
    at = open_page(PRODUCT_PAGE)
    assert at.selectbox[0].options == ["サンプリンα錠", "テスタミドOD錠", "モックセプト皮下注"]
    assert len(at.dataframe[0].value) == 3


def test_product_page_filters_by_category():
    """区分で「競合」を選ぶと、競合製品だけが一覧に残ることを確認します。"""
    at = open_page(PRODUCT_PAGE)
    at.radio[0].set_value("競合").run()
    assert list(at.dataframe[0].value["販売名"]) == ["モックセプト皮下注"]


def test_product_detail_shows_status_and_source():
    """製品の詳細に、確認状態の印と出典（文書名・版・該当箇所）が表示されることを確認します。"""
    at = open_page(PRODUCT_PAGE)
    text = all_text(at)
    assert "✅ 原文確認済み" in text and "🔁 再確認要" in text
    assert "サンプリンα錠 添付文書（架空）" in text
    assert "2025年4月改訂（第2版）" in text
    assert "該当箇所：18. 薬効薬理" in text
    assert "（架空）本剤の成分に対し過敏症の既往歴のある患者" in text  # 安全性情報タブ


def test_unverified_product_is_shown_as_unverified():
    """未確認の情報だけの製品では、「確認済み」の印が出ないことを確認します。"""
    at = open_page(PRODUCT_PAGE)
    at.selectbox[0].select("テスタミドOD錠").run()
    # 確認状態の印が付いた見出しだけを集める
    headings = [m.value for m in at.markdown if any(icon in m.value for icon in ("✅", "⚠️", "🔁"))]
    assert headings, "確認状態の付いた見出しが見つかりません"
    assert all("⚠️ 未確認" in h for h in headings), headings
    assert "確認：未確認" in all_text(at)


def test_product_documents_show_old_and_current_versions():
    """文書タブに、最新版と過去の版の両方が表示されることを確認します。"""
    at = open_page(PRODUCT_PAGE)
    # 版の一覧の表（「区分」と「改訂年月」の列がある表）をすべて集める
    version_tables = [d.value for d in at.dataframe if "改訂年月" in d.value.columns]
    labels = set().union(*(set(t["区分"]) for t in version_tables))
    assert labels == {"最新版", "過去の版"}


def test_product_to_disease_navigation():
    """適応症タブのボタンを押すと、その疾患が選ばれた状態で疾患情報画面に移動することを確認します。"""
    at = open_page(PRODUCT_PAGE)
    at.selectbox[0].select("テスタミドOD錠").run()
    at.button[0].click().run()
    assert not at.exception
    assert at.title[0].value == "🩺 疾患情報"
    # 選択欄の値はID。架空慢性疾患B が選ばれていることを、表示されている見出しで確かめる
    assert at.header[0].value == "架空慢性疾患B"


# ---- 疾患情報画面 ----

def test_disease_page_shows_overview_and_products():
    """疾患の詳細に、概要と、対象企業の製品・競合製品が分けて表示されることを確認します。"""
    at = open_page(DISEASE_PAGE)
    text = all_text(at)
    assert "（架空）架空臓器Aの働きが少しずつ低下する、学習用の架空の疾患。" in text
    subheaders = [s.value for s in at.subheader]
    assert "対象企業の製品" in subheaders and "競合製品" in subheaders
    assert "架空慢性疾患A 診療ガイドライン（架空）" in text


def test_disease_notes_are_separated_from_facts():
    """学習メモのタブに、「事実ではない」ことの説明が表示されることを確認します。"""
    at = open_page(DISEASE_PAGE)
    assert any("原文で確認した事実ではありません" in c.value for c in at.caption)


def test_disease_to_product_navigation():
    """関連製品のボタンを押すと、その製品が選ばれた状態で製品情報画面に移動することを確認します。"""
    at = open_page(DISEASE_PAGE)
    at.button[-1].click().run()  # 最後のボタン = 競合製品（モックセプト皮下注）
    assert not at.exception
    assert at.title[0].value == "💊 製品情報"
    assert at.header[0].value == "モックセプト皮下注"


# ---- 画面に出すデータ（queries.py）の品質ルール ----

def test_replaced_fact_is_not_shown(loaded):
    """置き換えられた古い情報は表示されず、新しい情報だけが表示されることを確認します。"""
    facts = get_product_facts(loaded, 1)
    old = next(f for f in facts if f["fact_type"] == "作用機序")
    supersede_record(loaded, "medical_facts", old["id"], {"content": "新しい作用機序（架空）"}, "確認者", "テスト")

    contents = [f["content"] for f in get_product_facts(loaded, 1) if f["fact_type"] == "作用機序"]
    assert contents == ["新しい作用機序（架空）"]


def test_source_text_marks_old_version(loaded):
    """出典が過去の版のときは、出典の説明に「過去の版」と表示されることを確認します。"""
    fact = dict(get_product_facts(loaded, 1)[0])
    fact["version_is_current"] = 0
    assert "過去の版" in source_text(fact)


def test_status_labels():
    """3つの確認状態に、それぞれ違う印が付くことを確認します。"""
    assert status_label("原文確認済み") == "✅ 原文確認済み"
    assert status_label("未確認") == "⚠️ 未確認"
    assert status_label("再確認要") == "🔁 再確認要"


def test_list_tables_show_status_icons(loaded):
    """一覧表でも、薬効分類などに確認状態の印が付くことを確認します。"""
    products = list_products(loaded)
    testamid = products[products["販売名"] == "テスタミドOD錠"].iloc[0]
    assert testamid["薬効分類"].startswith("⚠️")
    assert testamid["製造販売元"].startswith("⚠️")


def test_disease_list_separates_target_and_competitor(loaded):
    """疾患一覧で、対象企業の製品と競合製品が別の列に表示されることを確認します。"""
    diseases = list_diseases(loaded).set_index("疾患名")
    assert diseases.loc["架空慢性疾患A", "対象企業の製品"] == "サンプリンα錠"
    assert diseases.loc["架空慢性疾患A", "競合製品"] == "モックセプト皮下注"


def test_status_change_is_reflected(loaded):
    """確認状態を変えると、画面に出すデータにもすぐ反映されることを確認します。"""
    fact = next(f for f in get_product_facts(loaded, 2) if f["fact_type"] == "作用機序")
    set_status(loaded, "medical_facts", fact["id"], "原文確認済み", "確認者", "原文と照合")
    updated = next(f for f in get_product_facts(loaded, 2) if f["fact_type"] == "作用機序")
    assert updated["status"] == "原文確認済み" and updated["verified_by"] == "確認者"

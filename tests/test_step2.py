"""
test_step2.py：Step 2（ホーム画面とメニュー）の自動テストです。
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).parent.parent
APP = str(ROOT / "app.py")

# メニューにある画面の一覧（ファイル名, 画面タイトル）
PAGES = [
    ("pages/製品情報.py", "💊 製品情報"),
    ("pages/疾患情報.py", "🩺 疾患情報"),
    ("pages/競合製品比較.py", "📊 競合製品比較"),
    ("pages/更新管理.py", "🔄 更新管理"),
]


def test_home_shows_counts():
    """起動するとホーム画面が開き、件数欄が表示されるか確認します（登録試験数は Step 10 で追加）。"""
    at = AppTest.from_file(APP).run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels == ["登録製品数", "登録疾患数", "登録文書数", "登録試験数", "更新確認待ち"]


def test_home_search_box_responds():
    """横断検索にキーワードを入れると、案内が表示されるか確認します。"""
    at = AppTest.from_file(APP).run()
    at.text_input[0].input("テスト").run()
    assert not at.exception
    assert any("テスト" in info.value for info in at.info)


@pytest.mark.parametrize("page_file, title", PAGES)
def test_each_page_opens(page_file, title):
    """メニューの各画面に移動して、エラーなく表示できるか確認します。"""
    at = AppTest.from_file(APP).run()
    at.switch_page(page_file).run()
    assert not at.exception
    assert at.title[0].value == title

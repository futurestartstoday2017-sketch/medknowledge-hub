"""
app.py：アプリの起動ファイルです。

`streamlit run app.py` で起動します。このファイルでは次の2つだけを行います。
  1. 全画面に共通する設定（タブ名・レイアウト・注意書き）
  2. サイドバーのメニュー（どの画面があるか）の定義

各画面の中身は pages/ フォルダの中のファイルに書きます。
"""

import streamlit as st

from db.database import get_connection, init_db
from services.sample_loader import load_sample_data_if_empty

# ページ全体の設定（ブラウザのタブ名と、PC向けの横長レイアウト）
# ※ st.set_page_config は、他の st.〇〇 より先に呼ぶ必要があります
st.set_page_config(page_title="MedKnowledge Hub", page_icon="💊", layout="wide")


# @st.cache_resource：この関数は、アプリを起動してから最初の1回だけ実行される
# （画面を操作するたびにDBの準備をくり返さないため）
@st.cache_resource
def prepare_database():
    """データベースがなければ作り、空なら架空サンプルデータを登録します。"""
    init_db()
    conn = get_connection()
    try:
        load_sample_data_if_empty(conn)
    finally:
        conn.close()


prepare_database()

# サイドバーのメニューに並べる画面の一覧
# st.Page(ファイルの場所, title=メニューに表示する名前, icon=アイコン, url_path=URLの末尾)
# url_path は英字にしておくと、ブラウザのアドレス欄が文字化けしにくくなります
PAGES = [
    st.Page("pages/ホーム.py", title="ホーム", icon="🏠", default=True),
    st.Page("pages/製品情報.py", title="製品情報", icon="💊", url_path="products"),
    st.Page("pages/疾患情報.py", title="疾患情報", icon="🩺", url_path="diseases"),
    st.Page("pages/競合製品比較.py", title="競合製品比較", icon="📊", url_path="compare"),
    st.Page("pages/更新管理.py", title="更新管理", icon="🔄", url_path="updates"),
    st.Page("pages/データ管理.py", title="データ管理", icon="🗂️", url_path="data"),
]

# メニューを作り、選ばれた画面を表示する
current_page = st.navigation(PAGES)

# 全画面共通の注意書き（サイドバーの下に表示）
st.sidebar.caption(
    "⚠️ 個人の学習・情報整理用アプリです。実際の診療判断には使用しないでください。"
)

current_page.run()

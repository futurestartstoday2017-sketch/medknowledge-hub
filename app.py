"""
app.py：アプリの起動ファイルです。

`streamlit run app.py` で起動します。このファイルでは次の2つだけを行います。
  1. 全画面に共通する設定（タブ名・レイアウト・注意書き）
  2. サイドバーのメニュー（どの画面があるか）の定義

各画面の中身は pages/ フォルダの中のファイルに書きます。
"""

import streamlit as st

from db.database import MODES, current_db_path, get_connection, get_mode, init_db
from services.sample_loader import load_sample_data_if_empty

# ページ全体の設定（ブラウザのタブ名と、PC向けの横長レイアウト）
# ※ st.set_page_config は、他の st.〇〇 より先に呼ぶ必要があります
st.set_page_config(page_title="MedKnowledge Hub", page_icon="💊", layout="wide")


# @st.cache_resource：この関数は、同じ引数（ここではデータベースの場所）について最初の1回だけ実行される
# （画面を操作するたびにDBの準備をくり返さないため。データベースを切り替えると、切り替え先で1回実行される）
@st.cache_resource
def prepare_database(db_path, mode):
    """
    データベースがなければ作り、古ければ最新の形にします。
    架空データ用のデータベースが空なら、架空サンプルデータを登録します（実データ用には登録しない）。
    """
    init_db(db_path)
    if mode == "sample":
        conn = get_connection(db_path)
        try:
            load_sample_data_if_empty(conn)
        finally:
            conn.close()


mode = get_mode()
prepare_database(str(current_db_path()), mode)

# サイドバーのメニューに並べる画面の一覧
# st.Page(ファイルの場所, title=メニューに表示する名前, icon=アイコン, url_path=URLの末尾)
# url_path は英字にしておくと、ブラウザのアドレス欄が文字化けしにくくなります
PAGES = [
    st.Page("pages/ホーム.py", title="ホーム", icon="🏠", default=True),
    st.Page("pages/製品情報.py", title="製品情報", icon="💊", url_path="products"),
    st.Page("pages/疾患情報.py", title="疾患情報", icon="🩺", url_path="diseases"),
    st.Page("pages/競合製品比較.py", title="競合製品比較", icon="📊", url_path="compare"),
    st.Page("pages/臨床試験.py", title="臨床試験", icon="🧪", url_path="trials"),
    st.Page("pages/更新管理.py", title="更新管理", icon="🔄", url_path="updates"),
    st.Page("pages/データ管理.py", title="データ管理", icon="🗂️", url_path="data"),
]

# メニューを作り、選ばれた画面を表示する
current_page = st.navigation(PAGES)

# 今どちらのデータベースを使っているか（架空データ／実データ）を、すべての画面で表示する
st.sidebar.markdown(f"**使用中のデータ：** {MODES[mode]}")

# 全画面共通の注意書き（サイドバーの下に表示）
st.sidebar.caption(
    "⚠️ 個人の学習・情報整理用アプリです。実際の診療判断には使用しないでください。"
)

current_page.run()

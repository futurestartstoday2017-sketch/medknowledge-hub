"""
app.py：アプリの起動ファイル兼ホーム画面です。

`streamlit run app.py` で起動すると、最初にこの画面が表示されます。
（Step 1 では仮の画面です。件数表示や横断検索は Step 2 以降で作ります。）
"""

import streamlit as st

# ページ全体の設定（ブラウザのタブ名と、PC向けの横長レイアウト）
# ※ st.set_page_config は、他の st.〇〇 より先に呼ぶ必要があります
st.set_page_config(page_title="MedKnowledge Hub", page_icon="💊", layout="wide")

st.title("💊 MedKnowledge Hub")
st.info("Step 1：フォルダ構成の準備が完了しました。ホーム画面は Step 2 で作ります。")

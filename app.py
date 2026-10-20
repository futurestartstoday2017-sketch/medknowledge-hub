"""
app.py：アプリの起動ファイル兼ホーム画面です。

`streamlit run app.py` で起動すると、最初にこの画面が表示されます。
"""

import streamlit as st

from db.database import init_db
from db.queries import count_diseases, count_products

# ページ全体の設定（ブラウザのタブ名と、PC向けの横長レイアウト）
# ※ st.set_page_config は、他の st.〇〇 より先に呼ぶ必要があります
st.set_page_config(page_title="MedKnowledge Hub", page_icon="💊", layout="wide")

# データベースの準備（テーブルがなければ作り、空ならサンプルデータを登録する）
init_db()

st.title("💊 MedKnowledge Hub")
st.write("製品情報・疾患情報を一元管理し、検索・比較・学習するためのアプリです。")
st.caption("※ 登録されているデータはすべて学習用の架空のものです。")

# 登録件数をデータベースから数えて、横に並べて表示する
col1, col2 = st.columns(2)
col1.metric("登録製品数", count_products())
col2.metric("登録疾患数", count_diseases())

st.info("第2段階：データベースとサンプルデータの準備が完了しました。各画面はこれから追加していきます。")

"""
app.py：アプリの起動ファイル兼ホーム画面です。

`streamlit run app.py` で起動すると、最初にこの画面が表示されます。
（第1段階では仮のホーム画面です。製品数・疾患数は第2段階でDBから取得します。）
"""

import streamlit as st

# ページ全体の設定（ブラウザのタブ名と、PC向けの横長レイアウト）
# ※ st.set_page_config は、他の st.〇〇 より先に呼ぶ必要があります
st.set_page_config(page_title="MedKnowledge Hub", page_icon="💊", layout="wide")

st.title("💊 MedKnowledge Hub")
st.write("製品情報・疾患情報を一元管理し、検索・比較・学習するためのアプリです。")
st.caption("※ 登録されているデータはすべて学習用の架空のものです。")

# 登録件数を横に並べて表示する（今は仮の値 0）
col1, col2 = st.columns(2)
col1.metric("登録製品数", 0)
col2.metric("登録疾患数", 0)

st.info("第1段階：開発環境の準備が完了しました。各機能はこれから段階的に追加していきます。")

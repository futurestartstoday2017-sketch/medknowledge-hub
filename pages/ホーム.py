"""
ホーム.py：① ホーム画面です。

登録件数の一覧、横断検索の入力欄、各画面への入口を表示します。
（Step 2 では件数は「—」の仮表示です。データベースとは Step 3 以降でつなぎます。）
"""

import streamlit as st

st.title("💊 MedKnowledge Hub")
st.write("製品・競合製品・疾患・文書の公開情報を整理し、検索・比較・学習するためのアプリです。")

# ---- 登録件数（4つを横に並べて表示）----
# データベースができるまでは「—」を表示しておく
col1, col2, col3, col4 = st.columns(4)
col1.metric("登録製品数", "—")
col2.metric("登録疾患数", "—")
col3.metric("登録文書数", "—")
col4.metric("更新確認待ち", "—")

st.divider()  # 区切り線

# ---- 横断検索 ----
st.subheader("🔍 横断検索")
keyword = st.text_input(
    "キーワード",
    placeholder="販売名・一般名・疾患名などを入力",
    label_visibility="collapsed",  # 見出しと重なるので、入力欄のラベルは隠す
)
if keyword:
    # 検索の仕組みは Step 6 で作る。今は入力されたことだけを表示する
    st.info(f"「{keyword}」の検索は Step 6 で使えるようになります。")

st.divider()

# ---- 各画面への入口 ----
st.subheader("メニュー")
nav1, nav2, nav3, nav4 = st.columns(4)
# st.page_link：押すとその画面に移動するリンク
nav1.page_link("pages/製品情報.py", label="製品情報", icon="💊")
nav1.caption("製品の一覧・詳細、適応症、安全性情報")
nav2.page_link("pages/疾患情報.py", label="疾患情報", icon="🩺")
nav2.caption("疾患の一覧・詳細、関連製品、関連文献")
nav3.page_link("pages/競合製品比較.py", label="競合製品比較", icon="📊")
nav3.caption("同じ適応症の製品を出典つきで比較")
nav4.page_link("pages/更新管理.py", label="更新管理", icon="🔄")
nav4.caption("文書の改訂・確認状況と更新履歴")

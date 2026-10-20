"""
ホーム.py：① ホーム画面です。

登録件数の一覧、横断検索の入力欄、各画面への入口を表示します。
"""

from contextlib import closing

import streamlit as st

from components.display import escape, go_to_disease, go_to_product, show_fact
from db.database import get_connection
from db.queries import get_home_counts
from services.search import search_all

st.title("💊 MedKnowledge Hub")
st.write("製品・競合製品・疾患・文書の公開情報を整理し、検索・比較・学習するためのアプリです。")

# ---- 登録件数（4つを横に並べて表示）----
conn = get_connection()
try:
    counts = get_home_counts(conn)
finally:
    conn.close()  # 使い終わった接続は必ず閉じる

col1, col2, col3, col4 = st.columns(4)
col1.metric("登録製品数", counts["products"])
col2.metric("登録疾患数", counts["diseases"])
col3.metric("登録文書数", counts["documents"])
col4.metric(
    "更新確認待ち",
    counts["unverified"] + counts["recheck"],
    help="原文の確認がまだ済んでいない情報の件数です（⚠️ 未確認 ＋ 🔁 再確認要）",
)
col4.caption(f"⚠️ 未確認 {counts['unverified']} 件 ／ 🔁 再確認要 {counts['recheck']} 件")

# 架空のサンプルデータが入っているときは、実在の情報と誤解しないよう、はっきり表示する
if counts["sample_companies"]:
    st.warning("現在は、動作確認用の**架空データ**が登録されています。実在する製品・疾患の情報ではありません。")

st.divider()  # 区切り線

# ---- 横断検索 ----
st.subheader("🔍 横断検索")
keyword = st.text_input(
    "キーワード",
    placeholder="販売名・一般名・企業名・疾患名・文書名・医学的情報の内容などを入力",
    label_visibility="collapsed",  # 見出しと重なるので、入力欄のラベルは隠す
)
st.caption("空白で区切って複数の語を入れると、すべての語を含むものを探します。")

if keyword.strip():
    with closing(get_connection()) as conn:
        results = search_all(conn, keyword)
    total = sum(len(v) for v in results.values())

    if total == 0:
        st.info(f"「{keyword}」に一致する情報は見つかりませんでした。")
    else:
        st.success(f"「{keyword}」の検索結果：{total} 件")

    # 種類ごとに、件数つきの折りたたみ欄（expander）で表示する
    if results["products"]:
        with st.expander(f"💊 製品（{len(results['products'])} 件）", expanded=True):
            for p in results["products"]:
                st.markdown(f"**{escape(p['brand_name'])}**（{escape(p['generic_name'] or '—')}／{p['category']}）")
                go_to_product(p["id"], key=f"search_product_{p['id']}")

    if results["diseases"]:
        with st.expander(f"🩺 疾患（{len(results['diseases'])} 件）", expanded=True):
            for d in results["diseases"]:
                english = f"（{escape(d['name_en'])}）" if d["name_en"] else ""
                st.markdown(f"**{escape(d['name_ja'])}**{english}")
                go_to_disease(d["id"], key=f"search_disease_{d['id']}")

    if results["documents"]:
        with st.expander(f"📄 文書（{len(results['documents'])} 件）", expanded=True):
            for doc in results["documents"]:
                st.markdown(f"**{escape(doc['title'])}**（{doc['doc_type']}）")
                if doc["product_id"]:
                    go_to_product(doc["product_id"], key=f"search_doc_p_{doc['id']}", label="関連する製品を見る")
                elif doc["disease_id"]:
                    go_to_disease(doc["disease_id"], key=f"search_doc_d_{doc['id']}", label="関連する疾患を見る")

    if results["facts"]:
        with st.expander(f"📋 医学的情報（{len(results['facts'])} 件）", expanded=True):
            for fact in results["facts"]:
                subject = " × ".join(x for x in (fact["subject_product"], fact["subject_disease"]) if x)
                show_fact(fact, title=f"{subject}：{fact['fact_type']}")
                if fact["subject_product_id"]:
                    go_to_product(fact["subject_product_id"], key=f"search_fact_{fact['id']}")
                else:
                    go_to_disease(fact["subject_disease_id"], key=f"search_fact_{fact['id']}")

    if results["safety"]:
        with st.expander(f"⚠️ 安全性情報（{len(results['safety'])} 件）", expanded=True):
            for fact in results["safety"]:
                show_fact(fact, title=f"{fact['subject_product']}：{fact['category']}")
                go_to_product(fact["subject_product_id"], key=f"search_safety_{fact['id']}")

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

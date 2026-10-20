"""
製品情報.py：② 製品情報画面です。

上に製品一覧、下に選んだ製品の詳細をタブで表示します。
医学的情報・安全性情報は、すべて確認状態と出典（文書名・版・該当箇所・確認日）付きで表示します。
"""

from contextlib import closing

import streamlit as st

from components.display import (
    PRODUCT_FACT_ORDER, SAFETY_ORDER, STATUS_LEGEND, escape, show_documents, show_fact,
    show_facts_in_order, show_notes, show_planned,
)
from db.database import get_connection
from db.queries import (
    get_documents, get_notes, get_product, get_product_companies, get_product_facts,
    get_product_indications, get_safety_info, list_products,
)

st.title("💊 製品情報")
st.caption(STATUS_LEGEND)

# closing(...)：with の中の処理が終わったら、データベースの接続を自動で閉じる
with closing(get_connection()) as conn:
    products = list_products(conn)

if products.empty:
    st.info("製品が登録されていません。")
    st.stop()  # ここで画面の表示を終える

# ---- 製品一覧 ----
st.subheader("製品一覧")
category = st.radio("区分で絞り込み", ["すべて", "対象企業", "競合"], horizontal=True)
shown = products if category == "すべて" else products[products["区分"] == category]
st.dataframe(shown.drop(columns="id"), hide_index=True)

# ---- 詳細を表示する製品を選ぶ ----
# int(...)：表から取り出したIDを普通の整数に直す（SQLiteにそのまま渡せる形にするため）
names = {int(i): name for i, name in zip(products["id"], products["販売名"])}
options = list(names)
# 疾患情報画面などから移動してきたときは、その製品を最初から選んでおく
goto = st.session_state.pop("goto_product_id", None)
selected_id = st.selectbox(
    "詳細を表示する製品",
    options,
    index=options.index(goto) if goto in options else 0,
    format_func=lambda product_id: names[product_id],
)

with closing(get_connection()) as conn:
    product = get_product(conn, selected_id)
    companies = get_product_companies(conn, selected_id)
    facts = get_product_facts(conn, selected_id)
    indications = get_product_indications(conn, selected_id)
    safety = get_safety_info(conn, selected_id)
    documents = get_documents(conn, product_id=selected_id)
    notes = get_notes(conn, product_id=selected_id)

st.divider()
st.header(escape(product["brand_name"]))

# 基本情報を横に並べる
col1, col2, col3, col4 = st.columns(4)
col1.markdown(f"**一般名**  \n{escape(product['generic_name'] or '—')}")
col2.markdown(f"**区分**  \n{product['category']}")
col3.markdown(
    f"**公式製品URL**  \n[開く]({product['official_url']})" if product["official_url"]
    else "**公式製品URL**  \n未登録"
)
col4.markdown(f"**最終確認日**  \n{product['last_checked_on'] or '未確認'}")

tabs = st.tabs(["基本情報", "適応症", "安全性情報", "承認・再審査", "ライセンス・特許", "文書", "学習メモ"])

with tabs[0]:
    st.subheader("製造販売元・販売元")
    show_facts_in_order(companies, "role", ["製造販売元", "販売元"])
    st.subheader("医学的情報")
    show_facts_in_order(facts, "fact_type", PRODUCT_FACT_ORDER)

with tabs[1]:
    if not indications:
        st.info("適応症は登録されていません。")
    for indication in indications:
        st.subheader(escape(indication["disease_name"]))
        if indication["facts"]:
            for fact in indication["facts"]:
                show_fact(fact, title="承認された効能・効果")
        else:
            st.warning("効能・効果の文言が、出典付きで登録されていません。")
        # ボタンを押したら、その疾患を選んだ状態で疾患情報画面に移動する
        if st.button("この疾患の情報を見る", key=f"to_disease_{indication['id']}"):
            st.session_state["goto_disease_id"] = indication["disease_id"]
            st.switch_page("pages/疾患情報.py")

with tabs[2]:
    show_facts_in_order(safety, "category", SAFETY_ORDER, "安全性情報は登録されていません。")

with tabs[3]:
    show_planned(9, "承認情報（承認年月日）・再審査期間の表示")

with tabs[4]:
    show_planned(9, "導入元・提携先、ライセンス契約、特許情報の表示")

with tabs[5]:
    show_documents(documents)

with tabs[6]:
    show_notes(notes)

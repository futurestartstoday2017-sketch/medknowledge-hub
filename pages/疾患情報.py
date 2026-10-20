"""
疾患情報.py：③ 疾患情報画面です。

上に疾患一覧、下に選んだ疾患の詳細（MA学習の整理）をタブで表示します。
医学的情報は、すべて確認状態と出典付きで表示します。
学習メモ・考察（エビデンスギャップなど）は、事実とは分けて表示します。
"""

from contextlib import closing

import streamlit as st

from components.display import (
    DISEASE_OVERVIEW_ORDER, DISEASE_TREATMENT_ORDER, STATUS_LEGEND, escape, go_to_product, show_documents,
    show_fact, show_facts_in_order, show_notes, show_planned,
)
from db.database import get_connection
from db.queries import get_disease, get_disease_facts, get_disease_products, get_documents, get_notes, list_diseases

st.title("🩺 疾患情報")
st.caption(STATUS_LEGEND)

with closing(get_connection()) as conn:
    diseases = list_diseases(conn)

if diseases.empty:
    st.info("疾患が登録されていません。")
    st.stop()

# ---- 疾患一覧 ----
st.subheader("疾患一覧")
st.dataframe(diseases.drop(columns="id"), hide_index=True)

# ---- 詳細を表示する疾患を選ぶ ----
# int(...)：表から取り出したIDを普通の整数に直す（SQLiteにそのまま渡せる形にするため）
names = {int(i): name for i, name in zip(diseases["id"], diseases["疾患名"])}
options = list(names)
# 製品情報画面から移動してきたときは、その疾患を最初から選んでおく
goto = st.session_state.pop("goto_disease_id", None)
selected_id = st.selectbox(
    "詳細を表示する疾患",
    options,
    index=options.index(goto) if goto in options else 0,
    format_func=lambda disease_id: names[disease_id],
)

with closing(get_connection()) as conn:
    disease = get_disease(conn, selected_id)
    facts = get_disease_facts(conn, selected_id)
    products = get_disease_products(conn, selected_id)
    documents = get_documents(conn, disease_id=selected_id)
    notes = get_notes(conn, disease_id=selected_id)

st.divider()
st.header(escape(disease["name_ja"]))
if disease["name_en"]:
    st.caption(escape(disease["name_en"]))

tabs = st.tabs(["概要・アンメットニーズ", "治療・ガイドライン", "関連製品", "臨床試験", "主要論文", "文書",
                "エビデンスギャップ・メモ"])

with tabs[0]:
    overview = [f for f in facts if f["fact_type"] in DISEASE_OVERVIEW_ORDER]
    show_facts_in_order(overview, "fact_type", DISEASE_OVERVIEW_ORDER)

with tabs[1]:
    treatment = [f for f in facts if f["fact_type"] in DISEASE_TREATMENT_ORDER]
    show_facts_in_order(treatment, "fact_type", DISEASE_TREATMENT_ORDER)
    st.subheader("診療ガイドライン")
    show_documents([d for d in documents if d["doc_type"] == "診療ガイドライン"])

with tabs[2]:
    if not products:
        st.info("この疾患に適応のある製品は登録されていません。")
    # 対象企業の製品と競合製品を分けて表示する（優劣の判定はしない）
    for category in ["対象企業", "競合"]:
        group = [p for p in products if p["category"] == category]
        if not group:
            continue
        st.subheader("対象企業の製品" if category == "対象企業" else "競合製品")
        for product in group:
            st.markdown(f"#### {escape(product['brand_name'])}（{escape(product['generic_name'] or '—')}）")
            if product["facts"]:
                for fact in product["facts"]:
                    show_fact(fact, title="承認された効能・効果")
            else:
                st.warning("効能・効果の文言が、出典付きで登録されていません。")
            # ボタンを押したら、その製品を選んだ状態で製品情報画面に移動する
            go_to_product(product["product_id"], key=f"to_product_{product['id']}")

with tabs[3]:
    show_planned(10, "この疾患の臨床試験の一覧")

with tabs[4]:
    show_planned(12, "この疾患の主要論文の一覧")

with tabs[5]:
    show_documents(documents)

with tabs[6]:
    show_notes(notes)

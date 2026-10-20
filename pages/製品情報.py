"""
製品情報.py：② 製品情報画面です。

上に製品一覧、下に選んだ製品の詳細をタブで表示します。
医学的情報・安全性情報・承認・特許などは、すべて確認状態と出典（文書名・版・該当箇所・確認日）付きで表示します。
「承認・再審査・PMS」タブの最初に、承認から特許満了までのタイムラインを表示します。
"""

from contextlib import closing

import streamlit as st

from components.display import (
    DISCLOSURE_LEGEND, PRODUCT_FACT_ORDER, SAFETY_ORDER, STATUS_LEGEND, disclosed_value, escape, go_to_disease,
    show_documents, show_fact, show_facts_in_order, show_facts_table, show_notes, show_timeline,
    show_trials_with_links,
)
from db.database import get_connection
from db.queries import (
    get_documents, get_notes, get_product, get_product_companies, get_product_facts,
    get_product_indications, get_product_regulatory, get_safety_info, list_products, list_trials,
    trial_codes_by_registration,
)
from services.timeline import build_timeline

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
    regulatory = get_product_regulatory(conn, selected_id)
    # この製品が試験薬・対照薬などになっている臨床試験
    product_trials = [t for t in list_trials(conn) if any(p["product_id"] == selected_id for p in t["products"])]
    trial_codes = trial_codes_by_registration(conn)
    timeline = build_timeline(conn, selected_id)

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

tabs = st.tabs(["基本情報", "適応症", "安全性情報", "承認・再審査・PMS", "ライセンス・特許", "臨床試験", "文書",
               "学習メモ"])

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
        go_to_disease(indication["disease_id"], key=f"to_disease_{indication['id']}")

with tabs[2]:
    show_facts_in_order(safety, "category", SAFETY_ORDER, "安全性情報は登録されていません。")

with tabs[3]:
    show_timeline(timeline)

    st.subheader("承認の履歴")
    show_facts_table(regulatory["approvals"], [
        ("承認年月日", lambda f: f["approval_date"]),
        ("承認の種類", lambda f: f["approval_type"]),
        ("対象", lambda f: f["subject"]),
        ("承認内容", lambda f: f["content"]),
        ("承認番号", lambda f: f["approval_number"] or "—"),
    ], "承認情報は登録されていません。")

    st.subheader("再審査期間")
    st.caption(DISCLOSURE_LEGEND)
    show_facts_table(regulatory["reexaminations"], [
        ("対象", lambda f: f["subject"]),
        ("説明", lambda f: f["content"]),
        ("再審査期間（年）", lambda f: disclosed_value(f["disclosure"], f["period_years"])),
        ("再審査期間の開始日", lambda f: disclosed_value(f["disclosure"], f["start_date"])),
        ("再審査期間の終了日", lambda f: disclosed_value(f["disclosure"], f["end_date"])),
    ], "再審査期間は登録されていません。")

    st.subheader("PMS（製造販売後調査等）")
    show_facts_table(regulatory["pms_studies"], [
        ("種類", lambda f: f["study_type"]),
        ("調査名", lambda f: f["title"]),
        ("全例調査か", lambda f: f["all_case"]),
        ("承認条件か", lambda f: f["approval_condition"]),
        ("実施状況", lambda f: f["progress"]),
        ("目標症例数", lambda f: f["target_cases"] or "—"),
        ("実施期間", lambda f: disclosed_value(
            f["disclosure"], f"{f['start_date'] or '?'} 〜 {f['end_date'] or '（終了日なし）'}")),
        ("登録番号", lambda f: f["registration_no"] or "—"),
        ("対応する臨床試験", lambda f: trial_codes.get(f["registration_no"], "—")),
    ], "PMSは登録されていません。")

with tabs[4]:
    st.caption(DISCLOSURE_LEGEND)
    st.subheader("導入元・提携先（ライセンス）")
    show_facts_table(regulatory["licenses"], [
        ("相手先", lambda f: f["item"]),
        ("契約の種類", lambda f: f["license_type"]),
        ("対象地域", lambda f: f["territory"] or "—"),
        ("契約内容", lambda f: f["content"]),
        ("契約開始日", lambda f: disclosed_value(f["disclosure"], f["contract_start"])),
        ("契約終了日", lambda f: disclosed_value(f["disclosure"], f["contract_end"])),
        ("開示年度", lambda f: f["disclosed_fiscal_year"] or "—"),
    ], "ライセンス情報は登録されていません。")

    st.subheader("特許")
    show_facts_table(regulatory["patents"], [
        ("特許番号", lambda f: f["patent_number"]),
        ("国・地域", lambda f: f["country"]),
        ("種類", lambda f: f["patent_kind"]),
        ("発明の名称", lambda f: f["title"] or "—"),
        ("特許の存続期間満了日", lambda f: disclosed_value(f["disclosure"], f["expiry_date"])),
        ("延長登録後の満了日", lambda f: disclosed_value(f["disclosure"], f["extended_expiry_date"])),
    ], "特許は登録されていません。")

with tabs[5]:
    show_trials_with_links(product_trials, "product", product_id=selected_id,
                           empty_message="この製品が試験薬・対照薬になっている臨床試験は登録されていません。")

with tabs[6]:
    show_documents(documents)

with tabs[7]:
    show_notes(notes)

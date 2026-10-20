"""
臨床試験.py：⑤ 臨床試験画面です。

上で条件を選んで試験の一覧を絞り込み、下に選んだ試験の詳細を表示します。
1つの試験が複数のレジストリ（jRCT・ClinicalTrials.gov など）に登録されていても、1件として数えます。
試験の内容・登録番号は、すべて確認状態と出典（登録ページ）付きで表示します。
"""

from contextlib import closing

import streamlit as st

from components.display import (
    STATUS_LEGEND, escape, go_to_disease, go_to_product, show_facts_table, source_text, status_label,
    trial_date, trials_table,
)
from db.database import get_connection
from db.queries import get_trial_pms, list_trials

st.title("🧪 臨床試験")
st.caption(STATUS_LEGEND)
st.caption("登録の対象：対象企業・競合の製品が試験薬・対照薬になっている試験。"
           "日付は登録ページの記載のとおりです（月までしかわからないものは YYYY-MM。日は推測で補いません）。")

with closing(get_connection()) as conn:
    trials = list_trials(conn)

if not trials:
    st.info("臨床試験は登録されていません（データ管理画面の CSV インポートから登録できます）。")
    st.stop()

# ---- 絞り込み ----
def options(values):
    """選択肢を、重複なし・並べ替え済みのリストにします。"""
    return sorted({v for v in values if v})


filters = st.columns(3)
chosen_products = filters[0].multiselect("製品", options(p["brand_name"] for t in trials for p in t["products"]))
chosen_diseases = filters[1].multiselect("疾患", options(d["name_ja"] for t in trials for d in t["diseases"]))
chosen_phases = filters[2].multiselect("フェーズ", options((t["detail"] or {}).get("phase") for t in trials))
filters = st.columns(3)
chosen_status = filters[0].multiselect("募集状況", options((t["detail"] or {}).get("recruitment_status") for t in trials))
chosen_sponsor = filters[1].multiselect("スポンサー区分", ["対象企業", "競合", "その他"])
chosen_registry = filters[2].multiselect("レジストリ", options(r["registry"] for t in trials for r in t["registrations"]))


def matches(trial):
    """選んだ条件にすべて合う試験かどうかを返します（条件を選んでいない項目は、すべて合うものとする）。"""
    detail = trial["detail"] or {}
    checks = [
        (chosen_products, {p["brand_name"] for p in trial["products"]}),
        (chosen_diseases, {d["name_ja"] for d in trial["diseases"]}),
        (chosen_phases, {detail.get("phase")}),
        (chosen_status, {detail.get("recruitment_status")}),
        (chosen_sponsor, {trial["sponsor_category"]}),
        (chosen_registry, {r["registry"] for r in trial["registrations"]}),
    ]
    return all(not chosen or set(chosen) & values for chosen, values in checks)


shown = [t for t in trials if matches(t)]
st.subheader(f"試験の一覧（{len(shown)} 件 ／ 全 {len(trials)} 件）")
st.caption("複数のレジストリに登録された試験も、1件として数えています。")
if not shown:
    st.info("条件に合う試験はありません。")
    st.stop()
st.dataframe(trials_table(shown), hide_index=True)

# ---- 詳細を表示する試験を選ぶ ----
labels = {t["trial_id"]: f"{t['code']}　{(t['detail'] or {}).get('title', '（内容が未登録）')}" for t in shown}
ids = list(labels)
goto = st.session_state.pop("goto_trial_id", None)  # ほかの画面から移動してきたときは、その試験を選んでおく
selected_id = st.selectbox("詳細を表示する試験", ids, index=ids.index(goto) if goto in ids else 0,
                           format_func=lambda i: labels[i])
trial = next(t for t in shown if t["trial_id"] == selected_id)
detail = trial["detail"]

st.divider()
st.header(f"{trial['code']}　{escape(detail['title']) if detail else '（内容が未登録）'}")

if detail:
    st.markdown(f"**試験の内容**　{status_label(detail['status'])}")
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f"**開発フェーズ**  \n{detail['phase']}")
    col2.markdown(f"**研究の種類**  \n{detail['study_type']}")
    col3.markdown(f"**募集状況**  \n{detail['recruitment_status']}")
    col4.markdown(f"**結果公開状況**  \n{detail['results_status']}")
    col1, col2, col3 = st.columns(3)
    sponsor = detail["sponsor_company"] or detail["sponsor_text"] or "—"
    col1.markdown(f"**スポンサー**  \n{escape(sponsor)}（{trial['sponsor_category']}）")
    col2.markdown(f"**研究開始日**  \n{trial_date(detail['start_date'], detail['start_date_type'])}")
    col3.markdown(f"**研究終了日**  \n{trial_date(detail['end_date'], detail['end_date_type'])}")
    st.markdown(f"**対象疾患（登録ページの記載）**  \n{escape(detail['conditions_text'])}")
    st.markdown(f"**試験薬・介入（登録ページの記載）**  \n{escape(detail['interventions_text'])}")
    st.markdown(f"**研究デザイン**  \n{escape(detail['design'] or '—')}")
    st.markdown(f"**主要評価項目**  \n{escape(detail['primary_endpoint'] or '—')}")
    st.caption(source_text(detail))
else:
    st.warning("この試験の内容（タイトルなど）が登録されていません。")

st.subheader("登録番号")
show_facts_table(trial["registrations"], [
    ("レジストリ", lambda r: r["registry"]),
    ("登録番号", lambda r: r["registration_no"]),
    ("他の登録番号（登録ページの記載）", lambda r: r["secondary_ids"] or "—"),
    ("登録情報の最終確認日", lambda r: r["last_checked_on"]),
], "登録番号がありません。")

st.subheader("このアプリでの分類")
st.caption("試験薬・対照薬・疾患が、このアプリのどの製品・疾患にあたるかの分類です（自分で行うひも付け）。")
left, right = st.columns(2)
with left:
    for product in trial["products"]:
        st.markdown(f"**{product['role']}**：{escape(product['brand_name'])}（{product['category']}）")
        go_to_product(product["product_id"], key=f"trial_product_{product['product_id']}_{product['role']}")
with right:
    for disease in trial["diseases"]:
        st.markdown(f"**疾患**：{escape(disease['name_ja'])}")
        go_to_disease(disease["disease_id"], key=f"trial_disease_{disease['disease_id']}")

# ---- 登録番号が同じ PMS ----
with closing(get_connection()) as conn:
    pms = get_trial_pms(conn, [r["registration_no"] for r in trial["registrations"]])
if pms:
    st.subheader("対応する PMS（製造販売後調査等）")
    st.caption("登録番号が同じ PMS です。")
    show_facts_table(pms, [
        ("製品", lambda p: p["subject"]),
        ("種類", lambda p: p["study_type"]),
        ("調査名", lambda p: p["title"]),
        ("全例調査か", lambda p: p["all_case"]),
        ("実施状況", lambda p: p["progress"]),
    ], "")

"""
競合製品比較.py：④ 競合製品比較画面です。

疾患（適応症）を選ぶと、その疾患に適応のある製品を横に並べた比較表を表示します。
各値の出典と確認日は、表の下に一覧で表示します。
この画面は情報を並べて見るためのもので、製品の優劣を判定するものではありません。
"""

from contextlib import closing

import streamlit as st

from components.display import STATUS_LEGEND
from db.database import get_connection
from db.queries import list_diseases
from services.comparison import build_comparison, comparison_table, sources_table

st.title("📊 競合製品比較")
st.caption(STATUS_LEGEND)
st.info("この画面は、公開情報を並べて見るためのものです。製品の優劣を判定するものではありません。"
        "並び順は「対象企業の製品 → 競合製品」で固定しています。")

with closing(get_connection()) as conn:
    diseases = list_diseases(conn)

if diseases.empty:
    st.info("疾患が登録されていません。")
    st.stop()

# ---- 比較する適応症（疾患）を選ぶ ----
names = {int(i): name for i, name in zip(diseases["id"], diseases["疾患名"])}
disease_id = st.selectbox("適応症（疾患）", list(names), format_func=lambda i: names[i])

with closing(get_connection()) as conn:
    all_entries = build_comparison(conn, disease_id)

if not all_entries:
    st.warning("この疾患に適応のある製品は登録されていません。")
    st.stop()

# ---- 比較する製品をしぼる（初めはすべて）----
labels = {e["product"]["product_id"]: f"{e['product']['brand_name']}（{e['product']['category']}）"
          for e in all_entries}
selected = st.multiselect("比較する製品", list(labels), default=list(labels), format_func=lambda i: labels[i])
verified_only = st.toggle(
    "原文確認済みの情報だけを表示する",
    help="オンにすると、⚠️ 未確認・🔁 再確認要 の情報を比較表から外します。",
)

entries = [e for e in all_entries if e["product"]["product_id"] in selected]
if not entries:
    st.info("比較する製品を1つ以上選んでください。")
    st.stop()
if len(entries) == 1:
    st.caption("※ 製品が1つだけのため、比較ではなくその製品の情報だけを表示しています。")

# ---- 比較表 ----
st.subheader(f"比較表：{names[disease_id]}")
# st.table：表の中の長い文字も折り返して全部表示する
st.table(comparison_table(entries, verified_only))

# ---- 出典と確認日 ----
st.subheader("出典と確認日")
st.caption("比較表の各値が、どの文書のどの版・どの箇所に基づくかの一覧です。")
st.dataframe(
    sources_table(entries, verified_only),
    hide_index=True,
    column_config={"原文URL": st.column_config.LinkColumn("原文URL", display_text="原文を開く")},
)

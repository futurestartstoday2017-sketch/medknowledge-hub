"""
display.py：複数の画面で共通して使う「表示の部品」をまとめたファイルです。

事実（医学的情報など）は、必ずこのファイルの show_fact()（1件ずつの枠）か
show_facts_table()（表）で表示します。
内容と一緒に、確認状態の印と出典（文書名・版・該当箇所・確認日）が必ず表示されるようにするためです。
"""

import pandas as pd
import streamlit as st

# 確認状態の印
STATUS_ICONS = {"原文確認済み": "✅", "未確認": "⚠️", "再確認要": "🔁"}

# 画面の上に出す、印の説明
STATUS_LEGEND = "✅ 原文確認済み ／ ⚠️ 未確認（確認待ち） ／ 🔁 再確認要（出典の改訂などで、確認し直しが必要）"

# 表示する順番（この順に並べ、ここにない種類は最後に並べる）
PRODUCT_FACT_ORDER = ["薬効分類", "作用機序", "投与経路", "剤形", "用法・用量"]
DISEASE_OVERVIEW_ORDER = ["疾患概要", "診断", "アンメットニーズ"]
DISEASE_TREATMENT_ORDER = ["治療", "標準治療"]
SAFETY_ORDER = ["警告", "禁忌", "重要な基本的注意", "特定の背景を有する患者に関する注意",
                "相互作用", "重大な副作用", "その他の副作用", "その他"]


def status_label(status):
    """確認状態を「印 + 文字」にして返します（例：⚠️ 未確認）。"""
    return f"{STATUS_ICONS.get(status, '❓')} {status}"


def escape(text):
    """
    文字に含まれる記号（* _ [ ] など）が、Markdown の太字やリンクとして解釈されないようにします。
    原文の文言を、書かれたとおりに表示するためです。
    """
    for mark in ["\\", "*", "_", "[", "]", "`", "#", "<", ">", "|", "~"]:
        text = text.replace(mark, "\\" + mark)
    return text


def source_text(fact):
    """出典の説明文を作ります（例：出典：文書名 版 ／ 該当箇所：… ／ 確認：2025-05-10）。"""
    revised = fact["revised_on"] or "記載なし"
    old_version = "（※ 過去の版）" if not fact["version_is_current"] else ""
    if fact["status"] == "原文確認済み" and fact["verified_at"]:
        checked = f"確認：{fact['verified_at'][:10]}（{escape(fact['verified_by'])}）"
    else:
        checked = "確認：未確認"
    return (
        f"出典：[{escape(fact['doc_title'])}]({fact['source_url']}) "
        f"{escape(fact['version_label'])}（改訂 {revised}）{old_version}"
        f" ／ 該当箇所：{escape(fact['source_location'])} ／ {checked}"
    )


def show_fact(fact, title=None):
    """事実を1件、枠で囲んで表示します（見出し・確認状態・内容・出典）。"""
    with st.container(border=True):
        heading = f"**{escape(title)}**　" if title else ""
        st.markdown(f"{heading}{status_label(fact['status'])}")
        st.markdown(escape(fact["content"]))
        st.caption(source_text(fact))


def show_facts_in_order(facts, key, order, empty_message="登録されている情報はありません。"):
    """
    事実のリストを、決めた順番（order）で見出し付きで表示します。
    key は、見出しに使う列の名前です（例：fact_type、category）。
    """
    if not facts:
        st.info(empty_message)
        return
    position = {name: i for i, name in enumerate(order)}
    for fact in sorted(facts, key=lambda f: position.get(f[key], len(order))):
        show_fact(fact, title=fact[key])


def show_documents(documents):
    """文書と、その版の一覧を表示します。"""
    if not documents:
        st.info("ひも付いている文書はありません。")
        return
    for doc in documents:
        with st.container(border=True):
            publisher = f"／{escape(doc['publisher'])}" if doc["publisher"] else ""
            st.markdown(f"**{escape(doc['title'])}**　（{doc['doc_type']}{publisher}）")
            st.dataframe(
                doc["versions"],
                hide_index=True,
                column_config={
                    # 原文URLを、押すと開けるリンクとして表示する
                    "原文URL": st.column_config.LinkColumn("原文URL", display_text="原文を開く"),
                },
            )


def show_notes(notes):
    """学習メモ・考察を表示します。事実とは違うデータであることがわかる見た目にします。"""
    st.caption("📝 ここに表示されるのは自分の学習メモ・考察です。原文で確認した事実ではありません。")
    if not notes:
        st.info("学習メモはまだありません（メモの登録機能は Step 15 で作ります）。")
        return
    for note in notes:
        with st.container(border=True):
            st.markdown(f"📝 **{note['note_type']}**　（更新：{note['updated_at'][:10]}）")
            st.markdown(escape(note["body"]))


# 公開状況（disclosure）の説明。確認状態の「⚠️ 未確認」と区別するため、別の印と説明を付ける
DISCLOSURE_LEGEND = ("🔒 非公開（公表されていない）／ ❔ 未確認（公開情報で確認できていない）"
                     "　※確認状態の「⚠️ 未確認（原文と未照合）」とは別の意味です")


def disclosed_value(disclosure, value):
    """
    公開状況に合わせて、日付などの値を表示用の文字にします。
    公開 → 値（空なら「—」）／ 非公開 → 🔒 非公開 ／ 未確認 → ❔ 未確認
    """
    if disclosure == "非公開":
        return "🔒 非公開"
    if disclosure == "未確認":
        return "❔ 未確認"
    return value if value not in (None, "") else "—"


def facts_table(facts, columns):
    """
    事実のリストを、表（DataFrame）にします。
    columns：[(列の見出し, 1件の事実から値を作る関数), ...]
    どの表にも、最後に「確認状態・出典・版・該当箇所・確認日・原文URL」の列を必ず付けます。
    """
    rows = []
    for fact in facts:
        row = {header: make(fact) for header, make in columns}
        row.update({
            "確認状態": status_label(fact["status"]),
            "出典": fact["doc_title"] + ("（過去の版）" if not fact["version_is_current"] else ""),
            "版": fact["version_label"],
            "該当箇所": fact["source_location"],
            "確認日": fact["verified_at"][:10] if fact["status"] == "原文確認済み" and fact["verified_at"] else "未確認",
            "原文URL": fact["source_url"],
        })
        rows.append(row)
    return pd.DataFrame(rows)


def show_facts_table(facts, columns, empty_message):
    """facts_table() で作った表を表示します。原文URLは押すと開けるリンクにします。"""
    if not facts:
        st.info(empty_message)
        return
    st.dataframe(
        facts_table(facts, columns),
        hide_index=True,
        column_config={"原文URL": st.column_config.LinkColumn("原文URL", display_text="原文を開く")},
    )


def show_timeline(timeline):
    """
    承認から特許満了までのタイムライン（services/timeline.py の build_timeline() の結果）を表示します。
    3つの日付を数字の枠（メトリック）で、期間を表で示します。
    """
    st.subheader("⏱️ 承認から特許満了までのタイムライン")
    st.caption("エビデンス創出の計画を考えるための目安です。"
               "**後発品の参入時期を予測するものではありません**（実際は再審査・特許の種類・承認審査などで決まります）。")

    columns = st.columns(len(timeline["milestones"]))
    for column, milestone in zip(columns, timeline["milestones"]):
        column.metric(milestone["label"], milestone["date"] or "—")
        fact = milestone["fact"]
        if fact and milestone["date"]:
            column.caption(f"{status_label(fact['status'])}　出典：{escape(fact['doc_title'])}")
        elif fact:
            column.caption(disclosed_value(fact.get("disclosure"), None) if fact.get("disclosure") else "日付なし")
        else:
            column.caption("未登録")

    for note in timeline["notes"]:
        st.warning(note)
    if timeline["durations"]:
        st.table(pd.DataFrame(timeline["durations"]).set_index("区間"))
    if len(timeline["patents"]) > 1:
        st.caption("比べた特許の満了日（延長登録後があればその日）："
                   + "、".join(f"{p['patent_number']}＝{p['extended_expiry_date'] or p['expiry_date']}"
                              for p in timeline["patents"]))


def go_to_product(product_id, key, label="この製品の情報を見る"):
    """押すと、その製品を選んだ状態で製品情報画面に移動するボタンを表示します。"""
    if st.button(label, key=key):
        st.session_state["goto_product_id"] = int(product_id)
        st.switch_page("pages/製品情報.py")


def go_to_disease(disease_id, key, label="この疾患の情報を見る"):
    """押すと、その疾患を選んだ状態で疾患情報画面に移動するボタンを表示します。"""
    if st.button(label, key=key):
        st.session_state["goto_disease_id"] = int(disease_id)
        st.switch_page("pages/疾患情報.py")


def show_planned(step, what):
    """まだ作っていない機能の場所に、いつ作るかを表示します。"""
    st.info(f"{what}は Step {step} で作ります。")

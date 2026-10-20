"""
display.py：複数の画面で共通して使う「表示の部品」をまとめたファイルです。

事実（医学的情報など）は、必ずこのファイルの show_fact() で表示します。
内容と一緒に、確認状態の印と出典（文書名・版・該当箇所・確認日）が必ず表示されるようにするためです。
"""

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


def show_planned(step, what):
    """まだ作っていない機能の場所に、いつ作るかを表示します。"""
    st.info(f"{what}は Step {step} で作ります。")

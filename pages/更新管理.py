"""
更新管理.py：⑤ 確認・更新管理画面です。

4つのタブで構成します。
  1. 確認待ち         ：未確認・再確認要の情報を、原文を見ながら確認する／内容を修正する
  2. 変更候補・文書の版：改訂の気づき（変更候補）の登録と対応、新しい版の登録
  3. 品質チェック     ：出典の不一致や、改訂前の版を出典にした確認済み情報などの一覧
  4. 更新履歴         ：すべての変更の記録（閲覧のみ。編集・削除はできない）

データを変える操作では、必ず「確認者名」と「理由」を入力してもらい、更新履歴に残します。
最初の変更の前に、データベースのバックアップを自動で取ります。
"""

import sqlite3
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st

from components.display import STATUS_LEGEND, show_fact, status_label
from db.backup import backup_db
from db.changes import set_status
from db.database import TABLE_LABELS, get_connection
from db.quality import find_quality_problems
from db.queries import (
    get_change_log_entry, get_fact_detail, get_version_choices, list_all_documents, list_all_versions,
    list_candidates, list_change_log, list_companies, list_review_facts,
)
from db.settings import get_setting, set_setting
from services.diff import diff_records, parse_json
from services.updates import (
    CANDIDATE_STATUSES, add_candidate, confirm_document_version, register_document_version,
    revise_fact, update_candidate_status,
)

st.title("🔄 更新管理")
st.caption("原文を確認して情報を確定する／修正する／改訂を管理するための画面です。" + STATUS_LEGEND)

# 前回の操作の結果（成功メッセージ）を表示する
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

# ---- 確認者名（すべての変更で使う）----
with closing(get_connection()) as conn:
    last_reviewer = get_setting(conn, "last_reviewer", "")
if "reviewer" not in st.session_state:
    st.session_state["reviewer"] = last_reviewer  # 前回の確認者名を自動で入れておく
st.text_input("確認者名（変更するときは必須）", key="reviewer", placeholder="例：山田")

if st.session_state.get("backup_path"):
    st.caption(f"💾 この画面を開いてから最初の変更の前に、バックアップを取りました：{st.session_state['backup_path']}")


def run_update(update, message, reason):
    """
    データを変える処理（update）を、決まった手順で実行します。
      1. 確認者名と理由が入力されているか確かめる
      2. （この画面で最初の変更なら）バックアップを取る
      3. 処理を実行し、確認者名を次回のために保存する
      4. 成功したらメッセージを残して画面を読み込み直す。失敗したら原因を表示する
    update は「接続と確認者名を受け取って処理する関数」、message は「処理の結果を受け取って文を作る関数」です。
    """
    reviewer = st.session_state["reviewer"].strip()
    if not reviewer:
        st.error("確認者名を入力してください（画面の上の入力欄）。")
        return
    if not reason.strip():
        st.error("理由を入力してください。")
        return
    try:
        if not st.session_state.get("backup_path"):
            st.session_state["backup_path"] = str(backup_db())
        with closing(get_connection()) as conn:
            result = update(conn, reviewer)
            set_setting(conn, "last_reviewer", reviewer)
    except (sqlite3.IntegrityError, ValueError) as error:
        # DBのルール違反など。何も変更されていない（トランザクションで取り消されている）
        st.error(f"反映できませんでした（データは変更されていません）：{error}")
        return
    st.session_state["flash"] = message(result)
    st.rerun()  # 画面を最新の状態で表示し直す


tabs = st.tabs(["確認待ち", "変更候補・文書の版", "品質チェック", "更新履歴"])


# =====================================================================
# 1. 確認待ち
# =====================================================================
with tabs[0]:
    statuses = st.multiselect("表示する確認状態", ["再確認要", "未確認", "原文確認済み"],
                              default=["再確認要", "未確認"], key="review_statuses")
    with closing(get_connection()) as conn:
        facts = list_review_facts(conn, statuses)

    if not facts:
        st.success("該当する情報はありません。")
    else:
        st.dataframe(
            pd.DataFrame([{
                "確認状態": status_label(f["status"]), "種類": f["table_label"], "対象": f["subject"],
                "項目": f["item"], "内容": f["content"], "出典": f["doc_title"], "版": f["version_label"],
            } for f in facts]),
            hide_index=True,
        )

        # 詳しく見る情報を選ぶ（「テーブル名:ID」で区別する）
        choices = {f"{f['table']}:{f['id']}": f for f in facts}
        key = st.selectbox(
            "確認・修正する情報",
            list(choices),
            format_func=lambda k: (f"{status_label(choices[k]['status'])}［{choices[k]['table_label']}］"
                                   f"{choices[k]['subject']}：{choices[k]['item']} — {choices[k]['content'][:30]}"),
            key="review_target",
        )
        table, fact_id = key.split(":")[0], int(key.split(":")[1])
        with closing(get_connection()) as conn:
            fact = get_fact_detail(conn, table, fact_id)
            version_choices = get_version_choices(conn, fact)
            companies = list_companies(conn)

        show_fact(fact, title=f"{fact['subject']}：{fact['item']}")
        st.caption("👆 出典のリンクから原文を開き、該当箇所を読んでから操作してください。")

        # 入力欄の名前（key）に、選んだ情報の「テーブル名:ID」を付ける。
        # こうしないと、別の情報に切り替えたときに、前の情報で入力した値が残ってしまう
        left, right = st.columns(2)

        # ---- 確認状態を変える ----
        with left, st.form("status_form"):
            st.markdown("**確認状態を変える**")
            new_status = st.radio("新しい確認状態", [s for s in ("原文確認済み", "再確認要", "未確認")
                                                if s != fact["status"]], key=f"new_status_{key}")
            status_reason = st.text_input("理由（必須）", placeholder="例：原文の該当箇所と照合した",
                                          key=f"status_reason_{key}")
            read_source = st.checkbox("出典の原文（該当箇所）を自分で読んで確認しました", key=f"status_read_{key}")
            if st.form_submit_button("確認状態を変更する", key="status_submit"):
                if new_status == "原文確認済み" and not read_source:
                    st.error("「原文確認済み」にするには、原文を読んで確認したことのチェックが必要です。")
                else:
                    run_update(
                        lambda conn, reviewer: set_status(conn, table, fact_id, new_status, reviewer, status_reason),
                        lambda _: f"確認状態を「{new_status}」に変更しました。",
                        status_reason,
                    )

        # ---- 内容を修正する（差分を確認してから反映）----
        if table not in ("medical_facts", "safety_info", "product_companies"):
            # 承認・特許などの修正フォームは Step 9-2 で作る（確認状態の変更は今も使える）
            right.info(f"{fact['table_label']}の内容を修正するフォームは、Step 9-2 で作ります。")
        else:
            with right, st.form("revise_form"):
                st.markdown("**内容を修正する**（古い情報は削除せず、履歴として残ります）")
                changes = {}
                if table == "product_companies":
                    company_ids = [c[0] for c in companies]
                    company_names = dict(companies)
                    new_company = st.selectbox("企業", company_ids, index=company_ids.index(fact["company_id"]),
                                               format_func=lambda i: company_names[i], key=f"revise_company_{key}")
                    if new_company != fact["company_id"]:
                        changes["company_id"] = new_company
                else:
                    new_content = st.text_area("内容", value=fact["content"], key=f"revise_content_{key}")
                    if new_content.strip() != fact["content"]:
                        changes["content"] = new_content.strip()

                version_ids = [v[0] for v in version_choices]
                version_names = dict(version_choices)
                new_version = st.selectbox("出典の版", version_ids, index=version_ids.index(fact["source_version_id"]),
                                           format_func=lambda i: version_names[i], key=f"revise_version_{key}")
                if new_version != fact["source_version_id"]:
                    changes["source_version_id"] = new_version
                new_location = st.text_input("該当箇所", value=fact["source_location"], key=f"revise_location_{key}")
                if new_location.strip() != fact["source_location"]:
                    changes["source_location"] = new_location.strip()

                revise_reason = st.text_input("修正の理由（必須）", placeholder="例：添付文書の改訂に合わせて修正",
                                              key=f"revise_reason_{key}")
                mark_verified = st.checkbox("原文を確認したので、修正後の情報を「原文確認済み」にする",
                                            key=f"revise_verified_{key}")
                if st.form_submit_button("変更内容を確認する", key="revise_preview"):
                    if not changes:
                        st.warning("変更された項目がありません。")
                    else:
                        # すぐには反映せず、差分を見てもらうために一時的に覚えておく
                        st.session_state["pending_revision"] = {
                            "key": key, "changes": changes, "reason": revise_reason, "verified": mark_verified,
                        }

        # ---- 差分の確認と反映 ----
        pending = st.session_state.get("pending_revision")
        if pending and pending["key"] == key:
            st.markdown("#### 変更内容の確認（差分）")
            with closing(get_connection()) as conn:
                after = {**fact, **pending["changes"]}
                diff = diff_records({k: fact[k] for k in pending["changes"]},
                                    {k: after[k] for k in pending["changes"]}, conn)
            st.table(pd.DataFrame(diff).set_index("項目"))
            st.caption("反映すると、今の情報は「過去の情報」として残り、新しい情報が追加されます。"
                       + ("新しい情報は「原文確認済み」になります。" if pending["verified"]
                          else "新しい情報は「⚠️ 未確認」から始まります。"))
            do_it, cancel = st.columns(2)
            if do_it.button("この内容で反映する", type="primary", key="revise_apply"):
                st.session_state.pop("pending_revision")
                run_update(
                    lambda conn, reviewer: revise_fact(conn, table, fact_id, pending["changes"], reviewer,
                                                       pending["reason"], pending["verified"]),
                    lambda new_id: f"修正を反映しました（新しい情報のID：{new_id}）。古い情報は履歴に残っています。",
                    pending["reason"],
                )
            if cancel.button("やめる", key="revise_cancel"):
                st.session_state.pop("pending_revision")
                st.rerun()


# =====================================================================
# 2. 変更候補・文書の版
# =====================================================================
with tabs[1]:
    with closing(get_connection()) as conn:
        candidates = list_candidates(conn)
        documents = list_all_documents(conn)
        versions = list_all_versions(conn)
    document_ids = [d[0] for d in documents]
    document_names = dict(documents)

    st.subheader("変更候補")
    st.caption("「添付文書が改訂されたかもしれない」などの気づきを登録し、原文を確認してから対応します"
               "（変更の検出と、内容の確認を別の工程にするため）。")
    if candidates.empty:
        st.info("変更候補はありません。")
    else:
        st.dataframe(candidates, hide_index=True)

    with st.expander("➕ 変更候補を登録する"):
        with st.form("candidate_add_form", clear_on_submit=True):
            cand_doc = st.selectbox("対象の文書", document_ids, format_func=lambda i: document_names[i],
                                    key="cand_doc")
            cand_desc = st.text_area("内容（何に気づいたか）", placeholder="例：公式サイトに新しい改訂日の掲載あり",
                                     key="cand_desc")
            cand_reason = st.text_input("登録の理由（必須）", value="改訂の可能性に気づいたため", key="cand_reason")
            if st.form_submit_button("登録する", key="cand_add"):
                if not cand_desc.strip():
                    st.error("内容を入力してください。")
                else:
                    run_update(
                        lambda conn, reviewer: add_candidate(conn, cand_doc, cand_desc.strip(), reviewer, cand_reason),
                        lambda cid: f"変更候補を登録しました（候補ID：{cid}）。",
                        cand_reason,
                    )

    if not candidates.empty:
        with st.expander("✏️ 変更候補の対応状況を変える"):
            with st.form("candidate_status_form"):
                cand_ids = [int(i) for i in candidates["候補ID"]]
                cand_labels = {int(r["候補ID"]): f"［{r['対応状況']}］{r['文書']}：{r['内容'][:30]}"
                               for _, r in candidates.iterrows()}
                cand_id = st.selectbox("変更候補", cand_ids, format_func=lambda i: cand_labels[i], key="cand_target")
                cand_status = st.radio("新しい対応状況", CANDIDATE_STATUSES, horizontal=True, key="cand_status")
                cand_status_reason = st.text_input("理由（必須）", placeholder="例：原文を確認し、変更がないことを確認した",
                                                   key="cand_status_reason")
                if st.form_submit_button("変更する", key="cand_status_submit"):
                    run_update(
                        lambda conn, reviewer: update_candidate_status(conn, cand_id, cand_status, reviewer,
                                                                       cand_status_reason),
                        lambda _: f"変更候補の対応状況を「{cand_status}」にしました。",
                        cand_status_reason,
                    )

    st.subheader("文書の版")
    st.dataframe(versions, hide_index=True,
                 column_config={"原文URL": st.column_config.LinkColumn("原文URL", display_text="原文を開く")})

    with st.expander("➕ 新しい版を登録する"):
        st.caption("最新版として登録すると、それまでの最新版を出典にしていた「原文確認済み」の情報は、"
                   "自動で「🔁 再確認要」になります（改訂後の原文で確認し直すため）。")
        with st.form("version_add_form"):
            ver_doc = st.selectbox("文書", document_ids, format_func=lambda i: document_names[i], key="ver_doc")
            ver_label = st.text_input("版の表記", placeholder="例：2025年10月改訂（第3版）", key="ver_label")
            ver_revised = st.text_input("原文の改訂年月（YYYY-MM。記載がなければ空欄）", placeholder="例：2025-10",
                                        key="ver_revised")
            ver_retrieved = st.date_input("入手日（原文を取得した日）", value=date.today(), key="ver_retrieved")
            ver_url = st.text_input("原文URL", placeholder="https://", key="ver_url")
            ver_current = st.checkbox("最新版として登録する", value=True, key="ver_current")
            open_candidates = candidates[candidates["対応状況"].isin(["未対応", "確認中"])] if not candidates.empty \
                else candidates
            cand_options = [None] + [int(i) for i in open_candidates.get("候補ID", [])]
            ver_cand = st.selectbox(
                "関係する変更候補（任意）", cand_options,
                format_func=lambda i: "なし" if i is None else f"候補ID {i}", key="ver_cand")
            ver_reason = st.text_input("登録の理由（必須）", placeholder="例：添付文書の改訂を確認", key="ver_reason")
            if st.form_submit_button("登録する", key="ver_add"):
                if not ver_label.strip() or not ver_url.strip():
                    st.error("版の表記と原文URLを入力してください。")
                else:
                    run_update(
                        lambda conn, reviewer: register_document_version(
                            conn, ver_doc, ver_label.strip(), ver_revised.strip(), ver_retrieved.isoformat(),
                            ver_url.strip(), ver_current, reviewer, ver_reason, ver_cand),
                        lambda r: (f"新しい版を登録しました（版ID：{r['version_id']}）。"
                                   + (f"確認済みだった {r['rechecked']} 件の情報を「再確認要」にしました。"
                                      if r["rechecked"] else "")),
                        ver_reason,
                    )

    unconfirmed = versions[~versions["確認状態"].str.contains("原文確認済み")]
    if not unconfirmed.empty:
        with st.expander("✅ 文書の版を「原文確認済み」にする"):
            with st.form("version_confirm_form"):
                ver_ids = [int(i) for i in unconfirmed["版ID"]]
                ver_names = {int(r["版ID"]): f"{r['文書']} ／ {r['版']}" for _, r in unconfirmed.iterrows()}
                conf_id = st.selectbox("文書の版", ver_ids, format_func=lambda i: ver_names[i], key="conf_target")
                conf_date = st.date_input("確認日", value=date.today(), key="conf_date")
                conf_read = st.checkbox("原文を開いて、版の表記・改訂年月が正しいことを確認しました", key="conf_read")
                conf_reason = st.text_input("理由（必須）", value="原文を確認したため", key="conf_reason")
                if st.form_submit_button("原文確認済みにする", key="conf_submit"):
                    if not conf_read:
                        st.error("原文を確認したことのチェックが必要です。")
                    else:
                        run_update(
                            lambda conn, reviewer: confirm_document_version(conn, conf_id, conf_date.isoformat(),
                                                                            reviewer, conf_reason),
                            lambda _: "文書の版を「原文確認済み」にしました。",
                            conf_reason,
                        )


# =====================================================================
# 3. 品質チェック
# =====================================================================
with tabs[2]:
    st.caption("データベースのルールだけでは防げない「つじつまの合わない状態」を一覧にします。"
               "自動では直さないので、内容を確認して対応してください。")
    with closing(get_connection()) as conn:
        problems = find_quality_problems(conn)
    if not problems:
        st.success("問題は見つかりませんでした。")
    else:
        st.warning(f"{len(problems)} 件の問題が見つかりました。")
        st.dataframe(pd.DataFrame([{
            "問題の種類": p["kind"], "対象": TABLE_LABELS.get(p["table"], p["table"]),
            "ID": p["record_id"], "説明": p["message"],
        } for p in problems]), hide_index=True)


# =====================================================================
# 4. 更新履歴（閲覧のみ）
# =====================================================================
with tabs[3]:
    st.caption("🔒 更新履歴は閲覧のみです。編集・削除はできません（データベースのルールで禁止しています）。")
    table_options = [None] + list(TABLE_LABELS)
    log_table = st.selectbox("対象でしぼり込む", table_options,
                             format_func=lambda t: "すべて" if t is None else TABLE_LABELS[t], key="log_table")
    with closing(get_connection()) as conn:
        log = list_change_log(conn, log_table)

    if log.empty:
        st.info("更新履歴はありません。")
    else:
        st.dataframe(log, hide_index=True)
        log_id = st.selectbox("変更前・変更後を見る履歴", [int(i) for i in log["履歴ID"]],
                              format_func=lambda i: f"履歴ID {i}", key="log_target")
        with closing(get_connection()) as conn:
            entry = get_change_log_entry(conn, log_id)
            diff = diff_records(parse_json(entry["before_json"]), parse_json(entry["after_json"]), conn)
        st.markdown(f"**{entry['changed_at']}　{entry['changed_by']}　［{entry['action']}］** 理由：{entry['reason']}")
        if diff:
            st.table(pd.DataFrame(diff).set_index("項目"))
        else:
            st.info("変更された項目はありません。")

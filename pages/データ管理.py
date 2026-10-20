"""
データ管理.py：⑨ データ管理画面です。

  1. CSVインポート：テンプレートに記入したCSVを検証し、誤りがなければ確認してから登録する
  2. バックアップ ：バックアップの作成と一覧、復元のしかた

CSVで取り込んだ医学的情報は「⚠️ 未確認」で登録されます。
原文を確認したら、更新管理画面で「原文確認済み」にしてください。
"""

import sqlite3
from contextlib import closing
from datetime import datetime

import pandas as pd
import streamlit as st

from db.backup import BACKUP_DIR, backup_db
from db.database import get_connection
from db.errors import friendly_db_error
from db.settings import get_setting, set_setting
from services.csv_importer import KINDS, example_table, import_rows, read_csv, template_bytes, validate

st.title("🗂️ データ管理")

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

tabs = st.tabs(["CSVインポート", "バックアップ"])

# =====================================================================
# 1. CSVインポート
# =====================================================================
with tabs[0]:
    st.caption("取り込む順番：① 企業・製品・疾患 → ② 文書と版 → ③ 適応症 → ④ 承認・再審査・特許・ライセンス・PMS"
               "（先に登録したものを、あとのCSVで参照するため）")

    kind = st.radio("取り込む種類", list(KINDS), format_func=lambda k: KINDS[k]["label"], horizontal=True,
                    key="import_kind")
    spec = KINDS[kind]

    # ---- テンプレートと列の説明 ----
    left, right = st.columns([1, 2])
    with left:
        st.download_button(
            f"📥 {spec['label']}のテンプレートをダウンロード", template_bytes(kind), file_name=spec["file"],
            mime="text/csv", key=f"template_{kind}",
        )
        st.dataframe(
            pd.DataFrame([{"列": h, "必須": "必須" if r else "任意"} for h, _, r in spec["columns"]]),
            hide_index=True,
        )
    with right:
        st.markdown("**記入例**（架空のデータです）")
        st.dataframe(example_table(kind), hide_index=True)
        if kind == "indications":
            st.caption("効能・効果の文言を入れるときは、出典（文書タイトル・版・該当箇所）が必須です。"
                       "文言は「⚠️ 未確認」で登録されます。")
        if kind == "documents":
            st.caption("「最新版」を「はい」（空欄も「はい」）にすると、それまでの最新版は過去の版になり、"
                       "その版を出典にしていた確認済みの情報は「🔁 再確認要」になります。")
        if "fact_table" in spec:
            st.caption("出典（文書タイトル・版・該当箇所）が必須です。取り込んだ情報は「⚠️ 未確認」で登録されます。"
                       "公開状況が「非公開」「未確認」のときは、日付を空欄にしてください（推測で埋めないため）。")

    # ---- ファイルの読み込みと検証 ----
    uploaded = st.file_uploader("CSVファイルを選ぶ", type=["csv"], key=f"upload_{kind}")
    if uploaded is not None:
        try:
            table = read_csv(uploaded.getvalue())
        except (ValueError, pd.errors.ParserError) as error:
            st.error(f"CSVを読み込めませんでした：{error}")
            st.stop()

        with closing(get_connection()) as conn:
            errors = validate(conn, kind, table)
            last_reviewer = get_setting(conn, "last_reviewer", "")

        if errors:
            st.error(f"{len(errors)} 件の誤りがあるため、**何も登録していません**。CSVを直してから、もう一度選んでください。")
            st.dataframe(pd.DataFrame({"誤りの内容": errors}), hide_index=True)
        else:
            st.success(f"検証で誤りは見つかりませんでした。{len(table)} 行を登録できます。内容を確認してください。")
            st.dataframe(table, hide_index=True)

            with st.form("import_form"):
                reviewer = st.text_input("確認者名（必須）", value=last_reviewer, key="import_reviewer")
                reason = st.text_input("登録の理由（必須）", value=f"CSVインポート（{uploaded.name}）", key="import_reason")
                checked = st.checkbox("上の内容を確認しました", key="import_checked")
                if st.form_submit_button("この内容で登録する", type="primary", key="import_submit"):
                    if not reviewer.strip() or not reason.strip():
                        st.error("確認者名と理由を入力してください。")
                    elif not checked:
                        st.error("内容を確認したことのチェックが必要です。")
                    else:
                        try:
                            backup_path = backup_db()  # 登録の前に、必ずバックアップを取る
                            with closing(get_connection()) as conn:
                                count = import_rows(conn, kind, table, reviewer.strip(), reason.strip())
                                set_setting(conn, "last_reviewer", reviewer.strip())
                        except (sqlite3.IntegrityError, ValueError) as error:
                            st.error(f"登録できませんでした（データは変更されていません）：{friendly_db_error(error)}")
                        else:
                            st.session_state["flash"] = (
                                f"{spec['label']}を {count} 行登録しました（登録前のバックアップ：{backup_path.name}）。"
                                + ("医学的情報は「⚠️ 未確認」です。更新管理画面で原文を確認してください。"
                                   if kind == "indications" or "fact_table" in spec else ""))
                            # アップロード欄を空に戻す（同じファイルを二重に登録しないため）
                            st.session_state.pop(f"upload_{kind}", None)
                            st.rerun()

# =====================================================================
# 2. バックアップ
# =====================================================================
with tabs[1]:
    st.caption("データベースの控えです。GitHub にはアップロードされません。")
    if st.button("💾 今すぐバックアップを取る", key="backup_now"):
        try:
            path = backup_db()
        except FileNotFoundError as error:
            st.error(str(error))
        else:
            st.session_state["flash"] = f"バックアップを作成しました：{path.name}"
            st.rerun()

    files = sorted(BACKUP_DIR.glob("*.db"), reverse=True) if BACKUP_DIR.exists() else []
    if files:
        st.dataframe(pd.DataFrame([{
            "ファイル名": f.name,
            "作成日時": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "大きさ(KB)": round(f.stat().st_size / 1024),
        } for f in files]), hide_index=True)
    else:
        st.info("バックアップはまだありません。")

    st.markdown("**復元のしかた**（アプリを使用中に復元すると危ないため、画面からは行いません）")
    st.markdown("1. ターミナルで `Ctrl + C` を押して、アプリを止めます。\n"
                "2. 次のコマンドを入力します（ファイル名は上の一覧から選んでください）。")
    st.code("python -m db.backup restore data\\backups\\ファイル名.db", language="powershell")
    st.markdown("3. もう一度 `streamlit run app.py` で起動します。")

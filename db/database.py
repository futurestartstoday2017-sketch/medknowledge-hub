"""
database.py：データベース（SQLite）への接続と、テーブルの作成を担当するファイルです。

- get_connection()：データベースに接続する（外部キーのチェックを必ず有効にする）
- init_db()       ：DBを最新の設計図の形にする（新しく作る／マイグレーションで追加する）
"""

import sqlite3
from pathlib import Path

# プロジェクトのフォルダ（このファイルの1つ上のフォルダ）
ROOT = Path(__file__).parent.parent
# データベースファイルの場所
DB_PATH = ROOT / "data" / "medknowledge.db"
# テーブルの設計図（SQL）の場所
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# 設計図のバージョン番号。テーブルの形を変えたら数字を上げ、MIGRATIONS に追加分のSQLを登録する
SCHEMA_VERSION = 2

# マイグレーション（古いDBを新しい設計図の形にするための追加分のSQL）の場所と一覧
#   バージョン1 = schema.sql（最初の設計図）
#   バージョン2以降 = 下の一覧のファイルを順に実行する
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATIONS = {
    2: "002_regulatory_pms.sql",  # 承認・再審査・特許・ライセンス・PMS
}

# 【出典セット】を持つ「事実」のテーブルと、あとから書き換えてはいけない列の一覧
# 書き換えたいときは、古い行を残したまま新しい行を追加する（db/changes.py）
FACT_TABLES = {
    "product_companies": [
        "product_id", "company_id", "role",
        "source_version_id", "source_location", "entry_method",
    ],
    "medical_facts": [
        "product_id", "disease_id", "indication_id", "fact_type", "subcategory", "content",
        "source_version_id", "source_location", "entry_method",
    ],
    "safety_info": [
        "product_id", "category", "content",
        "source_version_id", "source_location", "entry_method",
    ],
    # ---- ここから下は設計図バージョン2（db/migrations/002_regulatory_pms.sql）で追加 ----
    "approvals": [
        "product_id", "indication_id", "approval_type", "approval_date", "approval_number", "content",
        "source_version_id", "source_location", "entry_method",
    ],
    "reexaminations": [
        "product_id", "indication_id", "content", "disclosure", "period_years", "start_date", "end_date",
        "source_version_id", "source_location", "entry_method",
    ],
    "patents": [
        "product_id", "patent_number", "country", "patent_kind", "title", "disclosure",
        "expiry_date", "extended_expiry_date",
        "source_version_id", "source_location", "entry_method",
    ],
    "licenses": [
        "product_id", "partner_company_id", "role", "license_type", "territory", "content", "disclosure",
        "contract_start", "contract_end", "disclosed_fiscal_year",
        "source_version_id", "source_location", "entry_method",
    ],
    "pms_studies": [
        "product_id", "indication_id", "study_type", "title", "all_case", "approval_condition", "progress",
        "target_cases", "disclosure", "start_date", "end_date", "registration_no",
        "source_version_id", "source_location", "entry_method",
    ],
}


# テーブルの日本語名（画面やメッセージで使う）
TABLE_LABELS = {
    "companies": "企業",
    "products": "製品",
    "diseases": "疾患",
    "indications": "適応症",
    "documents": "文書",
    "document_versions": "文書の版",
    "document_links": "文書と製品・疾患の対応",
    "product_companies": "製造販売元・販売元",
    "medical_facts": "医学的情報",
    "safety_info": "安全性情報",
    "notes": "学習メモ",
    "change_candidates": "変更候補",
    "change_log": "更新履歴",
    "approvals": "承認",
    "reexaminations": "再審査",
    "patents": "特許",
    "licenses": "ライセンス",
    "pms_studies": "PMS（製造販売後調査等）",
}


def get_connection(db_path=None):
    """データベースに接続し、接続（コネクション）を返します。"""
    conn = sqlite3.connect(db_path or DB_PATH)
    # 結果を「列名でアクセスできる形」で受け取る設定（row["brand_name"] のように使える）
    conn.row_factory = sqlite3.Row
    # SQLiteは初期設定では外部キーのチェックが無効なので、接続のたびに有効にする
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    """
    データベースを、アプリが使う最新の設計図の形にします。

    - まだ何もないDB（バージョン0）：schema.sql（バージョン1）から順に、最新まで作る
    - 古いバージョンのDB：足りない分だけマイグレーションを実行する（先に自動でバックアップを取る）
    - 最新のDB：何もしない
    新しいDBも古いDBも同じ手順を通るので、「新しく作ったDB」と「追加したDB」の形が食い違いません。
    """
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)  # data フォルダがなければ作る

    conn = get_connection(path)
    try:
        # user_version：DBファイルに保存しておける番号。0 なら「まだ何も作っていない」
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"データベースの設計図のバージョン（{version}）が、アプリ（{SCHEMA_VERSION}）より新しいため開けません。"
            )
        if version >= 1:
            # 既存のデータが入ったDBを変更する前に、念のためバックアップを取る
            from db.backup import backup_db  # ここで読み込む（backup.py もこのファイルを読み込むため）
            conn.close()
            backup_db(path)
            conn = get_connection(path)

        if version == 0:
            _apply(conn, SCHEMA_PATH.read_text(encoding="utf-8"), 1)
        for new_version in range(max(version, 1) + 1, SCHEMA_VERSION + 1):
            _apply(conn, (MIGRATIONS_DIR / MIGRATIONS[new_version]).read_text(encoding="utf-8"), new_version)
    finally:
        conn.close()


def _apply(conn, sql, new_version):
    """
    設計図（またはマイグレーション）のSQLを実行し、バージョン番号を new_version にします。
    その SQL で新しく作られる事実のテーブルには、守るためのトリガーも一緒に作ります。
    「全部成功するか、全部なかったことにするか」（トランザクション）で実行します。
    """
    created_fact_tables = [t for t in FACT_TABLES if f"CREATE TABLE {t} (" in sql]
    script = (
        "BEGIN;\n"
        + sql
        + "\n".join(_fact_table_triggers(t, FACT_TABLES[t]) for t in created_fact_tables)
        + f"\nPRAGMA user_version = {new_version};\nCOMMIT;"
    )
    conn.executescript(script)


def _fact_table_triggers(table, protected_columns):
    """
    【出典セット】を持つテーブルを守るトリガー（自動チェック）のSQLを作ります。

    1. 行を削除できない（旧版を必ず残す）
    2. 内容・出典を書き換えできない（新しい行を追加して置き換える）
    3. API・AIで取得した情報は「未確認」でしか登録できない
    4. 一度「過去の情報」になった行を「今の情報」に戻せない
    5. 置き換え先（superseded_by）は一度しか設定できない
    """
    columns = ", ".join(protected_columns)
    return f"""
CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
BEGIN
    SELECT RAISE(ABORT, '{table}：事実の記録は削除できません（旧版として保持します）');
END;

CREATE TRIGGER {table}_no_edit BEFORE UPDATE OF {columns} ON {table}
BEGIN
    SELECT RAISE(ABORT, '{table}：内容や出典は書き換えできません。新しい行として登録してください');
END;

CREATE TRIGGER {table}_machine_unverified BEFORE INSERT ON {table}
WHEN NEW.entry_method IN ('API', 'AI抽出') AND NEW.status <> '未確認'
BEGIN
    SELECT RAISE(ABORT, '{table}：API・AIで取得した情報は「未確認」で登録してください');
END;

CREATE TRIGGER {table}_no_revive BEFORE UPDATE OF is_current ON {table}
WHEN OLD.is_current = 0 AND NEW.is_current = 1
BEGIN
    SELECT RAISE(ABORT, '{table}：過去の情報を今の情報に戻すことはできません');
END;

CREATE TRIGGER {table}_superseded_once BEFORE UPDATE OF superseded_by ON {table}
WHEN OLD.superseded_by IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, '{table}：置き換え先はすでに設定されています');
END;
"""

"""
database.py：データベース（SQLite）への接続と、テーブルの作成を担当するファイルです。

- get_connection()：データベースに接続する
- init_db()      ：テーブルを作り、空ならサンプルデータを登録する
"""

import sqlite3
from pathlib import Path

from data.sample_data import DISEASES, PRODUCT_DISEASES, PRODUCTS

# データベースファイルの場所（プロジェクト直下の data/medknowledge.db）
# __file__ はこのファイル自身の場所。parent で1つ上のフォルダへ移動します。
DB_PATH = Path(__file__).parent.parent / "data" / "medknowledge.db"

# テーブルを作るSQL文
# 「IF NOT EXISTS」を付けているので、すでにテーブルがあれば何もしません。
CREATE_TABLES_SQL = """
-- 製品テーブル
CREATE TABLE IF NOT EXISTS products (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,  -- 製品ID（自動で連番）
    product_name       TEXT NOT NULL UNIQUE,  -- 製品名（重複不可）
    generic_name       TEXT,                  -- 一般名
    drug_class         TEXT,                  -- 薬効分類
    mechanism          TEXT,                  -- 作用機序
    route              TEXT,                  -- 投与経路
    dosage_form        TEXT,                  -- 剤形
    dosage             TEXT,                  -- 用法・用量
    package_insert_url TEXT,                  -- 添付文書URL
    interview_form_url TEXT                   -- インタビューフォームURL
);

-- 疾患テーブル
CREATE TABLE IF NOT EXISTS diseases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,  -- 疾患ID（自動で連番）
    disease_name TEXT NOT NULL UNIQUE,  -- 疾患名（重複不可）
    overview     TEXT,                  -- 疾患概要
    diagnosis    TEXT,                  -- 診断情報
    treatment    TEXT                   -- 治療情報
);

-- 製品と疾患をつなぐ中間テーブル（多対多の関係を表す）
-- 1行 =「この製品は、この疾患に適応がある」という1つの組み合わせ
CREATE TABLE IF NOT EXISTS product_diseases (
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    disease_id INTEGER NOT NULL REFERENCES diseases(id) ON DELETE CASCADE,
    PRIMARY KEY (product_id, disease_id)  -- 同じ組み合わせの二重登録を防ぐ
);
"""


def get_connection():
    """データベースに接続し、接続（コネクション）を返します。"""
    conn = sqlite3.connect(DB_PATH)
    # 結果を「列名でアクセスできる形」で受け取る設定（row["product_name"] のように使える）
    conn.row_factory = sqlite3.Row
    # SQLiteは初期設定では外部キーのチェックが無効なので、有効にする
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """テーブルを作成し、データが1件もなければサンプルデータを登録します。"""
    # with 文を使うと、処理が終わったときに自動で保存（コミット）されます
    with get_connection() as conn:
        conn.executescript(CREATE_TABLES_SQL)

        # 製品が0件のときだけサンプルデータを入れる（起動のたびに重複登録しないため）
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if product_count == 0:
            _insert_sample_data(conn)
    conn.close()


def _insert_sample_data(conn):
    """サンプルデータを登録します（init_db の中からだけ使う補助関数）。"""
    # 製品を登録する（:product_name などの部分に、辞書の値が入ります）
    conn.executemany(
        """
        INSERT INTO products (
            product_name, generic_name, drug_class, mechanism, route,
            dosage_form, dosage, package_insert_url, interview_form_url
        ) VALUES (
            :product_name, :generic_name, :drug_class, :mechanism, :route,
            :dosage_form, :dosage, :package_insert_url, :interview_form_url
        )
        """,
        PRODUCTS,
    )

    # 疾患を登録する
    conn.executemany(
        """
        INSERT INTO diseases (disease_name, overview, diagnosis, treatment)
        VALUES (:disease_name, :overview, :diagnosis, :treatment)
        """,
        DISEASES,
    )

    # 製品名・疾患名からIDを探して、中間テーブルに組み合わせを登録する
    conn.executemany(
        """
        INSERT INTO product_diseases (product_id, disease_id)
        VALUES (
            (SELECT id FROM products WHERE product_name = ?),
            (SELECT id FROM diseases WHERE disease_name = ?)
        )
        """,
        PRODUCT_DISEASES,
    )

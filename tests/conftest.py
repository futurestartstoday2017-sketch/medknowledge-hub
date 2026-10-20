"""
conftest.py：テストで共通して使う準備（フィクスチャ）をまとめたファイルです。

フィクスチャ：テストの前に自動で用意される部品のことです。
テスト関数の引数に名前を書くだけで使えます（例：def test_xxx(conn, base): ...）。
本物のデータベース（data/medknowledge.db）には触らず、テストごとに使い捨てのDBを作ります。
"""

import pytest
import streamlit as st

import db.backup
import db.database
from db.database import get_connection, init_db


@pytest.fixture(autouse=True)
def isolated_app_db(tmp_path, monkeypatch):
    """
    すべてのテストで自動的に使われる準備です（autouse=True）。
    アプリ（app.py）を動かすテストが、本物の data/medknowledge.db やバックアップを作ったり変えたりしないよう、
    データベースとバックアップの場所を使い捨ての場所に差し替えます。
    """
    monkeypatch.setattr(db.database, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db.backup, "BACKUP_DIR", tmp_path / "backups")
    st.cache_resource.clear()  # 「最初の1回だけ」のDB準備を、テストごとにやり直させる
    yield
    st.cache_resource.clear()


@pytest.fixture
def db_path(tmp_path):
    """テスト用の使い捨てデータベースを作り、その場所を返します。"""
    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def conn(db_path):
    """テスト用データベースへの接続。テストが終わったら自動で閉じます。"""
    connection = get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def base(conn):
    """
    テストの土台になる架空データを登録し、それぞれのIDを辞書で返します。
    （架空の企業・製品・疾患・適応症と、製品にひも付いた添付文書1版）
    """
    with conn:
        ids = {}
        ids["company"] = conn.execute(
            "INSERT INTO companies (name_ja, is_target) VALUES ('テスト製薬', 1)").lastrowid
        ids["product"] = conn.execute(
            "INSERT INTO products (brand_name, generic_name, category) "
            "VALUES ('テストール錠', 'テストール', '対象企業')").lastrowid
        ids["disease"] = conn.execute(
            "INSERT INTO diseases (name_ja) VALUES ('架空疾患X')").lastrowid
        ids["indication"] = conn.execute(
            "INSERT INTO indications (product_id, disease_id) VALUES (?, ?)",
            (ids["product"], ids["disease"])).lastrowid
        ids["document"] = conn.execute(
            "INSERT INTO documents (doc_type, title) VALUES ('添付文書', 'テストール錠 添付文書')").lastrowid
        ids["version"] = conn.execute(
            "INSERT INTO document_versions (document_id, version_label, revised_on, retrieved_on, source_url) "
            "VALUES (?, '第1版', '2025-04', '2025-05-01', 'https://example.com/test/v1')",
            (ids["document"],)).lastrowid
        conn.execute(
            "INSERT INTO document_links (document_id, product_id) VALUES (?, ?)",
            (ids["document"], ids["product"]))
    return ids


def fact_values(base, **overrides):
    """医学的情報を1件登録するときの、標準的な値の組み合わせを作ります。"""
    values = {
        "product_id": base["product"],
        "fact_type": "作用機序",
        "content": "架空受容体Xを遮断する（架空）",
        "source_version_id": base["version"],
        "source_location": "18. 薬効薬理",
    }
    values.update(overrides)
    return values

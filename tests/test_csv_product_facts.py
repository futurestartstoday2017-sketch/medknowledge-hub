"""
test_csv_product_facts.py：「製造販売元・販売元」「製品の医学的情報」のCSVインポートのテストです。
（実データの準備で、添付文書から集めた情報を取り込むために追加した種類）
"""

import pytest

from services.csv_importer import KINDS, example_table, import_rows, read_csv, validate
from services.sample_loader import load_sample_data

SOURCE = "サンプル製薬 決算説明資料（架空）,2024年度 決算説明資料,p.1"


def table(kind, line):
    header = ",".join(h for h, _, _ in KINDS[kind]["columns"])
    return read_csv(f"{header}\n{line}\n".encode("utf-8"))


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


@pytest.mark.parametrize("kind", ["product_companies", "product_facts"])
def test_examples_import_as_unverified(loaded, kind):
    """記入例が取り込め、「未確認」で、指定した入力方法（AI抽出）で記録されることを確認します。"""
    assert validate(loaded, kind, example_table(kind)) == []
    import_rows(loaded, kind, example_table(kind), "山田", "テスト", entry_method="AI抽出")
    table_name = KINDS[kind]["fact_table"]
    row = loaded.execute(f"SELECT status, entry_method FROM {table_name} ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ("未確認", "AI抽出")


def test_product_company_is_linked_by_name(loaded):
    """企業名から企業IDに直して、製造販売元・販売元として登録されることを確認します。"""
    import_rows(loaded, "product_companies", example_table("product_companies"), "山田", "テスト")
    row = loaded.execute("""
        SELECT p.brand_name, c.name_ja, pc.role FROM product_companies pc
        JOIN products p ON p.id = pc.product_id JOIN companies c ON c.id = pc.company_id
        ORDER BY pc.id DESC LIMIT 1""").fetchone()
    assert tuple(row) == ("サンプリンα錠", "モデル薬品（架空）", "販売元")


@pytest.mark.parametrize("kind, line, expected", [
    ("product_companies", f"サンプリンα錠,存在しない製薬,販売元,{SOURCE}", "企業「存在しない製薬」が登録されていません"),
    ("product_companies", f"サンプリンα錠,モデル薬品（架空）,発売元,{SOURCE}", "「役割」は次のどれか"),
    ("product_companies", f"サンプリンα錠,サンプル製薬（架空）,製造販売元,{SOURCE}", "すでに登録"),
    ("product_facts", f"サンプリンα錠,効能・効果,（架空）,{SOURCE}", "「情報の種類」は次のどれか"),
    ("product_facts", "サンプリンα錠,その他,（架空）,,,", "「出典文書タイトル」は必須"),
    ("product_facts", f"サンプリンα錠,薬効分類,架空A系薬（架空）,{SOURCE}", "すでに登録"),
])
def test_errors(loaded, kind, line, expected):
    """誤りが日本語で知らされることを確認します。"""
    errors = validate(loaded, kind, table(kind, line))
    assert any(expected in e for e in errors), errors

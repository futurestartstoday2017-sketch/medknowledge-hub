"""
test_step4_samples.py：Step 4（架空データの登録）のテストです。
"""

import shutil

import pytest
from streamlit.testing.v1 import AppTest

from db.database import FACT_TABLES
from db.quality import find_quality_problems
from services.sample_loader import SAMPLES_DIR, load_sample_data, load_sample_data_if_empty
from tests.test_step2 import APP


@pytest.fixture
def loaded(conn):
    """架空データを登録した状態のデータベース接続を返します。"""
    load_sample_data(conn)
    return conn


def count(conn, sql):
    return conn.execute(sql).fetchone()[0]


# ---- 登録された件数 ----

def test_sample_counts(loaded):
    """指示書どおり、製品3件・疾患2件が登録されることを確認します。"""
    assert count(loaded, "SELECT COUNT(*) FROM products") == 3
    assert count(loaded, "SELECT COUNT(*) FROM diseases") == 2
    assert count(loaded, "SELECT COUNT(*) FROM companies WHERE is_target = 1") == 1
    assert count(loaded, "SELECT COUNT(*) FROM products WHERE category = '競合'") >= 1


def test_every_product_has_manufacturer_and_distributor(loaded):
    """すべての製品に、製造販売元と販売元が別々に登録されていることを確認します。"""
    rows = loaded.execute("""
        SELECT p.brand_name, COUNT(DISTINCT pc.role) AS roles
        FROM products p LEFT JOIN product_companies pc ON pc.product_id = p.id AND pc.is_current = 1
        GROUP BY p.id
    """).fetchall()
    assert all(r["roles"] == 2 for r in rows), [dict(r) for r in rows]


# ---- 品質 ----

def test_sample_data_has_no_quality_problems(loaded):
    """架空データに、出典の不一致や版の不整合がないことを確認します。"""
    assert find_quality_problems(loaded) == []


def test_sample_data_is_clearly_fictional(loaded):
    """
    実在の情報と誤解されないよう、架空データであることが明記されているか確認します。
    （内容に「架空」の文字があり、URLは例示用ドメイン example.com だけを使っている）
    """
    for table in ("medical_facts", "safety_info"):
        contents = [r[0] for r in loaded.execute(f"SELECT content FROM {table}")]
        assert all("架空" in c for c in contents), f"{table} に「架空」と書かれていない内容があります"
    urls = [r[0] for r in loaded.execute(
        "SELECT source_url FROM document_versions UNION ALL "
        "SELECT official_url FROM products WHERE official_url IS NOT NULL")]
    assert all(u.startswith("https://example.com/") for u in urls)


def test_all_facts_have_history(loaded):
    """すべての事実が「CSV」から登録され、更新履歴に「追加」が記録されていることを確認します。"""
    for table in FACT_TABLES:
        facts = count(loaded, f"SELECT COUNT(*) FROM {table}")
        csv_facts = count(loaded, f"SELECT COUNT(*) FROM {table} WHERE entry_method = 'CSV'")
        logged = count(loaded, f"SELECT COUNT(*) FROM change_log WHERE table_name = '{table}' AND action = '追加'")
        assert facts == csv_facts == logged > 0


def test_all_three_statuses_are_included(loaded):
    """画面の確認用に、3つの確認状態がすべて含まれていることを確認します。"""
    statuses = {r[0] for r in loaded.execute("SELECT status FROM medical_facts")}
    assert statuses == {"未確認", "原文確認済み", "再確認要"}


# ---- 登録のしかた ----

def test_load_only_when_empty(conn):
    """すでにデータがあるときは、二重に登録しないことを確認します。"""
    assert load_sample_data_if_empty(conn) is True
    assert load_sample_data_if_empty(conn) is False
    assert count(conn, "SELECT COUNT(*) FROM products") == 3


def test_broken_sample_rolls_back_everything(conn, tmp_path):
    """CSVの途中に誤りがあると、エラーを日本語で知らせ、何も登録されないことを確認します。"""
    broken_dir = tmp_path / "samples"
    shutil.copytree(SAMPLES_DIR, broken_dir)
    # 最後に読むCSVに、存在しない製品の行を足す
    with open(broken_dir / "safety_info.csv", "a", encoding="utf-8") as f:
        f.write("存在しない製品,禁忌,（架空）テスト,サンプリンα錠 添付文書（架空）,"
                "2025年4月改訂（第2版）,2. 禁忌,未確認\n")

    with pytest.raises(ValueError, match="製品が見つかりません"):
        load_sample_data(conn, broken_dir)

    for table in ("products", "documents", "medical_facts", "change_log"):
        assert count(conn, f"SELECT COUNT(*) FROM {table}") == 0, f"{table} にデータが残っています"


# ---- ホーム画面 ----

def test_home_shows_counts_from_database():
    """アプリを起動すると架空データが登録され、ホームに実際の件数が表示されることを確認します。"""
    at = AppTest.from_file(APP).run()
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values["登録製品数"] == "3"
    assert values["登録疾患数"] == "2"
    # 添付文書・IF・ガイドライン6件 + RMP3件・決算説明資料2件（Step 9）+ 臨床試験の登録ページ5件（Step 10）
    assert values["登録文書数"] == "16"
    assert int(values["更新確認待ち"]) > 0
    assert any("架空データ" in w.value for w in at.warning)

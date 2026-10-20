"""
test_step8_csv_import.py：Step 8（CSVインポート）のテストです。

CSVの文字を直接書いてテストします。誤りがあるときに「何も登録されない」ことを重点的に確かめます。
"""

import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from services.csv_importer import (
    DOC_TYPES, KINDS, TEMPLATES_DIR, import_rows, read_csv, template_bytes, validate,
)
from services.sample_loader import load_sample_data
from tests.test_step2 import APP

PRODUCTS_CSV = """販売名,一般名,区分,公式製品URL,最終確認日
サンプリンβ錠,サンプリン,対象企業,https://example.com/b,2025-11-01
ベツモノ注,ベツモノ,競合,,
"""
DISEASES_CSV = """疾患名,英語名
架空慢性疾患C,Fictional chronic disease C
"""
DOCUMENTS_CSV = """文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名
添付文書,サンプリンβ錠 添付文書（架空）,サンプル製薬（架空）,,第1版,2025-10,2025-11-01,https://example.com/b/pi1,はい,サンプリンβ錠,
"""
INDICATIONS_CSV = """販売名,疾患名,効能・効果の文言,出典文書タイトル,出典の版,該当箇所
サンプリンβ錠,架空慢性疾患C,（架空）架空慢性疾患C,サンプリンβ錠 添付文書（架空）,第1版,4. 効能又は効果
"""


def table(text, encoding="utf-8"):
    """テスト用：CSVの文字から、読み込み済みの表を作ります。"""
    return read_csv(text.encode(encoding))


def count(conn, sql):
    return conn.execute(sql).fetchone()[0]


def import_all(conn):
    """テスト用：製品 → 疾患 → 文書と版 → 適応症 の順に取り込みます。"""
    for kind, text in [("products", PRODUCTS_CSV), ("diseases", DISEASES_CSV),
                       ("documents", DOCUMENTS_CSV), ("indications", INDICATIONS_CSV)]:
        assert validate(conn, kind, table(text)) == [], kind
        import_rows(conn, kind, table(text), "山田", f"CSVインポート（{kind}）")


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


# ---- テンプレート・読み込み ----

def test_templates_match_definitions():
    """data/templates/ のテンプレートの見出しが、取り込みの定義と一致していることを確認します。"""
    for kind, spec in KINDS.items():
        # 改行の違い（Windows の CRLF と LF）は、Git が自動で変えることがあるので無視して比べる
        content = (TEMPLATES_DIR / spec["file"]).read_bytes().replace(b"\r\n", b"\n")
        assert content == template_bytes(kind), f"{spec['file']} が古くなっています"


def test_examples_have_all_columns():
    """記入例の数が、列の数と一致していることを確認します。"""
    for spec in KINDS.values():
        assert len(spec["example"]) == len(spec["columns"])


def test_read_csv_from_excel_shift_jis():
    """Excel で保存した Shift_JIS のCSVも、文字化けせずに読めることを確認します。"""
    assert table(DISEASES_CSV, "cp932").iloc[0]["疾患名"] == "架空慢性疾患C"
    assert table(DISEASES_CSV, "utf-8-sig").iloc[0]["疾患名"] == "架空慢性疾患C"


def test_doc_types_are_accepted_by_database(conn):
    """取り込みで使える文書種別が、すべてデータベースのルールでも使えることを確認します。"""
    with conn:
        for i, doc_type in enumerate(DOC_TYPES):
            conn.execute("INSERT INTO documents (doc_type, title) VALUES (?, ?)", (doc_type, f"テスト{i}"))


# ---- 正しいCSVの取り込み ----

def test_import_all_kinds(loaded):
    """4種類のCSVを順番に取り込めることを確認します。"""
    import_all(loaded)
    assert count(loaded, "SELECT COUNT(*) FROM products") == 5
    assert count(loaded, "SELECT COUNT(*) FROM diseases") == 3
    assert count(loaded, "SELECT COUNT(*) FROM document_links l JOIN products p ON p.id = l.product_id "
                         "WHERE p.brand_name = 'サンプリンβ錠'") == 1


def test_imported_fact_is_unverified_and_logged(loaded):
    """CSVで取り込んだ効能・効果は「未確認」で、入力方法が「CSV」、確認者つきで履歴に残ることを確認します。"""
    import_all(loaded)
    fact = loaded.execute("SELECT * FROM medical_facts WHERE content = '（架空）架空慢性疾患C'").fetchone()
    assert fact["status"] == "未確認" and fact["entry_method"] == "CSV"
    logged = loaded.execute("SELECT changed_by FROM change_log WHERE table_name = 'medical_facts' "
                            "AND record_id = ?", (fact["id"],)).fetchone()
    assert logged["changed_by"] == "山田"


def test_every_imported_row_is_logged(loaded):
    """取り込んだ製品・疾患などが、すべて更新履歴に記録されることを確認します。"""
    import_all(loaded)
    for table_name in ("products", "diseases", "documents", "document_versions", "document_links", "indications"):
        assert count(loaded, f"SELECT COUNT(*) FROM change_log WHERE table_name = '{table_name}' "
                             "AND changed_by = '山田'") >= 1, table_name


def test_new_version_of_existing_document(loaded):
    """登録済みの文書に新しい版を取り込むと最新版が切り替わり、確認済み情報が「再確認要」になることを確認します。"""
    csv = ("文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名\n"
           "添付文書,サンプリンα錠 添付文書（架空）,,,第3版,2025-10,2025-11-01,https://example.com/v3,はい,サンプリンα錠,\n")
    assert validate(loaded, "documents", table(csv)) == []
    import_rows(loaded, "documents", table(csv), "山田", "改訂版の取り込み")
    assert count(loaded, "SELECT COUNT(*) FROM medical_facts f JOIN document_versions v ON v.id = f.source_version_id "
                         "WHERE v.is_current = 0 AND f.is_current = 1 AND f.status = '原文確認済み'") == 0


def test_blank_lines_are_ignored(loaded):
    """空の行は無視されることを確認します。"""
    assert validate(loaded, "diseases", table(DISEASES_CSV + ",\n\n")) == []


# ---- 誤りの検出（何も登録しない） ----

@pytest.mark.parametrize("kind, csv, expected", [
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\n,テスト,対象企業,,\n", "「販売名」は必須"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\nテスト錠,,自社,,\n", "「区分」は「対象企業」か「競合」"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\nテスト錠,,競合,,2025/11/01\n", "YYYY-MM-DD"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\nテスト錠,,競合,,2025-02-30\n", "正しい日付"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\nテスト錠,,競合,example.com,\n", "http"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\nサンプリンα錠,,対象企業,,\n", "すでに登録"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\nA錠,,競合,,\nA錠,,競合,,\n", "3行目：販売名が 2行目 と重複"),
    ("products", "販売名,一般名,区分\nA錠,,競合\n", "見出しに必要な列がありません"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日,メモ\nA錠,,競合,,,\n", "知らない列"),
    ("products", "販売名,一般名,区分,公式製品URL,最終確認日\n", "データの行がありません"),
    ("diseases", "疾患名,英語名\n架空慢性疾患A,\n", "すでに登録"),
    ("documents",
     "文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名\n"
     "添付文書,新文書,,,第1版,2025-10,2025-11-01,https://example.com/x,はい,存在しない錠,\n", "登録されていません"),
    ("documents",
     "文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名\n"
     "添付文書,新文書,,,第1版,2025-10,2025-11-01,https://example.com/x,はい,,\n", "どちらかを入力"),
    ("documents",
     "文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名\n"
     "メモ,新文書,,,第1版,2025-10,2025-11-01,https://example.com/x,はい,サンプリンα錠,\n", "文書種別"),
    ("documents",
     "文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名\n"
     "添付文書,サンプリンα錠 添付文書（架空）,,,古い版,2020-01,2025-11-01,https://example.com/x,はい,サンプリンα錠,\n",
     "最新版にできません"),
    ("documents",
     "文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名\n"
     "添付文書,新文書,,,第1版,2025-10,2025-11-01,https://example.com/x,いいえ,サンプリンα錠,\n", "最新版の行がありません"),
    ("documents",
     "文書種別,文書タイトル,発行元,識別番号,版,改訂年月,入手日,原文URL,最新版,関連する販売名,関連する疾患名\n"
     "添付文書,新文書,,,第1版,2025-10,2025-11-01,https://example.com/x,はい,サンプリンα錠,\n"
     "添付文書,新文書,,,第2版,2025-11,2025-11-01,https://example.com/y,はい,サンプリンα錠,\n", "最新版は1つ"),
    ("indications", "販売名,疾患名,効能・効果の文言,出典文書タイトル,出典の版,該当箇所\n"
                    "サンプリンα錠,架空慢性疾患A,,,,\n", "すでに登録"),
    ("indications", "販売名,疾患名,効能・効果の文言,出典文書タイトル,出典の版,該当箇所\n"
                    "サンプリンα錠,架空慢性疾患B,（架空）文言,,,\n", "出典のない医学的情報は登録できません"),
    ("indications", "販売名,疾患名,効能・効果の文言,出典文書タイトル,出典の版,該当箇所\n"
                    "サンプリンα錠,架空慢性疾患B,（架空）文言,存在しない文書,第1版,4.\n", "登録されていません"),
    ("indications", "販売名,疾患名,効能・効果の文言,出典文書タイトル,出典の版,該当箇所\n"
                    "サンプリンα錠,架空慢性疾患B,（架空）文言,テスタミドOD錠 添付文書（架空）,2025年1月作成（第1版）,4.\n",
     "ひも付いていません"),
    ("indications", "販売名,疾患名,効能・効果の文言,出典文書タイトル,出典の版,該当箇所\n"
                    "サンプリンα錠,架空慢性疾患A,（架空）架空慢性疾患A,サンプリンα錠 添付文書（架空）,"
                    "2025年4月改訂（第2版）,4. 効能又は効果\n", "同じ効能・効果の文言"),
])
def test_errors_are_detected_in_japanese(loaded, kind, csv, expected):
    """誤りが日本語で報告され、登録しようとしても何も変わらないことを確認します。"""
    errors = validate(loaded, kind, table(csv))
    assert any(expected in e for e in errors), errors

    logs_before = count(loaded, "SELECT COUNT(*) FROM change_log")
    with pytest.raises(ValueError):
        import_rows(loaded, kind, table(csv), "山田", "テスト")
    assert count(loaded, "SELECT COUNT(*) FROM change_log") == logs_before


def test_one_bad_row_blocks_whole_file(loaded):
    """正しい行があっても、1行でも誤りがあればファイル全体を登録しないことを確認します。"""
    csv = "販売名,一般名,区分,公式製品URL,最終確認日\n正しい錠,,競合,,\n誤り錠,,不明,,\n"
    with pytest.raises(ValueError):
        import_rows(loaded, "products", table(csv), "山田", "テスト")
    assert count(loaded, "SELECT COUNT(*) FROM products WHERE brand_name = '正しい錠'") == 0


def test_failure_during_import_rolls_back(loaded):
    """検証のあとの登録中にエラーが起きても、途中までの登録が残らないことを確認します。"""
    import_all(loaded)
    products_before = count(loaded, "SELECT COUNT(*) FROM products")
    with pytest.raises(sqlite3.IntegrityError):
        # 確認者名が空 → 更新履歴のルールで登録中にエラーになる
        import_rows(loaded, "products", table("販売名,一般名,区分,公式製品URL,最終確認日\nX錠,,競合,,\nY錠,,競合,,\n"),
                    "", "テスト")
    assert count(loaded, "SELECT COUNT(*) FROM products") == products_before


# ---- 画面 ----

def test_data_page_runs():
    """データ管理画面が表示され、種類を切り替えても動くことを確認します。"""
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.switch_page("pages/データ管理.py").run()
    assert not at.exception
    for kind in KINDS:
        at.radio(key="import_kind").set_value(kind).run()
        assert not at.exception, kind
    assert any("バックアップはまだありません" in i.value for i in at.info)

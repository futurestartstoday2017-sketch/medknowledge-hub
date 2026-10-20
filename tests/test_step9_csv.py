"""
test_step9_csv.py：Step 9-3（企業・承認・再審査・特許・ライセンス・PMS のCSVインポート）のテストです。
"""

import pytest

from services.csv_importer import KINDS, example_table, import_rows, read_csv, validate
from services.sample_loader import load_sample_data

FACT_KINDS = ["approvals", "reexaminations", "patents", "licenses", "pms_studies"]
SOURCE = "サンプル製薬 決算説明資料（架空）,2024年度 決算説明資料,（架空）p.14"  # サンプリンα錠にひも付いた出典


def table(text):
    return read_csv(text.encode("utf-8"))


def header(kind):
    return ",".join(h for h, _, _ in KINDS[kind]["columns"])


def count(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


@pytest.fixture
def loaded(conn):
    load_sample_data(conn)
    return conn


# ---- 正しいCSVの取り込み ----

@pytest.mark.parametrize("kind", ["companies", *FACT_KINDS])
def test_examples_can_be_imported(loaded, kind):
    """画面に出す記入例が、そのまま正しく取り込めることを確認します（記入例の誤りを防ぐ）。"""
    assert validate(loaded, kind, example_table(kind)) == []
    assert import_rows(loaded, kind, example_table(kind), "山田", "テスト") == 1


@pytest.mark.parametrize("kind", FACT_KINDS)
def test_imported_facts_are_unverified_and_logged(loaded, kind):
    """取り込んだ承認・特許などが「未確認」「CSV」で登録され、確認者つきで履歴に残ることを確認します。"""
    table_name = KINDS[kind]["fact_table"]
    import_rows(loaded, kind, example_table(kind), "山田", "CSVインポート")
    row = loaded.execute(f"SELECT * FROM {table_name} ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["status"], row["entry_method"]) == ("未確認", "CSV")
    assert count(loaded, "SELECT COUNT(*) FROM change_log WHERE table_name = ? AND record_id = ? "
                         "AND changed_by = '山田'", (table_name, row["id"])) == 1


def test_defaults_are_applied(loaded):
    """空欄のとき、特許の国は「日本」、種類は「不明」、PMSの全例調査かなどは「未確認」になることを確認します。"""
    import_rows(loaded, "patents", table(f"{header('patents')}\n"
                                         f"サンプリンα錠,特許第0000008号（架空）,,,,未確認,,,{SOURCE}\n"), "山田", "テスト")
    patent = loaded.execute("SELECT country, patent_kind FROM patents ORDER BY id DESC LIMIT 1").fetchone()
    assert (patent["country"], patent["patent_kind"]) == ("日本", "不明")

    import_rows(loaded, "pms_studies", table(f"{header('pms_studies')}\n"
                                             f"サンプリンα錠,,その他,（架空）新しい調査,,,,,未確認,,,,{SOURCE}\n"),
                "山田", "テスト")
    pms = loaded.execute("SELECT all_case, approval_condition, progress FROM pms_studies "
                         "ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(pms) == ("未確認", "未確認", "未確認")


def test_indication_is_linked_by_disease_name(loaded):
    """「対象の疾患名」を書くと、その製品の適応症にひも付いて登録されることを確認します。"""
    csv = f"{header('reexaminations')}\nサンプリンα錠,架空慢性疾患A,（架空）効能追加の再審査,非公開,,,,{SOURCE}\n"
    import_rows(loaded, "reexaminations", table(csv), "山田", "テスト")
    row = loaded.execute("SELECT i.product_id, i.disease_id FROM reexaminations r "
                         "JOIN indications i ON i.id = r.indication_id ORDER BY r.id DESC LIMIT 1").fetchone()
    assert tuple(row) == (1, 1)


# ---- 誤りの検出（何も登録しない） ----

@pytest.mark.parametrize("kind, line, expected", [
    # 企業
    ("companies", "サンプル製薬（架空）,,", "すでに登録"),
    ("companies", "新しい製薬,,はい", "対象企業は1社だけ"),
    ("companies", "新しい製薬,,たぶん", "「はい」か「いいえ」"),
    # 承認
    ("approvals", f"サンプリンα錠,,初回承認,2020-01-01,,（架空）,{SOURCE}", "初回承認はすでに登録"),
    ("approvals", f"サンプリンα錠,,本承認,2020-01-01,,（架空）,{SOURCE}", "「承認の種類」は次のどれか"),
    ("approvals", f"サンプリンα錠,,その他,2020/01/01,,（架空）,{SOURCE}", "YYYY-MM-DD"),
    ("approvals", f"存在しない錠,,その他,2020-01-01,,（架空）,{SOURCE}", "登録されていません"),
    ("approvals", f"サンプリンα錠,架空慢性疾患B,その他,2020-01-01,,（架空）,{SOURCE}", "適応症「サンプリンα錠 × 架空慢性疾患B」"),
    ("approvals", "サンプリンα錠,,その他,2020-01-01,,（架空）,,,", "「出典文書タイトル」は必須"),
    ("approvals", "サンプリンα錠,,その他,2020-01-01,,（架空）,モデル薬品 決算説明資料（架空）,2024年度 決算説明資料,p.1",
     "ひも付いていません"),
    ("approvals", "サンプリンα錠,,その他,2020-01-01,,（架空）,存在しない文書,第1版,p.1", "登録されていません"),
    # 再審査
    ("reexaminations", f"サンプリンα錠,,（架空）,非公開,8,,,{SOURCE}", "空欄にしてください"),
    ("reexaminations", f"サンプリンα錠,,（架空）,公開,,,,{SOURCE}", "1つ以上入力"),
    ("reexaminations", f"サンプリンα錠,,（架空）,公開,八,,,{SOURCE}", "1以上の整数"),
    ("reexaminations", f"サンプリンα錠,,（架空）新有効成分含有医薬品としての再審査期間,公開,8,2016-03-28,2024-03-27,{SOURCE}",
     "すでに登録"),
    # 特許
    ("patents", f"サンプリンα錠,特許第0000001号（架空）,日本,物質,,公開,2027-05-31,,{SOURCE}", "すでに登録"),
    ("patents", f"サンプリンα錠,特許第0000007号（架空）,,特殊,,公開,2030-01-01,,{SOURCE}", "「特許の種類」は次のどれか"),
    ("patents", f"サンプリンα錠,特許第0000007号（架空）,,,,公開,2030-01-01,2029-01-01,{SOURCE}", "より後の日付"),
    # ライセンス
    ("licenses", f"サンプリンα錠,存在しない薬品,導入元,導入,,（架空）,未確認,,,,{SOURCE}", "先に「企業」を取り込んで"),
    ("licenses", f"サンプリンα錠,モデル薬品（架空）,親会社,導入,,（架空）,未確認,,,,{SOURCE}", "「相手先の役割」は次のどれか"),
    # PMS
    ("pms_studies", f"サンプリンα錠,,その他,（架空）調査,たぶん全例,,,,未確認,,,,{SOURCE}", "「全例調査か」は次のどれか"),
    ("pms_studies", f"サンプリンα錠,,その他,サンプリンα錠 一般使用成績調査（架空）,,,,,未確認,,,,{SOURCE}", "すでに登録"),
])
def test_errors_are_detected_in_japanese(loaded, kind, line, expected):
    """誤りが行番号つきの日本語で報告され、登録しようとしても何も変わらないことを確認します。"""
    csv = table(f"{header(kind)}\n{line}\n")
    errors = validate(loaded, kind, csv)
    assert any(expected in e for e in errors), errors
    assert all(e.startswith("2行目") or "行目" not in e for e in errors)

    logs_before = count(loaded, "SELECT COUNT(*) FROM change_log")
    with pytest.raises(ValueError):
        import_rows(loaded, kind, csv, "山田", "テスト")
    assert count(loaded, "SELECT COUNT(*) FROM change_log") == logs_before


def test_duplicate_rows_in_file(loaded):
    """CSVの中に同じ内容の行が2つあると、重複として知らされることを確認します。"""
    row = f"サンプリンα錠,特許第0000007号（架空）,,,,未確認,,,{SOURCE}"
    errors = validate(loaded, "patents", table(f"{header('patents')}\n{row}\n{row}\n"))
    assert any("3行目：2行目 と同じ内容" in e for e in errors), errors


def test_two_first_approvals_in_file(conn, base):
    """同じ製品の初回承認が、CSVの中に2行あると知らされることを確認します。"""
    source = "テストール錠 添付文書,第1版,p.1"  # tests/conftest.py の base で作る出典
    csv = (f"{header('approvals')}\n"
           f"テストール錠,,初回承認,2020-01-01,,（架空）,{source}\n"
           f"テストール錠,,初回承認,2020-02-01,,（架空）,{source}\n")
    errors = validate(conn, "approvals", table(csv))
    assert any("初回承認が 2行目 にも" in e for e in errors), errors

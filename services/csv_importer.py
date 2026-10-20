"""
csv_importer.py：CSVファイルを検証して、データベースに取り込む処理です。

取り込みは次の順で行います。
  1. read_csv()     ：CSVを読み込む（UTF-8 と、Excel の Shift_JIS のどちらでも読める）
  2. validate()     ：必須項目・値の形・重複・関連付けを検証し、誤りを日本語の一覧で返す
  3. import_rows()  ：誤りが1つもなければ、1つのトランザクションで登録する（1つでもあれば何も登録しない）

CSVで取り込んだ医学的情報（効能・効果の文言）は、必ず「未確認」で登録します。
「原文確認済み」にするのは、更新管理画面で原文を確認してからです。

取り込める種類（KINDS）：製品 / 疾患 / 文書と版 / 適応症
"""

import io
import re
from collections import Counter
from datetime import date

import pandas as pd

from db.changes import add_record, get_row, log_change, transaction
from db.database import ROOT
from services.updates import register_document_version

TEMPLATES_DIR = ROOT / "data" / "templates"

# 文書種別として使える値（db/schema.sql の documents テーブルのルールと同じ）
DOC_TYPES = [
    "添付文書", "インタビューフォーム", "RMP", "審査報告書", "診療ガイドライン", "論文", "臨床試験登録",
    "有価証券報告書・IR資料", "プレスリリース", "特許公報", "企業サイト", "その他",
]

# 取り込める種類と、その列の定義：(CSVの見出し, 中での名前, 必須かどうか)
KINDS = {
    "products": {
        "label": "製品",
        "file": "products.csv",
        "columns": [
            ("販売名", "brand_name", True),
            ("一般名", "generic_name", False),
            ("区分", "category", True),
            ("公式製品URL", "official_url", False),
            ("最終確認日", "last_checked_on", False),
        ],
        "example": ["サンプリンβ錠", "サンプリン", "対象企業", "https://example.com/sampurin-b", "2025-11-01"],
    },
    "diseases": {
        "label": "疾患",
        "file": "diseases.csv",
        "columns": [
            ("疾患名", "name_ja", True),
            ("英語名", "name_en", False),
        ],
        "example": ["架空慢性疾患C", "Fictional chronic disease C"],
    },
    "documents": {
        "label": "文書と版",
        "file": "documents.csv",
        "columns": [
            ("文書種別", "doc_type", True),
            ("文書タイトル", "title", True),
            ("発行元", "publisher", False),
            ("識別番号", "external_id", False),
            ("版", "version_label", True),
            ("改訂年月", "revised_on", False),
            ("入手日", "retrieved_on", True),
            ("原文URL", "source_url", True),
            ("最新版", "is_current", False),
            ("関連する販売名", "brand_name", False),
            ("関連する疾患名", "disease_name", False),
        ],
        "example": ["添付文書", "サンプリンβ錠 添付文書（架空）", "サンプル製薬（架空）", "", "2025年10月作成（第1版）",
                    "2025-10", "2025-11-01", "https://example.com/sampurin-b/pi/v1", "はい", "サンプリンβ錠", ""],
    },
    "indications": {
        "label": "適応症",
        "file": "indications.csv",
        "columns": [
            ("販売名", "brand_name", True),
            ("疾患名", "disease_name", True),
            ("効能・効果の文言", "content", False),
            ("出典文書タイトル", "doc_title", False),
            ("出典の版", "version_label", False),
            ("該当箇所", "source_location", False),
        ],
        "example": ["サンプリンβ錠", "架空慢性疾患C", "（架空）架空慢性疾患C", "サンプリンβ錠 添付文書（架空）",
                    "2025年10月作成（第1版）", "4. 効能又は効果"],
    },
}


# ---------------------------------------------------------------------
# 1. 読み込み
# ---------------------------------------------------------------------

def read_csv(data):
    """
    CSVのバイト列（アップロードされたファイルの中身）を読み込み、表（DataFrame）で返します。
    まず UTF-8 で読み、文字化けする場合は Excel の標準の Shift_JIS（cp932）で読み直します。
    """
    for encoding in ("utf-8-sig", "cp932"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSVの文字コードを読み取れませんでした。UTF-8 か Shift_JIS で保存してください。")
    # dtype=str：すべて文字列として読む／keep_default_na=False：空欄を勝手に NaN にしない
    table = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    table.columns = [str(c).strip() for c in table.columns]
    return table


def to_rows(kind, table):
    """
    表を、中での名前（brand_name など）を使った辞書のリストにします。空欄は None になります。
    1行ごとに "_line"（CSVファイル上の行番号。見出しが1行目なので、データは2行目から）を付けます。
    すべての列が空の行は無視します。
    """
    columns = KINDS[kind]["columns"]
    rows = []
    for index, record in enumerate(table.to_dict(orient="records")):
        row = {name: (str(record.get(header, "")).strip() or None) for header, name, _ in columns}
        if any(value is not None for value in row.values()):
            rows.append({**row, "_line": index + 2})
    return rows


# ---------------------------------------------------------------------
# 2. 検証
# ---------------------------------------------------------------------

def validate(conn, kind, table):
    """CSVの内容を検証し、誤りの説明（日本語）のリストを返します。誤りがなければ空のリストです。"""
    spec = KINDS[kind]
    expected = [header for header, _, _ in spec["columns"]]

    # 見出しの確認（足りない列・知らない列）
    missing = [h for h in expected if h not in table.columns]
    unknown = [h for h in table.columns if h not in expected]
    errors = []
    if missing:
        errors.append(f"見出しに必要な列がありません：{'、'.join(missing)}")
    if unknown:
        errors.append(f"知らない列があります（見出しの書き間違いの可能性）：{'、'.join(unknown)}")
    if errors:
        return errors

    rows = to_rows(kind, table)
    if not rows:
        return ["データの行がありません（見出しの下に1行以上必要です）。"]

    # 必須項目の確認
    for row in rows:
        for header, name, required in spec["columns"]:
            if required and not row[name]:
                errors.append(f"{row['_line']}行目：「{header}」は必須です。")

    # 種類ごとの確認
    checker = {"products": _check_products, "diseases": _check_diseases,
               "documents": _check_documents, "indications": _check_indications}[kind]
    errors.extend(checker(conn, rows))
    return errors


def _check_products(conn, rows):
    errors = []
    for row in rows:
        line = row["_line"]
        if row["category"] and row["category"] not in ("対象企業", "競合"):
            errors.append(f"{line}行目：「区分」は「対象企業」か「競合」にしてください（今の値：{row['category']}）。")
        errors += _check_date(line, "最終確認日", row["last_checked_on"])
        errors += _check_url(line, "公式製品URL", row["official_url"])
        if row["brand_name"] and _product_id(conn, row["brand_name"]):
            errors.append(f"{line}行目：販売名「{row['brand_name']}」はすでに登録されています。")
    errors += _check_duplicates(rows, ["brand_name"], "販売名")
    return errors


def _check_diseases(conn, rows):
    errors = []
    for row in rows:
        if row["name_ja"] and _disease_id(conn, row["name_ja"]):
            errors.append(f"{row['_line']}行目：疾患名「{row['name_ja']}」はすでに登録されています。")
    errors += _check_duplicates(rows, ["name_ja"], "疾患名")
    return errors


def _check_documents(conn, rows):
    errors = []
    current_rows = Counter()  # 文書ごとの「最新版=はい」の行数
    for row in rows:
        line = row["_line"]
        if row["doc_type"] and row["doc_type"] not in DOC_TYPES:
            errors.append(f"{line}行目：「文書種別」は次のどれかにしてください：{'、'.join(DOC_TYPES)}")
        errors += _check_date(line, "入手日", row["retrieved_on"])
        errors += _check_url(line, "原文URL", row["source_url"])
        if row["revised_on"] and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", row["revised_on"]):
            errors.append(f"{line}行目：「改訂年月」は YYYY-MM の形にしてください（例：2025-10）。")
        if row["is_current"] not in (None, "はい", "いいえ"):
            errors.append(f"{line}行目：「最新版」は「はい」か「いいえ」にしてください（空欄は「はい」）。")
        is_current = row["is_current"] != "いいえ"

        # 関連する製品・疾患（どちらか1つ以上必要。登録済みのものだけ指定できる）
        if not row["brand_name"] and not row["disease_name"]:
            errors.append(f"{line}行目：「関連する販売名」か「関連する疾患名」のどちらかを入力してください。")
        if row["brand_name"] and not _product_id(conn, row["brand_name"]):
            errors.append(f"{line}行目：関連する販売名「{row['brand_name']}」が登録されていません（先に製品を取り込んでください）。")
        if row["disease_name"] and not _disease_id(conn, row["disease_name"]):
            errors.append(f"{line}行目：関連する疾患名「{row['disease_name']}」が登録されていません（先に疾患を取り込んでください）。")

        if not (row["doc_type"] and row["title"]):
            continue
        document = _document(conn, row["doc_type"], row["title"])
        if is_current:
            current_rows[(row["doc_type"], row["title"])] += 1
        if document:
            # 同じ版がすでに登録されていないか
            if row["version_label"] and conn.execute(
                    "SELECT 1 FROM document_versions WHERE document_id = ? AND version_label = ?",
                    (document["id"], row["version_label"])).fetchone():
                errors.append(f"{line}行目：「{row['title']}」の版「{row['version_label']}」はすでに登録されています。")
            # 最新版にする版が、登録済みの版より古くないか
            if is_current and row["revised_on"]:
                newest = conn.execute("SELECT max(revised_on) FROM document_versions WHERE document_id = ?",
                                      (document["id"],)).fetchone()[0]
                if newest and newest > row["revised_on"]:
                    errors.append(f"{line}行目：改訂年月 {row['revised_on']} は、登録済みの版（{newest}）より古いため、"
                                  "最新版にできません（「最新版」を「いいえ」にしてください）。")
        else:
            # 新しい文書なのに、識別番号が別の文書と重なっていないか
            if row["external_id"] and conn.execute(
                    "SELECT 1 FROM documents WHERE doc_type = ? AND external_id = ?",
                    (row["doc_type"], row["external_id"])).fetchone():
                errors.append(f"{line}行目：識別番号「{row['external_id']}」は、別の文書ですでに使われています。")

    for (doc_type, title), number in current_rows.items():
        if number > 1:
            errors.append(f"文書「{title}」で「最新版=はい」の行が {number} 行あります。最新版は1つにしてください。")
    # 新しく登録する文書には、最新版の行が1つ必要
    for row in rows:
        key = (row["doc_type"], row["title"])
        if all(key) and not _document(conn, *key) and current_rows[key] == 0:
            errors.append(f"{row['_line']}行目：新しい文書「{row['title']}」に最新版の行がありません。")
            current_rows[key] = -1  # 同じ文書で何度も表示しないための印
    errors += _check_duplicates(rows, ["doc_type", "title", "version_label"], "文書種別・文書タイトル・版")
    return errors


def _check_indications(conn, rows):
    errors = []
    for row in rows:
        line = row["_line"]
        product_id = _product_id(conn, row["brand_name"]) if row["brand_name"] else None
        disease_id = _disease_id(conn, row["disease_name"]) if row["disease_name"] else None
        if row["brand_name"] and not product_id:
            errors.append(f"{line}行目：販売名「{row['brand_name']}」が登録されていません（先に製品を取り込んでください）。")
        if row["disease_name"] and not disease_id:
            errors.append(f"{line}行目：疾患名「{row['disease_name']}」が登録されていません（先に疾患を取り込んでください）。")
        if not (product_id and disease_id):
            continue

        indication = conn.execute("SELECT id FROM indications WHERE product_id = ? AND disease_id = ?",
                                  (product_id, disease_id)).fetchone()
        if not row["content"]:
            if indication:
                errors.append(f"{line}行目：「{row['brand_name']} × {row['disease_name']}」はすでに登録されています"
                              "（効能・効果の文言を追加する場合は、文言と出典を入力してください）。")
            if row["doc_title"] or row["version_label"] or row["source_location"]:
                errors.append(f"{line}行目：出典を入力するときは「効能・効果の文言」も入力してください。")
            continue

        # 効能・効果の文言があるときは、出典（文書タイトル・版・該当箇所）が必須
        for header, name in [("出典文書タイトル", "doc_title"), ("出典の版", "version_label"), ("該当箇所", "source_location")]:
            if not row[name]:
                errors.append(f"{line}行目：効能・効果の文言を入力したときは「{header}」も必須です（出典のない医学的情報は登録できません）。")
        if not (row["doc_title"] and row["version_label"]):
            continue
        versions = conn.execute(
            "SELECT v.id, v.document_id FROM document_versions v JOIN documents d ON d.id = v.document_id "
            "WHERE d.title = ? AND v.version_label = ?", (row["doc_title"], row["version_label"])).fetchall()
        if not versions:
            errors.append(f"{line}行目：出典「{row['doc_title']} ／ {row['version_label']}」が登録されていません"
                          "（先に「文書と版」を取り込んでください）。")
            continue
        if len(versions) > 1:
            errors.append(f"{line}行目：出典「{row['doc_title']}」に一致する文書が複数あります。")
            continue
        linked = conn.execute(
            "SELECT 1 FROM document_links WHERE document_id = ? AND (product_id = ? OR disease_id = ?)",
            (versions[0]["document_id"], product_id, disease_id)).fetchone()
        if not linked:
            errors.append(f"{line}行目：出典「{row['doc_title']}」が、製品「{row['brand_name']}」にも"
                          f"疾患「{row['disease_name']}」にもひも付いていません。")
        if indication and conn.execute(
                "SELECT 1 FROM medical_facts WHERE indication_id = ? AND fact_type = '効能・効果' "
                "AND content = ? AND is_current = 1", (indication["id"], row["content"])).fetchone():
            errors.append(f"{line}行目：同じ効能・効果の文言がすでに登録されています。")
    errors += _check_duplicates(rows, ["brand_name", "disease_name"], "販売名・疾患名の組み合わせ")
    return errors


def _check_duplicates(rows, names, label):
    """CSVの中で、同じ値（names の組み合わせ）の行が2つ以上ないか確かめます。"""
    seen = {}
    errors = []
    for row in rows:
        key = tuple(row[n] for n in names)
        if not all(key):
            continue
        if key in seen:
            errors.append(f"{row['_line']}行目：{label}が {seen[key]}行目 と重複しています。")
        else:
            seen[key] = row["_line"]
    return errors


def _check_date(line, header, value):
    """日付が YYYY-MM-DD の形で、実在する日付か確かめます。"""
    if not value:
        return []
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        return [f"{line}行目：「{header}」は YYYY-MM-DD の形の正しい日付にしてください（例：2025-11-01）。"]
    return []


def _check_url(line, header, value):
    if value and not value.startswith(("http://", "https://")):
        return [f"{line}行目：「{header}」は http:// か https:// で始まるURLにしてください。"]
    return []


# ---------------------------------------------------------------------
# 3. 登録
# ---------------------------------------------------------------------

def import_rows(conn, kind, table, reviewer, reason):
    """
    CSVの内容を登録し、登録した行数を返します。
    登録の直前にもう一度検証し、誤りがあれば何も登録せずに ValueError を出します。
    すべての登録を更新履歴（確認者・理由つき）に残します。
    """
    errors = validate(conn, kind, table)
    if errors:
        raise ValueError("CSVに誤りがあるため登録しませんでした：" + " / ".join(errors))
    rows = to_rows(kind, table)
    importer = {"products": _import_products, "diseases": _import_diseases,
                "documents": _import_documents, "indications": _import_indications}[kind]
    with transaction(conn):
        for row in rows:
            importer(conn, row, reviewer, reason)
    return len(rows)


def _insert_logged(conn, table, values, reviewer, reason):
    """1行を追加し、更新履歴に「追加」を記録して、IDを返します。"""
    columns = list(values)
    new_id = conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        [values[c] for c in columns],
    ).lastrowid
    log_change(conn, table, new_id, "追加", None, get_row(conn, table, new_id), reviewer, reason)
    return new_id


def _import_products(conn, row, reviewer, reason):
    _insert_logged(conn, "products", {k: row[k] for k in
                   ("brand_name", "generic_name", "category", "official_url", "last_checked_on")}, reviewer, reason)


def _import_diseases(conn, row, reviewer, reason):
    _insert_logged(conn, "diseases", {"name_ja": row["name_ja"], "name_en": row["name_en"]}, reviewer, reason)


def _import_documents(conn, row, reviewer, reason):
    document = _document(conn, row["doc_type"], row["title"])
    document_id = document["id"] if document else _insert_logged(conn, "documents", {
        "doc_type": row["doc_type"], "title": row["title"],
        "publisher": row["publisher"], "external_id": row["external_id"],
    }, reviewer, reason)
    # 版の登録は、更新管理画面と同じ処理を使う（最新版の切り替え・再確認要への変更・履歴の記録をまとめて行う）
    register_document_version(conn, document_id, row["version_label"], row["revised_on"], row["retrieved_on"],
                              row["source_url"], row["is_current"] != "いいえ", reviewer, reason)
    # 文書と製品・疾患のひも付け（まだなければ追加する）
    for column, value in (("product_id", _product_id(conn, row["brand_name"]) if row["brand_name"] else None),
                          ("disease_id", _disease_id(conn, row["disease_name"]) if row["disease_name"] else None)):
        if value and not conn.execute(f"SELECT 1 FROM document_links WHERE document_id = ? AND {column} = ?",
                                      (document_id, value)).fetchone():
            _insert_logged(conn, "document_links", {"document_id": document_id, column: value}, reviewer, reason)


def _import_indications(conn, row, reviewer, reason):
    product_id = _product_id(conn, row["brand_name"])
    disease_id = _disease_id(conn, row["disease_name"])
    indication = conn.execute("SELECT id FROM indications WHERE product_id = ? AND disease_id = ?",
                              (product_id, disease_id)).fetchone()
    indication_id = indication["id"] if indication else _insert_logged(
        conn, "indications", {"product_id": product_id, "disease_id": disease_id}, reviewer, reason)
    if row["content"]:
        version_id = conn.execute(
            "SELECT v.id FROM document_versions v JOIN documents d ON d.id = v.document_id "
            "WHERE d.title = ? AND v.version_label = ?", (row["doc_title"], row["version_label"])).fetchone()[0]
        # 医学的情報は必ず「未確認」で登録する（原文の確認は更新管理画面で行う）
        add_record(conn, "medical_facts", {
            "indication_id": indication_id, "fact_type": "効能・効果", "content": row["content"],
            "source_version_id": version_id, "source_location": row["source_location"], "entry_method": "CSV",
        }, reviewer, reason)


# ---------------------------------------------------------------------
# テンプレート・補助関数
# ---------------------------------------------------------------------

def template_bytes(kind):
    """テンプレート（見出し行だけのCSV）の中身を返します。Excelで文字化けしないよう、先頭に目印（BOM）を付けます。"""
    headers = [header for header, _, _ in KINDS[kind]["columns"]]
    return (",".join(headers) + "\n").encode("utf-8-sig")


def example_table(kind):
    """記入例を表（DataFrame）で返します（画面で見せるためのもので、取り込まれることはありません）。"""
    headers = [header for header, _, _ in KINDS[kind]["columns"]]
    return pd.DataFrame([KINDS[kind]["example"]], columns=headers)


def write_templates():
    """data/templates/ にテンプレートのCSVを書き出します（テンプレートを作り直したいときに使います）。"""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    for kind, spec in KINDS.items():
        (TEMPLATES_DIR / spec["file"]).write_bytes(template_bytes(kind))


def _product_id(conn, brand_name):
    row = conn.execute("SELECT id FROM products WHERE brand_name = ?", (brand_name,)).fetchone()
    return row[0] if row else None


def _disease_id(conn, name):
    row = conn.execute("SELECT id FROM diseases WHERE name_ja = ?", (name,)).fetchone()
    return row[0] if row else None


def _document(conn, doc_type, title):
    row = conn.execute("SELECT * FROM documents WHERE doc_type = ? AND title = ?", (doc_type, title)).fetchone()
    return dict(row) if row else None

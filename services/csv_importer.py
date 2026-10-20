"""
csv_importer.py：CSVファイルを検証して、データベースに取り込む処理です。

取り込みは次の順で行います。
  1. read_csv()     ：CSVを読み込む（UTF-8 と、Excel の Shift_JIS のどちらでも読める）
  2. validate()     ：必須項目・値の形・重複・関連付けを検証し、誤りを日本語の一覧で返す
  3. import_rows()  ：誤りが1つもなければ、1つのトランザクションで登録する（1つでもあれば何も登録しない）

CSVで取り込んだ医学的情報（効能・効果の文言・承認・特許など）は、必ず「未確認」で登録します。
「原文確認済み」にするのは、更新管理画面で原文を確認してからです。

取り込める種類（KINDS）：
  企業 / 製品 / 疾患 / 文書と版 / 適応症
  承認 / 再審査 / 特許 / ライセンス / PMS（この5つは「事実」の種類。出典が必須で、まとめて同じ手順で検証する）
"""

import io
import re
from collections import Counter
from datetime import date

import pandas as pd

from db.changes import add_record, get_row, log_change, transaction
from db.database import ROOT
from services.fact_fields import FIELD_SPECS, check_combination, parse_value
from services.updates import register_document_version

TEMPLATES_DIR = ROOT / "data" / "templates"

# 文書種別として使える値（db/schema.sql の documents テーブルのルールと同じ）
DOC_TYPES = [
    "添付文書", "インタビューフォーム", "RMP", "審査報告書", "診療ガイドライン", "論文", "臨床試験登録",
    "有価証券報告書・IR資料", "プレスリリース", "特許公報", "企業サイト", "その他",
]

# 事実の種類（承認・特許など）に共通の「出典」の列（すべて必須）
SOURCE_COLUMNS = [
    ("出典文書タイトル", "doc_title", True),
    ("出典の版", "version_label", True),
    ("該当箇所", "source_location", True),
]
SOURCE_EXAMPLE = ["サンプル製薬 決算説明資料（架空）", "2024年度 決算説明資料", "（架空）p.14"]

# 取り込める種類と、その列の定義：(CSVの見出し, 中での名前, 必須かどうか)
# 事実の種類には、次の項目も付けます。
#   fact_table：登録先のテーブル
#   defaults  ：空欄のときに使う値（例：国・地域が空欄なら「日本」）
#   unique    ：重複とみなす列の組み合わせ（「今の情報」の中で重複していないかを確かめる）
KINDS = {
    "companies": {
        "label": "企業",
        "file": "companies.csv",
        "columns": [
            ("企業名（日本語）", "name_ja", True),
            ("企業名（英語）", "name_en", False),
            ("対象企業か", "is_target", False),
        ],
        "example": ["サンプル提携薬品（架空）", "Sample Partner Yakuhin (fictional)", "いいえ"],
    },
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
    # ---- ここから下は「事実」の種類（Step 9 で追加）----
    "approvals": {
        "label": "承認",
        "file": "approvals.csv",
        "fact_table": "approvals",
        "columns": [
            ("販売名", "brand_name", True),
            ("対象の疾患名", "disease_name", False),
            ("承認の種類", "approval_type", True),
            ("承認年月日", "approval_date", True),
            ("承認番号", "approval_number", False),
            ("承認内容の説明", "content", True),
            *SOURCE_COLUMNS,
        ],
        "unique": ["product_id", "approval_type", "approval_date", "indication_id"],
        "example": ["サンプリンα錠", "", "効能・効果追加", "2025-09-24", "", "（架空）効能・効果の追加", *SOURCE_EXAMPLE],
    },
    "reexaminations": {
        "label": "再審査",
        "file": "reexaminations.csv",
        "fact_table": "reexaminations",
        "columns": [
            ("販売名", "brand_name", True),
            ("対象の疾患名", "disease_name", False),
            ("説明", "content", True),
            ("公開状況", "disclosure", True),
            ("再審査期間（年）", "period_years", False),
            ("再審査期間の開始日", "start_date", False),
            ("再審査期間の終了日", "end_date", False),
            *SOURCE_COLUMNS,
        ],
        "unique": ["product_id", "indication_id", "content"],
        "example": ["サンプリンα錠", "架空慢性疾患A", "（架空）効能追加に係る再審査期間", "非公開", "", "", "",
                    *SOURCE_EXAMPLE],
    },
    "patents": {
        "label": "特許",
        "file": "patents.csv",
        "fact_table": "patents",
        "columns": [
            ("販売名", "brand_name", True),
            ("特許番号", "patent_number", True),
            ("国・地域", "country", False),
            ("特許の種類", "patent_kind", False),
            ("発明の名称", "title", False),
            ("満了日の公開状況", "disclosure", True),
            ("特許の存続期間満了日", "expiry_date", False),
            ("延長登録後の満了日", "extended_expiry_date", False),
            *SOURCE_COLUMNS,
        ],
        "defaults": {"country": "日本", "patent_kind": "不明"},
        "unique": ["product_id", "country", "patent_number"],
        "example": ["サンプリンα錠", "特許第0000005号（架空）", "日本", "製剤", "（架空）口腔内崩壊錠", "公開",
                    "2035-03-31", "", *SOURCE_EXAMPLE],
    },
    "licenses": {
        "label": "ライセンス",
        "file": "licenses.csv",
        "fact_table": "licenses",
        "columns": [
            ("販売名", "brand_name", True),
            ("相手先の企業", "partner_company", True),
            ("相手先の役割", "role", True),
            ("契約の種類", "license_type", True),
            ("対象地域", "territory", False),
            ("契約内容の説明", "content", True),
            ("契約期間の公開状況", "disclosure", True),
            ("契約開始日", "contract_start", False),
            ("契約終了日", "contract_end", False),
            ("開示年度", "disclosed_fiscal_year", False),
            *SOURCE_COLUMNS,
        ],
        "unique": ["product_id", "partner_company_id", "license_type", "territory"],
        "example": ["サンプリンα錠", "モデル薬品（架空）", "導出先", "導出", "海外", "（架空）海外での開発・販売権を導出",
                    "未確認", "", "", "2025年度", *SOURCE_EXAMPLE],
    },
    "pms_studies": {
        "label": "PMS",
        "file": "pms_studies.csv",
        "fact_table": "pms_studies",
        "columns": [
            ("販売名", "brand_name", True),
            ("対象の疾患名", "disease_name", False),
            ("調査・試験の種類", "study_type", True),
            ("調査名", "title", True),
            ("全例調査か", "all_case", False),
            ("承認条件か", "approval_condition", False),
            ("実施状況", "progress", False),
            ("目標症例数", "target_cases", False),
            ("実施期間の公開状況", "disclosure", True),
            ("実施期間の開始日", "start_date", False),
            ("実施期間の終了日", "end_date", False),
            ("登録番号", "registration_no", False),
            *SOURCE_COLUMNS,
        ],
        "defaults": {"all_case": "未確認", "approval_condition": "未確認", "progress": "未確認"},
        "unique": ["product_id", "title"],
        "example": ["サンプリンα錠", "", "製造販売後データベース調査", "（架空）データベース調査", "全例調査ではない",
                    "承認条件ではない", "実施中", "", "公開", "2025-04-01", "", "", *SOURCE_EXAMPLE],
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

    # 種類ごとの確認（事実の種類は、まとめて _check_facts で確かめる）
    if "fact_table" in spec:
        errors.extend(_check_facts(conn, kind, rows))
    else:
        checker = {"companies": _check_companies, "products": _check_products, "diseases": _check_diseases,
                   "documents": _check_documents, "indications": _check_indications}[kind]
        errors.extend(checker(conn, rows))
    return errors


def _check_companies(conn, rows):
    errors = []
    targets = []
    for row in rows:
        line = row["_line"]
        if row["is_target"] not in (None, "はい", "いいえ"):
            errors.append(f"{line}行目：「対象企業か」は「はい」か「いいえ」にしてください（空欄は「いいえ」）。")
        if row["is_target"] == "はい":
            targets.append(line)
        if row["name_ja"] and _company_id(conn, row["name_ja"]):
            errors.append(f"{line}行目：企業名「{row['name_ja']}」はすでに登録されています。")
    existing = conn.execute("SELECT name_ja FROM companies WHERE is_target = 1").fetchone()
    if targets and existing:
        errors.append(f"{targets[0]}行目：対象企業は1社だけです。すでに「{existing[0]}」が対象企業として登録されています。")
    elif len(targets) > 1:
        errors.append(f"「対象企業か」が「はい」の行が {len(targets)} 行あります。対象企業は1社だけです。")
    errors += _check_duplicates(rows, ["name_ja"], "企業名")
    return errors


def _check_facts(conn, kind, rows):
    """承認・再審査・特許・ライセンス・PMS の行を検証します。"""
    spec = KINDS[kind]
    errors = []
    seen = {}  # CSVの中での重複を見つけるため：重複とみなす値の組み合わせ → 行番号
    for row in rows:
        values, row_errors = _fact_values(conn, kind, row)
        errors += row_errors
        if row_errors:
            continue
        line = row["_line"]
        key = tuple(values.get(c) for c in spec["unique"])
        if key in seen:
            errors.append(f"{line}行目：{seen[key]}行目 と同じ内容です（重複）。")
        seen.setdefault(key, line)

        # 登録済みの「今の情報」との重複（IS は空欄どうしも「同じ」とみなす比べ方）
        where = " AND ".join(f"{c} IS ?" for c in spec["unique"])
        if conn.execute(f"SELECT 1 FROM {spec['fact_table']} WHERE is_current = 1 AND {where}",
                        list(key)).fetchone():
            errors.append(f"{line}行目：同じ{spec['label']}の情報がすでに登録されています。")

        # 初回承認は1つの製品につき1つだけ
        if kind == "approvals" and values["approval_type"] == "初回承認":
            if conn.execute("SELECT 1 FROM approvals WHERE is_current = 1 AND approval_type = '初回承認' "
                            "AND product_id = ?", (values["product_id"],)).fetchone():
                errors.append(f"{line}行目：「{row['brand_name']}」の初回承認はすでに登録されています。")
            first_key = ("初回承認", values["product_id"])
            if first_key in seen:
                errors.append(f"{line}行目：同じ製品の初回承認が {seen[first_key]}行目 にもあります。")
            seen.setdefault(first_key, line)
    return errors


def _fact_values(conn, kind, row):
    """
    CSVの1行から、事実のテーブルに入れる値を作ります。
    名前をIDに直し（販売名 → 製品ID など）、日付・整数を確かめます。
    戻り値：(値の辞書, 誤りの説明のリスト)
    """
    spec = KINDS[kind]
    table = spec["fact_table"]
    line = row["_line"]
    errors = []
    values = {}

    # ---- 名前をIDに直す（製品・適応症・相手先の企業）----
    product_id = _product_id(conn, row["brand_name"]) if row["brand_name"] else None
    if row["brand_name"] and not product_id:
        errors.append(f"{line}行目：販売名「{row['brand_name']}」が登録されていません（先に製品を取り込んでください）。")
    values["product_id"] = product_id

    if "disease_name" in row:
        values["indication_id"] = None
        if row["disease_name"]:
            disease_id = _disease_id(conn, row["disease_name"])
            indication = conn.execute("SELECT id FROM indications WHERE product_id = ? AND disease_id = ?",
                                      (product_id, disease_id)).fetchone() if disease_id else None
            if not disease_id:
                errors.append(f"{line}行目：疾患名「{row['disease_name']}」が登録されていません。")
            elif product_id and not indication:
                errors.append(f"{line}行目：適応症「{row['brand_name']} × {row['disease_name']}」が登録されていません"
                              "（先に「適応症」を取り込んでください）。")
            elif indication:
                values["indication_id"] = indication[0]

    if "partner_company" in row and row["partner_company"]:
        company_id = _company_id(conn, row["partner_company"])
        if not company_id:
            errors.append(f"{line}行目：相手先の企業「{row['partner_company']}」が登録されていません"
                          "（先に「企業」を取り込んでください）。")
        values["partner_company_id"] = company_id

    # ---- 選択肢・日付・整数の確認（更新管理の修正フォームと同じ定義を使う）----
    fields = {column: (kind_, options) for column, _, kind_, options in FIELD_SPECS[table]}
    for header, name, _ in spec["columns"]:
        if name not in fields or fields[name][0] == "company":
            continue
        field_kind, options = fields[name]
        raw = row[name] if row[name] is not None else spec.get("defaults", {}).get(name)
        if field_kind == "select":
            if raw is not None and raw not in options:
                errors.append(f"{line}行目：「{header}」は次のどれかにしてください：{'、'.join(options)}")
            values[name] = raw
        else:
            try:
                values[name] = parse_value(field_kind, header, raw)
            except ValueError as error:
                errors.append(f"{line}行目：{error}")
    if not errors:
        errors += [f"{line}行目：{message}" for message in check_combination(table, values)]

    # ---- 出典（文書の版が登録済みで、製品にひも付いていること）----
    if row["doc_title"] and row["version_label"]:
        versions = conn.execute(
            "SELECT v.id, v.document_id FROM document_versions v JOIN documents d ON d.id = v.document_id "
            "WHERE d.title = ? AND v.version_label = ?", (row["doc_title"], row["version_label"])).fetchall()
        if not versions:
            errors.append(f"{line}行目：出典「{row['doc_title']} ／ {row['version_label']}」が登録されていません"
                          "（先に「文書と版」を取り込んでください）。")
        elif len(versions) > 1:
            errors.append(f"{line}行目：出典「{row['doc_title']}」に一致する文書が複数あります。")
        else:
            values["source_version_id"] = versions[0]["id"]
            if product_id and not conn.execute(
                    "SELECT 1 FROM document_links WHERE document_id = ? AND product_id = ?",
                    (versions[0]["document_id"], product_id)).fetchone():
                errors.append(f"{line}行目：出典「{row['doc_title']}」が、製品「{row['brand_name']}」にひも付いていません。")
    values["source_location"] = row["source_location"]
    values["entry_method"] = "CSV"
    return values, errors


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
    with transaction(conn):
        for row in rows:
            if "fact_table" in KINDS[kind]:
                # 事実は「未確認」で登録する（原文の確認は更新管理画面で行う）
                values, _ = _fact_values(conn, kind, row)
                add_record(conn, KINDS[kind]["fact_table"], values, reviewer, reason)
            else:
                importer = {"companies": _import_companies, "products": _import_products,
                            "diseases": _import_diseases, "documents": _import_documents,
                            "indications": _import_indications}[kind]
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


def _import_companies(conn, row, reviewer, reason):
    _insert_logged(conn, "companies", {"name_ja": row["name_ja"], "name_en": row["name_en"],
                                       "is_target": 1 if row["is_target"] == "はい" else 0}, reviewer, reason)


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


def _company_id(conn, name):
    row = conn.execute("SELECT id FROM companies WHERE name_ja = ?", (name,)).fetchone()
    return row[0] if row else None


def _document(conn, doc_type, title):
    row = conn.execute("SELECT * FROM documents WHERE doc_type = ? AND title = ?", (doc_type, title)).fetchone()
    return dict(row) if row else None

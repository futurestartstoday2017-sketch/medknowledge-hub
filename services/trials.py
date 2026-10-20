"""
trials.py：臨床試験を登録する処理です（架空データの読み込みと、CSVインポートの両方で使います）。

1行 = 1つの登録番号（例：jRCT の番号 1行、ClinicalTrials.gov の番号 1行）として登録します。
  - 「同じ試験の登録番号」（same_trial_as）が空なら、新しい試験を作る
  - 書かれていれば、その登録番号の試験に、この登録番号を追加する（同じ試験を重複して数えないため）
登録ページ（URL）は、出典の「文書（臨床試験登録）」と「版」として自動で登録します。
すべての登録を更新履歴に残し、1行分を1つのトランザクションで行います。
"""

from db.changes import add_record, get_row, log_change, transaction
from services.updates import register_document_version

# 試験の内容（trial_details）の列のうち、1行の値をそのまま使うもの
DETAIL_COLUMNS = [
    "title", "conditions_text", "interventions_text", "study_type", "design", "phase", "sponsor_text",
    "primary_endpoint", "start_date", "start_date_type", "end_date", "end_date_type",
    "recruitment_status", "results_status",
]
DEFAULT_LOCATION = "登録情報（全体）"


def add_trial_entry(conn, row, entry_method, changed_by, reason):
    """
    試験の1行（1つの登録番号）を登録し、{"trial_id", "detail_id", "registration_id"} を返します。
    row は次の名前の辞書です（空欄は None）。
      same_trial_as, registry, registration_no, url, last_updated, retrieved_on, secondary_ids,
      title など DETAIL_COLUMNS, sponsor_company, test_products, control_products, diseases, source_location
    """
    with transaction(conn):
        version_id = _registration_version(conn, row, changed_by, reason)
        location = row.get("source_location") or DEFAULT_LOCATION
        detail_id = None

        if row.get("same_trial_as"):
            # すでにある試験に、登録番号を追加する
            found = conn.execute(
                "SELECT trial_id FROM trial_registrations WHERE registration_no = ? AND is_current = 1",
                (row["same_trial_as"],)).fetchone()
            if found is None:
                raise ValueError(f"「同じ試験の登録番号」{row['same_trial_as']} の試験が見つかりません")
            trial_id = found[0]
        else:
            # 新しい試験を作り、その内容を登録する
            trial_id = conn.execute("INSERT INTO trials DEFAULT VALUES").lastrowid
            log_change(conn, "trials", trial_id, "追加", None, get_row(conn, "trials", trial_id), changed_by, reason)
            detail = {c: row.get(c) for c in DETAIL_COLUMNS if row.get(c) is not None}
            detail.update({
                "trial_id": trial_id,
                "sponsor_company_id": _company_id(conn, row["sponsor_company"]) if row.get("sponsor_company") else None,
                "source_version_id": version_id, "source_location": location, "entry_method": entry_method,
            })
            detail_id = add_record(conn, "trial_details", detail, changed_by, reason)

        registration_id = add_record(conn, "trial_registrations", {
            "trial_id": trial_id, "registry": row["registry"], "registration_no": row["registration_no"],
            "secondary_ids": row.get("secondary_ids"), "last_checked_on": row["retrieved_on"],
            "source_version_id": version_id, "source_location": location, "entry_method": entry_method,
        }, changed_by, reason)

        # 分類（自分で行うひも付け）：製品と疾患
        for column, role in (("test_products", "試験薬"), ("control_products", "対照薬")):
            for name in _split(row.get(column)):
                _link(conn, "trial_products", {"trial_id": trial_id, "product_id": _product_id(conn, name),
                                               "role": role}, changed_by, reason)
        for name in _split(row.get("diseases")):
            _link(conn, "trial_diseases", {"trial_id": trial_id, "disease_id": _disease_id(conn, name)},
                  changed_by, reason)

    return {"trial_id": trial_id, "detail_id": detail_id, "registration_id": registration_id}


def _registration_version(conn, row, changed_by, reason):
    """登録ページを、出典の文書（臨床試験登録）と版として登録し、版のIDを返します。"""
    document = conn.execute("SELECT id FROM documents WHERE doc_type = '臨床試験登録' AND external_id = ?",
                            (row["registration_no"],)).fetchone()
    if document:
        document_id = document[0]
    else:
        document_id = conn.execute(
            "INSERT INTO documents (doc_type, title, publisher, external_id) VALUES ('臨床試験登録', ?, ?, ?)",
            (f"{row['registry']} {row['registration_no']} 登録情報", row["registry"], row["registration_no"]),
        ).lastrowid
        log_change(conn, "documents", document_id, "追加", None, get_row(conn, "documents", document_id),
                   changed_by, reason)

    # 版の表記：登録情報の最終更新日がわかればその日、わからなければ取得日
    label = f"最終更新 {row['last_updated']}" if row.get("last_updated") else f"取得 {row['retrieved_on']}"
    existing = conn.execute("SELECT id FROM document_versions WHERE document_id = ? AND version_label = ?",
                            (document_id, label)).fetchone()
    if existing:
        return existing[0]
    revised_on = row["last_updated"][:7] if row.get("last_updated") else None
    if document:
        # 登録済みの登録ページが更新されていた：更新管理と同じ処理で新しい版にする
        # （旧版を出典にしていた確認済み情報は「再確認要」になり、履歴も残る）
        return register_document_version(conn, document_id, label, revised_on, row["retrieved_on"], row["url"],
                                         True, changed_by, reason)["version_id"]
    version_id = conn.execute(
        "INSERT INTO document_versions (document_id, version_label, revised_on, retrieved_on, source_url) "
        "VALUES (?, ?, ?, ?, ?)",
        (document_id, label, revised_on, row["retrieved_on"], row["url"]),
    ).lastrowid
    log_change(conn, "document_versions", version_id, "追加", None, get_row(conn, "document_versions", version_id),
               changed_by, reason)
    return version_id


def _link(conn, table, values, changed_by, reason):
    """分類のひも付けを1つ追加します（すでにあれば何もしません）。"""
    where = " AND ".join(f"{c} = ?" for c in values)
    if conn.execute(f"SELECT 1 FROM {table} WHERE {where}", list(values.values())).fetchone():
        return
    columns = ", ".join(values)
    new_id = conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join('?' * len(values))})",
                          list(values.values())).lastrowid
    log_change(conn, table, new_id, "追加", None, get_row(conn, table, new_id), changed_by, reason)


def _split(text):
    """「;」で区切られた名前を、リストにします（空なら空のリスト）。"""
    return [part.strip() for part in (text or "").split(";") if part.strip()]


def _find(conn, sql, value, label):
    row = conn.execute(sql, (value,)).fetchone()
    if row is None:
        raise ValueError(f"{label}「{value}」が登録されていません")
    return row[0]


def _product_id(conn, name):
    return _find(conn, "SELECT id FROM products WHERE brand_name = ?", name, "製品")


def _disease_id(conn, name):
    return _find(conn, "SELECT id FROM diseases WHERE name_ja = ?", name, "疾患")


def _company_id(conn, name):
    return _find(conn, "SELECT id FROM companies WHERE name_ja = ?", name, "企業")

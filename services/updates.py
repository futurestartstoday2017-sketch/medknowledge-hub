"""
updates.py：確認・更新管理画面から使う「データを変える」処理です。

どの関数も1つのトランザクションで行い、すべての変更を更新履歴（確認者・日時・理由つき）に残します。
途中でエラーが起きたら、その関数で行った変更はすべて取り消されます。

- revise_fact()             ：事実の内容を修正する（古い行は残し、新しい行で置き換える）
- register_document_version()：文書の新しい版を登録する
- confirm_document_version()：文書の版を「原文確認済み」にする
- add_candidate()           ：変更候補を登録する（「検出」の工程）
- update_candidate_status() ：変更候補の対応状況を変える
"""

from db.changes import get_row, log_change, now_text, set_status, supersede_record, transaction
from db.database import FACT_TABLES

CANDIDATE_STATUSES = ("未対応", "確認中", "反映済み", "見送り")


def revise_fact(conn, table, fact_id, changes, reviewer, reason, mark_verified=False):
    """
    事実の内容を修正します。古い行は「過去の情報」として残ります。
    mark_verified=True のときは、修正後の情報をそのまま「原文確認済み」にします。
    新しい行のIDを返します。
    """
    with transaction(conn):
        new_id = supersede_record(conn, table, fact_id, changes, reviewer, reason)
        if mark_verified:
            set_status(conn, table, new_id, "原文確認済み", reviewer, reason)
    return new_id


def register_document_version(conn, document_id, version_label, revised_on, retrieved_on, source_url,
                              make_current, reviewer, reason, candidate_id=None):
    """
    文書の新しい版を登録します。

    make_current=True（最新版にする）のときは、次のことも同時に行います。
      - それまでの最新版を「過去の版」にする
      - それまでの最新版を出典にしていた「原文確認済み」の情報を「再確認要」にする
        （原文が改訂されたので、確認済みのままにしておくと誤解につながるため）
    candidate_id を渡すと、その変更候補に新しい版をひも付け、「確認中」にします。

    戻り値：{"version_id": 新しい版のID, "rechecked": 再確認要にした情報の件数}
    """
    with transaction(conn):
        old = conn.execute(
            "SELECT * FROM document_versions WHERE document_id = ? AND is_current = 1", (document_id,)
        ).fetchone()

        # ① それまでの最新版を「過去の版」にする（最新版は1つだけというルールがあるので、先に行う）
        if make_current and old:
            conn.execute("UPDATE document_versions SET is_current = 0 WHERE id = ?", (old["id"],))
            log_change(conn, "document_versions", old["id"], "変更", dict(old),
                       get_row(conn, "document_versions", old["id"]), reviewer, reason, candidate_id)

        # ② 新しい版を登録する（改訂年月が古い版を最新版にしようとすると、DBのルールでエラーになる）
        version_id = conn.execute(
            "INSERT INTO document_versions (document_id, version_label, revised_on, retrieved_on, source_url, "
            "is_current) VALUES (?, ?, ?, ?, ?, ?)",
            (document_id, version_label, revised_on or None, retrieved_on, source_url, 1 if make_current else 0),
        ).lastrowid
        log_change(conn, "document_versions", version_id, "追加", None,
                   get_row(conn, "document_versions", version_id), reviewer, reason, candidate_id)

        # ③ 古い版を出典にしていた「原文確認済み」の情報を「再確認要」にする
        rechecked = 0
        if make_current and old:
            for table in FACT_TABLES:
                fact_ids = [r[0] for r in conn.execute(
                    f"SELECT id FROM {table} WHERE is_current = 1 AND status = '原文確認済み' "
                    "AND source_version_id = ?", (old["id"],))]
                for fact_id in fact_ids:
                    set_status(conn, table, fact_id, "再確認要", reviewer,
                               f"出典文書に新しい版（{version_label}）が登録されたため")
                    rechecked += 1

        # ④ 変更候補にひも付ける
        if candidate_id:
            before = get_row(conn, "change_candidates", candidate_id)
            if before is None:
                raise ValueError(f"変更候補 ID {candidate_id} が見つかりません")
            conn.execute(
                "UPDATE change_candidates SET new_version_id = ?, "
                "status = CASE status WHEN '未対応' THEN '確認中' ELSE status END WHERE id = ?",
                (version_id, candidate_id),
            )
            log_change(conn, "change_candidates", candidate_id, "変更", before,
                       get_row(conn, "change_candidates", candidate_id), reviewer, reason, candidate_id)

    return {"version_id": version_id, "rechecked": rechecked}


def confirm_document_version(conn, version_id, confirmed_on, reviewer, reason):
    """文書の版を「原文確認済み」にし、確認日を記録します。"""
    with transaction(conn):
        before = get_row(conn, "document_versions", version_id)
        if before is None:
            raise ValueError(f"文書の版 ID {version_id} が見つかりません")
        conn.execute(
            "UPDATE document_versions SET status = '原文確認済み', confirmed_on = ? WHERE id = ?",
            (confirmed_on, version_id),
        )
        log_change(conn, "document_versions", version_id, "状態変更", before,
                   get_row(conn, "document_versions", version_id), reviewer, reason)


def add_candidate(conn, document_id, description, reviewer, reason, detection_method="手動"):
    """変更候補を登録し、そのIDを返します。"""
    with transaction(conn):
        candidate_id = conn.execute(
            "INSERT INTO change_candidates (document_id, description, detection_method) VALUES (?, ?, ?)",
            (document_id, description, detection_method),
        ).lastrowid
        log_change(conn, "change_candidates", candidate_id, "追加", None,
                   get_row(conn, "change_candidates", candidate_id), reviewer, reason, candidate_id)
    return candidate_id


def update_candidate_status(conn, candidate_id, status, reviewer, reason):
    """変更候補の対応状況を変えます。「反映済み」「見送り」にすると、対応者と日時を記録します。"""
    if status not in CANDIDATE_STATUSES:
        raise ValueError(f"対応状況は {CANDIDATE_STATUSES} のどれかにしてください")
    with transaction(conn):
        before = get_row(conn, "change_candidates", candidate_id)
        if before is None:
            raise ValueError(f"変更候補 ID {candidate_id} が見つかりません")
        resolved = status in ("反映済み", "見送り")
        conn.execute(
            "UPDATE change_candidates SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
            (status, reviewer if resolved else None, now_text() if resolved else None, candidate_id),
        )
        log_change(conn, "change_candidates", candidate_id, "状態変更", before,
                   get_row(conn, "change_candidates", candidate_id), reviewer, reason, candidate_id)

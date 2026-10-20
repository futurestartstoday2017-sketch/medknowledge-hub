"""
changes.py：【出典セット】を持つ「事実」のデータを、更新履歴を残しながら書き込む処理です。

事実のデータは、必ずこのファイルの関数を通して登録・変更します。
どの関数も「データの書き込み」と「更新履歴の記録」を1つのトランザクションで行います。
（トランザクション：全部成功するか、途中で失敗したら全部なかったことになる、というまとまり）

- add_record()       ：新しく登録する
- supersede_record() ：内容を変える（古い行は残し、新しい行で置き換える）
- set_status()       ：確認状態（未確認 / 原文確認済み / 再確認要）を変える
- transaction()      ：複数の処理を1つのトランザクションにまとめる
"""

import json
from contextlib import contextmanager
from datetime import datetime

from db.database import FACT_TABLES

STATUSES = ("未確認", "原文確認済み", "再確認要")

# 置き換えのときに、古い行からコピーしない列（新しい行で自動的に決まる・やり直す列）
_NOT_COPIED = ("id", "status", "verified_by", "verified_at", "is_current", "superseded_by", "created_at")


@contextmanager
def transaction(conn):
    """
    with transaction(conn): の中の処理を、1つのトランザクションにまとめます。
    中でエラーが起きたら、それまでの処理をすべて取り消します。

    すでに外側でトランザクションが始まっている場合は、新しく始めずにその一部として動きます。
    （例：架空データをまとめて登録するとき、途中で失敗したら全部を取り消せる）
    """
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def add_record(conn, table, values, changed_by, reason):
    """事実のデータを1件登録し、更新履歴に「追加」を記録します。登録した行のIDを返します。"""
    _check_table(conn, table, values)
    with transaction(conn):  # with の中でエラーが起きたら、すべて取り消される
        new_id = _insert(conn, table, values)
        _log(conn, table, new_id, "追加", None, _get(conn, table, new_id), changed_by, reason)
    return new_id


def supersede_record(conn, table, old_id, changes, changed_by, reason):
    """
    事実のデータの内容を変えます。古い行は削除せず「過去の情報」として残します。
    新しい行の確認状態は「未確認」から始まります（changes で指定した場合を除く）。
    新しい行のIDを返します。
    """
    _check_table(conn, table, changes)
    with transaction(conn):
        old = _get(conn, table, old_id)
        if old is None:
            raise ValueError(f"{table} に ID {old_id} のデータがありません")
        if not old["is_current"]:
            raise ValueError(f"{table} の ID {old_id} は、すでに過去の情報になっています")

        # 新しい行 = 古い行の内容 + 変更点
        new_values = {k: v for k, v in old.items() if k not in _NOT_COPIED}
        new_values.update(changes)

        # ① 古い行に「過去の情報」の印を付ける（重複チェックにかからないよう、先に行う）
        conn.execute(f"UPDATE {table} SET is_current = 0 WHERE id = ?", (old_id,))
        # ② 新しい行を追加する
        new_id = _insert(conn, table, new_values)
        # ③ 古い行に「どの行に置き換えられたか」を記録する
        conn.execute(f"UPDATE {table} SET superseded_by = ? WHERE id = ?", (new_id, old_id))
        # ④ 更新履歴に、変更前と変更後を記録する
        _log(conn, table, new_id, "置き換え", old, _get(conn, table, new_id), changed_by, reason)
    return new_id


def set_status(conn, table, record_id, status, changed_by, reason):
    """
    確認状態を変えます。「原文確認済み」にすると、確認者と確認日時が記録されます。
    """
    _check_table(conn, table)
    if status not in STATUSES:
        raise ValueError(f"確認状態は {STATUSES} のどれかにしてください")
    with transaction(conn):
        before = _get(conn, table, record_id)
        if before is None:
            raise ValueError(f"{table} に ID {record_id} のデータがありません")
        if not before["is_current"]:
            raise ValueError("過去の情報の確認状態は変更できません")

        if status == "原文確認済み":
            conn.execute(
                f"UPDATE {table} SET status = ?, verified_by = ?, verified_at = ? WHERE id = ?",
                (status, changed_by, _now(), record_id),
            )
        else:
            conn.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (status, record_id))
        _log(conn, table, record_id, "状態変更", before, _get(conn, table, record_id), changed_by, reason)


# ---- ここから下は、このファイルの中だけで使う補助関数 ----

def _now():
    """今の日時を「YYYY-MM-DD HH:MM:SS」の文字列で返します。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _check_table(conn, table, values=None):
    """
    テーブル名と列名が正しいか確かめます。
    SQL文にテーブル名・列名を直接埋め込むので、決められた名前以外は使えないようにします。
    """
    if table not in FACT_TABLES:
        raise ValueError(f"{table} は【出典セット】を持つテーブルではありません")
    if values:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        unknown = set(values) - columns
        if unknown:
            raise ValueError(f"{table} にない列が指定されています：{sorted(unknown)}")


def _insert(conn, table, values):
    """1行を追加して、そのIDを返します。"""
    columns = list(values)
    placeholders = ", ".join("?" * len(columns))  # 例：「?, ?, ?」
    cursor = conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        [values[c] for c in columns],
    )
    return cursor.lastrowid


def _get(conn, table, record_id):
    """1行を取り出して、辞書（列名: 値）にして返します。見つからなければ None。"""
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
    return dict(row) if row else None


def _log(conn, table, record_id, action, before, after, changed_by, reason):
    """更新履歴に1行を追記します。"""
    def to_json(data):
        return json.dumps(data, ensure_ascii=False) if data is not None else None

    conn.execute(
        """
        INSERT INTO change_log (table_name, record_id, action, before_json, after_json, changed_by, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (table, record_id, action, to_json(before), to_json(after), changed_by, reason),
    )

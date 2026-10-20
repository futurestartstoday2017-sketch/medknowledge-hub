"""
queries.py：データベースからデータを取り出す処理をまとめたファイルです。

画面（app.py や pages/ のファイル）からは、SQLを直接書かずに、
このファイルの関数を呼び出してデータを受け取ります。
（段階が進むごとに、検索や比較のための関数を追加していきます。）
"""

from db.database import get_connection


def count_products():
    """登録されている製品の数を返します。"""
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    return count


def count_diseases():
    """登録されている疾患の数を返します。"""
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM diseases").fetchone()[0]
    conn.close()
    return count

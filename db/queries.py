"""
queries.py：画面に表示するためのデータを、データベースから取り出す処理をまとめたファイルです。

画面（pages/ のファイル）からは SQL を直接書かずに、このファイルの関数を呼び出します。
（Step が進むごとに、一覧・詳細・検索・比較のための関数を追加していきます。）
"""

from db.database import FACT_TABLES


def get_home_counts(conn):
    """ホーム画面に表示する件数をまとめて返します。"""
    def count(sql):
        return conn.execute(sql).fetchone()[0]

    # 確認待ち：今の情報のうち「未確認」と「再確認要」のもの（事実のテーブルすべての合計）
    unverified = sum(
        count(f"SELECT COUNT(*) FROM {t} WHERE is_current = 1 AND status = '未確認'") for t in FACT_TABLES
    )
    recheck = sum(
        count(f"SELECT COUNT(*) FROM {t} WHERE is_current = 1 AND status = '再確認要'") for t in FACT_TABLES
    )

    return {
        "products": count("SELECT COUNT(*) FROM products"),
        "diseases": count("SELECT COUNT(*) FROM diseases"),
        "documents": count("SELECT COUNT(*) FROM documents"),
        "unverified": unverified,
        "recheck": recheck,
        # 名前に「（架空）」が付いた企業の数（架空のサンプルデータが入っているかの目印）
        "sample_companies": count("SELECT COUNT(*) FROM companies WHERE name_ja LIKE '%（架空）%'"),
    }

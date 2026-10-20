"""
settings.py：アプリの設定（前回の確認者名など）を保存・取り出す処理です。

設定は app_settings テーブルに「名前（key）と値（value）」の組で保存します。
設定は事実のデータではないので、更新履歴には記録しません。
"""


def get_setting(conn, key, default=None):
    """設定の値を返します。保存されていなければ default を返します。"""
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key, value):
    """設定の値を保存します（すでにあれば上書きします）。"""
    with conn:
        # ON CONFLICT ... DO UPDATE：同じ名前の設定があれば、新しく追加せずに値を書き換える
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

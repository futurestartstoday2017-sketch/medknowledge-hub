"""
errors.py：データベースのエラー（英語）を、初心者にもわかる日本語の説明に直す処理です。

トリガーで出すエラー（「更新履歴は削除できません」など）はもともと日本語なので、そのまま使います。
"""


def friendly_db_error(error):
    """エラーを、画面に出す日本語の説明にして返します。"""
    message = str(error)
    if "UNIQUE constraint failed" in message:
        return "同じ内容の情報がすでに登録されています（重複登録はできません）。"
    if "CHECK constraint failed" in message:
        return ("入力した値が、データベースのルールに合いません"
                "（日付の形・日付の順序・公開状況と日付の組み合わせ・空欄にできない項目などを確認してください）。")
    if "FOREIGN KEY constraint failed" in message:
        return "存在しない製品・文書などを指定しています。"
    if "NOT NULL constraint failed" in message:
        return "必須の項目が空欄です。"
    return message

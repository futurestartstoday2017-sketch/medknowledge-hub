"""
test_step1.py：Step 1（フォルダ構成と環境）の自動テストです。

ターミナルで `pytest` と入力すると、tests フォルダ内のテストがまとめて実行されます。
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

# プロジェクトのフォルダ（このファイルの1つ上のフォルダ）
ROOT = Path(__file__).parent.parent


def test_folders_exist():
    """必要なフォルダがそろっているか確認します。"""
    for folder in ["pages", "db", "services", "data/templates", "data/samples", "tests"]:
        assert (ROOT / folder).is_dir(), f"フォルダがありません: {folder}"


def test_gitignore_protects_secrets_and_db():
    """DBファイルや秘密情報が .gitignore で除外されているか確認します。"""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in [".venv/", ".env", "*.db", "secrets.toml"]:
        assert pattern in gitignore, f".gitignore に {pattern} がありません"


def test_app_runs_without_error():
    """ホーム画面（app.py）がエラーなく表示できるか確認します。"""
    at = AppTest.from_file(str(ROOT / "app.py")).run()
    assert not at.exception, "app.py の実行中にエラーが発生しました"
    assert at.title[0].value == "💊 MedKnowledge Hub"

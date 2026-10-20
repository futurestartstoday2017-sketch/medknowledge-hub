"""
backup.py：データベースのバックアップ（控えの保存）と復元（控えから戻す）を行います。

ターミナルからも使えます（仮想環境を有効にしてから実行してください）。
    python -m db.backup backup                     … バックアップを作る
    python -m db.backup list                       … バックアップの一覧を表示する
    python -m db.backup restore <バックアップファイル> … バックアップから復元する
※ 復元するときは、先にアプリ（streamlit）を止めてください。
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

import db.database as database
from db.database import ROOT

# バックアップの保存先（.gitignore で GitHub には上げない設定にしています）
BACKUP_DIR = ROOT / "data" / "backups"


def backup_db(db_path=None, backup_dir=None):
    """
    データベースの控えを「データベースの名前_日時.db」として保存し、その場所を返します。
    （例：medknowledge_20251020_153000.db、実データなら medknowledge_real_20251020_153000.db）
    """
    # 今使うデータベースと BACKUP_DIR は「呼ばれた時点」の値を使う（切り替えやテストで場所が変わるため）
    db_path = Path(db_path or database.current_db_path())
    backup_dir = Path(backup_dir or BACKUP_DIR)
    if not db_path.exists():
        raise FileNotFoundError(f"データベースが見つかりません：{db_path}")
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 同じ秒に2回実行しても上書きしないよう、名前が重なったら番号を付ける
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{db_path.stem}_{stamp}.db"
    number = 2
    while dest.exists():
        dest = backup_dir / f"{db_path.stem}_{stamp}_{number}.db"
        number += 1

    # SQLite 標準のバックアップ機能を使う（使用中のDBでも安全にコピーできる）
    _copy_database(db_path, dest)
    return dest


def check_integrity(db_path):
    """データベースファイルが壊れていないか確かめます。問題なければ True を返します。"""
    conn = sqlite3.connect(db_path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        has_schema = conn.execute("PRAGMA user_version").fetchone()[0] > 0
    except sqlite3.DatabaseError:
        return False  # そもそもSQLiteのファイルとして読めない
    finally:
        conn.close()
    return result == "ok" and has_schema


def restore_db(backup_path, db_path=None, backup_dir=None):
    """
    バックアップからデータベースを復元します。
    念のため、復元する前の今のデータベースもバックアップしておきます（その場所を返します）。
    """
    backup_path = Path(backup_path)
    db_path = Path(db_path or database.current_db_path())
    if not backup_path.exists():
        raise FileNotFoundError(f"バックアップが見つかりません：{backup_path}")
    if not check_integrity(backup_path):
        raise ValueError(f"バックアップが壊れているか、このアプリのデータベースではありません：{backup_path}")

    safety_copy = backup_db(db_path, backup_dir) if db_path.exists() else None
    _copy_database(backup_path, db_path)
    return safety_copy


def _copy_database(src_path, dest_path):
    """SQLite のバックアップ機能で、src_path の中身を dest_path にコピーします。"""
    src = sqlite3.connect(src_path)
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
    finally:
        # Windows では、接続を閉じないとファイルを消したり動かしたりできないため必ず閉じる
        src.close()
        dest.close()


def main():
    """ターミナルから実行したときの処理です。"""
    parser = argparse.ArgumentParser(description="データベースのバックアップと復元")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="バックアップを作る")
    sub.add_parser("list", help="バックアップの一覧を表示する")
    restore = sub.add_parser("restore", help="バックアップから復元する")
    restore.add_argument("file", help="復元に使うバックアップファイル")
    args = parser.parse_args()

    try:
        if args.command == "backup":
            print(f"バックアップを作成しました：{backup_db()}")
        elif args.command == "list":
            files = sorted(BACKUP_DIR.glob("*.db")) if BACKUP_DIR.exists() else []
            print("\n".join(str(f) for f in files) or "バックアップはまだありません")
        elif args.command == "restore":
            safety_copy = restore_db(args.file)
            print(f"復元しました：{args.file}")
            if safety_copy:
                print(f"復元前のデータベースは、念のためここに保存しました：{safety_copy}")
    except (FileNotFoundError, ValueError) as error:
        # 想定しているエラーは、英語の長いメッセージではなく日本語で短く表示する
        print(f"エラー：{error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

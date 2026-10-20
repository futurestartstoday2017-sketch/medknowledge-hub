# MedKnowledge Hub

製薬企業1社の製品と、その競合製品・関連疾患・添付文書などの公開情報を整理し、検索・比較・学習するための個人学習用アプリです。

> ⚠️ **このアプリは個人の学習・情報整理用です。実際の診療判断には使用しないでください。**
> 登録されている初期データは、すべて学習用の架空のものです。

## 基本方針

- 一般に公開されている情報のみを扱います。
- 医学的情報には出典（原文URL・版・確認日）をつけて登録します。
- 公開情報と自分の学習メモは区別して管理します。
- 製品同士を比較するときに、優劣を自動で判定することはしません。
- ローカルPCだけで動かします（外部公開やクラウドサービスは使いません）。

## 使用技術

| 技術 | 用途 |
|---|---|
| Python | プログラミング言語 |
| Streamlit | Webアプリの画面を作るライブラリ |
| SQLite | ファイル1つで動くデータベース |
| pandas | 表形式のデータ（CSVなど）を扱うライブラリ |
| pytest | 自動テストを実行するツール |

## 起動方法（Windows / VS Code のターミナル）

```powershell
# 1. 仮想環境を作る（初回のみ）
python -m venv .venv

# 2. 仮想環境を有効にする（ターミナルを開くたびに実行）
.venv\Scripts\Activate.ps1

# 3. ライブラリをインストールする（初回と、requirements.txt が変わったとき）
pip install -r requirements.txt

# 4. アプリを起動する（ブラウザが自動で開きます）
streamlit run app.py

# 5. 自動テストを実行する
pytest
```

アプリを止めるときは、ターミナルで `Ctrl + C` を押します。

## バックアップと復元

```powershell
# バックアップを作る（data/backups/ に「medknowledge_日時.db」として保存）
python -m db.backup backup

# バックアップの一覧を表示する
python -m db.backup list

# バックアップから復元する（先にアプリを Ctrl + C で止めてください）
python -m db.backup restore data\backups\medknowledge_20251020_153000.db
```

復元するときは、壊れていないかを自動でチェックします。また、復元前のデータベースも念のためバックアップとして残します。
データベースとバックアップは、GitHubにはアップロードされません。

## フォルダ構成

| 場所 | 役割 |
|---|---|
| `app.py` | 起動ファイル（共通設定とサイドバーのメニュー定義） |
| `pages/` | ①〜⑤ の各画面（ホーム・製品情報・疾患情報・競合製品比較・更新管理） |
| `db/schema.sql` | データベースの設計図（テーブルの定義） |
| `db/database.py` | データベースへの接続・テーブル作成 |
| `db/changes.py` | 事実のデータを、更新履歴を残しながら登録・変更する処理 |
| `db/quality.py` | 出典と版の不整合を見つける品質チェック |
| `db/backup.py` | バックアップと復元 |
| `services/` | CSVインポートなど、画面から使う処理 |
| `data/templates/` | CSVテンプレート（見出し行のみ） |
| `data/samples/` | 学習用の架空データ（CSV） |
| `data/medknowledge.db` | データベース本体（自動作成・Gitには含めない） |
| `data/backups/` | データベースのバックアップ（Gitには含めない） |
| `docs/design.md` | 設計書（テーブル・画面・開発計画） |
| `tests/` | 自動テスト |
| `.streamlit/config.toml` | 画面のテーマ（色）の設定 |
| `requirements.txt` | 必要なライブラリの一覧 |
| `.gitignore` | Gitに含めないファイルの一覧 |
| `CLAUDE.md` | Claude Code向けの作業ルール |

## 開発状況

詳しい計画は [docs/design.md](docs/design.md) を参照してください。

- [x] Step 1：フォルダ構成と仮想環境の作成
- [x] Step 2：Streamlitの起動とホーム画面
- [x] Step 3：テーブル作成・品質を守る仕組み・バックアップと復元
- [ ] Step 4：架空データの登録
- [ ] Step 5：製品・疾患画面
- [ ] Step 6：横断検索・競合製品比較
- [ ] Step 7：確認・更新管理画面
- [ ] Step 8：CSVインポート
- [ ] Step 9：承認・再審査・特許・ライセンス
- [ ] Step 10〜11：臨床試験（ClinicalTrials.gov 取得は利用条件の確認後）
- [ ] Step 12〜13：論文（PubMed 取得は利用条件の確認後）
- [ ] Step 14〜15：メディカル活動・疾患別MA学習ビュー
- [ ] Step 16：実製品の登録

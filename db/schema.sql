-- =====================================================================
-- schema.sql：データベースの設計図（テーブルの定義）です。
--
-- 用語の補足
--   PRIMARY KEY  … その行を見分けるための番号（ID）
--   NOT NULL     … 空欄を禁止する
--   UNIQUE       … 同じ値の二重登録を禁止する
--   CHECK (...)  … 入れてよい値のルール
--   REFERENCES   … 外部キー。別のテーブルに実在するIDしか入れられない
--   TRIGGER      … 決まった操作（削除など）が行われたときに自動で動くチェック
--
-- 日付は「YYYY-MM-DD」、日時は「YYYY-MM-DD HH:MM:SS」の文字列で保存します。
-- 「date(x) IS x」は、x が正しい日付の形かどうかを確かめる書き方です。
--
-- 【出典セット】が付いたテーブルの削除禁止・書き換え禁止のトリガーは、
-- db/database.py の中で自動的に作ります（同じ処理を何度も書かないため）。
-- =====================================================================


-- ---------------------------------------------------------------------
-- A 基本
-- ---------------------------------------------------------------------

-- 企業
CREATE TABLE companies (
    id        INTEGER PRIMARY KEY,
    name_ja   TEXT NOT NULL UNIQUE CHECK (trim(name_ja) <> ''),  -- 企業名（日本語）
    name_en   TEXT,                                               -- 企業名（英語）
    is_target INTEGER NOT NULL DEFAULT 0 CHECK (is_target IN (0, 1))  -- 対象企業なら 1
);
-- 対象企業（is_target = 1）は1社だけにする
CREATE UNIQUE INDEX ux_companies_one_target ON companies (is_target) WHERE is_target = 1;

-- 製品（見分けるための情報だけ。医学的情報は medical_facts に入れる）
CREATE TABLE products (
    id              INTEGER PRIMARY KEY,
    brand_name      TEXT NOT NULL UNIQUE CHECK (trim(brand_name) <> ''),  -- 販売名
    generic_name    TEXT,                                                  -- 一般名
    category        TEXT NOT NULL CHECK (category IN ('対象企業', '競合')),  -- 区分
    official_url    TEXT,                                                  -- 公式製品URL
    last_checked_on TEXT CHECK (last_checked_on IS NULL OR date(last_checked_on) IS last_checked_on)  -- 最終確認日
);

-- 疾患
CREATE TABLE diseases (
    id      INTEGER PRIMARY KEY,
    name_ja TEXT NOT NULL UNIQUE CHECK (trim(name_ja) <> ''),  -- 疾患名（日本語）
    name_en TEXT                                                -- 疾患名（英語）
);

-- 適応症（製品と疾患の組み合わせ。多対多の関係を表す中間テーブル）
CREATE TABLE indications (
    id         INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products (id),
    disease_id INTEGER NOT NULL REFERENCES diseases (id),
    UNIQUE (product_id, disease_id)  -- 同じ組み合わせの二重登録を防ぐ
);


-- ---------------------------------------------------------------------
-- B 出典
-- ---------------------------------------------------------------------

-- 文書（版が変わっても同じ1行）
CREATE TABLE documents (
    id          INTEGER PRIMARY KEY,
    doc_type    TEXT NOT NULL CHECK (doc_type IN (
                    '添付文書', 'インタビューフォーム', 'RMP', '審査報告書',
                    '診療ガイドライン', '論文', '臨床試験登録', '有価証券報告書・IR資料',
                    'プレスリリース', '特許公報', '企業サイト', 'その他')),
    title       TEXT NOT NULL CHECK (trim(title) <> ''),  -- 文書タイトル
    publisher   TEXT,                                      -- 発行元（企業・学会・PMDA など）
    external_id TEXT                                       -- PMID・DOI・登録番号などの識別番号
);
-- 同じ種類で同じ識別番号の文書は1つだけ（識別番号が空の文書は対象外）
CREATE UNIQUE INDEX ux_documents_external_id ON documents (doc_type, external_id)
    WHERE external_id IS NOT NULL;

-- 文書の版（改訂されるたびに1行増える）
CREATE TABLE document_versions (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents (id),
    version_label TEXT NOT NULL CHECK (trim(version_label) <> ''),  -- 版の表記（例：2025年4月改訂（第3版））
    revised_on    TEXT CHECK (revised_on IS NULL OR revised_on GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'),
                                                                     -- 原文の改訂年月（YYYY-MM。記載がなければ空欄）
    retrieved_on  TEXT NOT NULL CHECK (date(retrieved_on) IS retrieved_on),  -- 入手日（原文を取得した日）
    confirmed_on  TEXT CHECK (confirmed_on IS NULL OR date(confirmed_on) IS confirmed_on),  -- 確認日（原文を読んで確認した日）
    source_url    TEXT NOT NULL CHECK (source_url LIKE 'http%'),      -- 原文URL
    is_current    INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),  -- 最新版なら 1
    status        TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (document_id, version_label),                               -- 同じ文書で同じ版表記は1つだけ
    CHECK (status <> '原文確認済み' OR confirmed_on IS NOT NULL)        -- 確認済みなら確認日が必須
);
-- 1つの文書につき、最新版は1つだけ
CREATE UNIQUE INDEX ux_versions_one_current ON document_versions (document_id) WHERE is_current = 1;

-- 文書と製品・疾患の対応（1つのガイドラインが複数の製品・疾患に関わることがあるため）
CREATE TABLE document_links (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents (id),
    product_id  INTEGER REFERENCES products (id),
    disease_id  INTEGER REFERENCES diseases (id),
    CHECK ((product_id IS NOT NULL) + (disease_id IS NOT NULL) = 1)  -- どちらか一方だけ
);
CREATE UNIQUE INDEX ux_document_links ON document_links
    (document_id, coalesce(product_id, 0), coalesce(disease_id, 0));


-- ---------------------------------------------------------------------
-- C 事実（【出典セット】付き）
-- ---------------------------------------------------------------------

-- 製造販売元・販売元
CREATE TABLE product_companies (
    id                INTEGER PRIMARY KEY,
    product_id        INTEGER NOT NULL REFERENCES products (id),
    company_id        INTEGER NOT NULL REFERENCES companies (id),
    role              TEXT NOT NULL CHECK (role IN ('製造販売元', '販売元')),
    -- 【出典セット】ここから
    source_version_id INTEGER NOT NULL REFERENCES document_versions (id),
    source_location   TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status            TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by       TEXT,
    verified_at       TEXT,
    entry_method      TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current        INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by     INTEGER REFERENCES product_companies (id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL))
    -- 【出典セット】ここまで
);
CREATE UNIQUE INDEX ux_product_companies ON product_companies (product_id, company_id, role)
    WHERE is_current = 1;

-- 医学的情報（対象は 製品・疾患・適応症 のどれか1つ）
CREATE TABLE medical_facts (
    id                INTEGER PRIMARY KEY,
    product_id        INTEGER REFERENCES products (id),
    disease_id        INTEGER REFERENCES diseases (id),
    indication_id     INTEGER REFERENCES indications (id),
    fact_type         TEXT NOT NULL CHECK (fact_type IN (
                          '効能・効果', '用法・用量', '薬効分類', '作用機序', '投与経路', '剤形',
                          '疾患概要', '診断', '治療', '標準治療', 'アンメットニーズ', 'その他')),
    subcategory       TEXT,                                    -- 細かい区分（任意）
    content           TEXT NOT NULL CHECK (trim(content) <> ''),  -- 内容
    -- 【出典セット】ここから
    source_version_id INTEGER NOT NULL REFERENCES document_versions (id),
    source_location   TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status            TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by       TEXT,
    verified_at       TEXT,
    entry_method      TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current        INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by     INTEGER REFERENCES medical_facts (id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL)),
    -- 【出典セット】ここまで
    CHECK ((product_id IS NOT NULL) + (disease_id IS NOT NULL) + (indication_id IS NOT NULL) = 1)
);
-- 同じ対象・同じ種類・同じ内容の「今の情報」は1つだけ
CREATE UNIQUE INDEX ux_medical_facts ON medical_facts
    (coalesce(product_id, 0), coalesce(disease_id, 0), coalesce(indication_id, 0), fact_type, content)
    WHERE is_current = 1;

-- 安全性情報（製品ごと）
CREATE TABLE safety_info (
    id                INTEGER PRIMARY KEY,
    product_id        INTEGER NOT NULL REFERENCES products (id),
    category          TEXT NOT NULL CHECK (category IN (
                          '警告', '禁忌', '重要な基本的注意', '特定の背景を有する患者に関する注意',
                          '相互作用', '重大な副作用', 'その他の副作用', 'その他')),  -- 情報区分
    content           TEXT NOT NULL CHECK (trim(content) <> ''),
    -- 【出典セット】ここから
    source_version_id INTEGER NOT NULL REFERENCES document_versions (id),
    source_location   TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status            TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by       TEXT,
    verified_at       TEXT,
    entry_method      TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current        INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by     INTEGER REFERENCES safety_info (id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL))
    -- 【出典セット】ここまで
);
CREATE UNIQUE INDEX ux_safety_info ON safety_info (product_id, category, content) WHERE is_current = 1;


-- ---------------------------------------------------------------------
-- G 学習・管理
-- ---------------------------------------------------------------------

-- 学習メモ・考察（事実ではないので出典セットはない。自由に編集・削除できる）
CREATE TABLE notes (
    id                  INTEGER PRIMARY KEY,
    product_id          INTEGER REFERENCES products (id),
    disease_id          INTEGER REFERENCES diseases (id),
    indication_id       INTEGER REFERENCES indications (id),
    note_type           TEXT NOT NULL CHECK (note_type IN ('学習メモ', 'エビデンスギャップ', '考察', '疑問')),
    body                TEXT NOT NULL CHECK (trim(body) <> ''),
    related_document_id INTEGER REFERENCES documents (id),  -- 参考にした文書（任意）
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK ((product_id IS NOT NULL) + (disease_id IS NOT NULL) + (indication_id IS NOT NULL) = 1)
);

-- 変更候補（「検出」の工程。確認して反映するまでは医学的情報を変えない）
CREATE TABLE change_candidates (
    id               INTEGER PRIMARY KEY,
    document_id      INTEGER NOT NULL REFERENCES documents (id),
    new_version_id   INTEGER REFERENCES document_versions (id),  -- 新しく見つかった版（任意）
    detected_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    detection_method TEXT NOT NULL DEFAULT '手動' CHECK (detection_method IN ('手動', '自動')),
    description      TEXT NOT NULL CHECK (trim(description) <> ''),
    status           TEXT NOT NULL DEFAULT '未対応' CHECK (status IN ('未対応', '確認中', '反映済み', '見送り')),
    resolved_by      TEXT,
    resolved_at      TEXT
);

-- 更新履歴（追記のみ。下のトリガーで編集・削除を禁止する）
CREATE TABLE change_log (
    id           INTEGER PRIMARY KEY,
    table_name   TEXT NOT NULL,                                -- 対象テーブル
    record_id    INTEGER NOT NULL,                             -- 対象の行のID
    action       TEXT NOT NULL CHECK (action IN ('追加', '置き換え', '状態変更', '変更')),
    before_json  TEXT,                                         -- 変更前の内容（JSON形式）
    after_json   TEXT,                                         -- 変更後の内容（JSON形式）
    changed_by   TEXT NOT NULL CHECK (trim(changed_by) <> ''), -- 確認者
    changed_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    reason       TEXT NOT NULL CHECK (trim(reason) <> ''),     -- 変更理由
    candidate_id INTEGER REFERENCES change_candidates (id)     -- 関係する変更候補（任意）
);

CREATE TRIGGER change_log_no_update BEFORE UPDATE ON change_log
BEGIN
    SELECT RAISE(ABORT, '更新履歴は編集できません');
END;

CREATE TRIGGER change_log_no_delete BEFORE DELETE ON change_log
BEGIN
    SELECT RAISE(ABORT, '更新履歴は削除できません');
END;

-- アプリの設定（前回の確認者名など）
CREATE TABLE app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);


-- ---------------------------------------------------------------------
-- 出典（文書・版）を守るトリガー
-- ---------------------------------------------------------------------

-- 文書と版は削除できない（過去の出典をたどれなくなるため）
CREATE TRIGGER documents_no_delete BEFORE DELETE ON documents
BEGIN
    SELECT RAISE(ABORT, '文書は削除できません');
END;

CREATE TRIGGER document_versions_no_delete BEFORE DELETE ON document_versions
BEGIN
    SELECT RAISE(ABORT, '文書の版は削除できません');
END;

-- 版の中身（改訂年月・URL など）は書き換えできない。変わったときは新しい版を登録する
CREATE TRIGGER document_versions_no_edit
BEFORE UPDATE OF document_id, version_label, revised_on, retrieved_on, source_url ON document_versions
BEGIN
    SELECT RAISE(ABORT, '文書の版の内容は書き換えできません。新しい版として登録してください');
END;

-- 最新版として登録する版の改訂年月が、既存の版より古い場合は登録しない（版の逆転を防ぐ）
CREATE TRIGGER document_versions_order BEFORE INSERT ON document_versions
WHEN NEW.is_current = 1 AND NEW.revised_on IS NOT NULL AND EXISTS (
    SELECT 1 FROM document_versions
    WHERE document_id = NEW.document_id AND revised_on > NEW.revised_on
)
BEGIN
    SELECT RAISE(ABORT, '既存の版より古い改訂年月の版は、最新版として登録できません');
END;

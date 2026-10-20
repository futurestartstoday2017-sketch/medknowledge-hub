-- =====================================================================
-- 002_regulatory_pms.sql：設計図バージョン2への追加分（マイグレーション）です。
--
-- 承認・再審査・特許・ライセンス・PMS（製造販売後調査等）のテーブルを追加します。
-- 5つとも【出典セット】付きの「事実」のテーブルです。
-- 削除禁止・書き換え禁止のトリガーは、db/database.py が自動で作ります。
--
-- 日付の混同を防ぐため、種類の違う日付は別のテーブル・別の列名にしています。
--   承認年月日（approvals.approval_date）
--   再審査期間の終了日（reexaminations.end_date）
--   特許の存続期間満了日（patents.expiry_date / extended_expiry_date）
--   契約終了日（licenses.contract_end）
--
-- disclosure（公開状況）：公開 / 非公開 / 未確認
--   「公開」のときだけ日付を入力でき、「非公開」「未確認」のときは日付を空欄にするルールです。
--   （空欄が「非公開」なのか「まだ調べていない」のかを区別するため）
-- =====================================================================


-- ---------------------------------------------------------------------
-- 承認
-- ---------------------------------------------------------------------
CREATE TABLE approvals (
    id                INTEGER PRIMARY KEY,
    product_id        INTEGER NOT NULL REFERENCES products (id),
    indication_id     INTEGER REFERENCES indications (id),          -- 対象の適応症（効能追加などのとき）
    approval_type     TEXT NOT NULL CHECK (approval_type IN (
                          '初回承認', '効能・効果追加', '用法・用量追加・変更', '剤形追加', 'その他')),
    approval_date     TEXT NOT NULL CHECK (date(approval_date) IS approval_date),  -- 承認年月日
    approval_number   TEXT,                                           -- 承認番号
    content           TEXT NOT NULL CHECK (trim(content) <> ''),     -- 承認内容の説明
    -- 【出典セット】ここから
    source_version_id INTEGER NOT NULL REFERENCES document_versions (id),
    source_location   TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status            TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by       TEXT,
    verified_at       TEXT,
    entry_method      TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current        INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by     INTEGER REFERENCES approvals (id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL))
    -- 【出典セット】ここまで
);
CREATE UNIQUE INDEX ux_approvals ON approvals
    (product_id, approval_type, approval_date, coalesce(indication_id, 0)) WHERE is_current = 1;
-- 初回承認は、1つの製品につき1つだけ
CREATE UNIQUE INDEX ux_approvals_first ON approvals (product_id)
    WHERE is_current = 1 AND approval_type = '初回承認';


-- ---------------------------------------------------------------------
-- 再審査
-- ---------------------------------------------------------------------
CREATE TABLE reexaminations (
    id                INTEGER PRIMARY KEY,
    product_id        INTEGER NOT NULL REFERENCES products (id),
    indication_id     INTEGER REFERENCES indications (id),
    content           TEXT NOT NULL CHECK (trim(content) <> ''),     -- 説明（例：新有効成分としての再審査）
    disclosure        TEXT NOT NULL CHECK (disclosure IN ('公開', '非公開', '未確認')),
    period_years      INTEGER CHECK (period_years IS NULL OR period_years > 0),          -- 再審査期間（年）
    start_date        TEXT CHECK (start_date IS NULL OR date(start_date) IS start_date), -- 再審査期間の開始日
    end_date          TEXT CHECK (end_date IS NULL OR date(end_date) IS end_date),       -- 再審査期間の終了日
    -- 【出典セット】ここから
    source_version_id INTEGER NOT NULL REFERENCES document_versions (id),
    source_location   TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status            TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by       TEXT,
    verified_at       TEXT,
    entry_method      TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current        INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by     INTEGER REFERENCES reexaminations (id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL)),
    -- 【出典セット】ここまで
    -- 「公開」でなければ期間・日付は空欄
    CHECK (disclosure = '公開' OR (period_years IS NULL AND start_date IS NULL AND end_date IS NULL)),
    -- 「公開」なら、期間か終了日の少なくとも一方が必要
    CHECK (disclosure <> '公開' OR period_years IS NOT NULL OR end_date IS NOT NULL),
    -- 終了日は開始日より後
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date > start_date)
);
CREATE UNIQUE INDEX ux_reexaminations ON reexaminations
    (product_id, coalesce(indication_id, 0), content) WHERE is_current = 1;


-- ---------------------------------------------------------------------
-- 特許
-- ---------------------------------------------------------------------
CREATE TABLE patents (
    id                   INTEGER PRIMARY KEY,
    product_id           INTEGER NOT NULL REFERENCES products (id),
    patent_number        TEXT NOT NULL CHECK (trim(patent_number) <> ''),     -- 特許番号
    country              TEXT NOT NULL DEFAULT '日本' CHECK (trim(country) <> ''),  -- 国・地域
    patent_kind          TEXT NOT NULL DEFAULT '不明' CHECK (patent_kind IN (
                             '物質', '用途', '製剤', '製法', 'その他', '不明')),
    title                TEXT,                                                -- 発明の名称
    disclosure           TEXT NOT NULL CHECK (disclosure IN ('公開', '非公開', '未確認')),  -- 満了日の公開状況
    expiry_date          TEXT CHECK (expiry_date IS NULL OR date(expiry_date) IS expiry_date),  -- 存続期間満了日
    extended_expiry_date TEXT CHECK (extended_expiry_date IS NULL
                                     OR date(extended_expiry_date) IS extended_expiry_date),    -- 延長登録後の満了日
    -- 【出典セット】ここから
    source_version_id    INTEGER NOT NULL REFERENCES document_versions (id),
    source_location      TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status               TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by          TEXT,
    verified_at          TEXT,
    entry_method         TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current           INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by        INTEGER REFERENCES patents (id),
    created_at           TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL)),
    -- 【出典セット】ここまで
    CHECK (disclosure = '公開' OR (expiry_date IS NULL AND extended_expiry_date IS NULL)),
    CHECK (disclosure <> '公開' OR expiry_date IS NOT NULL),
    -- 延長登録後の満了日は、もとの満了日より後
    CHECK (extended_expiry_date IS NULL OR expiry_date IS NULL OR extended_expiry_date > expiry_date)
);
CREATE UNIQUE INDEX ux_patents ON patents (product_id, country, patent_number) WHERE is_current = 1;


-- ---------------------------------------------------------------------
-- ライセンス（導入元・提携先）
-- ---------------------------------------------------------------------
CREATE TABLE licenses (
    id                    INTEGER PRIMARY KEY,
    product_id            INTEGER NOT NULL REFERENCES products (id),
    partner_company_id    INTEGER NOT NULL REFERENCES companies (id),       -- 相手先の企業
    role                  TEXT NOT NULL CHECK (role IN ('導入元', '導出先', '提携先')),
    license_type          TEXT NOT NULL CHECK (license_type IN (
                              '導入', '導出', '共同開発', '共同販売', '販売提携', 'その他')),
    territory             TEXT,                                              -- 対象地域
    content               TEXT NOT NULL CHECK (trim(content) <> ''),        -- 契約内容の説明
    disclosure            TEXT NOT NULL CHECK (disclosure IN ('公開', '非公開', '未確認')),  -- 契約期間の公開状況
    contract_start        TEXT CHECK (contract_start IS NULL OR date(contract_start) IS contract_start),
    contract_end          TEXT CHECK (contract_end IS NULL OR date(contract_end) IS contract_end),
    disclosed_fiscal_year TEXT CHECK (disclosed_fiscal_year IS NULL OR trim(disclosed_fiscal_year) <> ''),  -- 開示年度
    -- 【出典セット】ここから
    source_version_id     INTEGER NOT NULL REFERENCES document_versions (id),
    source_location       TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status                TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by           TEXT,
    verified_at           TEXT,
    entry_method          TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current            INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by         INTEGER REFERENCES licenses (id),
    created_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL)),
    -- 【出典セット】ここまで
    CHECK (disclosure = '公開' OR (contract_start IS NULL AND contract_end IS NULL)),
    CHECK (disclosure <> '公開' OR contract_start IS NOT NULL OR contract_end IS NOT NULL),
    CHECK (contract_start IS NULL OR contract_end IS NULL OR contract_end > contract_start)
);
CREATE UNIQUE INDEX ux_licenses ON licenses
    (product_id, partner_company_id, license_type, coalesce(territory, '')) WHERE is_current = 1;


-- ---------------------------------------------------------------------
-- PMS（製造販売後調査等）
-- ---------------------------------------------------------------------
CREATE TABLE pms_studies (
    id                 INTEGER PRIMARY KEY,
    product_id         INTEGER NOT NULL REFERENCES products (id),
    indication_id      INTEGER REFERENCES indications (id),
    study_type         TEXT NOT NULL CHECK (study_type IN (
                           '一般使用成績調査', '特定使用成績調査', '使用成績比較調査',
                           '製造販売後データベース調査', '製造販売後臨床試験', 'その他')),
    title              TEXT NOT NULL CHECK (trim(title) <> ''),                 -- 調査名
    all_case           TEXT NOT NULL DEFAULT '未確認' CHECK (all_case IN ('全例調査', '全例調査ではない', '未確認')),
    approval_condition TEXT NOT NULL DEFAULT '未確認' CHECK (approval_condition IN ('承認条件', '承認条件ではない', '未確認')),
    progress           TEXT NOT NULL DEFAULT '未確認' CHECK (progress IN ('計画中', '実施中', '終了', '結果公表済み', '未確認')),
    target_cases       TEXT,                                                    -- 目標症例数
    disclosure         TEXT NOT NULL CHECK (disclosure IN ('公開', '非公開', '未確認')),  -- 実施期間の公開状況
    start_date         TEXT CHECK (start_date IS NULL OR date(start_date) IS start_date),
    end_date           TEXT CHECK (end_date IS NULL OR date(end_date) IS end_date),
    registration_no    TEXT,                                                    -- 登録番号（jRCT など）
    -- 【出典セット】ここから
    source_version_id  INTEGER NOT NULL REFERENCES document_versions (id),
    source_location    TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status             TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by        TEXT,
    verified_at        TEXT,
    entry_method       TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current         INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by      INTEGER REFERENCES pms_studies (id),
    created_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL)),
    -- 【出典セット】ここまで
    CHECK (disclosure = '公開' OR (start_date IS NULL AND end_date IS NULL)),
    CHECK (disclosure <> '公開' OR start_date IS NOT NULL OR end_date IS NOT NULL),
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date > start_date)
);
CREATE UNIQUE INDEX ux_pms_studies ON pms_studies (product_id, title) WHERE is_current = 1;


-- ---------------------------------------------------------------------
-- 適応症は、同じ製品のものだけを指定できる（別の製品の適応症を指定する間違いを防ぐ）
-- ---------------------------------------------------------------------
CREATE TRIGGER approvals_indication_matches BEFORE INSERT ON approvals
WHEN NEW.indication_id IS NOT NULL
 AND (SELECT product_id FROM indications WHERE id = NEW.indication_id) IS NOT NEW.product_id
BEGIN
    SELECT RAISE(ABORT, 'approvals：指定した適応症は、別の製品のものです');
END;

CREATE TRIGGER reexaminations_indication_matches BEFORE INSERT ON reexaminations
WHEN NEW.indication_id IS NOT NULL
 AND (SELECT product_id FROM indications WHERE id = NEW.indication_id) IS NOT NEW.product_id
BEGIN
    SELECT RAISE(ABORT, 'reexaminations：指定した適応症は、別の製品のものです');
END;

CREATE TRIGGER pms_studies_indication_matches BEFORE INSERT ON pms_studies
WHEN NEW.indication_id IS NOT NULL
 AND (SELECT product_id FROM indications WHERE id = NEW.indication_id) IS NOT NEW.product_id
BEGIN
    SELECT RAISE(ABORT, 'pms_studies：指定した適応症は、別の製品のものです');
END;

-- =====================================================================
-- 003_trials.sql：設計図バージョン3への追加分（マイグレーション）です。
--
-- 臨床試験のテーブルを追加します。
--   trials                試験そのもの（見分けるためのIDだけ。研究ID TR-0001 は内容を修正しても変わらない）
--   trial_details       ◆ 試験の内容（タイトル・フェーズ・日付など。修正すると新しい行で置き換え、旧版を残す）
--   trial_registrations ◆ 登録番号（1つの試験に、jRCT・ClinicalTrials.gov などの複数の登録番号）
--   trial_products        試験とアプリの製品の対応（自分で行う分類）
--   trial_diseases        試験とアプリの疾患の対応（自分で行う分類）
--
-- ◆ は【出典セット】付きの「事実」のテーブルです（出典は、各レジストリの登録ページ）。
-- 「試験そのもの」と「内容」を分けるのは、内容を修正して行が置き換わっても、
-- 登録番号や製品とのひも付け（trials を指している）がそのまま使えるようにするためです。
--
-- 対象疾患・介入は、登録ページに書かれたとおりの文（conditions_text / interventions_text）を事実として残し、
-- 「アプリのどの疾患・製品にあたるか」の分類（trial_diseases / trial_products）とは分けます。
--
-- 日付は YYYY-MM-DD か YYYY-MM（月までしかわからないとき。日は推測で補わない）。
-- 日付には「実績」か「予定」かを付けます（レジストリの予定日を、実績と混同しないため）。
-- =====================================================================


-- ---------------------------------------------------------------------
-- 試験そのもの
-- ---------------------------------------------------------------------
CREATE TABLE trials (
    id         INTEGER PRIMARY KEY,                                -- 研究ID（画面では TR-0001 のように表示）
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TRIGGER trials_no_delete BEFORE DELETE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trials：試験は削除できません');
END;


-- ---------------------------------------------------------------------
-- 試験の内容
-- ---------------------------------------------------------------------
CREATE TABLE trial_details (
    id                 INTEGER PRIMARY KEY,
    trial_id           INTEGER NOT NULL REFERENCES trials (id),
    title              TEXT NOT NULL CHECK (trim(title) <> ''),           -- 研究タイトル
    conditions_text    TEXT NOT NULL CHECK (trim(conditions_text) <> ''), -- 対象疾患（登録ページの記載のとおり）
    interventions_text TEXT NOT NULL CHECK (trim(interventions_text) <> ''),  -- 試験薬・介入（登録ページの記載のとおり）
    study_type         TEXT NOT NULL DEFAULT '未確認' CHECK (study_type IN ('介入研究', '観察研究', 'その他', '未確認')),
    design             TEXT,                                              -- 研究デザイン
    phase              TEXT NOT NULL DEFAULT '未確認' CHECK (phase IN (
                           '第1相', '第1/2相', '第2相', '第2/3相', '第3相', '第4相',
                           '製造販売後臨床試験', '該当なし', '未確認')),
    sponsor_company_id INTEGER REFERENCES companies (id),                 -- スポンサー（企業テーブルにある場合）
    sponsor_text       TEXT,                                              -- スポンサー（登録ページの記載のとおり）
    primary_endpoint   TEXT,                                              -- 主要評価項目
    start_date         TEXT CHECK (start_date IS NULL OR date(start_date) IS start_date
                                   OR start_date GLOB '[0-9][0-9][0-9][0-9]-0[1-9]'
                                   OR start_date GLOB '[0-9][0-9][0-9][0-9]-1[0-2]'),
    start_date_type    TEXT NOT NULL DEFAULT '未確認' CHECK (start_date_type IN ('実績', '予定', '未確認')),
    end_date           TEXT CHECK (end_date IS NULL OR date(end_date) IS end_date
                                   OR end_date GLOB '[0-9][0-9][0-9][0-9]-0[1-9]'
                                   OR end_date GLOB '[0-9][0-9][0-9][0-9]-1[0-2]'),
    end_date_type      TEXT NOT NULL DEFAULT '未確認' CHECK (end_date_type IN ('実績', '予定', '未確認')),
    recruitment_status TEXT NOT NULL DEFAULT '未確認' CHECK (recruitment_status IN (
                           '募集前', '募集中', '募集終了', '完了', '中止', '中断', '未確認')),
    results_status     TEXT NOT NULL DEFAULT '未確認' CHECK (results_status IN ('結果公開あり', '結果未公開', '未確認')),
    -- 【出典セット】ここから
    source_version_id  INTEGER NOT NULL REFERENCES document_versions (id),
    source_location    TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status             TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by        TEXT,
    verified_at        TEXT,
    entry_method       TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current         INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by      INTEGER REFERENCES trial_details (id),
    created_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL)),
    -- 【出典セット】ここまで
    -- 日付がないのに「実績」「予定」と書かない
    CHECK (start_date IS NOT NULL OR start_date_type = '未確認'),
    CHECK (end_date IS NOT NULL OR end_date_type = '未確認'),
    -- 終了日は開始日より前にならない（文字の順で比べる。YYYY-MM と YYYY-MM-DD が混ざっても前後は正しく比べられる）
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= substr(start_date, 1, 7))
);
-- 1つの試験の「今の内容」は1つだけ
CREATE UNIQUE INDEX ux_trial_details ON trial_details (trial_id) WHERE is_current = 1;


-- ---------------------------------------------------------------------
-- 登録番号
-- ---------------------------------------------------------------------
CREATE TABLE trial_registrations (
    id                INTEGER PRIMARY KEY,
    trial_id          INTEGER NOT NULL REFERENCES trials (id),
    registry          TEXT NOT NULL CHECK (registry IN ('jRCT', 'UMIN-CTR', 'ClinicalTrials.gov', 'その他')),
    registration_no   TEXT NOT NULL CHECK (trim(registration_no) <> ''),  -- 登録番号
    secondary_ids     TEXT,                                              -- 登録ページに書かれた他の登録番号（; 区切り）
    last_checked_on   TEXT NOT NULL CHECK (date(last_checked_on) IS last_checked_on),  -- 登録情報の最終確認日
    -- 【出典セット】ここから
    source_version_id INTEGER NOT NULL REFERENCES document_versions (id),
    source_location   TEXT NOT NULL CHECK (trim(source_location) <> ''),
    status            TEXT NOT NULL DEFAULT '未確認' CHECK (status IN ('未確認', '原文確認済み', '再確認要')),
    verified_by       TEXT,
    verified_at       TEXT,
    entry_method      TEXT NOT NULL DEFAULT '手入力' CHECK (entry_method IN ('手入力', 'CSV', 'API', 'AI抽出')),
    is_current        INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    superseded_by     INTEGER REFERENCES trial_registrations (id),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (status <> '原文確認済み' OR (trim(coalesce(verified_by, '')) <> '' AND verified_at IS NOT NULL))
    -- 【出典セット】ここまで
);
-- 同じレジストリの同じ登録番号は、1つの試験にしか登録できない（同じ試験を重複して数えないため）
CREATE UNIQUE INDEX ux_trial_registrations ON trial_registrations (registry, registration_no) WHERE is_current = 1;


-- ---------------------------------------------------------------------
-- 分類（自分で行うひも付け。出典セットはなく、変更は更新履歴に記録する）
-- ---------------------------------------------------------------------
CREATE TABLE trial_products (
    id         INTEGER PRIMARY KEY,
    trial_id   INTEGER NOT NULL REFERENCES trials (id),
    product_id INTEGER NOT NULL REFERENCES products (id),
    role       TEXT NOT NULL CHECK (role IN ('試験薬', '対照薬', '併用薬', 'その他')),
    UNIQUE (trial_id, product_id, role)
);

CREATE TABLE trial_diseases (
    id         INTEGER PRIMARY KEY,
    trial_id   INTEGER NOT NULL REFERENCES trials (id),
    disease_id INTEGER NOT NULL REFERENCES diseases (id),
    UNIQUE (trial_id, disease_id)
);


-- ---------------------------------------------------------------------
-- 文書の版の「原文の改訂年月」（db/schema.sql）を、正しい月（01〜12）だけにする
-- （バージョン1のルールでは「2025-13」のような月も通ってしまっていたため、ここで追加でチェックする）
-- ---------------------------------------------------------------------
CREATE TRIGGER document_versions_revised_month BEFORE INSERT ON document_versions
WHEN NEW.revised_on IS NOT NULL AND CAST(substr(NEW.revised_on, 6, 2) AS INTEGER) NOT BETWEEN 1 AND 12
BEGIN
    SELECT RAISE(ABORT, '原文の改訂年月の月は 01〜12 にしてください');
END;

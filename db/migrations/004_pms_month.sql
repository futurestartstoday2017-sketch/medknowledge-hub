-- =====================================================================
-- 設計図バージョン4：PMSの実施期間に「年月」（YYYY-MM）も入れられるようにする
-- =====================================================================
-- インタビューフォームなどでは、PMSの調査期間が「2019年8月～2023年7月」のように
-- 月までしか書かれていないことが多いため、臨床試験（trial_details）と同じく
-- YYYY-MM か YYYY-MM-DD を入れられるようにします（日は推測で補いません）。
--
-- SQLite では、あとからテーブルのルール（CHECK）を変えられないため、次の手順で作り直します。
--   ① 今のテーブルの名前を pms_studies_old に変える（トリガー・索引も一緒についていく）
--   ② 新しいルールで pms_studies を作る（守るためのトリガーは、database.py が自動で付ける）
--   ③ データをそのまま写す（id も同じ。旧版・置き換え先のつながりも保たれる）
--   ④ 古いテーブルを消し、索引と「適応症は同じ製品のもの」のトリガーを作り直す
-- 全体を1つのトランザクションで実行するので、途中で失敗したら何も変わりません。
-- =====================================================================

ALTER TABLE pms_studies RENAME TO pms_studies_old;

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
    -- 実施期間：YYYY-MM-DD か YYYY-MM（月までしかわからないとき）
    start_date         TEXT CHECK (start_date IS NULL OR date(start_date) IS start_date
                                   OR start_date GLOB '[0-9][0-9][0-9][0-9]-0[1-9]'
                                   OR start_date GLOB '[0-9][0-9][0-9][0-9]-1[0-2]'),
    end_date           TEXT CHECK (end_date IS NULL OR date(end_date) IS end_date
                                   OR end_date GLOB '[0-9][0-9][0-9][0-9]-0[1-9]'
                                   OR end_date GLOB '[0-9][0-9][0-9][0-9]-1[0-2]'),
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
    -- 終了日は開始日より後（文字の順で比べる。YYYY-MM と YYYY-MM-DD が混ざっても前後は正しく比べられる）
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date > start_date)
);

INSERT INTO pms_studies SELECT * FROM pms_studies_old;

DROP TABLE pms_studies_old;

CREATE UNIQUE INDEX ux_pms_studies ON pms_studies (product_id, title) WHERE is_current = 1;

CREATE TRIGGER pms_studies_indication_matches BEFORE INSERT ON pms_studies
WHEN NEW.indication_id IS NOT NULL
 AND (SELECT product_id FROM indications WHERE id = NEW.indication_id) IS NOT NEW.product_id
BEGIN
    SELECT RAISE(ABORT, 'pms_studies：指定した適応症は、別の製品のものです');
END;

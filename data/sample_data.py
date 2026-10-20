"""
sample_data.py：学習用の架空サンプルデータです。

ここにある製品・疾患・作用機序などは、すべて架空のものです。
実在する製品・疾患の医学的情報ではありません。
URLには、例示用に予約されているドメイン example.com を使っています。

データベースが空のときに、このデータが自動で登録されます（db/database.py）。
"""

# 疾患データ（1件 = 1つの辞書）
DISEASES = [
    {
        "disease_name": "架空循環器疾患A",
        "overview": "（架空）血液の流れを調整する仕組みが乱れる、学習用の架空の疾患です。",
        "diagnosis": "（架空）架空検査値Xが基準値を超えた状態が続く場合に診断します。",
        "treatment": "（架空）生活習慣の見直しに加え、架空循環器用薬を使用します。",
    },
    {
        "disease_name": "架空循環器疾患B",
        "overview": "（架空）架空循環器疾患Aが進行した状態とされる、学習用の架空の疾患です。",
        "diagnosis": "（架空）架空画像検査Yで特徴的な所見がみられた場合に診断します。",
        "treatment": "（架空）経口薬に加え、重症例では注射薬を併用します。",
    },
    {
        "disease_name": "架空免疫疾患C",
        "overview": "（架空）体の防御反応が過剰に働く、学習用の架空の疾患です。",
        "diagnosis": "（架空）架空マーカーZの上昇と症状の組み合わせで診断します。",
        "treatment": "（架空）架空免疫調整薬（経口薬・注射薬）を使用します。",
    },
    {
        "disease_name": "架空皮膚疾患D",
        "overview": "（架空）皮膚に赤みとかゆみが出る、学習用の架空の疾患です。",
        "diagnosis": "（架空）皮膚の見た目と経過から診断します。",
        "treatment": "（架空）外用薬を基本とし、広範囲の場合は注射薬を検討します。",
    },
]

# 製品データ（1件 = 1つの辞書）
PRODUCTS = [
    {
        "product_name": "サンプリンα錠",
        "generic_name": "サンプリン",
        "drug_class": "架空循環器用薬",
        "mechanism": "架空受容体Aを遮断する（架空）",
        "route": "経口",
        "dosage_form": "錠剤",
        "dosage": "（架空）通常、1日1回1錠を服用する。",
        "package_insert_url": "https://example.com/sampurin/package-insert",
        "interview_form_url": "https://example.com/sampurin/interview-form",
    },
    {
        "product_name": "テスタミドOD錠",
        "generic_name": "テスタミド",
        "drug_class": "架空循環器用薬",
        "mechanism": "架空酵素Bの働きを阻害する（架空）",
        "route": "経口",
        "dosage_form": "口腔内崩壊錠",
        "dosage": "（架空）通常、1日2回、朝夕に1錠ずつ服用する。",
        "package_insert_url": "https://example.com/testamid/package-insert",
        "interview_form_url": "https://example.com/testamid/interview-form",
    },
    {
        "product_name": "プレースボリン点滴静注",
        "generic_name": "プレースボリン",
        "drug_class": "架空循環器用薬",
        "mechanism": "架空イオンチャネルFを調節する（架空）",
        "route": "静脈内注射",
        "dosage_form": "注射剤（バイアル）",
        "dosage": "（架空）通常、4週に1回、点滴で静脈内に投与する。",
        "package_insert_url": "https://example.com/placeborin/package-insert",
        "interview_form_url": "https://example.com/placeborin/interview-form",
    },
    {
        "product_name": "モックセプト皮下注",
        "generic_name": "モックセプト",
        "drug_class": "架空免疫調整薬",
        "mechanism": "架空サイトカインCに結合して働きを抑える（架空）",
        "route": "皮下注射",
        "dosage_form": "注射剤（シリンジ）",
        "dosage": "（架空）通常、2週に1回、皮下に注射する。",
        "package_insert_url": "https://example.com/mockcept/package-insert",
        "interview_form_url": "https://example.com/mockcept/interview-form",
    },
    {
        "product_name": "ダミルカプセル",
        "generic_name": "ダミル",
        "drug_class": "架空免疫調整薬",
        "mechanism": "架空シグナルDの伝達を阻害する（架空）",
        "route": "経口",
        "dosage_form": "カプセル剤",
        "dosage": "（架空）通常、1日1回1カプセルを服用する。",
        "package_insert_url": "https://example.com/damil/package-insert",
        "interview_form_url": "https://example.com/damil/interview-form",
    },
    {
        "product_name": "フィクタゾン軟膏",
        "generic_name": "フィクタゾン",
        "drug_class": "架空外用薬",
        "mechanism": "架空受容体Eを刺激して炎症を抑える（架空）",
        "route": "外用",
        "dosage_form": "軟膏",
        "dosage": "（架空）通常、1日2回、患部に薄く塗る。",
        "package_insert_url": "https://example.com/fictazone/package-insert",
        "interview_form_url": "https://example.com/fictazone/interview-form",
    },
]

# 製品と疾患（適応症）の組み合わせ：(製品名, 疾患名)
# 1つの製品が複数の疾患に、1つの疾患に複数の製品が対応する「多対多」の関係です。
PRODUCT_DISEASES = [
    ("サンプリンα錠", "架空循環器疾患A"),
    ("サンプリンα錠", "架空循環器疾患B"),
    ("テスタミドOD錠", "架空循環器疾患A"),
    ("プレースボリン点滴静注", "架空循環器疾患B"),
    ("モックセプト皮下注", "架空免疫疾患C"),
    ("モックセプト皮下注", "架空皮膚疾患D"),
    ("ダミルカプセル", "架空免疫疾患C"),
    ("フィクタゾン軟膏", "架空皮膚疾患D"),
]

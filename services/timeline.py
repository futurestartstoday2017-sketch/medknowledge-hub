"""
timeline.py：初回承認から再審査期間の終了・特許満了までの「タイムライン」を作る処理です。

エビデンス創出の計画を考えるための目安として、期間（約○年）と今日時点の経過・残りを計算します。

計算のルール
  - 使うのは、登録済みで「公開」の日付だけ（推測で補わない）
  - 特許が複数あるときは、それぞれの満了日（延長登録があれば延長後）のうち、最も遅い日を目安に使う
  - 再審査期間は、製品全体のもの（適応症の指定がないもの）を使う
  - 使った値のどれかが「原文確認済み」でなければ、そのことを注意として返す
  - 後発品の参入時期を予測するものではない（実際は再審査・特許の種類・承認審査などで決まる）
"""

from datetime import date

from db.queries import FACT_SUBJECTS, fetch_facts


def first_approval(approvals):
    """承認のリストから「初回承認」を返します（なければ None）。"""
    return next((a for a in approvals if a["approval_type"] == "初回承認"), None)


def product_reexam(reexams):
    """再審査のリストから、製品全体の再審査（適応症の指定がないもの）を返します（なければ None）。"""
    return next((r for r in reexams if r["indication_id"] is None), None)


def effective_expiry(patent):
    """特許の実際の満了日（延長登録後の満了日があればその日、なければ存続期間満了日）を返します。"""
    return patent["extended_expiry_date"] or patent["expiry_date"]


def latest_patent(patents):
    """「公開」で満了日のある特許のうち、満了日が最も遅いものを返します（なければ None）。"""
    public = [p for p in patents if p["disclosure"] == "公開" and effective_expiry(p)]
    return max(public, key=effective_expiry) if public else None


def years_between(start, end):
    """2つの日付（YYYY-MM-DD）の間が何年か（小数）を返します。"""
    return (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25


def about_years(years):
    """年数を「約 8.0 年」の形の文字にします。"""
    return f"約 {abs(years):.1f} 年"


def build_timeline(conn, product_id, today=None):
    """
    製品のタイムラインを作り、次の辞書で返します。
      milestones：[{"label", "date", "fact"}]   … 初回承認・再審査期間の終了・特許満了（最も遅いもの）
      durations ：[{"区間", "期間"}]             … 表に出す期間の一覧
      notes     ：[文]                           … 足りない情報・未確認の値についての注意
      patents   ：[特許の事実]                   … 満了日の比較に使った特許（公開のもの）
    """
    today = (today or date.today()).isoformat()

    def facts(table):
        return fetch_facts(conn, table, "f.product_id = ?", (product_id,), **FACT_SUBJECTS[table])

    approval = first_approval(facts("approvals"))
    reexam = product_reexam(facts("reexaminations"))
    patents = facts("patents")
    patent = latest_patent(patents)

    approval_date = approval["approval_date"] if approval else None
    reexam_end = reexam["end_date"] if reexam and reexam["disclosure"] == "公開" else None
    patent_end = effective_expiry(patent) if patent else None

    milestones = [
        {"label": "初回承認年月日", "date": approval_date, "fact": approval},
        {"label": "再審査期間の終了日", "date": reexam_end, "fact": reexam},
        {"label": "特許満了日（最も遅いもの）", "date": patent_end, "fact": patent},
    ]

    # ---- 足りない情報・未確認の値についての注意 ----
    notes = []
    if not approval:
        notes.append("初回承認年月日が登録されていないため、期間を計算できません。")
    if not reexam:
        notes.append("製品全体の再審査期間が登録されていません。")
    elif reexam["disclosure"] != "公開":
        notes.append(f"再審査期間は「{reexam['disclosure']}」のため、終了日を計算に使っていません。")
    elif not reexam_end:
        notes.append("再審査期間の終了日が登録されていません（期間の年数だけが登録されています）。")
    if not patents:
        notes.append("特許が登録されていません。")
    hidden = [p for p in patents if p["disclosure"] != "公開"]
    if hidden:
        numbers = "、".join(p["patent_number"] for p in hidden)
        notes.append(f"満了日が非公開・未確認の特許があります（{numbers}）。最も遅い満了日が変わる可能性があります。")
    unverified = [m["label"] for m in milestones if m["fact"] and m["date"] and m["fact"]["status"] != "原文確認済み"]
    if unverified:
        notes.append(f"原文で確認できていない値を含む目安です（{'、'.join(unverified)}）。")

    # ---- 期間の計算（両方の日付がそろっているものだけ）----
    durations = []
    if approval_date and reexam_end:
        durations.append({"区間": "初回承認 → 再審査期間の終了", "期間": about_years(years_between(approval_date, reexam_end))})
    if approval_date and patent_end:
        durations.append({"区間": "初回承認 → 特許満了（最も遅いもの）",
                          "期間": about_years(years_between(approval_date, patent_end))})
    if approval_date:
        durations.append({"区間": f"初回承認 → 今日（{today}）",
                          "期間": about_years(years_between(approval_date, today)) + " 経過"})
    for label, end in (("再審査期間の終了", reexam_end), ("特許満了（最も遅いもの）", patent_end)):
        if end:
            years = years_between(today, end)
            remaining = f"残り {about_years(years)}" if years >= 0 else f"終了済み（{about_years(years)}前）"
            durations.append({"区間": f"今日 → {label}", "期間": remaining})

    return {
        "milestones": milestones,
        "durations": durations,
        "notes": notes,
        "patents": [p for p in patents if p["disclosure"] == "公開"],
    }

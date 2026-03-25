"""
ski_data.jsonの各スキー場の営業状態をSURF&SNOWから更新する。
source_urlを使って詳細ページを取得し、status と season_end を更新。
"""

import json
import re
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
DELAY = 1.0


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Error: {e}")
        return ""


def extract_status(html):
    """HTMLから営業状態とクローズ予定日を抽出"""
    status = "unknown"
    season_end = ""

    # クローズ予定日: "クローズ予定日  2026/04/05" パターン
    m = re.search(r'クローズ予定日\s*(\d{4}/\d{2}/\d{2})', html)
    if m:
        season_end = m.group(1).replace("/", "-")

    # 営業状態を判定（順序重要: 終了を先にチェック）
    # HTMLタグ除去した本文で判定
    text = re.sub(r'<[^>]+>', ' ', html)

    if re.search(r'営業は終了|今季営業終了|シーズン終了|今シーズンの営業は|営業を終了|シーズンの営業は終了|閉鎖いたしました', text):
        status = "closed"
    elif re.search(r'営業中|全\d+コースで営業|現在営業|オープン中|ゲレンデ営業', text):
        status = "open"
    else:
        # オープン予定日とクローズ予定日から判定
        open_match = re.search(r'オープン予定日\s*(\d{4}/\d{2}/\d{2})', text)
        close_match = re.search(r'クローズ予定日\s*(\d{4}/\d{2}/\d{2})', text)
        if close_match:
            season_end = close_match.group(1).replace("/", "-")
        if open_match and season_end:
            from datetime import date
            today = date.today()
            try:
                open_date = date.fromisoformat(open_match.group(1).replace("/", "-"))
                close_date = date.fromisoformat(season_end)
                if open_date <= today <= close_date:
                    status = "open"
                elif today > close_date:
                    status = "closed"
                elif today < open_date:
                    status = "not_yet"
            except ValueError:
                pass

    return status, season_end


def main():
    with open("ski_data.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"=== {len(data)}件の営業状態を更新 ===")

    updated = 0
    for i, resort in enumerate(data):
        url = resort.get("source_url", "")
        if not url:
            continue

        print(f"[{i+1}/{len(data)}] {resort['name']}...", end=" ")
        html = fetch(url)
        if not html:
            print("取得失敗")
            continue

        status, season_end = extract_status(html)
        resort["status"] = status
        if season_end:
            resort["season_end"] = season_end

        print(f"status={status}, end={season_end or 'N/A'}")
        updated += 1
        time.sleep(DELAY)

    # 保存
    with open("ski_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 統計
    statuses = {}
    for r in data:
        s = r.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    print(f"\n=== 完了: {updated}件更新 ===")
    print(f"営業状態: {statuses}")


if __name__ == "__main__":
    main()

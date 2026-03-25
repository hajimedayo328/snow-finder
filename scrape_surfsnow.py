"""
SURF&SNOW（surfsnow.jp）から全国スキー場データを取得するスクリプト。
GitHub Actionsで毎朝自動実行される想定。

出力: ski_data.json（全スキー場の情報）
"""

import json
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
BASE = "https://surfsnow.jp"
LIST_URL = BASE + "/search/list/spl_area01.php?page={}"
DELAY = 1.5  # リクエスト間隔（秒）


def fetch(url):
    """URLからHTMLを取得"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {url}")
        return ""
    except Exception as e:
        print(f"  Error: {e}: {url}")
        return ""


# ==================================================
# 一覧ページから個別ページURLを収集
# ==================================================
def collect_detail_urls():
    """サイトマップから全スキー場の詳細ページURLを収集"""
    print("サイトマップを取得中...")
    sitemap_url = BASE + "/sitemap.xml"
    xml = fetch(sitemap_url)
    if not xml:
        print("サイトマップ取得失敗、一覧ページからフォールバック")
        return collect_detail_urls_from_list()

    # サイトマップからr????s.htmを抽出
    urls = re.findall(r'(https://surfsnow\.jp/guide/htm/r\d+s\.htm)', xml)
    urls = list(dict.fromkeys(urls))  # 重複除去
    print(f"サイトマップから {len(urls)} 件のスキー場URLを取得")
    return urls


def collect_detail_urls_from_list():
    """フォールバック: 一覧ページから収集"""
    urls = []
    for page in range(1, 30):
        print(f"一覧ページ {page}...")
        html = fetch(LIST_URL.format(page))
        if not html:
            break
        found_raw = re.findall(r'href="(/guide/htm/r(\d+)tk\.htm)[^"]*"', html)
        found = [f"{BASE}/guide/htm/r{num}s.htm" for _, num in found_raw]
        if not found:
            break
        for path in found:
            if path not in urls:
                urls.append(path)
        print(f"  累計: {len(urls)} 件")
        time.sleep(DELAY)
    return urls


# ==================================================
# 個別ページからJSON-LDを抽出
# ==================================================
def extract_jsonld(html):
    """HTML内のJSON-LD（schema.org/SkiResort）を抽出"""
    pattern = r'<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>'
    matches = re.findall(pattern, html, re.DOTALL)
    for m in matches:
        try:
            data = json.loads(m)
            if isinstance(data, dict) and data.get("@type") == "SkiResort":
                return data
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "SkiResort":
                        return item
        except json.JSONDecodeError:
            continue
    return None


def extract_from_html(html):
    """JSON-LDがない場合にHTMLから直接データを抽出"""
    result = {}

    # スキー場名
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    if m:
        result["name"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()

    # コース数
    m = re.search(r'コース数[^0-9]*(\d+)', html)
    if m:
        result["courses_total"] = int(m.group(1))

    # リフト数
    m = re.search(r'リフト[^0-9]*(\d+)', html)
    if m:
        result["lifts_total"] = int(m.group(1))

    # 標高
    for pat in [r'(?:トップ|山頂|最高)[^0-9]*(\d{3,4})\s*m', r'標高[^0-9]*(\d{3,4})']:
        m = re.search(pat, html)
        if m:
            result["max_elevation"] = int(m.group(1))
            break

    # 最長滑走距離
    for pat in [r'最長[^0-9]*(\d{1,5})\s*m', r'最大滑走[^0-9]*(\d{1,5})']:
        m = re.search(pat, html)
        if m:
            result["longest_run"] = int(m.group(1))
            break

    # 難易度
    for level, key in [("初級", "beginner_pct"), ("中級", "intermediate_pct"), ("上級", "advanced_pct")]:
        m = re.search(rf'{level}[^0-9]*(\d+)\s*%', html)
        if m:
            result[key] = int(m.group(1))

    # 営業状況（「クローズ」「オープン」両方出る場合があるので、クローズ優先）
    if re.search(r'営業終了|クローズ|今季営業終了|シーズン終了', html):
        result["status"] = "closed"
    elif re.search(r'営業中|オープン中|オープン', html):
        result["status"] = "open"

    return result


def parse_resort(url, html):
    """個別ページからスキー場データを構築"""
    resort = {
        "name": "",
        "region": "",
        "prefecture": "",
        "courses_total": 0,
        "beginner_pct": 30,
        "intermediate_pct": 40,
        "advanced_pct": 30,
        "lifts_total": 0,
        "max_elevation": 0,
        "longest_run": 0,
        "url": "",
        "lat": 0,
        "lon": 0,
        "status": "unknown",
        "source_url": url,
    }

    # JSON-LDを試す
    jsonld = extract_jsonld(html)
    if jsonld:
        resort["name"] = jsonld.get("name", "")
        geo = jsonld.get("geo", {})
        if geo:
            resort["lat"] = round(float(geo.get("latitude", 0)), 2)
            resort["lon"] = round(float(geo.get("longitude", 0)), 2)
        addr = jsonld.get("address", {})
        if isinstance(addr, dict):
            resort["prefecture"] = addr.get("addressRegion", "")
        elif isinstance(addr, str):
            # 都道府県を抽出
            m = re.search(r'(北海道|.{2,3}[都府県])', addr)
            if m:
                resort["prefecture"] = m.group(1)
        resort["url"] = jsonld.get("url", "")

    # HTMLからも補完
    html_data = extract_from_html(html)
    if not resort["name"] and html_data.get("name"):
        resort["name"] = html_data["name"]
    for key in ["courses_total", "lifts_total", "max_elevation", "longest_run",
                "beginner_pct", "intermediate_pct", "advanced_pct", "status"]:
        if html_data.get(key) and (not resort.get(key) or resort[key] == 0):
            resort[key] = html_data[key]

    # 地域を都道府県から推定
    pref = resort["prefecture"]
    region_map = {
        "北海道": "北海道",
        "青森県": "東北", "岩手県": "東北", "秋田県": "東北",
        "山形県": "東北", "宮城県": "東北", "福島県": "東北",
        "新潟県": "甲信越", "長野県": "甲信越", "山梨県": "甲信越",
        "群馬県": "関東", "栃木県": "関東", "埼玉県": "関東", "東京都": "関東", "神奈川県": "関東",
        "富山県": "中部", "石川県": "中部", "福井県": "中部",
        "岐阜県": "中部", "静岡県": "中部", "愛知県": "中部", "三重県": "中部",
        "滋賀県": "関西", "京都府": "関西", "大阪府": "関西",
        "兵庫県": "関西", "奈良県": "関西", "和歌山県": "関西",
        "鳥取県": "中国", "島根県": "中国", "岡山県": "中国",
        "広島県": "中国", "山口県": "中国",
        "徳島県": "四国", "香川県": "四国", "愛媛県": "四国", "高知県": "四国",
        "福岡県": "九州", "佐賀県": "九州", "長崎県": "九州",
        "熊本県": "九州", "大分県": "九州", "宮崎県": "九州", "鹿児島県": "九州",
    }
    resort["region"] = region_map.get(pref, "")

    return resort


# ==================================================
# メイン
# ==================================================
def main():
    print("=== SURF&SNOW スクレイピング開始 ===")

    # Step 1: 一覧から個別URLを収集
    detail_urls = collect_detail_urls()
    print(f"\n個別ページ: {len(detail_urls)} 件\n")

    # Step 2: 各個別ページからデータ取得
    resorts = []
    for i, url in enumerate(detail_urls):
        print(f"[{i+1}/{len(detail_urls)}] {url}")
        html = fetch(url)
        if not html:
            continue

        resort = parse_resort(url, html)
        if resort["name"]:
            resorts.append(resort)
            print(f"  → {resort['name']} ({resort['prefecture']})")
        else:
            print(f"  → 名前取得失敗、スキップ")

        time.sleep(DELAY)

    # Step 3: JSON保存
    # nameでソート
    resorts.sort(key=lambda r: r["name"])

    output_path = "ski_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(resorts, f, ensure_ascii=False, indent=2)

    print(f"\n=== 完了: {len(resorts)} 件 → {output_path} ===")

    # 統計
    regions = {}
    for r in resorts:
        reg = r["region"] or "不明"
        regions[reg] = regions.get(reg, 0) + 1
    print("\n地域別:")
    for reg, count in sorted(regions.items(), key=lambda x: -x[1]):
        print(f"  {reg}: {count}")


if __name__ == "__main__":
    main()

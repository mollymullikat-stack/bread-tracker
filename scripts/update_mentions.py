# -*- coding: utf-8 -*-
"""ดึงข้อมูล mention จริงจาก Apify (XHS + Douyin) แล้วอัปเดต data.json
รันโดย GitHub Actions (.github/workflows/apify-update.yml) — ใช้ stdlib ล้วน ไม่ต้องติดตั้งอะไร
ต้องมี env: APIFY_TOKEN
"""
import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

KEYWORDS = ["泰国面包", "海盐面包", "曼谷美食"]
POSTS_PER_KEYWORD = 10
THAI_HINTS = ["泰", "曼谷", "Bangkok", "bangkok"]
THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
BKK = timezone(timedelta(hours=7))
DATA = Path(__file__).resolve().parent.parent / "data.json"

ACTORS = {
    "xhs": ("zen-studio~rednote-search-scraper",
            {"keywords": KEYWORDS, "maxResults": POSTS_PER_KEYWORD,
             "topUpFromOtherSorts": False, "sortType": "general",
             "noteType": "all", "timeFilter": "all"}),
    "douyin": ("zen-studio~douyin-search-scraper",
               {"keywords": KEYWORDS, "maxResultsPerQuery": POSTS_PER_KEYWORD,
                "sort": "general", "publishTime": "unlimited",
                "shouldDownloadVideos": False, "shouldDownloadCovers": False}),
}


def run_actor(actor_id, payload, token):
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items?timeout=280"
    body = json.dumps(payload, ensure_ascii=True).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    })
    last_err = None
    for _ in range(2):  # ลองซ้ำ 1 ครั้งถ้าพลาด
        try:
            with urllib.request.urlopen(req, timeout=320) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"{actor_id} failed: {last_err}")


def norm(platform, item):
    """แปลงโพสต์ของแต่ละแพลตฟอร์มเป็นโครงเดียวกัน"""
    if platform == "xhs":
        e = item.get("engagement") or {}
        ts = item.get("timestamp") or 0
        when = datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=BKK) if ts else None
        return {
            "kw": item.get("keyword"),
            "title": (item.get("title") or item.get("desc") or "").strip(),
            "likes": int(e.get("liked_count") or 0),
            "comments": int(e.get("comments_count") or 0),
            "collects": int(e.get("collected_count") or 0),
            "when": when,
        }
    s = item.get("statistics") or {}
    when = None
    try:
        when = datetime.strptime(item.get("createDate", ""), "%Y-%m-%d").replace(tzinfo=BKK)
    except ValueError:
        pass
    return {
        "kw": item.get("searchKeyword") or item.get("inputKeyword"),
        "title": (item.get("itemTitle") or item.get("text") or "").strip().split("\n")[0],
        "likes": int(s.get("diggCount") or 0),
        "comments": int(s.get("commentCount") or 0),
        "collects": int(s.get("collectCount") or 0),
        "when": when,
    }


def kw_stats(posts):
    likes = [p["likes"] for p in posts] or [0]
    return {
        "posts": len(posts),
        "likesSum": sum(likes),
        "likesMedian": int(statistics.median(likes)),
        "likesMax": max(likes),
        "comments": sum(p["comments"] for p in posts),
        "collects": sum(p["collects"] for p in posts),
        "thaiRelated": sum(1 for p in posts if any(h in p["title"] for h in THAI_HINTS)),
    }


def fmt_likes(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def sample_card(plat_label, p):
    title = escape(p["title"][:60])
    when = f" ({THAI_MONTHS[p['when'].month - 1]} {p['when'].year})" if p["when"] else ""
    return {
        "plat": f"{plat_label} 🟢",
        "tone": "pos",
        "txt": (f"{title} ❤️{fmt_likes(p['likes'])}<br>"
                f"<span class='tx'>{p['likes']:,} ไลก์{when} · จากคีย์เวิร์ด {p['kw']}</span>"),
    }


def main():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("APIFY_TOKEN is not set")

    results = {}
    for plat, (actor_id, payload) in ACTORS.items():
        items = run_actor(actor_id, payload, token)
        results[plat] = [norm(plat, i) for i in items]
        print(f"{plat}: {len(items)} posts")

    now = datetime.now(BKK)
    data = json.loads(DATA.read_text(encoding="utf-8"))

    keywords_block = {}
    for kw in KEYWORDS:
        keywords_block[kw] = {
            plat: kw_stats([p for p in results[plat] if p["kw"] == kw])
            for plat in ("xhs", "douyin")
        }

    insights = []
    top_kw = max(KEYWORDS, key=lambda k: sum(keywords_block[k][p]["likesSum"] for p in ("xhs", "douyin")))
    insights.append(f"{top_kw} engagement สูงสุดในรอบนี้ "
                    f"(XHS {keywords_block[top_kw]['xhs']['likesSum']:,} + "
                    f"Douyin {keywords_block[top_kw]['douyin']['likesSum']:,} ไลก์)")
    for kw in KEYWORDS:
        if all(keywords_block[kw][p]["thaiRelated"] == 0 for p in ("xhs", "douyin")):
            insights.append(f"{kw}: โพสต์ท็อปไม่เกี่ยวกับไทยเลย (0/{POSTS_PER_KEYWORD}) — พิจารณาใช้คีย์เวิร์ดผสม เช่น 泰国{kw}")

    # ตัวอย่างโพสต์: top 2 ต่อแพลตฟอร์ม เอาเฉพาะที่เกี่ยวกับไทยก่อน
    def top2(plat):
        ps = sorted(results[plat], key=lambda p: p["likes"], reverse=True)
        thai = [p for p in ps if any(h in p["title"] for h in THAI_HINTS)]
        return (thai + [p for p in ps if p not in thai])[:2]

    data["mentions"]["samples"] = (
        [sample_card("小红书 RED", p) for p in top2("xhs")]
        + [sample_card("抖音 Douyin", p) for p in top2("douyin")]
    )
    data["apifySample"] = {
        "note": (f"🟢 ข้อมูลจริง — อัปเดตอัตโนมัติเมื่อ {now.day} {THAI_MONTHS[now.month - 1]} {now.year} "
                 f"ผ่าน GitHub Actions + Apify: top {POSTS_PER_KEYWORD} โพสต์ต่อคีย์เวิร์ดต่อแพลตฟอร์ม · "
                 "Actor: zen-studio/rednote-search-scraper + zen-studio/douyin-search-scraper"),
        "keywords": keywords_block,
        "insights": insights,
    }
    data["lastUpdated"] = (f"{now.day} {THAI_MONTHS[now.month - 1]} {now.year} "
                           f"{now:%H:%M} (อัปเดตอัตโนมัติผ่าน Apify)")

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("data.json updated:", data["lastUpdated"])


if __name__ == "__main__":
    main()

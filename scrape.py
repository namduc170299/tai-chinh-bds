#!/usr/bin/env python3
"""Cào tin Bất động sản, Tài chính, Xã hội & Mạng xã hội (viral) từ RSS các báo Việt Nam, lưu vào data/news.json.

Chỉ dùng thư viện chuẩn của Python, không cần cài thêm gì.
Chạy: python3 scrape.py
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

VN_TZ = timezone(timedelta(hours=7))
OUT = Path(__file__).parent / "data" / "news.json"
KEEP_DAYS = 7          # giữ tin trong 7 ngày gần nhất
MAX_ITEMS = 2500       # tối đa số tin lưu lại
TIMEOUT = 20

# (tên báo, mục, đường dẫn RSS). Mục: "bds" = Bất động sản, "tc" = Tài chính,
# "xh" = Xã hội: thời sự, pháp luật, vấn đề nóng/nhức nhối.
# "mxh" = Mạng xã hội: chủ đề đang lan truyền / được tìm và đọc nhiều nhất.
GN = "https://news.google.com/rss/search?hl=vi&gl=VN&ceid=VN:vi&"
FEEDS = [
    ("VnExpress", "bds", "https://vnexpress.net/rss/bat-dong-san.rss"),
    ("VnExpress", "tc", "https://vnexpress.net/rss/kinh-doanh.rss"),
    ("CafeF", "bds", "https://cafef.vn/bat-dong-san.rss"),
    ("CafeF", "tc", "https://cafef.vn/thi-truong-chung-khoan.rss"),
    ("CafeF", "tc", "https://cafef.vn/tai-chinh-ngan-hang.rss"),
    ("Dân Trí", "bds", "https://dantri.com.vn/rss/bat-dong-san.rss"),
    ("Dân Trí", "tc", "https://dantri.com.vn/rss/kinh-doanh.rss"),
    ("VietnamNet", "bds", "https://vietnamnet.vn/rss/bat-dong-san.rss"),
    ("VietnamNet", "tc", "https://vietnamnet.vn/rss/kinh-doanh.rss"),
    ("VnEconomy", "tc", "https://vneconomy.vn/tai-chinh.rss"),
    ("VnEconomy", "tc", "https://vneconomy.vn/chung-khoan.rss"),
    ("Thanh Niên", "tc", "https://thanhnien.vn/rss/kinh-te.rss"),
    ("Tuổi Trẻ", "tc", "https://tuoitre.vn/rss/kinh-doanh.rss"),
    # Báo Mới (baomoi.com) không còn RSS riêng -> lấy bài của Báo Mới qua Google News
    ("Báo Mới", "bds", GN + "q=site:baomoi.com+(b%E1%BA%A5t+%C4%91%E1%BB%99ng+s%E1%BA%A3n+OR+nh%C3%A0+%C4%91%E1%BA%A5t+OR+chung+c%C6%B0+OR+c%C4%83n+h%E1%BB%99+OR+d%E1%BB%B1+%C3%A1n)+when:7d"),
    ("Báo Mới", "tc", GN + "q=site:baomoi.com+(t%C3%A0i+ch%C3%ADnh+OR+ch%E1%BB%A9ng+kho%C3%A1n+OR+ng%C3%A2n+h%C3%A0ng+OR+l%C3%A3i+su%E1%BA%A5t)+when:2d"),
    # Xã hội: thời sự & pháp luật mới nhất
    ("VnExpress", "xh", "https://vnexpress.net/rss/thoi-su.rss"),
    ("VnExpress", "xh", "https://vnexpress.net/rss/phap-luat.rss"),
    ("Dân Trí", "xh", "https://dantri.com.vn/rss/phap-luat.rss"),
    ("Tuổi Trẻ", "xh", "https://tuoitre.vn/rss/thoi-su.rss"),
    ("Tuổi Trẻ", "xh", "https://tuoitre.vn/rss/phap-luat.rss"),
    ("Thanh Niên", "xh", "https://thanhnien.vn/rss/thoi-su.rss"),
    ("VietnamNet", "xh", "https://vietnamnet.vn/rss/thoi-su.rss"),
    # Vụ việc gây bức xúc, nhức nhối trong 48h qua (tổng hợp nhiều báo qua Google News)
    ("Google News", "xh", GN + "q=(%22b%E1%BB%A9c+x%C3%BAc%22+OR+%22nh%E1%BB%A9c+nh%E1%BB%91i%22+OR+%22ph%E1%BA%ABn+n%E1%BB%99%22+OR+%22g%C3%A2y+x%C3%B4n+xao%22)+when:2d"),
    ("Kenh14", "xh", "https://kenh14.vn/xa-hoi.rss"),
    # Mạng xã hội / viral
    ("Google Trends", "mxh", "https://trends.google.com/trending/rss?geo=VN"),
    ("VnExpress", "mxh", "https://vnexpress.net/rss/tin-xem-nhieu.rss"),
    ("VnExpress", "mxh", "https://vnexpress.net/rss/tin-noi-bat.rss"),
    ("Thanh Niên", "mxh", "https://thanhnien.vn/rss/gioi-tre.rss"),
    ("Tuổi Trẻ", "mxh", "https://tuoitre.vn/rss/nhip-song-tre.rss"),
]
HT_NS = "{https://trends.google.com/trending/rss}"

# Tin ở mục Tài chính nhưng nói về nhà đất thì chuyển sang Bất động sản.
BDS_WORDS = re.compile(
    r"bất động sản|nhà đất|chung cư|căn hộ|dự án nhà|nhà ở|đất nền|sổ đỏ|"
    r"giá nhà|giá đất|khu đô thị|biệt thự|nhà phố|môi giới nhà|bđs",
    re.IGNORECASE,
)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"
BAD_DATES: dict[str, str] = {}
TZ_FIXED: dict[str, str] = {}   # báo nào ghi sai múi giờ (đã tự sửa)  # báo nào ghi ngày giờ lạ -> mẫu để sửa


def clean_text(raw: str | None, limit: int = 280) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def find_image(item: ET.Element, desc: str) -> str:
    for tag in (f"{MEDIA_NS}content", f"{MEDIA_NS}thumbnail", "enclosure"):
        el = item.find(tag)
        if el is not None and el.get("url"):
            return el.get("url", "")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc or "")
    return html.unescape(m.group(1)) if m else ""


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("\u202f", " ").replace("\xa0", " ").strip()
    # Tuổi Trẻ và vài báo ghi múi giờ kiểu "GMT+7" -> đổi thành "+0700"
    value = re.sub(r"GMT\s*([+-])(\d{1,2})(?::?(\d{2}))?$",
                   lambda m: f"{m.group(1)}{int(m.group(2)):02d}{m.group(3) or '00'}", value)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                    "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def parse_feed(raw: bytes, source: str, cat: str, now: datetime) -> list[dict]:
    raw = raw.lstrip()  # vài báo có khoảng trắng trước <?xml
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        title = clean_text(it.findtext("title"), 300)
        link = (it.findtext("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        desc_raw = it.findtext("description") or ""
        raw_date = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
        pub = parse_date(raw_date)
        guess = pub is None
        if pub is None:
            BAD_DATES.setdefault(source, str(raw_date)[:60])
            pub = now
        c = cat
        if c == "tc" and BDS_WORDS.search(title):
            c = "bds"
        if source == "Báo Mới":
            # Google News: chỉ giữ bài của baomoi.com, bỏ đuôi " - Báo Mới" ở tiêu đề
            src_el = it.find("source")
            if src_el is not None and "baomoi.com" not in (src_el.get("url") or ""):
                continue
            title = re.sub(r"\s+-\s+(Báo Mới|BAOMOI\.COM|baomoi\.com)$", "", title, flags=re.IGNORECASE)
            desc_raw = ""  # mô tả của Google News chỉ lặp lại tiêu đề
        elif source == "Google News":
            # bỏ đuôi " - Tên báo" ở tiêu đề, ghi tên báo vào phần mô tả
            src_el = it.find("source")
            paper = (src_el.text or "").strip() if src_el is not None else ""
            if paper and title.endswith(" - " + paper):
                title = title[: -len(paper) - 3]
            desc_raw = f"Nguồn: {paper}" if paper else ""
        uid = link
        extra = {}
        if source == "Google Trends":
            # mỗi từ khoá đang hot: lấy bài báo đầu tiên làm link, kèm lượt tìm
            uid = f"gt:{title.lower()}:{pub:%Y%m%d}"
            traffic = (it.findtext(f"{HT_NS}approx_traffic") or "").strip()
            news = it.find(f"{HT_NS}news_item")
            if news is not None:
                link = (news.findtext(f"{HT_NS}news_item_url") or link).strip()
                ntitle = clean_text(news.findtext(f"{HT_NS}news_item_title"))
                nsrc = clean_text(news.findtext(f"{HT_NS}news_item_source"), 60)
                desc_raw = f"{ntitle} ({nsrc})" if nsrc else ntitle
                if not find_image(it, "") and news.findtext(f"{HT_NS}news_item_picture"):
                    extra["image"] = news.findtext(f"{HT_NS}news_item_picture").strip()
            if traffic:
                extra["traffic"] = traffic
            img = it.findtext(f"{HT_NS}picture")
            if img:
                extra.setdefault("image", img.strip())
        items.append({
            "id": hashlib.sha1(uid.encode()).hexdigest()[:12],
            "title": title,
            "link": link,
            "summary": clean_text(desc_raw),
            "image": find_image(it, desc_raw),
            "source": source,
            "cat": c,
            "published": pub,
            "_guess": guess,
            **extra,
        })
    # Vài báo (vd Kenh14) ghi giờ Việt Nam nhưng gắn nhãn GMT -> lệch +7 tiếng,
    # tin mới bị "ở tương lai". Phát hiện theo cả nguồn rồi trừ 7 tiếng cho mọi tin.
    if any(i["published"] > now + timedelta(minutes=10) for i in items if not i["_guess"]):
        TZ_FIXED[source] = "-7h"
        for i in items:
            if not i["_guess"]:
                i["published"] -= timedelta(hours=7)
    for i in items:
        if i["published"] > now:  # vẫn còn lệch vài phút -> lấy giờ hiện tại
            i["published"] = now
        i["published"] = i["published"].isoformat(timespec="seconds")
    return items


def scrape_one(feed, now):
    source, cat, url = feed
    err = None
    for attempt in range(3):  # thử lại tối đa 3 lần nếu báo lỗi tạm thời
        try:
            items = parse_feed(fetch(url), source, cat, now)
            return {"name": source, "cat": cat, "url": url, "ok": True, "count": len(items)}, items
        except Exception as e:  # noqa: BLE001 - một báo lỗi không được làm hỏng cả lượt
            err = e
            time.sleep(3 * (attempt + 1))
    return {"name": source, "cat": cat, "url": url, "ok": False, "count": 0, "error": f"{type(err).__name__}: {err}"[:200]}, []


def norm_title(t: str) -> str:
    return re.sub(r"[^\w]+", " ", t.lower()).strip()


def main() -> int:
    now = datetime.now(VN_TZ)
    old = {"items": []}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text("utf-8"))
        except json.JSONDecodeError:
            pass
    known = {i["id"]: i for i in old.get("items", [])}
    if not old.get("fix_kenh14_tz"):
        # sửa 1 lần các tin Kenh14 cũ đã lưu với giờ lệch +7 tiếng
        for i in known.values():
            if i.get("source") != "Kenh14":
                continue
            m = re.search(r"-2\d{2}(\d{12})\d*\.chn$", i.get("link", ""))
            if i.get("published", "")[:16] == i.get("found", "")[:16] and m:
                t = datetime.strptime(m.group(1), "%y%m%d%H%M%S").replace(tzinfo=VN_TZ)  # giờ tạo bài trong link
            else:
                t = datetime.fromisoformat(i["published"]) - timedelta(hours=7)
            i["published"] = min(t, now).isoformat(timespec="seconds")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda f: scrape_one(f, now), FEEDS))

    statuses, new_count = [], 0
    for status, items in results:
        statuses.append(status)
        for item in items:
            if item["id"] in known:
                # giữ thời điểm phát hiện lần đầu, cập nhật mục nếu là BĐS
                old_item = known[item["id"]]
                if item["cat"] == "bds":
                    old_item["cat"] = "bds"
                if item.get("traffic"):
                    old_item["traffic"] = item["traffic"]
                # luôn dùng giờ đăng thật mới nhất từ RSS (sửa giờ cũ bị ghi sai)
                if not item["_guess"]:
                    old_item["published"] = item["published"]
                continue
            item.pop("_guess", None)
            item["found"] = now.isoformat(timespec="seconds")
            known[item["id"]] = item
            new_count += 1

    cutoff = now - timedelta(days=KEEP_DAYS)
    items = [i for i in known.values() if parse_date(i["published"]) and parse_date(i["published"]) >= cutoff]
    items.sort(key=lambda i: i["published"], reverse=True)

    # bỏ tin trùng tiêu đề (cùng một bài ở 2 mục RSS)
    seen, unique = set(), []
    for i in items:
        key = (i["source"], norm_title(i["title"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(i)
    unique = unique[:MAX_ITEMS]
    stamp = now.isoformat(timespec="seconds")
    new_count = sum(1 for i in unique if i.get("found") == stamp)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": now.isoformat(timespec="seconds"),
        "new": new_count,
        "sources": statuses,
        "bad_dates": BAD_DATES,
        "tz_fixed": TZ_FIXED,
        "fix_kenh14_tz": True,
        "items": unique,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0), "utf-8")

    ok = sum(s["ok"] for s in statuses)
    print(f"{now:%Y-%m-%d %H:%M} | nguồn OK {ok}/{len(statuses)} | tin mới {new_count} | tổng {len(unique)}")
    for s in statuses:
        if not s["ok"]:
            print(f"  LỖI {s['name']} {s['url']}: {s.get('error')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Kiểm tra nhanh tình trạng trang tin. In OK và thoát 0 nếu ổn; in lỗi và thoát 1 nếu cần sửa."""
import json
import sys
from datetime import datetime, timedelta, timezone

d = json.load(open("data/news.json", encoding="utf-8"))
now = datetime.now(timezone(timedelta(hours=7)))
age = (now - datetime.fromisoformat(d["updated"])).total_seconds() / 60
issues = []
if age > 50:  # cào 15 phút/lần, GitHub hay trễ vài phút
    issues.append(f"STALE: cập nhật cách đây {age:.0f} phút")
for s in d.get("sources", []):
    if not s["ok"] or s["count"] == 0:
        issues.append(f"SOURCE: {s['name']} ({s['cat']}) {s['url']} -> {s.get('error', '0 tin')}")
for name, sample in (d.get("bad_dates") or {}).items():
    issues.append(f"DATE: {name} ghi giờ dạng {sample!r}")
print("\n".join(issues) if issues else f"OK {d['updated'][11:16]}")
sys.exit(1 if issues else 0)

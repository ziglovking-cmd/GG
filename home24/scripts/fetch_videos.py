#!/usr/bin/env python3
"""Crawl public Yandex Disk folder into data-videos.json."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = "https://disk.yandex.ru/d/ZLKt8eDXJYKdnQ"
UA = "Mozilla/5.0 (compatible; Home24Guides/1.0)"
API = "https://cloud-api.yandex.net/v1/disk/public/resources"


def list_dir(path: str) -> dict:
    url = API + "?" + urllib.parse.urlencode(
        {"public_key": PUBLIC, "path": path, "limit": 200}
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def walk(path: str, out: list[dict]) -> None:
    data = list_dir(path)
    items = data.get("_embedded", {}).get("items") or []
    for it in items:
        typ = it.get("type")
        name = it.get("name") or ""
        p = it.get("path") or ""
        # API path looks like "disk:/..." or the public relative path
        rel = p
        if rel.startswith("disk:"):
            rel = rel[5:]
        if typ == "dir":
            time.sleep(0.15)
            walk(rel, out)
            continue
        low = name.lower()
        if not low.endswith((".mp4", ".mov", ".m4v", ".webm")):
            continue
        folder = rel.rsplit("/", 1)[0] if "/" in rel else path
        out.append(
            {
                "name": name,
                "path": rel if rel.startswith("/") else "/" + rel,
                "public_url": it.get("public_url"),
                "size": it.get("size"),
                "folder": folder if folder.startswith("/") else "/" + folder,
            }
        )


def main() -> None:
    files: list[dict] = []
    walk("/Видео материал ", files)
    seen = set()
    uniq = []
    for v in files:
        if v["path"] in seen:
            continue
        seen.add(v["path"])
        uniq.append(v)
    uniq.sort(key=lambda x: x["path"])
    dest = ROOT / "data-videos.json"
    dest.write_text(json.dumps(uniq, ensure_ascii=False, indent=2), encoding="utf-8")
    folders = sorted({v["folder"] for v in uniq})
    print("files", len(uniq), "folders", len(folders))
    for f in folders:
        n = sum(1 for v in uniq if v["folder"] == f)
        print(f"  {n:3d}  {f}")


if __name__ == "__main__":
    main()

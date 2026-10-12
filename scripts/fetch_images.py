"""从 Wikimedia Commons 获取可商用图片并写入署名清单。

用法：
    uv run python scripts/fetch_images.py preview   # 为未选定的素材位生成候选缩略图拼图到 .cache/candidates/
    uv run python scripts/fetch_images.py download  # 下载已选定的图片到 static/img/stock/ 并生成 credits.json

只接受 CC0 / 公有领域 / CC BY / CC BY-SA 许可证，署名信息在网站“图片来源”页展示。
"""

import html
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent.parent
STOCK_DIR = ROOT / "static" / "img" / "stock"
CACHE_DIR = ROOT / ".cache" / "candidates"
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "PawStayAssetFetcher/1.0 (https://github.com/; asset credits tooling)"
ALLOWED_LICENSE = re.compile(r"^(CC0|Public domain|CC BY(-SA)? \d\.\d)", re.I)

# 素材位 -> (检索关键词, 选定的 Commons 文件名；None 表示待挑选)
SLOTS: dict[str, tuple[str, str | None]] = {
    "hero": ("dog and cat", "File:Cat and Dog Game.jpg"),
    "service-walk": ("dog walking leash park", "File:(1)Walking the dog.jpg"),
    "service-grooming": ("dog grooming bath", "File:MWD Spa Day (9568305).jpg"),
    "service-feeding": ("puppy eating", "File:Kölyök kuvasz.jpg"),
    "service-health": (
        "veterinarian examining dog",
        "File:Close-up of a veterinarian examining a maltese dog with a stethoscope. (51687314898).jpg",
    ),
    "service-cat": ("cat playing toy", "File:Tabby Cat with Toy Mouse.jpg"),
    "room-dog-standard": ("dog sleeping dog bed", 'File:This dog is "comfy"- 2013-12-27 10-51.jpg'),
    "room-dog-deluxe": ("dog sleeping dog bed", "File:A spoiled dog tucked in bed.jpg"),
    "room-cat-standard": (
        "cat tree scratching post",
        "File:Mama , I'm bored-There's nothing to do !!!!! (4507339843).jpg",
    ),
    "room-cat-suite": ("cat sleeping window", "File:White sleeping cat in Breitenstein.jpg"),
    "room-any": ("dog sleeping dog bed", "File:December 2008 sleeping cat and dog.jpg"),
    "room-dog-economy": ("puppy sleeping blanket", "File:12-week-old Choclolate Labrador Retriever Puppy.jpg"),
    "pet-labrador": ("labrador retriever", "File:Labrador Retriever (1210559).jpg"),
    "care-golden-eat": ("golden retriever food", "File:Tea Time (237593935).jpeg"),
    "care-golden-walk": ("golden retriever leash walk", "File:Search and Rescue Canine Team (50518063476).jpg"),
    "care-golden-bath": ("golden retriever wet", "File:Golden wet.jpg"),
    "pet-golden": ("golden retriever portrait", "File:Golden Retriever Hund Dog.JPG"),
    "pet-british": ("british shorthair cat", "File:Mystica from British Empire Cattery.jpg"),
    "pet-corgi": ("pembroke welsh corgi", "File:Welsh Pembroke Corgi.jpg"),
    "cta": ("happy dog running beach", "File:Penny at the beach - Flickr - marneejill.jpg"),
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                time.sleep(0.8)
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 5:
                raise
            time.sleep(int(exc.headers.get("Retry-After") or 0) or 5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 5:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def _query(params: dict) -> list[dict]:
    params = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata|size", **params}
    data = json.loads(_get(f"{API}?{urllib.parse.urlencode(params)}"))
    pages = data.get("query", {}).get("pages", {}).values()
    return sorted(pages, key=lambda p: p.get("index", 0))


def _license(page: dict) -> str:
    meta = page["imageinfo"][0].get("extmetadata", {})
    return meta.get("LicenseShortName", {}).get("value", "")


def _strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def search(query: str, width: int) -> list[dict]:
    pages = _query(
        {
            "generator": "search",
            "gsrnamespace": 6,
            "gsrlimit": 30,
            "gsrsearch": f"{query} filetype:bitmap",
            "iiurlwidth": width,
        }
    )
    result = []
    for page in pages:
        info = page["imageinfo"][0]
        if not ALLOWED_LICENSE.match(_license(page)):
            continue
        if info["width"] < 1200 or info["width"] < info["height"]:
            continue
        result.append(page)
    return result[:12]


def preview():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for slot, (query, chosen) in SLOTS.items():
        if chosen or (CACHE_DIR / f"{slot}.png").exists():
            continue
        pages = search(query, 360)
        tile_w, tile_h, cols = 360, 240, 4
        rows = max(1, (len(pages) + cols - 1) // cols)
        sheet = Image.new("RGB", (tile_w * cols, (tile_h + 28) * rows), "white")
        draw = ImageDraw.Draw(sheet)
        lines = []
        for i, page in enumerate(pages):
            img = Image.open(io.BytesIO(_get(page["imageinfo"][0]["thumburl"]))).convert("RGB")
            img = ImageOps.fit(img, (tile_w, tile_h))
            x, y = (i % cols) * tile_w, (i // cols) * (tile_h + 28)
            sheet.paste(img, (x, y))
            draw.text((x + 6, y + tile_h + 6), f"#{i}", fill="black")
            lines.append(f"#{i} {page['title']} [{_license(page)}]")
        sheet.save(CACHE_DIR / f"{slot}.png")
        (CACHE_DIR / f"{slot}.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"{slot}: {len(pages)} candidates")


def download():
    STOCK_DIR.mkdir(parents=True, exist_ok=True)
    credits_file = STOCK_DIR / "credits.json"
    existing = json.loads(credits_file.read_text(encoding="utf-8")) if credits_file.exists() else {}
    credits = {}
    for slot, (_, title) in SLOTS.items():
        if not title:
            print(f"跳过未选定素材位：{slot}")
            continue
        old = existing.get(slot)
        if old and old["title"] == title.removeprefix("File:") and (STOCK_DIR / f"{slot}.jpg").exists():
            credits[slot] = old
            continue
        page = _query({"titles": title, "iiurlwidth": 1600})[0]
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        img = Image.open(io.BytesIO(_get(info["thumburl"]))).convert("RGB")
        img = ImageOps.fit(img, (1600, 1067), centering=(0.5, 0.45))
        img.save(STOCK_DIR / f"{slot}.jpg", quality=82, optimize=True, progressive=True)
        credits[slot] = {
            "title": title.removeprefix("File:"),
            "author": _strip_tags(meta.get("Artist", {}).get("value", "未知作者")),
            "license": _license(page),
            "license_url": meta.get("LicenseUrl", {}).get("value", ""),
            "source": info["descriptionurl"],
        }
        print(f"{slot}: {title}")
    credits_file.write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    {"preview": preview, "download": download}[sys.argv[1] if len(sys.argv) > 1 else "preview"]()

#!/usr/bin/env python3
"""Автоматический поиск и подготовка студийных фото очков по артикулам из ITigris.

Ищет официальные каталожные изображения по (Бренд + Модель) в специализированных
оптических каталогах и официальных витринах брендов, проверяет совпадение
модели, приводит изображение к единому студийному формату 640×800 (4:5, светлый фон)
и сохраняет в assets/img/frames/<sku>.jpg, после чего обновляет assets/data/catalog.json.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageChops

_SHOPIFY_LOCK = threading.Lock()
_LAST_SHOPIFY_REQ = 0.0
_MIN_INTERVAL = 0.65

BASE_DIR = Path(__file__).resolve().parent.parent
FRAMES_DIR = BASE_DIR / "assets" / "img" / "frames"
CATALOG_JSON = BASE_DIR / "assets" / "data" / "catalog.json"
MISSING_JSON = BASE_DIR / "scripts" / "missing_photos.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Официальные брендовые витрины Shopify
BRAND_STORES: Dict[str, List[str]] = {
    "lespecs": ["https://intl.lespecs.com"],
    "kaleos eyehunters": ["https://kaleoscollection.com"],
    "cazal": ["https://www.cazal-eyewear.com", "https://www.eurooptica.com"],
    "matsuda": ["https://www.matsuda.com", "https://www.goodseeco.com"],
    "retrosuperfuture": ["https://retrosuperfuture.com"],
    "linda farrow": ["https://www.lindafarrow.com"],
    "ahlem": ["https://www.ahlemeyewear.com", "https://www.goodseeco.com"],
    "eyepetizer": ["https://www.eyepetizer.it"],
    "john dalia": ["https://www.johndalia.com", "https://parislunetier.com"],
    "cutler and gross": ["https://www.cutlerandgross.com", "https://www.pretavoir.co.uk"],
    "moscot": ["https://www.moscot.com"],
    "garrett leight": ["https://garrettleight.com"],
    "dita": ["https://dita.com", "https://www.goodseeco.com", "https://parislunetier.com"],
    "cartier": ["https://www.pretavoir.co.uk", "https://parislunetier.com", "https://www.leidmann.com"],
    "gucci": ["https://www.pretavoir.co.uk", "https://www.goodseeco.com", "https://www.fashioneyewear.com"],
    "saint laurent": ["https://www.pretavoir.co.uk", "https://www.fashioneyewear.com", "https://www.solsticesunglasses.com"],
    "prada": ["https://www.pretavoir.co.uk", "https://www.fashioneyewear.com", "https://www.solsticesunglasses.com"],
    "miu miu": ["https://www.pretavoir.co.uk", "https://www.fashioneyewear.com"],
    "tom ford": ["https://www.pretavoir.co.uk", "https://www.fashioneyewear.com", "https://www.goodseeco.com"],
    "ray-ban": ["https://www.pretavoir.co.uk", "https://www.fashioneyewear.com"],
    "gotti": ["https://www.eurooptica.com", "https://www.seen.co.uk"],
    "andy wolf": ["https://www.eurooptica.com", "https://www.goodseeco.com"],
    "ic! berlin": ["https://www.eurooptica.com", "https://www.goodseeco.com"],
    "mykita": ["https://www.goodseeco.com", "https://www.eurooptica.com", "https://www.leidmann.com"],
    "kuboraum": ["https://www.seen.co.uk", "https://www.goodseeco.com"],
    "silhouette": ["https://www.eurooptica.com", "https://www.pretavoir.co.uk"],
}

DEFAULT_MULTI_STORES = [
    "https://www.pretavoir.co.uk",
    "https://www.goodseeco.com",
    "https://www.eurooptica.com",
    "https://www.fashioneyewear.com",
    "https://parislunetier.com",
]

# Внутренние или неподходящие для веб-поиска бренды
SKIP_BRANDS = {
    "refaced",
    "импорт",
    "фиксики",
    "смешарики",
    "no name (винтаж)",
}


def norm_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def build_queries_and_token(brand: str, model_raw: str) -> Tuple[List[str], str]:
    """Строит список поисковых запросов и ключевой токен модели для верификации."""
    b_low = brand.lower().strip()
    m = model_raw.partition("+")[0].strip()

    # Cartier: CTO550S 008 -> CT0550S 008
    if b_low == "cartier":
        m = re.sub(r"^CTO(?=\d)", "CT0", m, flags=re.I)
        parts = m.split()
        code = parts[0] if parts else m
        color = parts[1] if len(parts) > 1 else ""
        queries = [f"{code} {color}".strip(), code]
        return queries, norm_alnum(code)

    # Gucci: GG 1221S 001 -> GG1221S 001
    if b_low == "gucci":
        m_compact = re.sub(r"^GG\s+(\d+\w*)", r"GG\1", m, flags=re.I)
        parts = m_compact.split()
        code = parts[0] if parts else m_compact
        return [m_compact, code], norm_alnum(code)

    # Saint Laurent: SL 653 LEON 001 -> SL 653 001 / SL 653
    if b_low == "saint laurent":
        m_sl = re.match(r"^(SL\s*\d+\w*)\s+(?:[A-Z]+\s+)?(\d{3})?", m, flags=re.I)
        if m_sl:
            base_sl = re.sub(r"\s+", " ", m_sl.group(1).upper())
            col_sl = m_sl.group(2) or ""
            q1 = f"{base_sl} {col_sl}".strip()
            return [q1, base_sl], norm_alnum(base_sl)

    # Prada: SPR A60 ZVN-30C -> PR A60S, VPR A14 -> PR A14V
    if b_low == "prada":
        m_pr = re.match(r"^(S|V)PR\s+([A-Z0-9]+)\s*([A-Z0-9\-]+)?", m, flags=re.I)
        if m_pr:
            kind_ch = "S" if m_pr.group(1).upper() == "S" else "V"
            code = m_pr.group(2).upper()
            col = (m_pr.group(3) or "").replace("-", "")
            pr_code = f"PR {code}{kind_ch}"
            return [f"{pr_code} {col}".strip(), pr_code, f"SPR {code}"], norm_alnum(code)

    # Miu Miu: SMU 54Y 1BC-10F -> MU 54YS, VMU 01V -> MU 01VV
    if b_low == "miu miu":
        m_mu = re.match(r"^(S|V)MU\s+([A-Z0-9]+)\s*([A-Z0-9\-]+)?", m, flags=re.I)
        if m_mu:
            kind_ch = "S" if m_mu.group(1).upper() == "S" else "V"
            code = m_mu.group(2).upper()
            col = (m_mu.group(3) or "").replace("-", "")
            mu_code = f"MU {code}{kind_ch}"
            return [f"{mu_code} {col}".strip(), mu_code, f"SMU {code}"], norm_alnum(code)

    # Tom Ford: TF 1071 01A -> TF 1071 01A / FT1071
    if b_low == "tom ford":
        m_tf = re.match(r"^TF\s*([0-9]+\-?[A-Z]?)\s*(\w+)?", m, flags=re.I)
        if m_tf:
            num = m_tf.group(1).upper()
            col = m_tf.group(2) or ""
            return [f"TF {num} {col}".strip(), f"FT{num} {col}".strip(), f"TF {num}"], norm_alnum(num)

    # Ray-Ban: RB 3447 9198/B1 -> RB3447
    if b_low == "ray-ban":
        m_rb = re.match(r"^(RB|RX)\s*(\d+)\s*([\w/]+)?", m, flags=re.I)
        if m_rb:
            pref = m_rb.group(1).upper()
            num = m_rb.group(2)
            col = m_rb.group(3) or ""
            return [f"{pref}{num} {col}".strip(), f"{pref} {num} {col}".strip(), f"{pref}{num}"], num

    # Linda Farrow: LFL-1122 C08 -> LFL1122
    if b_low == "linda farrow":
        m_lf = re.search(r"(\d{3,4})", m)
        if m_lf:
            num = m_lf.group(1)
            return [f"LFL{num}", f"Linda Farrow {num}"], num

    # Cazal: Mod. 7098 col. 002 -> Cazal 7098
    if b_low == "cazal":
        m_cz = re.search(r"Mod\.\s*0*(\d{3,4})", m, flags=re.I)
        if m_cz:
            num = m_cz.group(1)
            return [f"MOD {num}", f"Cazal {num}"], num

    # LeSpecs: ENTANGLE 1926570 -> ENTANGLE
    if b_low == "lespecs":
        name = re.sub(r"\b\d{6,8}\b", "", m).strip()
        if name:
            return [name], norm_alnum(name.split()[0])

    # Kaleos: Alton C-004 -> Alton
    if b_low == "kaleos eyehunters":
        name = re.sub(r"\bC\-?\d+\b.*", "", m, flags=re.I).strip()
        if name:
            return [name], norm_alnum(name)

    # Matsuda: 2809H-V2-AG-BGN or M3023 SG MAS-MBK,57 -> 2809H / M3023
    if b_low == "matsuda":
        code = re.split(r"[\s,\-]+", m)[0]
        return [code, f"Matsuda {code}"], norm_alnum(code)

    # MYKITA: Reeves col.712 or CANYON, col.301 -> Reeves / CANYON
    if b_low == "mykita":
        name = re.split(r"\bcol\.|\,", m, flags=re.I)[0].strip()
        if name:
            return [f"Mykita {name}", name], norm_alnum(name)

    # RETROSUPERFUTURE: T4B Giusto Azure -> Giusto Azure
    if b_low == "retrosuperfuture":
        parts = m.split()
        name = " ".join(parts[1:]) if len(parts) > 1 and len(parts[0]) <= 4 else m
        tok = parts[1] if len(parts) > 1 and len(parts[0]) <= 4 else parts[0]
        return [name], norm_alnum(tok)

    # AHLEM / Eyepetizer / John Dalia / Gotti
    if b_low in ("ahlem", "eyepetizer", "john dalia", "gotti"):
        first = re.split(r"[\s,/]+", m)[0]
        return [m, first], norm_alnum(first)

    # Cutler and Gross: CGOP 1405-47-02 -> 1405
    if b_low == "cutler and gross":
        m_cg = re.search(r"\b0*(\d{3,4})\b", m)
        if m_cg:
            num = m_cg.group(1)
            return [num, f"Cutler and Gross {num}"], num

    # Dita: METAMAT DTS526-59-02 -> Metamat / DTS526
    if b_low == "dita":
        parts = m.split()
        first = parts[0]
        dts = re.search(r"(DT[A-Z]?\d{3,4})", m, flags=re.I)
        qs = [f"Dita {first}", first]
        if dts:
            qs.insert(0, dts.group(1))
        return qs, norm_alnum(first)

    # Общий случай
    first_tok = re.split(r"[\s,]+", m)[0]
    return [f"{brand} {m}", m], norm_alnum(first_tok)


def fetch_shopify_Matches(store: str, query: str) -> List[Dict[str, Any]]:
    global _LAST_SHOPIFY_REQ
    url = f"{store}/search/suggest.json?q={urllib.parse.quote(query)}"
    for attempt in range(2):
        with _SHOPIFY_LOCK:
            now = time.monotonic()
            wait = _MIN_INTERVAL - (now - _LAST_SHOPIFY_REQ)
            if wait > 0:
                time.sleep(wait)
            _LAST_SHOPIFY_REQ = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return data.get("resources", {}).get("results", {}).get("products", []) or []
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                with _SHOPIFY_LOCK:
                    time.sleep(4.0)
                    _LAST_SHOPIFY_REQ = time.monotonic()
                continue
            return []
        except Exception:
            return []
    return []


def normalize_product_image(raw_bytes: bytes, dst_path: Path) -> bool:
    """Приводит скачанное фото оправы к студийному формату 640×800 на белом фоне."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            if im.width < 220 or im.height < 120:
                return False

            # Если есть прозрачность — кладём на чистый белый студийный фон
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                im_rgb = Image.alpha_composite(white, rgba).convert("RGB")
            else:
                im_rgb = im.convert("RGB")

            target_w, target_h = 640, 800
            bg = Image.new("RGB", im_rgb.size, (255, 255, 255))
            diff = ImageChops.difference(im_rgb, bg).convert("L")
            mask = diff.point(lambda x: 255 if x > 12 else 0)
            bbox = mask.getbbox()
            cropped = im_rgb.crop(bbox) if bbox else im_rgb

            canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))

            # Масштабируем с сохранением пропорций так, чтобы очки аккуратно вписались с полями 8%
            pad_w, pad_h = int(target_w * 0.84), int(target_h * 0.76)
            scale = min(pad_w / cropped.width, pad_h / cropped.height)
            new_w = max(1, int(round(cropped.width * scale)))
            new_h = max(1, int(round(cropped.height * scale)))
            resized = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

            off_x = (target_w - new_w) // 2
            off_y = (target_h - new_h) // 2
            canvas.paste(resized, (off_x, off_y))

            dst_path.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(dst_path, "JPEG", quality=90, optimize=True)
            return True
    except Exception:
        return False


def find_and_download_photo(item: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    sku = item["sku"]
    brand = item["brand"]
    model_raw = item.get("modelRaw") or item.get("model") or ""
    dst_path = FRAMES_DIR / f"{sku}.jpg"
    if dst_path.is_file():
        return sku, f"assets/img/frames/{dst_path.name}"

    b_low = brand.lower().strip()
    if b_low in SKIP_BRANDS or "(винтаж)" in b_low:
        return sku, None

    queries, token = build_queries_and_token(brand, model_raw)
    if not token or len(token) < 2:
        return sku, None

    stores = list(BRAND_STORES.get(b_low, []))
    for s in DEFAULT_MULTI_STORES:
        if s not in stores:
            stores.append(s)

    for store in stores[:3]:
        for q in queries[:2]:
            try:
                prods = fetch_shopify_Matches(store, q)
            except Exception:
                continue

            for p in prods:
                title = str(p.get("title") or "")
                handle = str(p.get("handle") or "")
                body = str(p.get("body") or "")
                img_url = str(p.get("image") or p.get("featured_image", {}).get("url") or "")
                if not img_url:
                    continue
                if img_url.startswith("//"):
                    img_url = "https:" + img_url

                haystack = norm_alnum(f"{title} {handle} {body}")
                # Для брендовых магазинов (например Linda Farrow) поиск по SKU уже возвращает точный товар
                is_brand_official = store in BRAND_STORES.get(b_low, [])[:1] and b_low not in (
                    "cartier",
                    "gucci",
                    "saint laurent",
                    "prada",
                    "miu miu",
                    "tom ford",
                    "ray-ban",
                )
                if token not in haystack and not (is_brand_official and len(prods) <= 3):
                    continue

                try:
                    req = urllib.request.Request(img_url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        raw_bytes = resp.read()
                    if normalize_product_image(raw_bytes, dst_path):
                        return sku, f"assets/img/frames/{dst_path.name}"
                except Exception:
                    continue

    return sku, None


def update_catalog_with_photos() -> Tuple[int, int]:
    if not CATALOG_JSON.is_file():
        return 0, 0
    data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    products = data.get("products", [])
    with_photo = 0
    for p in products:
        sku = p["sku"]
        candidate = FRAMES_DIR / f"{sku}.jpg"
        if candidate.is_file():
            p["photo"] = f"assets/img/frames/{candidate.name}"
        if p.get("photo"):
            with_photo += 1

    # Пересортируем: товары с фото первыми
    products.sort(
        key=lambda x: (
            0 if x.get("photo") else 1,
            -len(x.get("boutiques", [])),
            -(x.get("price") or 0),
            x.get("brand", "").lower(),
            x.get("model", "").lower(),
        )
    )
    data["withPhotoCount"] = with_photo
    data["products"] = products
    CATALOG_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(products), with_photo


def main() -> int:
    parser = argparse.ArgumentParser(description="Автопоиск студийных фото очков по артикулам")
    parser.add_argument("--limit", type=int, default=80, help="Максимум позиций за один проход")
    parser.add_argument("--workers", type=int, default=8, help="Число параллельных потоков")
    parser.add_argument("--brand", type=str, default="", help="Фильтр по конкретному бренду")
    args = parser.parse_args()

    if not MISSING_JSON.is_file():
        print("Не найден scripts/missing_photos.json — сначала запустите sync_itigris.py")
        return 1

    missing = json.loads(MISSING_JSON.read_text(encoding="utf-8"))
    candidates = [
        m
        for m in missing
        if m["brand"].lower() not in SKIP_BRANDS
        and "(винтаж)" not in m["brand"].lower()
        and not (FRAMES_DIR / f"{m['sku']}.jpg").is_file()
        and (not args.brand or m["brand"].lower() == args.brand.lower())
    ]

    batch = candidates[: args.limit]
    print(f"Кандидатов без фото: {len(candidates)}, берём в работу пакет: {len(batch)}")

    found_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(find_and_download_photo, item): item for item in batch}
        for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            item = futures[fut]
            try:
                sku, rel_path = fut.result()
            except Exception:
                sku, rel_path = item["sku"], None
            if rel_path:
                found_count += 1
                print(f"[{idx}/{len(batch)}] + {item['brand']} {item['model']} -> {rel_path}")
            else:
                print(f"[{idx}/{len(batch)}] - {item['brand']} {item['model']} (не найдено)")

    total, with_photo = update_catalog_with_photos()
    print(f"\nНайдено новых фото за проход: {found_count}")
    print(f"Всего моделей в catalog.json: {total}, из них с фото: {with_photo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

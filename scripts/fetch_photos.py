#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Массовый и точный (с учётом кода цвета / линз) загрузчик студийных фото оправ и солнцезащитных очков
для каталога REFACED (`scripts/missing_photos.json` -> `assets/img/frames/<sku>.jpg`).

Принципы работы:
1. Строгое соответствие модели И цветового кода (colorway / цвет линз):
   - Разные цветовые коды одной модели (например, Cartier CT0551S 001 и CT0551S 003,
     Matsuda 2809H-V2-AG-BGN и 2809H-V2-SG-BRTM-BOR, Linda Farrow LFL-1131 C10 и C15,
     Kaleos C-002 и C-004, Cazal col.001 и col.003) НИКОГДА не получают общую фотографию
     без проверки кода цвета.
2. Двухэтапный поиск:
   - Этап 1: Пакетная выгрузка полных каталогов (`/products.json` и `/collections/<brand>/products.json`)
     с официальных сайтов брендов и крупных мультибрендовых оптик с поддержкой `variants[].sku`,
     `variants[].title` и `variants[].featured_image.src` (локальный кэш `scripts/.shopify_catalog_cache.json`).
   - Этап 2: Точечный поиск через `/search/suggest.json` + `/products/<handle>.js` и `mykita.com`
     для редких и архивных моделей с обязательной проверкой кода цвета.
3. Защита от дублей по MD5:
   - Если скачанное изображение по хэшу совпадает с фото другого цвета той же модели, оно отклоняется.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
FRAMES_DIR = BASE_DIR / "assets" / "img" / "frames"
MISSING_JSON = BASE_DIR / "scripts" / "missing_photos.json"
CACHE_JSON = BASE_DIR / "scripts" / ".shopify_catalog_cache.json"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CANVAS_W = 640
CANVAS_H = 800

# Официальные монобрендовые магазины на Shopify
OFFICIAL_BRAND_STORES: List[Tuple[str, str, int]] = [
    ("Matsuda", "https://www.matsuda.com", 3),
    ("Kaleos Eyehunters", "https://kaleoscollection.com", 8),
    ("LeSpecs", "https://intl.lespecs.com", 5),
    ("RETROSUPERFUTURE", "https://retrosuperfuture.com", 8),
    ("Linda Farrow", "https://www.lindafarrow.com", 6),
    ("Cazal", "https://www.cazal-eyewear.com", 2),
    ("AHLEM", "https://www.ahlemeyewear.com", 2),
    ("Eyepetizer", "https://www.eyepetizer.it", 5),
    ("John Dalia", "https://www.johndalia.com", 3),
    ("Cutler and Gross", "https://www.cutlerandgross.com", 3),
    ("Dita", "https://dita.com", 3),
    ("Leisure Society", "https://leisuresociety.com", 2),
    ("Karen Walker", "https://www.karenwalker.com", 2),
    ("Moscot", "https://www.moscot.com", 2),
    ("Garrett Leight", "https://garrettleight.com", 2),
    ("Haffmans & Neumeister", "https://haffmansneumeister.com", 3),
]

# Коллекции мультибрендовых магазинов (бренд в нашем каталоге -> список URL коллекций)
MULTIBRAND_COLLECTIONS: List[Tuple[str, str, int]] = [
    # Good See Co
    ("Cartier", "https://www.goodseeco.com/collections/sunglasses-cartier", 3),
    ("Cartier", "https://www.goodseeco.com/collections/eyeglasses-cartier", 3),
    ("Gucci", "https://www.goodseeco.com/collections/gucci-sunglasses", 4),
    ("Gucci", "https://www.goodseeco.com/collections/gucci-eyeglasses", 3),
    ("MYKITA", "https://www.goodseeco.com/collections/eyeglasses-mykita", 2),
    ("MYKITA", "https://www.goodseeco.com/collections/sunglasses-mykita", 2),
    ("Ic! Berlin", "https://www.goodseeco.com/collections/eyeglasses-ic-berlin", 2),
    ("Ic! Berlin", "https://www.goodseeco.com/collections/sunglasses-ic-berlin", 2),
    ("Kuboraum", "https://www.goodseeco.com/collections/eyeglasses-kuboraum", 2),
    ("Kuboraum", "https://www.goodseeco.com/collections/sunglasses-kuboraum", 2),
    ("Lunor", "https://www.goodseeco.com/collections/lunor-eyeglasses", 2),
    ("Matsuda", "https://www.goodseeco.com/collections/eyeglasses-matsuda", 3),
    ("Matsuda", "https://www.goodseeco.com/collections/sunglasses-matsuda", 3),
    ("Saint Laurent", "https://www.goodseeco.com/collections/eyeglasses-saint-laurent", 2),
    ("Saint Laurent", "https://www.goodseeco.com/collections/saint-laurent-sunglasses", 3),
    ("Prada", "https://www.goodseeco.com/collections/eyeglasses-prada", 3),
    ("Prada", "https://www.goodseeco.com/collections/sunglasses-prada", 4),
    ("Miu Miu", "https://www.goodseeco.com/collections/miu-miu-eyeglasses", 2),
    ("Miu Miu", "https://www.goodseeco.com/collections/miu-miu-sunglasses", 2),
    ("Ray-Ban", "https://www.goodseeco.com/collections/eyeglasses-ray-ban", 4),
    ("Ray-Ban", "https://www.goodseeco.com/collections/sunglasses-ray-ban", 3),
    ("Tom Ford", "https://www.goodseeco.com/collections/tom-ford-eyeglasses", 3),
    ("Tom Ford", "https://www.goodseeco.com/collections/tom-ford-sun", 3),
    ("Celine", "https://www.goodseeco.com/collections/celine-eyeglasses", 2),
    ("Celine", "https://www.goodseeco.com/collections/celine-sunglasses", 2),
    ("Dior", "https://www.goodseeco.com/collections/eyeglasses-dior", 2),
    ("Dior", "https://www.goodseeco.com/collections/sunglasses-dior", 2),
    ("Linda Farrow", "https://www.goodseeco.com/collections/eyeglasses-linda-farrow", 2),
    ("Linda Farrow", "https://www.goodseeco.com/collections/sunglasses-linda-farrow", 2),
    ("Masunaga", "https://www.goodseeco.com/collections/eyeglasses-masunaga", 2),
    ("Masunaga", "https://www.goodseeco.com/collections/sunglasses-masunaga", 2),
    ("Cutler and Gross", "https://www.goodseeco.com/collections/eyeglasses-cutler-and-gross", 2),
    ("Cutler and Gross", "https://www.goodseeco.com/collections/sunglasses-cutler-and-gross", 2),
    ("Anne & Valentin", "https://www.goodseeco.com/collections/eyeglasses-anne-et-valentin", 2),
    ("Anne & Valentin", "https://www.goodseeco.com/collections/sunglasses-anne-et-valentin", 2),
    ("Moscot", "https://www.goodseeco.com/collections/eyeglasses-moscot", 2),
    ("Moscot", "https://www.goodseeco.com/collections/sunglasses-moscot", 2),
    # EuroOptica
    ("MYKITA", "https://www.eurooptica.com/collections/mykita", 3),
    ("Ic! Berlin", "https://www.eurooptica.com/collections/ic-berlin", 2),
    ("Silhouette", "https://www.eurooptica.com/collections/silhouette", 2),
    ("Cazal", "https://www.eurooptica.com/collections/cazal", 3),
    ("Andy Wolf", "https://www.eurooptica.com/collections/andy-wolf", 4),
    ("Gotti", "https://www.eurooptica.com/collections/gotti", 5),
    ("BLACKFIN", "https://www.eurooptica.com/collections/blackfin", 3),
    ("Paul Smith", "https://www.eurooptica.com/collections/paul-smith", 2),
    ("PRODESIGN", "https://www.eurooptica.com/collections/prodesign-denmark", 2),
    ("Anne & Valentin", "https://www.eurooptica.com/collections/anne-valentin", 2),
    ("Matsuda", "https://www.eurooptica.com/collections/matsuda", 2),
    ("Masunaga", "https://www.eurooptica.com/collections/masunaga", 2),
    ("Cutler and Gross", "https://www.eurooptica.com/collections/cutler-gross", 2),
    ("Linda Farrow", "https://www.eurooptica.com/collections/linda-farrow", 2),
    # Fashion Eyewear
    ("Cartier", "https://www.fashioneyewear.com/collections/cartier", 3),
    ("Gucci", "https://www.fashioneyewear.com/collections/gucci", 4),
    ("Saint Laurent", "https://www.fashioneyewear.com/collections/saint-laurent", 3),
    ("Prada", "https://www.fashioneyewear.com/collections/prada", 3),
    ("Miu Miu", "https://www.fashioneyewear.com/collections/miu-miu-glasses", 2),
    ("Miu Miu", "https://www.fashioneyewear.com/collections/miu-miu-sunglasses", 2),
    ("Ray-Ban", "https://www.fashioneyewear.com/collections/ray-ban", 3),
    ("MYKITA", "https://www.fashioneyewear.com/collections/mykita", 2),
    ("Tom Ford", "https://www.fashioneyewear.com/collections/tom-ford", 3),
    ("Dior", "https://www.fashioneyewear.com/collections/dior", 2),
    ("Celine", "https://www.fashioneyewear.com/collections/celine", 2),
    ("Linda Farrow", "https://www.fashioneyewear.com/collections/linda-farrow", 2),
    ("Paul Smith", "https://www.fashioneyewear.com/collections/paul-smith", 2),
    ("Montblanc", "https://www.fashioneyewear.com/collections/montblanc", 2),
    ("Max Mara", "https://www.fashioneyewear.com/collections/maxmara-glasses", 2),
    ("Oakley", "https://www.fashioneyewear.com/collections/oakley", 2),
    ("Gotti", "https://www.fashioneyewear.com/collections/gotti", 2),
    ("Andy Wolf", "https://www.fashioneyewear.com/collections/andy-wolf-glasses", 2),
    ("Silhouette", "https://www.fashioneyewear.com/collections/silhouette-glasses", 2),
    ("Cutler and Gross", "https://www.fashioneyewear.com/collections/cutler-and-gross", 2),
    # Paris Lunetier
    ("Cartier", "https://parislunetier.com/collections/cartier", 3),
    ("Gucci", "https://parislunetier.com/collections/gucci", 2),
    ("Saint Laurent", "https://parislunetier.com/collections/saint-laurent", 2),
    ("Prada", "https://parislunetier.com/collections/prada", 2),
    ("Miu Miu", "https://parislunetier.com/collections/miu-miu", 2),
    ("MYKITA", "https://parislunetier.com/collections/mykita", 2),
    ("Cazal", "https://parislunetier.com/collections/cazal", 2),
    ("John Dalia", "https://parislunetier.com/collections/john-dalia", 2),
    ("Masunaga", "https://parislunetier.com/collections/masunaga", 2),
    ("Montblanc", "https://parislunetier.com/collections/montblanc", 2),
    ("Ray-Ban", "https://parislunetier.com/collections/ray-ban", 2),
    # Seen UK & Leidmann
    ("Kuboraum", "https://www.seen.co.uk/collections/kuboraum", 2),
    ("Anne & Valentin", "https://www.seen.co.uk/collections/anne-et-valentin", 2),
    ("Cutler and Gross", "https://www.seen.co.uk/collections/cutler-and-gross", 2),
    ("MYKITA", "https://www.seen.co.uk/collections/mykita", 2),
    ("Cartier", "https://www.leidmann.com/collections/cartier", 2),
    ("Kuboraum", "https://www.leidmann.com/collections/kuboraum", 2),
    ("Matsuda", "https://www.leidmann.com/collections/matsuda", 2),
    ("John Dalia", "https://www.leidmann.com/collections/john-dalia", 2),
]

RU_TO_EN_COLORS: Dict[str, List[str]] = {
    "черный": ["black", "blk", "noir", "001", "01a", "1ab"],
    "золотой": ["gold", "gld", "champagne", "peony gold", "yellow gold", "antique gold", "brushed gold", "gp", "ag", "bg"],
    "золотистый": ["gold", "gld", "champagne"],
    "серебряный": ["silver", "slv", "palladium", "ruthenium", "platinum", "chrome", "as", "pw", "bs", "sls", "pp"],
    "черепаховый": ["tortoise", "tort", "havana", "turtle", "demi", "tokyo tortoise"],
    "гавана": ["havana", "tortoise", "tort"],
    "коричневый": ["brown", "brn", "espresso", "coffee", "caramel", "cognac", "tan", "whiskey", "toffee", "chestnut", "brm"],
    "кофейный": ["coffee", "brown", "espresso", "mocha"],
    "серый": ["grey", "gray", "gry", "smoke", "graphite", "gunmetal", "gun", "pewter", "slate", "ash", "storm"],
    "графитный": ["graphite", "gunmetal", "dark grey", "anthracite", "ruthenium"],
    "синий": ["blue", "navy", "indigo", "cobalt", "denim", "ocean", "marine", "azure"],
    "голубой": ["light blue", "sky", "azure", "blue", "ice", "aqua"],
    "бирюзовый": ["turquoise", "aqua", "teal", "mint", "cyan", "green"],
    "зеленый": ["green", "grn", "olive", "sage", "khaki", "emerald", "forest", "bottle green", "bgn", "menta"],
    "хаки": ["khaki", "olive", "green", "moss", "military"],
    "оливковый": ["olive", "khaki", "sage", "green"],
    "розовый": ["pink", "rose", "blush", "peach", "coral", "fuchsia"],
    "розовое золото": ["rose gold", "rg", "peony gold", "copper"],
    "красный": ["red", "burgundy", "crimson", "bordeaux", "wine", "cherry", "scarlet", "bor"],
    "бордовый": ["burgundy", "bordeaux", "wine", "maroon", "bor"],
    "желтый": ["yellow", "amber", "honey", "ochre", "mustard", "citrine", "blonde"],
    "оранжевый": ["orange", "mandarin", "mandarino", "amber", "terracotta", "coral"],
    "фиолетовый": ["purple", "violet", "plum", "lavender", "lilac", "amethyst"],
    "сиреневый": ["lilac", "lavender", "violet", "purple", "mauve"],
    "белый": ["white", "ivory", "milk", "cream", "bone", "chalk"],
    "молочный": ["milk", "cream", "ivory", "bone", "off-white"],
    "бежевый": ["beige", "nude", "sand", "taupe", "champagne", "ecru", "stone"],
    "шампань": ["champagne", "beige", "crystal", "gold", "glb"],
    "прозрачный": ["clear", "crystal", "transparent", "trans", "ice"],
    "бронзовый": ["bronze", "antique gold", "copper", "brown", "ag", "brm"],
    "античный": ["antique", "ag", "as"],
}


def norm_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def english_color_keywords(color_ru: str) -> List[str]:
    kws: List[str] = []
    for part in re.split(r"[,/;]+", (color_ru or "").lower()):
        part = part.strip()
        if not part:
            continue
        for ru_k, en_list in RU_TO_EN_COLORS.items():
            if ru_k in part:
                for e in en_list:
                    if e not in kws:
                        kws.append(e)
    return kws


def fetch_collection_entries(task: Tuple[str, str, int, bool]) -> List[Dict[str, Any]]:
    brand, base_url, max_pages, is_root = task
    records: List[Dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        url = f"{base_url}/products.json?limit=250&page={page}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=14, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.5)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=14, context=SSL_CTX) as resp:
                        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                except Exception:
                    break
            else:
                break
        except Exception:
            break
        prods = data.get("products") or []
        if not prods:
            break
        for p in prods:
            p_title = str(p.get("title") or "").strip()
            p_handle = str(p.get("handle") or "").strip()
            p_vendor = str(p.get("vendor") or "").strip()
            p_tags = " ".join(p.get("tags") or []) if isinstance(p.get("tags"), list) else str(p.get("tags") or "")
            p_imgs = [im.get("src") for im in (p.get("images") or []) if isinstance(im, dict) and im.get("src")]
            default_img = p_imgs[0] if p_imgs else ""

            variants = p.get("variants") or []
            if not variants and default_img:
                records.append(
                    {
                        "brand": brand,
                        "source": base_url,
                        "title": p_title,
                        "handle": p_handle,
                        "vendor": p_vendor,
                        "tags": p_tags,
                        "var_sku": "",
                        "var_title": "",
                        "img": default_img,
                        "multi_variant": False,
                    }
                )
                continue

            # Проверяем, есть ли у вариантов собственные картинки (варианты = разные цвета)
            # или у всех вариантов нет featured_image (варианты = размеры S/M/L или опции линз одного цвета, как на RSF / GoodSeeCo)
            any_var_has_img = any(
                isinstance(v.get("featured_image"), dict) and v["featured_image"].get("src")
                for v in variants
            )
            for v in variants:
                v_sku = str(v.get("sku") or "").strip()
                v_title = str(v.get("title") or "").strip()
                f_img = ""
                if isinstance(v.get("featured_image"), dict):
                    f_img = str(v["featured_image"].get("src") or "").strip()
                img_url = f_img if any_var_has_img else default_img
                if not img_url:
                    continue
                records.append(
                    {
                        "brand": brand,
                        "source": base_url,
                        "title": p_title,
                        "handle": p_handle,
                        "vendor": p_vendor,
                        "tags": p_tags,
                        "var_sku": v_sku,
                        "var_title": v_title,
                        "img": img_url,
                        "multi_variant": any_var_has_img,
                    }
                )
        if len(prods) < 250:
            break
        time.sleep(0.35)
    return records


def load_or_build_catalog_cache(force_refresh: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    if CACHE_JSON.is_file() and not force_refresh:
        try:
            raw = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw:
                return raw
        except Exception:
            pass

    tasks: List[Tuple[str, str, int, bool]] = []
    for brand, url, pages in OFFICIAL_BRAND_STORES:
        tasks.append((brand, url, pages, True))
    for brand, url, pages in MULTIBRAND_COLLECTIONS:
        tasks.append((brand, url, pages, False))

    # Группируем задачи по домену, чтобы не вызывать 429 Too Many Requests на одном сайте
    by_domain: Dict[str, List[Tuple[str, str, int, bool]]] = {}
    for t in tasks:
        host = urllib.parse.urlparse(t[1]).netloc.lower()
        by_domain.setdefault(host, []).append(t)

    def run_domain_queue(domain_tasks: List[Tuple[str, str, int, bool]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for task in domain_tasks:
            out.extend(fetch_collection_entries(task))
            time.sleep(0.3)
        return out

    print(f"Выгрузка каталогов из {len(tasks)} коллекций ({len(by_domain)} доменов параллельно)...", flush=True)
    by_brand: Dict[str, List[Dict[str, Any]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(by_domain)) as ex:
        for recs in ex.map(run_domain_queue, by_domain.values()):
            for r in recs:
                b = r["brand"].lower()
                by_brand.setdefault(b, []).append(r)

    total_recs = sum(len(v) for v in by_brand.values())
    print(f"Собрано записей вариантов с фото: {total_recs} по {len(by_brand)} брендам", flush=True)
    CACHE_JSON.write_text(json.dumps(by_brand, ensure_ascii=False), encoding="utf-8")
    return by_brand


def normalize_and_save_image(raw_bytes: bytes, dst_path: Path) -> Optional[str]:
    """Проверяет изображение, укладывает на студийный холст 640x800 и возвращает MD5 контента."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as im:
            im = im.convert("RGBA")
            w, h = im.size
            if w < 180 or h < 90:
                return None

            bg = Image.new("RGB", (w, h), (255, 255, 255))
            bg.paste(im, mask=im.split()[3])

            canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (255, 255, 255))
            scale = min((CANVAS_W * 0.90) / w, (CANVAS_H * 0.84) / h)
            nw = max(1, int(round(w * scale)))
            nh = max(1, int(round(h * scale)))
            resized = bg.resize((nw, nh), Image.Resampling.LANCZOS)
            ox = (CANVAS_W - nw) // 2
            oy = (CANVAS_H - nh) // 2
            canvas.paste(resized, (ox, oy))

            buf = io.BytesIO()
            canvas.save(buf, "JPEG", quality=88, optimize=True)
            jpg_bytes = buf.getvalue()
            md5 = hashlib.md5(jpg_bytes).hexdigest()
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_bytes(jpg_bytes)
            return md5
    except Exception:
        return None


def download_bytes(url: str) -> Optional[bytes]:
    if not url:
        return None
    u = url.strip()
    if u.startswith("//"):
        u = "https:" + u
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            return resp.read()
    except Exception:
        return None


def strip_accents(s: str) -> str:
    return (
        s.replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("É", "E")
        .replace("È", "E")
        .replace("ö", "o")
        .replace("Ö", "O")
        .replace("ü", "u")
        .replace("Ü", "U")
        .replace("ä", "a")
        .replace("Ä", "A")
    )


def has_token(text: str, token: str) -> bool:
    """Проверяет вхождение токена как отдельного слова/числа (чтобы '01' не матчил '010', а '889' не матчил '1889')."""
    if not token:
        return False
    t_clean = strip_accents(token.lower())
    txt_clean = strip_accents(text.lower())
    pat = r"(?<![a-z0-9])" + re.escape(t_clean) + r"(?![a-z0-9])"
    return bool(re.search(pat, txt_clean))


EUROOPTICA_SKU_PREFIXES: Dict[str, Tuple[str, ...]] = {
    "mykita": ("myk ", "mykita"),
    "gotti": ("got ", "gotti"),
    "andy wolf": ("anw ", "andy"),
    "blackfin": ("blf ", "bf", "blackfin"),
    "paul smith": ("psm ", "psop", "pssun", "paul"),
    "ic! berlin": ("icb ", "ic!", "ic-berlin", "ic berlin"),
    "cazal": ("caz ", "cazal", "mod"),
    "silhouette": ("slh ", "silhouette", "tma"),
    "prodesign": ("prd ", "prodesign"),
    "masunaga": ("msng", "masunaga", "gms"),
    "matsuda": ("mts ", "matsuda", "m3", "m2", "m1", "m5", "10", "28"),
    "cutler and gross": ("cg", "cutler", "gfsn"),
    "linda farrow": ("lfl", "linda"),
}

OTHER_BRAND_MARKERS: Dict[str, Tuple[str, ...]] = {
    "dior": ("cd40", "dior", "30montaigne", "diorsignature", "diorblacksuit"),
    "celine": ("cl40", "cl50", "celine"),
    "gigi studios": ("gigi studios", "gigi-studios"),
    "jacques marie mage": ("jacques marie mage", "jacques-marie-mage"),
    "serengeti": ("serengeti",),
    "jf rey": ("jf rey", "jfr jf"),
    "kreuzbergkinder": ("kk jane", "kreuzbergkinder"),
}


def is_valid_brand_record(brand: str, r: Dict[str, Any]) -> bool:
    """Строгая проверка, что запись из кэша действительно принадлежит бренду (без примеси рекомендаций и чужих брендов)."""
    b_low = brand.strip().lower()
    title_low = strip_accents(str(r.get("title") or "").lower())
    handle_low = strip_accents(str(r.get("handle") or "").lower())
    vsku_low = strip_accents(str(r.get("var_sku") or "").lower().strip())
    vtitle_low = strip_accents(str(r.get("var_title") or "").lower())
    vendor_low = strip_accents(str(r.get("vendor") or "").lower())
    img_low = str(r.get("img") or "").lower()
    src_low = str(r.get("source") or "").lower()

    # 1. GoodSeeCo имеет формат title "Brand - Model (Color)"
    if "goodseeco.com" in src_low and " - " in title_low:
        gs_brand = norm_alnum(title_low.split(" - ", 1)[0])
        b_norm = norm_alnum(b_low.replace("eyehunters", ""))
        if b_norm and b_norm not in gs_brand and gs_brand not in b_norm:
            return False

    # 2. Проверка на явные маркеры чужих брендов в SKU/title/URL картинки
    blob_check = f"{title_low} {vsku_low} {vtitle_low} {vendor_low} {img_low}"
    for other_b, markers in OTHER_BRAND_MARKERS.items():
        if other_b != b_low:
            if any(m in blob_check for m in markers):
                return False

    # 3. Защита от чужих префиксов SKU EuroOptica (например GOT / KK / JFR внутри Ic! Berlin)
    if vsku_low.startswith(("got ", "anw ", "blf ", "psm ", "myk ", "kk ", "jfr ", "msng-")):
        allowed_prefixes = EUROOPTICA_SKU_PREFIXES.get(b_low, ())
        if not allowed_prefixes or not vsku_low.startswith(allowed_prefixes):
            return False

    # 4. Защита от HTML-скрапинга блока "You May Also Like" на FashionEyewear / EuroOptica
    if src_low in ("https://www.fashioneyewear.com", "https://www.eurooptica.com"):
        if "fashioneyewear.com" in src_low and vsku_low:
            # На FashionEyewear у карусели рекомендаций var_sku — это полный баркод другой модели (CD40231I..., CL40347U...)
            sku_head = norm_alnum(vsku_low)[:6]
            if sku_head and sku_head not in norm_alnum(handle_low + " " + title_low):
                return False
        if "eurooptica.com" in src_low:
            # На EuroOptica handle страницы должен перекликаться с var_sku или URL картинки
            b_words = set(re.findall(r"[a-z0-9]+", b_low)) | {"eyeglasses", "sunglasses", "optical", "frames", "men", "women", "unisex"}
            h_tokens = [t for t in re.findall(r"[a-z0-9]+", handle_low) if len(t) >= 3 and t not in b_words]
            if h_tokens:
                sku_img_blob = norm_alnum(vsku_low + " " + img_low)
                if not any(ht in sku_img_blob for ht in h_tokens):
                    return False

    return True


def match_record_for_item(item: Dict[str, Any], records: List[Dict[str, Any]]) -> Optional[str]:
    """
    Ищет 100% точное совпадение БРЕНДА, МОДЕЛИ И КОДА ЦВЕТА/ЛИНЗЫ в записях для данного бренда.
    Никаких угадываний по словесному цвету при наличии артикула цвета и никаких частичных кодов.
    """
    brand = item["brand"].strip()
    b_low = brand.lower()
    model = item["model"].strip()
    m_up = model.upper()
    color_ru = item.get("color", "")
    en_colors = english_color_keywords(color_ru)

    valid_records = [r for r in records if is_valid_brand_record(brand, r)]
    if not valid_records:
        return None

    def rec_blob(r: Dict[str, Any]) -> str:
        return strip_accents(f"{r['title']} | {r['handle']} | {r['var_sku']} | {r['var_title']}".lower())

    # 1. LeSpecs: 7-значный артикул цвета (например, ENTANGLE 1926570 -> LWF1926570 / LSU1926570)
    if b_low == "lespecs":
        m_sku = re.search(r"\b(\d{7})\b", m_up)
        if m_sku:
            code7 = m_sku.group(1)
            for r in valid_records:
                if code7 in r["var_sku"] or code7 in r["handle"] or code7 in r["title"]:
                    return r["img"]
            return None
        # Если 7-значного кода нет в названии модели (например, BANDWAGON, OUTTA LOVE), требуем точное имя модели + английский цвет
        base_name = re.sub(r"\b\d+\b", "", m_up).strip().lower()
        if len(base_name) >= 4 and en_colors:
            for r in valid_records:
                t_low = r["title"].lower()
                if has_token(t_low, base_name) and any(has_token(t_low + " " + r["var_title"].lower(), c) for c in en_colors):
                    return r["img"]
        return None

    # 2. Kaleos Eyehunters: "Unwin Big C-002" -> точное имя модели + SKU кончается на 2-значный код цвета ("02") или "c-002"
    if "kaleos" in b_low:
        m_kal = re.match(r"^(.+?)\s+C-?0*(\d{1,3})\b", model, flags=re.I)
        if m_kal:
            m_name = m_kal.group(1).strip().lower()
            c_num = int(m_kal.group(2))
            c_2d = f"{c_num:02d}"
            c_code = f"c-{c_num:03d}"
            for r in valid_records:
                t_low = r["title"].strip().lower()
                sku_low = r["var_sku"].strip().lower()
                # Граница слова обязательна, чтобы "Moon" не матчил "Mooney"
                if t_low == m_name or t_low.startswith(m_name + " ") or has_token(t_low, m_name):
                    if not t_low.startswith(m_name) or (len(t_low) > len(m_name) and t_low[len(m_name)].isalnum()):
                        continue
                    if (re.fullmatch(r"[a-z]\d{6}", sku_low) and sku_low.endswith(c_2d)) or has_token(rec_blob(r), c_code):
                        return r["img"]
        return None

    # 3. RETROSUPERFUTURE: строго 3-символьный код варианта ("B3L Amata Black" -> var_sku == "B3L")
    if b_low == "retrosuperfuture":
        m_rsf = re.match(r"^([A-Z0-9]{3})\s+(.+)$", m_up)
        if m_rsf:
            code3 = m_rsf.group(1).lower()
            for r in valid_records:
                if r["var_sku"].strip().lower() == code3 or has_token(r["var_sku"].lower(), code3):
                    return r["img"]
        return None

    # 4. Matsuda: "2809H-V2-AG-BGN", "M3169 SG AG", "M3123 SG RTM-MBK,55"
    if b_low == "matsuda":
        m_clean = re.sub(r"(?:[, ]\s*\d{2}|\b\d{2}[/-]\d{2}(?:[/-]\d{3})?)\b", "", m_up).strip()
        m_base = re.match(r"^([A-Z0-9]+(?:-V\d+)?)", m_clean)
        if not m_base:
            return None
        base_code = m_base.group(1).lower()
        rest = m_clean[m_base.end():].strip(" -")
        is_sg = bool(re.search(r"\bSG\b", m_up))
        is_rx = bool(re.search(r"\bRX\b", m_up))
        rest_tokens = [
            t.lower()
            for t in re.split(r"[\s,-]+", rest)
            if t and t.upper() not in ("SG", "RX", "OPT", "SUN", "V2", "I", "II") and not re.fullmatch(r"\d{2}", t)
        ]
        if not rest_tokens:
            return None
        for r in valid_records:
            blob = rec_blob(r)
            if not has_token(blob, base_code):
                continue
            # Не путаем M3023 с M3023-V2
            if "-v2" not in base_code and f"{base_code}-v2" in blob:
                continue
            if is_sg and "rx" in blob and "sg" not in blob and "sun" not in blob:
                continue
            if is_rx and "sg" in blob and "rx" not in blob and "optical" not in blob:
                continue
            if all(has_token(blob, tok) for tok in rest_tokens):
                return r["img"]
        return None

    # 5. Cazal: "Mod. 889 col. 002", "Mod. 757/3 col.002", "Mod. 683/3 col.003"
    if b_low == "cazal":
        m_mod = re.search(r"(?:MOD\.?\s*)?0*(\d{3,4})(?:/\d+)?", m_up)
        m_col = re.search(r"(?:COL\.?\s*|C\.?\s*)(\d{3})\b", m_up)
        if not m_col:
            m_col = re.search(r"\b(\d{3})\b(?!.*\b\d{3}\b)", m_up)
        if m_mod and m_col:
            mod_num = m_mod.group(1).lower()
            col_num = m_col.group(1).lower()
            for r in valid_records:
                t_blob = f"{r['title']} {r['handle']}".lower()
                v_blob = f"{r['var_sku']} {r['var_title']} {r['title']} {r['handle']}".lower()
                if (has_token(t_blob, mod_num) or has_token(t_blob, f"0{mod_num}")) and (
                    has_token(v_blob, col_num) or f"{mod_num}{col_num}" in norm_alnum(v_blob)
                ):
                    return r["img"]
        return None

    # 6. Linda Farrow: "LFL-1131 C10", "LFL-1455 C01", "Vandergoot C2", "Kostich C4"
    if b_low == "linda farrow":
        m_c = re.search(r"\bC0*(\d{1,2})\b", m_up)
        if not m_c:
            return None
        c_num = m_c.group(1)
        base_part = re.sub(r"\bLFL[-\s]*", "", m_up[:m_c.start()]).strip().lower()
        if not base_part:
            return None
        for r in valid_records:
            blob = rec_blob(r)
            sku_norm = norm_alnum(r["var_sku"] + " " + r["handle"] + " " + r["title"])
            if has_token(blob, base_part) or f"lfl{base_part}" in sku_norm:
                if (
                    has_token(blob, f"c{c_num}")
                    or has_token(blob, f"c0{c_num}")
                    or f"{base_part}c{c_num}" in sku_norm
                    or f"{base_part}c0{c_num}" in sku_norm
                ):
                    return r["img"]
        return None

    # 7. AHLEM: "Paris 02 Ruthenium", "Turbigo Peony Gold/Peach", "Bagnolet Champagne"
    if b_low == "ahlem":
        parts = m_up.split()
        if not parts:
            return None
        m_name = parts[0].lower()
        if m_name == "paris" and len(parts) >= 2 and parts[1].isdigit():
            m_name = f"paris {parts[1]}"
        color_part = model[len(m_name):].strip().lower()
        color_words = [w for w in re.split(r"[\s/,-]+", color_part) if len(w) >= 4 and w not in ("rim", "sun", "opt")]
        if not color_words:
            return None
        is_opt_item = item.get("type") == "Оправы" or "OPT" in m_up
        for r in valid_records:
            if is_opt_item and r["var_sku"].upper().startswith(("SM", "SA")):
                continue
            t_low = strip_accents(r["title"].lower())
            v_low = strip_accents(f"{r['var_title']} {r['title']}".lower())
            if has_token(t_low, m_name) and all(has_token(v_low, w) for w in color_words[:2]):
                return r["img"]
        return None

    # 8. Eyepetizer: "Colonial C.1-OP-26", "Odaiba C.1-65", "Odaiba C.6-OP-63" -> строго полный код C.1-65!
    if b_low == "eyepetizer":
        m_ep = re.match(r"^([A-Za-z]+)\s+(?:OPT\s+)?C\.?([A-Z0-9-]+)", m_up)
        if m_ep:
            m_name = m_ep.group(1).lower()
            c_full = m_ep.group(2).lower()
            c_norm = norm_alnum(f"c{c_full}")
            for r in valid_records:
                blob = rec_blob(r)
                if has_token(blob, m_name) and (
                    f"c.{c_full}" in blob
                    or f"c-{c_full}" in blob
                    or f"c {c_full}" in blob
                    or c_norm in norm_alnum(blob)
                ):
                    return r["img"]
        return None

    # 9. John Dalia: "Jared C107", "Jared C301", "Eddie C107"
    if b_low == "john dalia":
        m_jd = re.match(r"^([A-Za-z0-9]+)\s+(C\d{3})\b", m_up)
        if m_jd:
            m_name, c_code = m_jd.group(1).lower(), m_jd.group(2).lower()
            for r in valid_records:
                blob = rec_blob(r)
                if has_token(blob, m_name) and has_token(blob, c_code):
                    return r["img"]
        return None

    # 10. Cutler and Gross: "CGOP 1405-47-02", "CGSN 1396-52-02", "CGOP 1394-55-13", "GFSN 003-53-T5"
    if b_low == "cutler and gross":
        m_cg = re.search(r"^(?:([A-Z]{2}(?:OP|SN))\s+)?0*(\d{3,4})[-\s]+\d{2}[-\s]+([A-Z0-9]{2})\b", m_up)
        if m_cg:
            pref_cg = (m_cg.group(1) or "").lower()
            mod4 = m_cg.group(2).lower()
            col2 = m_cg.group(3).lower()
            for r in valid_records:
                v_str = f"{r['var_sku']} {r['title']} {r['handle']}".lower()
                if pref_cg and pref_cg.endswith("sn") and ("op-" in v_str or "opticals" in v_str):
                    continue
                if pref_cg and pref_cg.endswith("op") and ("sn-" in v_str or "sunglasses" in v_str):
                    continue
                if re.search(r"\b0*" + re.escape(mod4) + r"[-\s]+\d{2}[-\s]+" + re.escape(col2) + r"\b", v_str):
                    return r["img"]
        return None

    # 11. Kuboraum: "H80 SG RH", "H80 SG SI", "E21 BM", "P2 BS"
    if b_low == "kuboraum":
        tokens = [t for t in re.split(r"[\s-]+", m_up) if t and t not in ("SG", "RX", "OPT", "SUN", "MASK")]
        if len(tokens) >= 2:
            mod_tok = tokens[0].lower()
            col_toks = [t.lower() for t in tokens[1:] if not re.fullmatch(r"\d{2}/\d{2}", t)]
            for r in valid_records:
                blob = rec_blob(r)
                if has_token(blob, mod_tok) and col_toks and all(has_token(blob, c) for c in col_toks[:2]):
                    return r["img"]
        return None

    # 11b. Dita: "DTX506-50-02 RGD", "MACH EIGHT DTS400-A-02", "METAMAT DTS526-59-02 RGD"
    if b_low == "dita":
        m_dita = re.search(r"\b(DT[A-Z]?\d{3,4}|DRX-\d{4}[A-Z]?|DLX\s*\d{3})(?:[-\s]+(\d{2}|[A-Z]))?(?:[-\s]+(\d{2}|[A-Z]{2,3}))?", m_up)
        if m_dita:
            base_d = norm_alnum(m_dita.group(1))
            g2 = (m_dita.group(2) or "").lower()
            g3 = (m_dita.group(3) or "").lower()
            # Код цвета у Dita — это обычно 01/02/03 во 2-й или 3-й группе
            col_d = g3 if (g2.isdigit() and int(g2) >= 45 and g3) else (f"{g2}-{g3}" if g2 and g3 else g2)
            for r in valid_records:
                v_blob = f"{r['var_sku']} {r['handle']} {r['title']}".lower()
                if base_d in norm_alnum(v_blob) and col_d and has_token(v_blob, col_d):
                    return r["img"]
        return None

    # 11c. Leisure Society: "LEpine 12K Silver", "Meursault 12K WHT GOLD"
    if b_low == "leisure society":
        parts = m_up.split()
        if len(parts) >= 2:
            m_name = norm_alnum(parts[0])
            rest_up = " ".join(parts[1:])
            for r in valid_records:
                t_norm = norm_alnum(strip_accents(r["title"]))
                v_blob = strip_accents(f"{r['var_title']} {r['var_sku']}".lower())
                if m_name in t_norm:
                    if "12K" in rest_up and "SILVER" in rest_up and "12k" in v_blob and ("silver" in v_blob or "slv" in v_blob):
                        return r["img"]
                    if "12K" in rest_up and "WHT" in rest_up and "12k" in v_blob and ("white gold" in v_blob or "whtgld" in v_blob):
                        return r["img"]
        return None

    # 11d. Masunaga: "Orchid 41", "Empire 1 35", "Chord A 41", "GMS109 13"
    if b_low == "masunaga":
        parts = [p.lower() for p in m_up.split() if p]
        if len(parts) >= 2:
            for r in valid_records:
                blob = rec_blob(r)
                if all(has_token(blob, p) for p in parts):
                    return r["img"]
        return None

    # 12. MYKITA: "CANYON, col.301", "CANYON, col.325", "Edison col. 255", "Reeves col.712" -> строго по коду col.XXX!
    if b_low == "mykita":
        m_clean = re.sub(r",?\s*(?:col\.?|c\.)\s*([a-z0-9]+).*$", "", model, flags=re.I).strip().lower()
        m_col = re.search(r"(?:col\.?|c\.)\s*([a-z0-9]+)", model, flags=re.I)
        col_code = m_col.group(1).lower() if m_col else ""
        if not m_clean or not col_code:
            return None
        col_padded = col_code.zfill(3) if col_code.isdigit() else col_code
        for r in valid_records:
            blob = rec_blob(r)
            sku_norm = norm_alnum(r["var_sku"])
            if has_token(blob, m_clean):
                if (
                    has_token(blob, col_code)
                    or has_token(blob, col_padded)
                    or has_token(blob, f"c{col_code}")
                    or has_token(blob, f"c{col_padded}")
                    or f"{norm_alnum(m_clean)}{col_padded}" in sku_norm
                    or f"{norm_alnum(m_clean)}c{col_padded}" in sku_norm
                ):
                    return r["img"]
        return None

    # 13. Cartier / Gucci / Saint Laurent / Tom Ford / Celine / Balenciaga / Montblanc / Max Mara / Tod's / ZILLI / Dior
    if b_low in ("cartier", "gucci", "saint laurent", "tom ford", "celine", "balenciaga", "montblanc", "max mara", "tod's", "zilli", "dior"):
        # Убираем размер или букву M/L/S в конце (например, "55", "54/18", "M")
        m_trim = re.sub(r"\s+(?:\d{2}(?:/\d{2})?|[SML])$", "", m_up).strip()
        parts = m_trim.split()
        if len(parts) < 2:
            return None
        col_code = parts[-1].lower()
        if b_low == "cartier":
            m_ct = re.search(r"(CT\s*\d{4}[SO]?)", m_trim)
            mod_codes = [norm_alnum(m_ct.group(1))] if m_ct else [norm_alnum(" ".join(parts[:-1]))]
        elif b_low == "gucci":
            m_gg = re.search(r"(GG\s*\d{4}[A-Z]{0,2})", m_trim)
            mod_codes = [norm_alnum(m_gg.group(1))] if m_gg else [norm_alnum(" ".join(parts[:-1]))]
        elif b_low == "saint laurent":
            m_sl = re.search(r"(SL\s*[A-Z]?\d{2,4}[A-Z]?)", m_trim)
            mod_codes = [norm_alnum(m_sl.group(1))] if m_sl else [norm_alnum(" ".join(parts[:-1]))]
        elif b_low == "tom ford":
            m_tf = re.search(r"(?:TF|FT)\s*0*(\d{3,4}(?:-B)?)", m_trim)
            if m_tf:
                num = norm_alnum(m_tf.group(1))
                mod_codes = [f"tf{num}", f"ft{num}", f"tf0{num}", f"ft0{num}"]
            else:
                mod_codes = [norm_alnum(" ".join(parts[:-1]))]
        elif b_low == "celine":
            m_cl = re.search(r"(CL\s*\d{4,5}[A-Z]*)", m_trim)
            mod_codes = [norm_alnum(m_cl.group(1))] if m_cl else [norm_alnum(" ".join(parts[:-1]))]
        else:
            mod_codes = [norm_alnum(" ".join(parts[:-1]))]

        # Строго требуем совпадения И кода модели, И кода цвета (никакого fallback по английским словам цвета!)
        is_sl_opt = b_low == "saint laurent" and "OPT" in parts
        for r in valid_records:
            if is_sl_opt:
                src_title = f"{r.get('source','')} {r['title']} {r['handle']}".lower()
                if "sunglasses" in src_title and "opt" not in r["title"].lower() and "eyeglasses" not in src_title:
                    continue
            blob = rec_blob(r)
            blob_norm = norm_alnum(blob)
            if any(mc in blob_norm for mc in mod_codes):
                if has_token(blob, col_code) or any(f"{mc}{norm_alnum(col_code)}" in blob_norm for mc in mod_codes):
                    return r["img"]
        return None

    # 14. Prada & Miu Miu: "SPR C53 1BC-70B", "VPR A55 1AB-1O1", "SMU 54Y 1BC-10F"
    if b_low in ("prada", "miu miu"):
        m_pm = re.match(r"^([SV]?(?:PR|MU))\s*([A-Z0-9]{2,4})\s+([A-Z0-9]{3})(?:-([A-Z0-9]{3}))?", m_up)
        if m_pm:
            prefix = m_pm.group(1)
            code = m_pm.group(2).lower()
            col_frame = m_pm.group(3).lower()
            col_lens = (m_pm.group(4) or "").lower()
            # Оптическая оправа (VPR / VMU) не должна матчить солнцезащитные очки (SPR / SMU) и наоборот!
            is_opt = prefix.startswith("V")
            if b_low == "prada":
                aliases = [f"vpr{code}", f"pr{code}v", f"0pr{code}v"] if is_opt else [f"spr{code}", f"pr{code}s", f"0pr{code}s"]
                forbid = ("spr", f"pr{code}s", "sunglasses") if is_opt else ("vpr", f"pr{code}v", "eyeglasses", "optical")
            else:
                aliases = [f"vmu{code}", f"mu{code}v", f"0mu{code}v"] if is_opt else [f"smu{code}", f"mu{code}s", f"0mu{code}s"]
                forbid = ("smu", f"mu{code}s", "sunglasses") if is_opt else ("vmu", f"mu{code}v", "eyeglasses", "optical")

            # В Prada/Miu Miu 0 и O в коде линзы (1O1 vs 101) часто взаимозаменяемы в каталогах
            full_cols = set()
            if col_lens:
                for l_var in {col_lens, col_lens.replace("o", "0"), col_lens.replace("0", "o")}:
                    full_cols.add(f"{col_frame}-{l_var}")
                    full_cols.add(f"{col_frame}{l_var}")
            else:
                full_cols.add(col_frame)

            for r in valid_records:
                blob = rec_blob(r)
                blob_norm = norm_alnum(blob)
                if any(fb in blob_norm or fb in blob for fb in forbid):
                    continue
                if any(a in blob_norm or f"pr{code}" in blob_norm or f"mu{code}" in blob_norm for a in aliases):
                    if any(fc in blob or fc.replace("-", "") in blob_norm for fc in full_cols):
                        return r["img"]
        return None

    # 15. Ray-Ban: "RB 3929 002/81", "RB 0316-S 6826/J5", "RB3447 col.919648 53", "RB2132 col.902-58 58"
    if b_low == "ray-ban":
        m_rb = re.match(r"^RB\s*0*(\d{3,4})(?:-?S)?\s+(?:COL\.?\s*)?([A-Z0-9]{3,6})(?:[/-]([A-Z0-9]{2}))?", m_up)
        if m_rb:
            num = m_rb.group(1)
            col_main = m_rb.group(2).lower()
            col_lens = (m_rb.group(3) or "").lower()
            aliases = [f"rb{num}", f"rb0{num}"]
            for r in valid_records:
                blob = rec_blob(r)
                blob_norm = norm_alnum(blob)
                if not any(a in blob_norm for a in aliases):
                    continue
                if col_lens:
                    # Если код линзы состоит из 2 цифр (например /58, /32, /71, /31), требуем явный разделитель / или -,
                    # чтобы размер оправы "902 58" (58мм) после склейки norm_alnum не превращался в "90258"
                    if col_lens.isdigit():
                        if f"{col_main}/{col_lens}" in blob or f"{col_main}-{col_lens}" in blob:
                            return r["img"]
                    else:
                        if (
                            f"{col_main}/{col_lens}" in blob
                            or f"{col_main}-{col_lens}" in blob
                            or f"{col_main}{col_lens}" in blob_norm
                        ):
                            return r["img"]
                else:
                    if has_token(blob, col_main) or col_main in blob_norm:
                        return r["img"]
        return None

    # 16. Gotti: "AMALIA GLB-PL", "DAGLEY GLT", "DABBIS GSB", "LANCE BLKM" -> строго весь код цвета!
    if b_low == "gotti":
        parts = m_up.split()
        if len(parts) >= 2:
            m_name = parts[0].lower()
            c_full = parts[1].lower()
            for r in valid_records:
                blob = rec_blob(r)
                if has_token(blob, m_name) and has_token(blob, c_full):
                    # Дополнительно проверяем, что после c_full в SKU нет дефиса с другим под-кодом (чтобы GLB не матчил GLB-PL, а BLKM — BLKM-GRA)
                    if "-" not in c_full and re.search(r"\b" + re.escape(c_full) + r"-[a-z0-9]+", blob):
                        continue
                    return r["img"]
        return None

    # 17. Ic! Berlin: "Rast Large Gun Metal", "Basti S. Marine Blue RX-Clear", "Aurelie Bronze"
    if b_low == "ic! berlin":
        m_clean = re.sub(r"\bRX[-\s]*Clear\b", "", model, flags=re.I)
        m_clean = re.sub(r"\b\d{2}(?:/\d{2})?\b", "", m_clean).strip()
        words = m_clean.split()
        if words:
            m_name = words[0].lower()
            color_start = 1
            if len(words) >= 2 and (len(words[1].rstrip(".")) == 1 or words[1].lower() in ("large", "small", "medium", "east", "west")):
                m_name = f"{words[0]} {words[1].rstrip('.')}".lower()
                color_start = 2
                if len(words) >= 3 and words[2].lower() in ("large", "small", "medium"):
                    color_start = 3
            color_tokens = [
                w.lower().rstrip(".,")
                for w in words[color_start:]
                if len(w.rstrip(".,")) >= 3 and w.lower() not in ("large", "small", "medium", "new")
            ]
            if not color_tokens:
                return None
            base_first = words[0].lower()
            for r in valid_records:
                t_low = f"{r['title']} {r['handle']}".lower()
                v_low = f"{r['var_title']} {r['var_sku']}".lower()
                if has_token(t_low, base_first):
                    if all(has_token(v_low, ct) for ct in color_tokens):
                        # Если цвет в модели ровно один (например "Black"), не берём двухцветные варианты вроде "Teak-Black" или "Black-Gold"
                        if len(color_tokens) == 1:
                            ct0 = color_tokens[0]
                            if re.search(r"[a-z]+[-\s/]+" + re.escape(ct0) + r"|" + re.escape(ct0) + r"[-\s/]+(?:gold|silver|gun|teak|blue|green|red|orange|brown|pearl)", r["var_title"].lower()):
                                continue
                        return r["img"]
        return None

    if b_low == "haffmans & neumeister":
        parts = m_up.split()
        if len(parts) >= 2:
            m_name = parts[0].lower()
            c_code = parts[1].lower()
            for r in valid_records:
                t_low = r["title"].lower()
                v_low = f"{r['var_title']} {r['var_sku']}".lower()
                if has_token(t_low, m_name) and has_token(v_low, c_code):
                    return r["img"]
        return None

    if b_low == "lunor":
        # Например: "A5 Mod. 612 01m", "A6 Mod.259 col.41", "XXV Mod. 2502 GP"
        m_mod = re.search(r"MOD\.?\s*(\d{2,4})", m_up)
        if m_mod:
            mod_num = m_mod.group(1).lower()
            tail = m_up[m_mod.end():].strip()
            tail_col = re.sub(r"^COL\.?\s*", "", tail).split()[0].lower() if tail else ""
            if tail_col:
                for r in valid_records:
                    blob = rec_blob(r)
                    if has_token(blob, mod_num) and has_token(blob, tail_col):
                        return r["img"]
        return None

    if b_low == "paul smith":
        # Например: "Abbott V2 001", "Adelaide V2 002", "Albemarle 004 53/19"
        clean_ps = re.sub(r"\s+\d{2}/\d{2}$", "", m_up).strip()
        parts = clean_ps.split()
        if len(parts) >= 2:
            m_name = parts[0].lower()
            ver = parts[1].lower() if parts[1].upper() in ("V1", "V2") else ""
            c_code = parts[-1].lower().zfill(3) if parts[-1].isdigit() else parts[-1].lower()
            for r in valid_records:
                blob = rec_blob(r)
                if not has_token(blob, m_name):
                    continue
                if ver == "v2" and "v1" in blob and "v2" not in blob:
                    continue
                if ver == "v1" and "v2" in blob and "v1" not in blob:
                    continue
                if has_token(blob, c_code) or has_token(blob, c_code.lstrip("0") or "0"):
                    return r["img"]
        return None

    if b_low in ("silhouette", "andy wolf", "prodesign", "blackfin"):
        # Извлекаем номер/имя модели и точный код цвета (без fallback по словесному цвету!)
        m_col = re.search(r"\b(?:col\.?|c\.)\s*([a-z0-9]+)", m_up, flags=re.I)
        if m_col:
            c_code = m_col.group(1).lower()
            m_head = re.sub(r"\b\d{2}[/-]\d{2}\b", "", m_up[:m_col.start()]).strip()
            mod_toks = [
                t.lower()
                for t in re.split(r"[\s._]+", m_head)
                if len(t) >= 3 and t.upper() not in ("MOD", "TMA", "MUST") and not re.match(r"^BF\d+$", t.upper())
            ]
            if mod_toks and c_code:
                for r in valid_records:
                    blob = rec_blob(r)
                    if all(has_token(blob, mt) for mt in mod_toks) and has_token(blob, c_code):
                        return r["img"]
        else:
            clean_m = re.sub(r"\s+\d{2}/\d{2}$", "", m_up).strip()
            parts = [p for p in re.split(r"[\s._-]+", clean_m) if p]
            if len(parts) >= 2:
                c_code = parts[-1].lower()
                main_mod = parts[0].lower()
                for r in valid_records:
                    blob = rec_blob(r)
                    if has_token(blob, main_mod) and has_token(blob, c_code):
                        return r["img"]
        return None

    if b_low == "oakley":
        m_ok = re.search(r"(OO\d{4}|OX\d{4})\s*-\s*(\d{4})", m_up)
        if m_ok:
            mod_code = m_ok.group(1).lower()
            col4 = m_ok.group(2).lower()
            for r in valid_records:
                blob = rec_blob(r)
                blob_norm = norm_alnum(blob)
                if has_token(blob, mod_code) and (has_token(blob, col4) or f"{mod_code}{col4}" in blob_norm):
                    return r["img"]
        return None

    if b_low == "polaroid":
        m_pl = re.search(r"PLD\s*([A-Z]?\d{4})[^\s]*\s+([A-Z0-9]{3})", m_up)
        if m_pl:
            mod_code, col3 = m_pl.group(1).lower(), m_pl.group(2).lower()
            for r in valid_records:
                blob = rec_blob(r)
                if has_token(blob, mod_code) and has_token(blob, col3):
                    return r["img"]
        return None

    return None


SKIP_HTML_SEARCH_BRANDS = {
    "refaced",
    "avo",
    "eyerepublic",
    "фиксики",
    "bosara",
    "spine",
    "brevno",
    "dakota smith",
    "inface",
    "swissflex",
    "trama",
    "plus eyewear",
    "avalanche",
    "r.g.b",
    "marcolin (винтаж)",
    "silhouette (винтаж)",
    "lespecs",
    "gast",
    "davidoff",
    "hackett london bespoke",
    "orgreen",
    "kreuzbergkinder",
    "versace",
    "tavat",
    "karen walker",
    "retrosuperfuture",
}


def build_base_search_query(brand: str, model: str) -> Tuple[str, str]:
    """Возвращает (короткий код модели для поиска, запрос с брендом)."""
    b = brand.strip().lower()
    m = model.strip()
    if b == "lespecs":
        base = re.sub(r"\b\d{6,8}\b", "", m).strip()
        return base, f"Le Specs {base}"
    if "kaleos" in b:
        base = re.sub(r"\s+C-?0*\d+.*$", "", m, flags=re.I).strip()
        return base, f"Kaleos {base}"
    if b == "mykita":
        base = re.sub(r",?\s*(?:col\.?|c\.)\s*[a-z0-9]+.*$", "", m, flags=re.I).strip()
        return base, f"Mykita {base}"
    if b in ("gucci", "saint laurent", "tom ford", "celine", "balenciaga", "montblanc", "max mara", "tod's", "zilli", "dior"):
        m_t = re.sub(r"\s+(?:\d{2}(?:/\d{2})?|[SML])$", "", m).strip()
        parts = m_t.split()
        base = " ".join(parts[:-1]) if len(parts) >= 2 else m_t
        if b == "gucci":
            m_gg = re.search(r"(GG\s*\d{4}[SO]?)", base.upper())
            if m_gg:
                base = m_gg.group(1).replace(" ", "")
        elif b == "saint laurent":
            m_sl = re.search(r"(SL\s*[A-Z]?\d{2,4}[A-Z]?)", base.upper())
            if m_sl:
                base = m_sl.group(1)
        elif b == "tom ford":
            m_tf = re.search(r"(?:TF|FT)\s*0*(\d{3,4})", base.upper())
            if m_tf:
                base = f"TF{m_tf.group(1)}"
        elif b == "celine":
            m_cl = re.search(r"(CL\s*\d{4,5}[A-Z]*)", base.upper())
            if m_cl:
                base = m_cl.group(1).replace(" ", "")
        return base, f"{brand} {base}"
    if b in ("prada", "miu miu"):
        m_pm = re.match(r"^([SV]?(?:PR|MU))\s*([A-Z0-9]{2,4})", m.upper())
        if m_pm:
            code2 = m_pm.group(2)
            short_prefix = "PR" if b == "prada" else "MU"
            raw_code = f"{short_prefix} {code2}"
            return raw_code, f"{brand} {raw_code}"
    if b == "ray-ban":
        m_rb = re.match(r"^RB\s*0*(\d{3,4}[A-Z]?)(-?S)?", m.upper())
        if m_rb:
            s_flag = "S" if m_rb.group(2) else ""
            code = f"RB {m_rb.group(1)}{s_flag}"
            return code, f"Ray-Ban {code}"
    if b == "cazal":
        m_cz = re.search(r"(?:MOD\.?\s*)?(\d{3,4})", m.upper())
        base = m_cz.group(1) if m_cz else m.split()[0]
        return base, f"Cazal {base}"
    if b == "silhouette":
        m_s = re.search(r"\b([A-Z]?\d{3,4})\b", m.upper())
        base = m_s.group(1) if m_s else m.split()[0]
        return base, f"Silhouette {base}"
    if b == "blackfin":
        m_bf = re.search(r"BF\d{3,4}\s+([A-Z0-9-]+)", m.upper())
        base = m_bf.group(1) if m_bf else m.split()[0]
        return base, f"Blackfin {base}"
    if b == "lunor":
        m_l = re.search(r"Mod\.?\s*(\d{2,4})", m, flags=re.I)
        base = m_l.group(1) if m_l else m.split()[0]
        return base, f"Lunor {base}"
    base = m.split()[0]
    return base, f"{brand} {base}"


def extract_variants_from_shopify_product_html(html: str, brand: str, store_url: str, expected_handle: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    title_m = re.search(r"<title>([^<]+)</title>", html, flags=re.I)
    page_title = title_m.group(1).split("|")[0].split("–")[0].strip() if title_m else expected_handle

    # 1. Скрипты <script type="application/json"> с объектом товара (FashionEyewear и др.)
    for m in re.finditer(r'<script[^>]*type="application/json"[^>]*>([\s\S]*?)</script>', html):
        txt = m.group(1).strip()
        if '"variants"' not in txt or '"handle"' not in txt:
            continue
        try:
            obj = json.loads(txt)
            if not isinstance(obj, dict) or "variants" not in obj:
                continue
            p_title = str(obj.get("title") or page_title)
            p_handle = str(obj.get("handle") or expected_handle)
            for v in obj.get("variants") or []:
                if not isinstance(v, dict):
                    continue
                f_img = ""
                if isinstance(v.get("featured_image"), dict):
                    f_img = str(v["featured_image"].get("src") or "")
                if f_img:
                    if f_img.startswith("//"):
                        f_img = "https:" + f_img
                    records.append(
                        {
                            "brand": brand,
                            "source": store_url,
                            "title": p_title,
                            "handle": p_handle,
                            "vendor": brand,
                            "tags": "",
                            "var_sku": str(v.get("sku") or ""),
                            "var_title": str(v.get("title") or ""),
                            "img": f_img,
                            "multi_variant": True,
                        }
                    )
        except Exception:
            pass

    # 2. Встроенный массив вариантов Web Pixels (только если SKU/картинка подтверждают принадлежность к expected_handle, без блока рекомендаций!)
    pat = r'\{"id":"?\d+"?,"image":\{"src":"([^"]+)"\},"price":\{[^}]+\},"sku":"([^"]*)"\s*,"title":"([^"]*)"'
    for raw_img, raw_sku, raw_vtitle in re.findall(pat, html):
        img = raw_img.replace("\\/", "/").strip()
        if img.startswith("//"):
            img = "https:" + img
        sku = raw_sku.replace("\\/", "/").strip()
        vtitle = raw_vtitle.replace("\\/", "/").strip()
        if img:
            rec = {
                "brand": brand,
                "source": store_url,
                "title": page_title,
                "handle": expected_handle,
                "vendor": brand,
                "tags": "",
                "var_sku": sku,
                "var_title": vtitle,
                "img": img,
                "multi_variant": True,
            }
            if is_valid_brand_record(brand, rec):
                records.append(rec)
    return records


def search_html_stores_for_query(brand: str, short_q: str, full_q: str) -> List[Dict[str, Any]]:
    b_low = brand.lower()
    recs: List[Dict[str, Any]] = []

    # A. Visiofactory (отлично для Gucci, Ray-Ban, Oakley, Cazal, Saint Laurent, Polaroid)
    if b_low in ("gucci", "ray-ban", "oakley", "cazal", "saint laurent", "polaroid", "tom ford", "prada", "miu miu"):
        vf_url = f"https://www.visiofactory.com/en/recherche?controller=search&s={urllib.parse.quote(short_q)}"
        try:
            req = urllib.request.Request(vf_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            for src, alt in re.findall(
                r'src="(https://cdn\d*\.visiofactory\.com/\d+-thickbox/[^"]+\.jpg)"\s+alt="([^"]+)"',
                html,
            ):
                recs.append(
                    {
                        "brand": brand,
                        "source": "https://www.visiofactory.com",
                        "title": alt.strip(),
                        "handle": norm_alnum(alt),
                        "vendor": brand,
                        "tags": "",
                        "var_sku": alt.strip(),
                        "var_title": alt.strip(),
                        "img": src,
                        "multi_variant": False,
                    }
                )
        except Exception:
            pass

    # A2. Pretavoir HTML search (внутри HTML встроен JSON массив результатов по всему каталогу 74,000+ товаров)
    if b_low in ("gucci", "saint laurent", "prada", "miu miu", "ray-ban", "tom ford", "dior", "celine", "montblanc", "max mara", "oakley", "polaroid", "cazal", "cutler and gross", "linda farrow", "dita", "silhouette", "balenciaga", "cartier"):
        pr_url = f"https://pretavoir.co.uk/search?q={urllib.parse.quote(short_q)}&type=product"
        try:
            req = urllib.request.Request(pr_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            for p_title, p_handle, raw_img, p_vendor in re.findall(
                r'\{"title":"([^"]+)","id":\d+,"handle":"([^"]+)","price":\d+,"image":"([^"]+)","vendor":"([^"]+)"',
                html,
            ):
                img = raw_img.replace("\\/", "/").strip()
                if img.startswith("//"):
                    img = "https:" + img
                img = re.sub(r"_(?:small|medium|large|compact|grande)\.", ".", img)
                recs.append(
                    {
                        "brand": brand,
                        "source": "https://pretavoir.co.uk",
                        "title": p_title,
                        "handle": p_handle,
                        "vendor": p_vendor,
                        "tags": "",
                        "var_sku": p_title,
                        "var_title": p_title,
                        "img": img,
                        "multi_variant": False,
                    }
                )
        except Exception:
            pass

    # B. Paris Lunetier HTML search (карточки сразу содержат картинку и артикул цвета в URL/title)
    if b_low in ("gucci", "saint laurent", "prada", "miu miu", "ray-ban", "tom ford", "dior", "celine", "montblanc", "balenciaga", "mykita", "cazal", "john dalia", "masunaga"):
        pl_url = f"https://parislunetier.com/search?q={urllib.parse.quote(short_q)}&type=product"
        try:
            req = urllib.request.Request(pl_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            for m in re.finditer(r'href="(/products/([^"?#]+))"', html):
                handle = m.group(2)
                s = max(0, m.start() - 600)
                e = min(len(html), m.end() + 600)
                chunk = html[s:e]
                img_m = re.search(r'(//parislunetier\.com/cdn/shop/(?:files|products)/[^\s",]+?\.(?:jpg|png|webp))', chunk)
                if img_m:
                    img = "https:" + re.sub(r"_\d+x\.", "_1080x.", img_m.group(1))
                    recs.append(
                        {
                            "brand": brand,
                            "source": "https://parislunetier.com",
                            "title": handle.replace("-", " "),
                            "handle": handle,
                            "vendor": brand,
                            "tags": "",
                            "var_sku": handle,
                            "var_title": handle.replace("-", " "),
                            "img": img,
                            "multi_variant": False,
                        }
                    )
        except Exception:
            pass

    # B2. GoodSeeCo HTML search (карточки содержат alt="Brand - Model (Color)" и src="//www.goodseeco.com/cdn/shop/...")
    if b_low in ("gucci", "saint laurent", "cartier", "dita", "matsuda", "jacques marie mage", "ahlem", "kuboraum", "cutler and gross", "mykita", "tom ford", "celine", "prada", "miu miu", "gotti", "linda farrow", "leisuresociety"):
        gs_url = f"https://www.goodseeco.com/search?q={urllib.parse.quote(short_q)}&type=product"
        try:
            req = urllib.request.Request(gs_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            for m in re.finditer(r'<img[^>]+src="([^"]+cdn/shop/(?:files|products)/[^"]+)"[^>]*alt="([^"]+)"', html):
                raw_src, alt = m.group(1), m.group(2).strip()
                if "logo" in raw_src.lower():
                    continue
                img = ("https:" + raw_src if raw_src.startswith("//") else raw_src).replace("{width}", "900")
                img = re.sub(r"_\d+x\.", "_900x.", img)
                recs.append(
                    {
                        "brand": brand,
                        "source": "https://www.goodseeco.com",
                        "title": alt,
                        "handle": norm_alnum(alt),
                        "vendor": brand,
                        "tags": "",
                        "var_sku": alt,
                        "var_title": alt,
                        "img": img,
                        "multi_variant": False,
                    }
                )
        except Exception:
            pass

    # C. EuroOptica / FashionEyewear HTML search -> переход на страницу модели /products/<handle>
    target_stores: List[str] = []
    if b_low in ("gotti", "andy wolf", "blackfin", "silhouette", "prodesign", "paul smith", "mykita", "ic! berlin", "cazal", "anne & valentin", "masunaga", "cutler and gross", "linda farrow", "matsuda"):
        target_stores.append("https://www.eurooptica.com")
    if b_low in ("gucci", "saint laurent", "prada", "miu miu", "ray-ban", "tom ford", "dior", "celine", "montblanc", "max mara", "oakley", "paul smith", "gotti", "andy wolf", "silhouette"):
        target_stores.append("https://www.fashioneyewear.com")

    b_slug = re.sub(r"[^a-z0-9]+", "-", b_low).strip("-")[:4]
    q_slug = norm_alnum(short_q)[:4]

    for store in target_stores:
        s_url = f"{store}/search?q={urllib.parse.quote(full_q)}&type=product"
        try:
            req = urllib.request.Request(s_url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
                s_html = resp.read().decode("utf-8", errors="ignore")
            handles = list(dict.fromkeys(re.findall(r"/products/([a-z0-9-]+)", s_html)))
            good_handles = [
                h for h in handles
                if h not in ("gift-card", "e-gift-card") and (b_slug in h or (q_slug and q_slug in norm_alnum(h)))
            ][:2]
            for h in good_handles:
                p_url = f"{store}/products/{h}"
                req_p = urllib.request.Request(p_url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req_p, timeout=10, context=SSL_CTX) as resp_p:
                    p_html = resp_p.read().decode("utf-8", errors="ignore")
                recs.extend(extract_variants_from_shopify_product_html(p_html, brand, store, h))
        except Exception:
            pass

    return [r for r in recs if is_valid_brand_record(brand, r)]


def search_mykita_official(item: Dict[str, Any]) -> Optional[str]:
    """Ищет конкретный цвет модели MYKITA напрямую на mykita.com/en/search?q=<model> строго по коду col.XXX."""
    model = item["model"].strip()
    m_clean = re.sub(r",?\s*(?:col\.?|c\.)\s*([a-z0-9]+).*$", "", model, flags=re.I).strip()
    m_col = re.search(r"(?:col\.?|c\.)\s*([a-z0-9]+)", model, flags=re.I)
    if not m_clean or not m_col:
        return None
    col_code = m_col.group(1).upper()
    col_padded = col_code.zfill(3) if col_code.isdigit() else col_code
    q = urllib.parse.quote(m_clean)
    url = f"https://mykita.com/en/search?q={q}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    if "detail-list-colours" not in html:
        m_slug = re.sub(r"[^a-z0-9]+", "-", m_clean.lower()).strip("-")
        links = re.findall(r'href="(/en/(?:prescription-glasses|sunglasses)/[^"]+)"', html)
        good_links = [lnk for lnk in links if m_slug in lnk.lower()]
        if good_links:
            try:
                req2 = urllib.request.Request("https://mykita.com" + good_links[0], headers={"User-Agent": UA})
                with urllib.request.urlopen(req2, timeout=10, context=SSL_CTX) as resp2:
                    html = resp2.read().decode("utf-8", errors="ignore")
            except Exception:
                return None

    # Проверяем блок <ul class="detail-list-colours"> на странице модели (строго модель + код цвета!)
    colours = re.findall(
        r'<img\s+src="(//mykitamedia\.com/media/image/[^"]+\.jpg)"\s+alt="Frame:\s*([^"]+)"',
        html,
    )
    for img_src, alt_text in colours:
        if not has_token(alt_text.lower(), m_clean.lower()):
            continue
        if (
            has_token(alt_text, col_code)
            or has_token(alt_text, col_padded)
            or has_token(alt_text, f"C{col_code}")
            or has_token(alt_text, f"C{col_padded}")
        ):
            return "https:" + re.sub(r"/ri-s\d+/(?:tiny|small|bigger)/1x/", "/ri-s4/extra/1x/", img_src)
    return None


PRETAVOIR_COLLECTIONS: List[Tuple[str, str, int]] = [
    ("Gucci", "https://pretavoir.co.uk/collections/gucci-glasses", 4),
    ("Gucci", "https://pretavoir.co.uk/collections/gucci-sunglasses", 4),
    ("Saint Laurent", "https://pretavoir.co.uk/collections/saint-laurent-glasses", 4),
    ("Saint Laurent", "https://pretavoir.co.uk/collections/saint-laurent-sunglasses", 4),
    ("Prada", "https://pretavoir.co.uk/collections/prada-glasses", 2),
    ("Prada", "https://pretavoir.co.uk/collections/prada-sunglasses", 2),
    ("Miu Miu", "https://pretavoir.co.uk/collections/miu-miu-sunglasses", 2),
    ("Ray-Ban", "https://pretavoir.co.uk/collections/ray-ban-glasses", 4),
    ("Ray-Ban", "https://pretavoir.co.uk/collections/ray-ban-sunglasses", 4),
    ("Tom Ford", "https://pretavoir.co.uk/collections/tom-ford-glasses", 4),
    ("Tom Ford", "https://pretavoir.co.uk/collections/tom-ford-sunglasses", 4),
    ("Dior", "https://pretavoir.co.uk/collections/dior-glasses", 2),
    ("Dior", "https://pretavoir.co.uk/collections/dior-sunglasses", 2),
    ("Celine", "https://pretavoir.co.uk/collections/celine-glasses", 2),
    ("Celine", "https://pretavoir.co.uk/collections/celine-sunglasses", 2),
    ("Cartier", "https://pretavoir.co.uk/collections/cartier-glasses", 2),
    ("Cartier", "https://pretavoir.co.uk/collections/cartier-sunglasses", 3),
    ("Montblanc", "https://pretavoir.co.uk/collections/montblanc-glasses", 2),
    ("Montblanc", "https://pretavoir.co.uk/collections/montblanc-sunglasses", 2),
    ("Oakley", "https://pretavoir.co.uk/collections/oakley-glasses", 2),
    ("Oakley", "https://pretavoir.co.uk/collections/oakley-sunglasses", 2),
    ("Cazal", "https://pretavoir.co.uk/collections/cazal-glasses", 1),
    ("Cazal", "https://pretavoir.co.uk/collections/cazal-sunglasses", 1),
    ("Cutler and Gross", "https://pretavoir.co.uk/collections/cutler-and-gross-glasses", 2),
    ("Cutler and Gross", "https://pretavoir.co.uk/collections/cutler-and-gross-sunglasses", 2),
    ("Dita", "https://pretavoir.co.uk/collections/dita-glasses", 1),
    ("Dita", "https://pretavoir.co.uk/collections/dita-sunglasses", 2),
    ("Balenciaga", "https://pretavoir.co.uk/collections/balenciaga-glasses", 1),
    ("Balenciaga", "https://pretavoir.co.uk/collections/balenciaga-sunglasses", 1),
    ("Polaroid", "https://pretavoir.co.uk/collections/polaroid-sunglasses", 1),
    ("Polaroid", "https://pretavoir.co.uk/collections/polaroid-glasses", 1),
]


EUROOPTICA_AND_EXTRA_COLLECTIONS: List[Tuple[str, str, int]] = [
    ("Gotti", "https://www.eurooptica.com/collections/gotti", 4),
    ("Andy Wolf", "https://www.eurooptica.com/collections/andy-wolf", 3),
    ("BLACKFIN", "https://www.eurooptica.com/collections/blackfin", 2),
    ("Silhouette", "https://www.eurooptica.com/collections/silhouette", 1),
    ("PRODESIGN", "https://www.eurooptica.com/collections/prodesign-denmark", 1),
    ("Paul Smith", "https://www.eurooptica.com/collections/paul-smith", 1),
    ("Cazal", "https://www.eurooptica.com/collections/cazal", 2),
    ("Ic! Berlin", "https://www.eurooptica.com/collections/ic-berlin", 3),
    ("MYKITA", "https://www.eurooptica.com/collections/mykita", 2),
    ("Anne & Valentin", "https://www.eurooptica.com/collections/anne-valentin", 1),
    ("Masunaga", "https://www.eurooptica.com/collections/masunaga", 1),
    ("Matsuda", "https://www.eurooptica.com/collections/matsuda", 1),
    ("Cutler and Gross", "https://www.eurooptica.com/collections/cutler-and-gross", 2),
    ("Gucci", "https://www.eurooptica.com/collections/gucci", 3),
    ("Saint Laurent", "https://www.eurooptica.com/collections/saint-laurent", 3),
    ("Ray-Ban", "https://www.eurooptica.com/collections/ray-ban", 4),
    ("Tom Ford", "https://www.eurooptica.com/collections/tom-ford", 4),
    ("Dior", "https://www.eurooptica.com/collections/dior", 3),
    ("Celine", "https://www.eurooptica.com/collections/celine", 2),
    ("Miu Miu", "https://www.eurooptica.com/collections/miu-miu", 1),
    ("Balenciaga", "https://www.eurooptica.com/collections/balenciaga", 2),
    ("Oakley", "https://www.eurooptica.com/collections/oakley", 3),
    ("Polaroid", "https://www.fashioneyewear.com/collections/polaroid", 1),
    ("Paul Smith", "https://www.fashioneyewear.com/collections/paul-smith", 1),
    ("Kaleos Eyehunters", "https://www.fashioneyewear.com/collections/kaleos", 1),
    ("Max Mara", "https://www.fashioneyewear.com/collections/maxmara-glasses", 1),
    ("Max Mara", "https://www.fashioneyewear.com/collections/maxmara-sunglasses", 1),
    ("LeSpecs", "https://au.lespecs.com", 3),
    ("LeSpecs", "https://lespecs.com", 3),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка точных фото по моделям и кодам цветов")
    parser.add_argument("--refresh-cache", action="store_true", help="Принудительно обновить кэш каталогов Shopify")
    parser.add_argument("--pretavoir", action="store_true", help="Догрузить брендовые коллекции с pretavoir.co.uk")
    parser.add_argument("--eurooptica-fix", action="store_true", help="Догрузить точные коллекции с eurooptica.com, fashioneyewear.com и lespecs")
    parser.add_argument("--mykita-official", action="store_true", help="Догрузить цвета MYKITA напрямую с mykita.com")
    parser.add_argument("--html-search", action="store_true", help="Дополнительно опросить HTML-поиск мультибрендовых магазинов по ненайденным моделям")
    parser.add_argument("--dry-run", action="store_true", help="Только проверить количество совпадений без скачивания")
    parser.add_argument("--limit", type=int, default=0, help="Ограничить число скачиваний")
    args = parser.parse_args()

    if not MISSING_JSON.is_file():
        print("Не найден scripts/missing_photos.json — сначала запустите sync_itigris.py")
        return 1

    missing_items: List[Dict[str, Any]] = json.loads(MISSING_JSON.read_text(encoding="utf-8"))
    print(f"Позиций в очереди на поиск фото: {len(missing_items)}", flush=True)

    catalog_by_brand = load_or_build_catalog_cache(force_refresh=args.refresh_cache)

    if args.eurooptica_fix:
        print(f"Загрузка {len(EUROOPTICA_AND_EXTRA_COLLECTIONS)} коллекций с EuroOptica / FashionEyewear / LeSpecs...", flush=True)
        added_eo = 0
        for idx, (b, u, pages) in enumerate(EUROOPTICA_AND_EXTRA_COLLECTIONS, 1):
            is_root = u in ("https://au.lespecs.com", "https://lespecs.com")
            new_recs = fetch_collection_entries((b, u, pages, is_root))
            if new_recs:
                catalog_by_brand.setdefault(b.lower(), []).extend(new_recs)
                added_eo += len(new_recs)
            print(f"  [{idx}/{len(EUROOPTICA_AND_EXTRA_COLLECTIONS)}] {b} ({u.split('//')[1].split('/')[0]}): +{len(new_recs)} (всего +{added_eo})", flush=True)
            time.sleep(0.55)
        if added_eo > 0:
            CACHE_JSON.write_text(json.dumps(catalog_by_brand, ensure_ascii=False), encoding="utf-8")
            print(f"Сохранено {added_eo} новых записей вариантов в кэш", flush=True)

    if args.pretavoir:
        print(f"Загрузка {len(PRETAVOIR_COLLECTIONS)} коллекций с pretavoir.co.uk...", flush=True)
        added_pr = 0
        for idx, (b, u, pages) in enumerate(PRETAVOIR_COLLECTIONS, 1):
            new_recs = fetch_collection_entries((b, u, pages, False))
            if new_recs:
                catalog_by_brand.setdefault(b.lower(), []).extend(new_recs)
                added_pr += len(new_recs)
            if idx % 5 == 0 or idx == len(PRETAVOIR_COLLECTIONS):
                print(f"  Pretavoir [{idx}/{len(PRETAVOIR_COLLECTIONS)}] (+{added_pr} записей)", flush=True)
            time.sleep(0.35)
        if added_pr > 0:
            CACHE_JSON.write_text(json.dumps(catalog_by_brand, ensure_ascii=False), encoding="utf-8")
            print(f"Добавлено {added_pr} записей с pretavoir.co.uk", flush=True)

    if args.mykita_official:
        mykita_items = [it for it in missing_items if it["brand"].strip().lower() == "mykita"]
        print(f"Проверка {len(mykita_items)} позиций MYKITA на mykita.com...", flush=True)
        added_mk = 0
        for it in mykita_items:
            recs = catalog_by_brand.get("mykita", [])
            if recs and match_record_for_item(it, recs):
                continue
            hi_url = search_mykita_official(it)
            if hi_url:
                catalog_by_brand.setdefault("mykita", []).append(
                    {
                        "brand": "MYKITA",
                        "source": "https://mykita.com",
                        "title": it["model"],
                        "handle": norm_alnum(it["model"]),
                        "vendor": "MYKITA",
                        "tags": "",
                        "var_sku": it["model"],
                        "var_title": it["model"],
                        "img": hi_url,
                        "multi_variant": False,
                    }
                )
                added_mk += 1
            time.sleep(0.2)
        if added_mk > 0:
            CACHE_JSON.write_text(json.dumps(catalog_by_brand, ensure_ascii=False), encoding="utf-8")
            print(f"Найдено {added_mk} точных цветов на mykita.com", flush=True)

    if args.html_search:
        # Собираем уникальные запросы (бренд + базовая модель) для позиций, не найденных в текущем кэше
        queries_map: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
        for item in missing_items:
            b = item["brand"].strip()
            b_low = b.lower()
            if b_low in SKIP_HTML_SEARCH_BRANDS:
                continue
            recs = catalog_by_brand.get(b_low, [])
            if recs and match_record_for_item(item, recs):
                continue
            short_q, full_q = build_base_search_query(b, item["model"])
            if len(norm_alnum(short_q)) < 2:
                continue
            key = (b_low, short_q.upper())
            if key not in queries_map:
                queries_map[key] = (b, short_q, full_q)

        q_list = list(queries_map.values())
        print(f"Запуск HTML-поиска по {len(q_list)} уникальным моделям...", flush=True)

        added_recs = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            for idx, ((b, sq, fq), new_recs) in enumerate(zip(q_list, ex.map(lambda t: search_html_stores_for_query(*t), q_list)), 1):
                if new_recs:
                    b_low = b.lower()
                    catalog_by_brand.setdefault(b_low, []).extend(new_recs)
                    added_recs += len(new_recs)
                if idx % 40 == 0 or idx == len(q_list):
                    print(f"  HTML-поиск [{idx}/{len(q_list)}] (+{added_recs} вариантов)", flush=True)

        if added_recs > 0:
            CACHE_JSON.write_text(json.dumps(catalog_by_brand, ensure_ascii=False), encoding="utf-8")
            print(f"В кэш добавлено {added_recs} новых вариантов из HTML-поиска", flush=True)

    # Индексируем существующие MD5 фото в папке assets/img/frames, чтобы исключить дублирование картинки между цветами
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    used_hashes: Set[str] = set()
    for p in FRAMES_DIR.glob("*.jpg"):
        try:
            used_hashes.add(hashlib.md5(p.read_bytes()).hexdigest())
        except Exception:
            pass

    matched_tasks: List[Tuple[Dict[str, Any], str]] = []
    by_brand_matched: Dict[str, int] = {}

    for item in missing_items:
        b_low = item["brand"].strip().lower()
        recs = catalog_by_brand.get(b_low, [])
        img_url = match_record_for_item(item, recs) if recs else None
        if img_url:
            matched_tasks.append((item, img_url))
            by_brand_matched[item["brand"]] = by_brand_matched.get(item["brand"], 0) + 1

    print(f"\nНайдено точных совпадений (модель + код цвета) в кэше Shopify: {len(matched_tasks)}", flush=True)
    for b, cnt in sorted(by_brand_matched.items(), key=lambda x: -x[1]):
        print(f"  {b}: {cnt}", flush=True)

    if args.dry_run:
        return 0

    if args.limit > 0:
        matched_tasks = matched_tasks[: args.limit]

    saved = 0
    skipped_dup = 0
    failed = 0

    def download_worker(pair: Tuple[Dict[str, Any], str]) -> Tuple[str, Optional[bytes]]:
        it, u = pair
        return it["sku"], download_bytes(u)

    print(f"\nСкачивание {len(matched_tasks)} изображений (в 12 потоков)...", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for (item, img_url), (_, raw_bytes) in zip(matched_tasks, ex.map(download_worker, matched_tasks)):
            if not raw_bytes:
                failed += 1
                continue
            dst = FRAMES_DIR / f"{item['sku']}.jpg"
            tmp = FRAMES_DIR / f".tmp_{item['sku']}.jpg"
            md5 = normalize_and_save_image(raw_bytes, tmp)
            if not md5:
                tmp.unlink(missing_ok=True)
                failed += 1
                continue
            if md5 in used_hashes:
                tmp.unlink(missing_ok=True)
                skipped_dup += 1
                continue
            used_hashes.add(md5)
            tmp.replace(dst)
            saved += 1
            if saved % 25 == 0:
                print(f"  [+{saved}] сохранено: {item['brand']} {item['model']} -> {dst.name}", flush=True)

    print(f"\nИтог этапа 1: сохранено уникальных фото={saved}, отклонено дублей={skipped_dup}, ошибок={failed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

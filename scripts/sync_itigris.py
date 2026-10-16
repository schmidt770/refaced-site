#!/usr/bin/env python3
"""Синхронизация каталога сайта REFACED с живыми остатками ITigris Optima.

Забирает полный XLS-отчёт «Остатки товара» (Оправы + Солнцезащитные очки)
по бутикам «Мойка, 58» и «Петровский, 22», объединяет остатки между бутиками,
сопоставляет фотографии из assets/img/frames/ (и при наличии подтягивает
исходники из ../optics-bot/data/frames/), сохраняет:
  - assets/data/catalog.json — каталог для фронтенда сайта
  - scripts/missing_photos.json — список позиций без фото для автопоиска
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import xlrd
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
FRAMES_DIR = BASE_DIR / "assets" / "img" / "frames"
CATALOG_JSON = BASE_DIR / "assets" / "data" / "catalog.json"
MISSING_JSON = BASE_DIR / "scripts" / "missing_photos.json"
OPTICS_BOT_FRAMES = BASE_DIR.parent / "optics-bot" / "data" / "frames"

# Департаменты бутиков в ITigris Optima
DEPARTMENTS = {
    "1000000004": ("moyka", "Мойка, 58"),
    "1000000011": ("petrovsky", "Петровский, 22"),
}
DEPT_NAME_TO_ID = {
    "Мойка, 58": "moyka",
    "Петровский, 22": "petrovsky",
}

# Список брендов-исключений (пополняется по мере уточнения у заказчика)
EXCLUDED_BRANDS = {
    "импорт",  # Техническая тестовая запись "Импорт / test / 1 ₽" в Итигрис
}

# Каноническое написание брендов (склейка дублей регистра в базе Итигрис)
BRAND_CANONICAL = {
    "cartier": "Cartier",
    "miu miu": "Miu Miu",
    "linda farrow": "Linda Farrow",
    "cutler and gross": "Cutler and Gross",
    "dolce and gabbana": "Dolce & Gabbana",
    "anna-karin karlsson": "Anna-Karin Karlsson",
    "garrett leight": "Garrett Leight",
    "for art sake": "For Art's Sake",
    "dzmitry samal": "Dzmitry Samal",
}

REPORT_TYPES = ("Солнцезащитные очки", "Оправы")


def load_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'").strip('"')
    for k in ("ITIGRIS_URL", "ITIGRIS_COMPANY", "ITIGRIS_LOGIN", "ITIGRIS_PASSWORD"):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def normalize_brand(raw: str) -> str:
    clean = re.sub(r"\s+", " ", raw.strip())
    low = clean.lower()
    if low in BRAND_CANONICAL:
        return BRAND_CANONICAL[low]
    return clean


def norm_sku_key(brand: str, model: str) -> str:
    """Нормализованный ключ для сопоставления артикула и файла фотографии."""
    s = model.strip().lower()
    # Убираем суффиксы комплектации вроде "+ clip-on"
    s = s.partition("+")[0].strip()
    # В базе Итигрис у Cartier иногда латинская O вместо 0 после CT: CTO430S -> ct0430s
    if brand.lower() == "cartier" or s.startswith("cto"):
        s = re.sub(r"^cto(?=\d)", "ct0", s)
    return re.sub(r"[^a-z0-9а-яё]+", "", s)


def make_safe_sku(brand: str, model: str) -> str:
    """Генерирует безопасное имя файла/артикула (ASCII/кириллица без пробелов)."""
    base = model.partition("+")[0].strip()
    if brand.lower() == "cartier":
        base = re.sub(r"^CTO(?=\d)", "CT0", base, flags=re.IGNORECASE)
    # Заменяем пробелы и запятые на подчёркивания, убираем лишние символы
    safe = re.sub(r"[^\w\-]+", "_", base, flags=re.UNICODE).strip("_")
    safe = re.sub(r"_+", "_", safe)
    if not safe:
        safe = "item"
    # Если артикул совсем короткий или числовой (например у собственных оправ), добавим префикс бренда
    if len(safe) < 5 or safe.isdigit():
        brand_prefix = re.sub(r"[^\w]+", "", brand)[:6].upper()
        safe = f"{brand_prefix}_{safe}"
    return safe


def clean_display_model(model: str) -> str:
    """Очищает название модели для красивого отображения на карточке."""
    base = model.partition("+")[0].strip()
    base = re.sub(r"^CTO(?=\d)", "CT0", base)
    return re.sub(r"\s+", " ", base)


def extract_base_model(brand: str, model_raw: str) -> str:
    """Выделяет базовую модель (без цветового кода) для объединения одинаковых очков из разных бутиков в одну карточку."""
    b = brand.strip().lower()
    m = clean_display_model(model_raw)

    if b == "cartier":
        mc = re.match(r"^(CT\d{4}[A-Z]?)\b", m, flags=re.I)
        if mc:
            return mc.group(1).upper()

    if b in ("gucci", "saint laurent", "balenciaga"):
        return re.sub(r"\s+\d{3}[A-Z]?$", "", m).strip()

    if b in ("prada", "miu miu", "versace"):
        mp = re.match(r"^([A-Z]{2,4}\s+[A-Z0-9]{2,5}(?:\-[A-Z])?)\b", m, flags=re.I)
        if mp:
            return re.sub(r"\s+", " ", mp.group(1)).upper()

    if b == "tom ford":
        mtf = re.match(r"^(TF\s*\d{3,4}(?:\-[A-Z])?)\b", m, flags=re.I)
        if mtf:
            return re.sub(r"\s+", " ", mtf.group(1)).upper()

    if b == "ray-ban":
        mrb = re.match(r"^((?:RB|RX)\s*\d{4}[A-Z]?)\b", m, flags=re.I)
        if mrb:
            return re.sub(r"\s+", " ", mrb.group(1)).upper()

    if b == "linda farrow":
        mlf = re.match(r"^(LFL[\-\s]*\d{3,4})\b", m, flags=re.I)
        if mlf:
            return re.sub(r"[\-\s]+", "-", mlf.group(1)).upper()
        return re.sub(r"\s+C\d+.*$", "", m, flags=re.I).strip()

    if b == "matsuda":
        mmt = re.match(r"^([M]?\d{4,5}[A-Z]?(?:[\-\s]+V2)?)\b", m, flags=re.I)
        if mmt:
            base = re.sub(r"[\-\s]+", "-", mmt.group(1)).upper()
            if re.match(r"^[M]?\d{4,5}[A-Z]?\s+SG\b", m, flags=re.I):
                return f"{base} SG"
            return base

    if b in ("kaleos eyehunters", "john dalia", "avo", "bosara", "kreuzbergkinder", "zilli", "фиксики"):
        return re.sub(r"\s+C[\-\.]?\d+.*$", "", m, flags=re.I).strip()

    if b == "lespecs":
        return re.sub(r"\s+\d{6,8}$", "", m).strip()

    if b == "gast":
        return re.sub(r"\s+(?:[A-Z]{2,3}\d{2}|\d{2})$", "", m, flags=re.I).strip()

    if b in ("paul smith", "haffmans & neumeister", "spine", "swissflex"):
        return re.sub(r"\s+\d{2,3}$", "", m).strip()

    if b == "davidoff":
        mdv = re.match(r"^(DA[PTS]?\s*\d{3})\b", m, flags=re.I)
        if mdv:
            return re.sub(r"\s+", " ", mdv.group(1)).upper()

    if b == "hackett london bespoke":
        mhb = re.match(r"^(HEB\s*\d{3})\b", m, flags=re.I)
        if mhb:
            return re.sub(r"\s+", " ", mhb.group(1)).upper()

    if b == "ic! berlin":
        mib = re.match(r"^([A-Za-z0-9\.\-]+(?:\s+[A-Z]\.)?(?:\s+Large|\s+Small|\s+East)?)", m)
        if mib:
            return mib.group(1).strip()

    if b in ("gotti", "brevno", "havaianas"):
        return m.split()[0]

    if b == "ahlem":
        mah = re.match(r"^(Saint\s+Benoit|[A-Za-z]+)", m, flags=re.I)
        if mah:
            return mah.group(1).strip()

    if b == "lunor":
        return re.sub(r"\s+(?:PP|AG|GP|AS|SWS|RG|col\.\d+|\d{2}[a-z]?)$", "", m, flags=re.I).strip()

    if b == "kuboraum":
        mku = re.match(r"^([A-Z]\d{1,3}(?:\s+SG)?)\b", m, flags=re.I)
        if mku:
            return mku.group(1).upper()

    if b == "eyerepublic":
        mer = re.match(r"^(№\s*\d+)", m)
        if mer:
            return mer.group(1)

    if b == "retrosuperfuture":
        parts = m.split()
        if len(parts) >= 2 and len(parts[0]) == 3 and parts[0].isalnum():
            if parts[1].lower() == "numero" and len(parts) >= 3:
                return f"Numero {parts[2]}"
            return parts[1].capitalize()

    if b == "celine":
        mcl = re.match(r"^(CL\s*\d{4,5}[A-Z]{1,2})\b", m, flags=re.I)
        if mcl:
            return re.sub(r"\s+", " ", mcl.group(1)).upper()

    if b == "trama":
        mtr = re.match(r"^([A-Z]{2}\d{3,4})\b", m, flags=re.I)
        if mtr:
            return mtr.group(1).upper()

    if b == "orgreen":
        mor = re.sub(r"\s+\d{3,4}(?:\s+\d{2}/\d{2})?$", "", m).strip()
        if mor:
            return mor

    if b == "prodesign":
        mpr = re.match(r"^(\d{4})\b", m)
        if mpr:
            return mpr.group(1)

    if b == "plus eyewear":
        mpl = re.sub(r"\s+[A-Z]\d{4}[A-Z]$", "", m).strip()
        if mpl:
            return mpl

    if b == "fakoshima":
        mfk = re.match(r"^([A-Z]+\s+\d{2})\b", m, flags=re.I)
        if mfk:
            return mfk.group(1).upper()

    if b == "gigibarcelona":
        return re.sub(r"[\-\/]\d+$", "", m).strip()

    m_nocol = re.sub(r"[\s,]+(?:col\.?|c\.|color)\s*[A-Z0-9\-\./]+.*$", "", m, flags=re.I).strip()
    if m_nocol and len(m_nocol) >= 3:
        return m_nocol

    if not re.match(r"^Mod\.?\s*\d+$", m, flags=re.I):
        m_gen = re.sub(r"\s+(?:C[\-\.]?\d{1,3}|\d{3}[A-Z]?)$", "", m, flags=re.I).strip()
        if len(m_gen) >= 3 and m_gen.upper() != "MOD.":
            return m_gen
    return m


def format_frame_size(raw: str) -> str:
    """Превращает '140,37,145,20,55' (общая, высота, заушник, мост, линза) в читаемый размер."""
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) == 5:
        total_w, lens_h, temple, bridge, lens_w = parts
        items = []
        if lens_w.isdigit() and int(lens_w) > 0:
            items.append(f"линза {int(lens_w)} мм")
        if bridge.isdigit() and int(bridge) > 0:
            items.append(f"мост {int(bridge)} мм")
        if temple.isdigit() and int(temple) > 0:
            items.append(f"заушник {int(temple)} мм")
        return " · ".join(items)
    return raw


class ItigrisClient:
    """Клиент выгрузки отчёта остатков из ITigris Optima."""

    def __init__(self, base_url: str, login: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.login = login
        self.password = password
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj)
        )
        self.opener.addheaders = [
            (
                "User-Agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            )
        ]
        self.uuid = ""
        self.page_uuid = ""
        self.version_desc = ""
        self.user_id = ""
        self.today = ""

    def _post(self, path: str, params: List[Tuple[str, str]]) -> str:
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        )
        with self.opener.open(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")

    @staticmethod
    def _input_val(html: str, field_id: str) -> str:
        for tag in re.findall(r"<input[^>]+>", html, flags=re.IGNORECASE):
            if re.search(rf'\b(?:id|name)="{re.escape(field_id)}"', tag):
                m = re.search(r'\bvalue="([^"]*)"', tag)
                if m:
                    return m.group(1)
        return ""

    @staticmethod
    def _extract_uuid(html: str) -> str:
        m = re.search(
            r"updateMainPageData(?:Min)?\([^)]*?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            html,
            flags=re.IGNORECASE,
        )
        return m.group(1) if m else ""

    def authenticate(self) -> None:
        with self.opener.open(self.base_url, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        self.uuid = self._input_val(html, "uuid")
        self.page_uuid = self._input_val(html, "pageUUID")
        self.version_desc = self._input_val(html, "versionDesc")
        company_uuid = self._input_val(html, "companyUUID") or "refaced"
        if not (self.uuid and self.page_uuid):
            raise RuntimeError("Не удалось получить токены сессии со страницы входа ITigris")

        r1 = self._post(
            "login/login?loadId=base",
            [
                ("userId", ""),
                ("uuidValue", self.uuid),
                ("pageUUID", self.page_uuid),
                ("companyUUID", company_uuid),
            ],
        )
        u1 = self._extract_uuid(r1)
        if u1:
            self.uuid = u1

        r2 = self._post(
            "login/login",
            [
                ("login", self.login),
                ("password", self.password),
                ("loginAction", "true"),
                ("loadId", "base"),
                ("devData", ""),
                ("versionDesc", self.version_desc),
                ("browserDesc", "Mozilla/5.0"),
                ("key", ""),
                ("userId", ""),
                ("uuidValue", self.uuid),
                ("pageUUID", self.page_uuid),
                ("companyUUID", company_uuid),
            ],
        )
        m_uid = re.search(r'userId"\)\.value\s*=\s*"(\d+)"', r2)
        if not m_uid:
            raise RuntimeError(f"Ошибка входа в ITigris: {r2[:300]}")
        self.user_id = m_uid.group(1)
        u2 = self._extract_uuid(r2)
        if u2:
            self.uuid = u2

        r3 = self._post(
            "remainGoodsReport/startPage",
            [
                ("userId", self.user_id),
                ("uuidValue", self.uuid),
                ("pageUUID", self.page_uuid),
                ("companyUUID", company_uuid),
            ],
        )
        u3 = self._extract_uuid(r3)
        if u3:
            self.uuid = u3
        self.today = (
            self._input_val(r3, "date")
            or self._input_val(r3, "today")
            or "16.10.2026"
        )

    def fetch_report_xls(self, report_type: str, dept_ids: List[str]) -> xlrd.Book:
        import uuid as uuid_mod

        params: List[Tuple[str, str]] = [
            ("userId", self.user_id),
            ("uuidValue", self.uuid),
            ("pageUUID", self.page_uuid),
            ("companyUUID", "refaced"),
            ("prepareData", "true"),
            ("date", self.today),
            ("supplyDateFrom", ""),
            ("supplyDateTo", ""),
            ("supplier", ""),
            ("groupByDepartment", "true"),
            ("priceFrom", ""),
            ("priceTo", ""),
            ("reportType", report_type),
            ("priceType", "Розничная"),
        ]
        for did in dept_ids:
            params.append(("department", did))

        if report_type == "Солнцезащитные очки":
            for k in (
                "sunglasses.manufacturer",
                "sunglasses.brand",
                "sunglasses.model",
                "sunglasses.material",
                "sunglasses.type",
                "sunglasses.frameType",
                "sunglasses.targetGroup",
                "sunglasses.design",
            ):
                params.append((k, ""))
        else:
            for k in (
                "glasses.manufacturer",
                "glasses.brand",
                "glasses.model",
                "glasses.material",
                "glasses.type",
                "glasses.targetGroup",
                "glasses.design",
            ):
                params.append((k, ""))

        res = self._post("remainGoodsReport/reportPage", params)
        self.uuid = str(uuid_mod.uuid4())
        if "Success" not in res:
            raise RuntimeError(f"ITigris не подготовил отчёт ({report_type}): {res[:200]}")

        qs = urllib.parse.urlencode(
            [
                ("userId", self.user_id),
                ("pageUUID", self.page_uuid),
                ("notUUIDAction", "true"),
                ("excelPage", "true"),
                ("excelPageStartPage", "true"),
            ]
        )
        url = f"{self.base_url}/remainGoodsReport/reportPage?{qs}"
        with self.opener.open(url, timeout=60) as resp:
            xls_bytes = resp.read()
        return xlrd.open_workbook(file_contents=xls_bytes)


def parse_report_sheet(book: xlrd.Book, report_type: str) -> List[Dict[str, Any]]:
    sheet = book.sheet_by_index(0)
    header_row: Optional[int] = None
    for r in range(min(30, sheet.nrows)):
        row_vals = [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]
        if "Бренд" in row_vals and "Модель" in row_vals:
            header_row = r
            break
    if header_row is None:
        return []

    headers = [str(sheet.cell_value(header_row, c)).strip() for c in range(sheet.ncols)]
    col = {name: idx for idx, name in enumerate(headers) if name}

    rows: List[Dict[str, Any]] = []
    for r in range(header_row + 1, sheet.nrows):
        dept_raw = str(sheet.cell_value(r, col["Департамент"])).strip()
        if dept_raw not in DEPT_NAME_TO_ID:
            continue
        brand_raw = str(sheet.cell_value(r, col["Бренд"])).strip()
        model_raw = str(sheet.cell_value(r, col["Модель"])).strip()
        if not brand_raw or not model_raw:
            continue

        qty_col = col.get("Количество") if "Количество" in col else col.get("Кол-во")
        qty_val = sheet.cell_value(r, qty_col) if qty_col is not None else 0
        price_val = sheet.cell_value(r, col["Стоимость"])
        try:
            qty = int(round(float(qty_val)))
        except (ValueError, TypeError):
            qty = 0
        try:
            price = int(round(float(price_val)))
        except (ValueError, TypeError):
            price = 0

        if qty <= 0:
            continue

        def cell_str(name: str) -> str:
            if name not in col:
                return ""
            val = sheet.cell_value(r, col[name])
            return str(val).strip()

        rows.append(
            {
                "boutique": DEPT_NAME_TO_ID[dept_raw],
                "type": report_type,
                "manufacturer": cell_str("Производитель"),
                "brand": normalize_brand(brand_raw),
                "model_raw": model_raw,
                "material": cell_str("Материал"),
                "lens_type": cell_str("Тип линз"),
                "rim_type": cell_str("Тип оправы") or cell_str("Тип"),
                "audience": cell_str("Целевая группа"),
                "color": cell_str("Цвет"),
                "size": cell_str("Размер"),
                "design": cell_str("Дизайн"),
                "price": price,
                "qty": qty,
            }
        )
    return rows


def sync_seed_photos_from_optics_bot() -> int:
    """Конвертирует готовые студийные PNG из ../optics-bot/data/frames в assets/img/frames/*.jpg."""
    if not OPTICS_BOT_FRAMES.is_dir():
        return 0
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    added = 0
    for src in sorted(OPTICS_BOT_FRAMES.glob("*.png")):
        dst = FRAMES_DIR / f"{src.stem}.jpg"
        if dst.is_file():
            continue
        with Image.open(src) as im:
            rgb = im.convert("RGB")
            rgb = rgb.resize((640, 800), Image.Resampling.LANCZOS)
            rgb.save(dst, "JPEG", quality=88, optimize=True)
            added += 1
    return added


def index_local_photos() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Возвращает (по norm_sku_key -> отн. путь, по точному stem -> отн. путь)."""
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    by_norm: Dict[str, str] = {}
    by_stem: Dict[str, str] = {}
    for p in sorted(FRAMES_DIR.iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        rel = f"assets/img/frames/{p.name}"
        by_stem[p.stem.lower()] = rel
        by_norm[norm_sku_key("", p.stem)] = rel
    return by_norm, by_stem


def merge_inventory(
    raw_rows: List[Dict[str, Any]],
    excluded_brands: set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    by_norm_photo, by_stem_photo = index_local_photos()
    grouped: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}

    for row in raw_rows:
        brand = row["brand"]
        if brand.lower() in excluded_brands:
            continue

        key_norm = norm_sku_key(brand, row["model_raw"])
        color_norm = row["color"].strip().lower()
        lens_norm = row["lens_type"].strip().lower()
        # Объединяем в одну карточку ТОЛЬКО 100% идентичные очки (одинаковый полный артикул с кодом цвета, цвет оправы и линз)
        group_key = (row["type"], brand.lower(), key_norm, color_norm, lens_norm)

        if group_key not in grouped:
            sku = make_safe_sku(brand, row["model_raw"])
            display_model = clean_display_model(row["model_raw"])
            photo = (
                by_stem_photo.get(sku.lower())
                or by_norm_photo.get(key_norm)
                or ""
            )
            shapes = [
                s.strip()
                for s in row["design"].split(",")
                if s.strip()
            ]
            _, _, extra = row["model_raw"].partition("+")
            grouped[group_key] = {
                "sku": sku,
                "brand": brand,
                "model": display_model,
                "modelRaw": row["model_raw"],
                "title": f"{brand} {display_model}".strip(),
                "type": row["type"],
                "price": row["price"],
                "photo": photo,
                "boutiques": [],
                "stock": {"moyka": 0, "petrovsky": 0, "total": 0},
                "shapes": shapes,
                "audience": row["audience"],
                "material": row["material"],
                "color": row["color"],
                "lens": row["lens_type"],
                "rim": row["rim_type"],
                "size": format_frame_size(row["size"]),
                "note": f"В комплекте: {extra.strip()}" if extra.strip() else "",
            }

        item = grouped[group_key]
        b_id = row["boutique"]
        if b_id not in item["boutiques"]:
            item["boutiques"].append(b_id)
        item["stock"][b_id] = item["stock"].get(b_id, 0) + row["qty"]
        item["stock"]["total"] += row["qty"]
        if row["price"] > item["price"]:
            item["price"] = row["price"]

    products = list(grouped.values())
    for item in products:
        item["boutiques"] = [
            b for b in ("moyka", "petrovsky") if b in item["boutiques"]
        ]

    # Сортировка: сначала модели с фото, затем по ценности/бренду и цене по убыванию
    products.sort(
        key=lambda x: (
            0 if x["photo"] else 1,
            -len(x["boutiques"]),
            -(x["price"] or 0),
            x["brand"].lower(),
            x["model"].lower(),
        )
    )

    missing = [
        {
            "sku": p["sku"],
            "brand": p["brand"],
            "model": p["model"],
            "modelRaw": p["modelRaw"],
            "type": p["type"],
            "color": p["color"],
            "price": p["price"],
            "boutiques": p["boutiques"],
        }
        for p in products
        if not p["photo"]
    ]
    return products, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Синхронизация каталога с ITigris Optima")
    parser.add_argument(
        "--exclude-brand",
        action="append",
        default=[],
        help="Исключить бренд (можно указать несколько раз)",
    )
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    base_url = env.get("ITIGRIS_URL", "https://optima.itigris.ru/refaced")
    login = env.get("ITIGRIS_LOGIN", "")
    password = env.get("ITIGRIS_PASSWORD", "")
    if not login or not password:
        print("ОШИБКА: не заданы ITIGRIS_LOGIN / ITIGRIS_PASSWORD в .env", file=sys.stderr)
        return 1

    seeded = sync_seed_photos_from_optics_bot()
    if seeded:
        print(f"Импортировано готовых фото из optics-bot: {seeded}")

    excluded = {b.lower() for b in EXCLUDED_BRANDS} | {
        b.strip().lower() for b in args.exclude_brand if b.strip()
    }

    print(f"Подключение к {base_url} под учётной записью «{login}»...")
    client = ItigrisClient(base_url, login, password)
    client.authenticate()
    print(f"Авторизация успешна (userId={client.user_id}, дата отчёта={client.today})")

    dept_ids = list(DEPARTMENTS.keys())
    all_rows: List[Dict[str, Any]] = []
    for rtype in REPORT_TYPES:
        book = client.fetch_report_xls(rtype, dept_ids)
        rows = parse_report_sheet(book, rtype)
        print(f"  {rtype}: выгружено {len(rows)} строк")
        all_rows.extend(rows)

    products, missing = merge_inventory(all_rows, excluded)
    with_photo = sum(1 for p in products if p["photo"])

    catalog_payload = {
        "source": "itigris-optima",
        "updatedAt": client.today,
        "boutiques": {
            "moyka": {"name": "REFACED Мойка", "short": "Мойка, 58"},
            "petrovsky": {"name": "REFACED Петровский", "short": "Петровский, 22"},
        },
        "totalProducts": len(products),
        "withPhotoCount": with_photo,
        "products": products,
    }

    CATALOG_JSON.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_JSON.write_text(
        json.dumps(catalog_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    MISSING_JSON.parent.mkdir(parents=True, exist_ok=True)
    MISSING_JSON.write_text(
        json.dumps(missing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"\nГотово! Уникальных моделей в каталоге: {len(products)} "
        f"(с фото: {with_photo}, без фото: {len(missing)})"
    )
    print(f"Каталог сохранён: {CATALOG_JSON}")
    print(f"Очередь на поиск фото: {MISSING_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

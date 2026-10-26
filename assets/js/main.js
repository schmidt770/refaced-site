import { mountBooking, selectBoutique } from "./booking.js";
import { initMetrika, bindGoals } from "./metrika.js";

const priceFormat = new Intl.NumberFormat("ru-RU");

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function initHeader() {
  const header = document.getElementById("header");
  const update = () => header.classList.toggle("is-scrolled", window.scrollY > 40);
  update();
  window.addEventListener("scroll", update, { passive: true });
}

function initMenu() {
  const burger = document.getElementById("burger");
  const menu = document.getElementById("menu");
  const setOpen = (open) => {
    document.body.classList.toggle("menu-open", open);
    burger.setAttribute("aria-expanded", String(open));
    menu.setAttribute("aria-hidden", String(!open));
  };
  burger.addEventListener("click", () => setOpen(!document.body.classList.contains("menu-open")));
  menu.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setOpen(false)));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
}

const revealObserver =
  "IntersectionObserver" in window
    ? new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add("is-visible");
            revealObserver.unobserve(entry.target);
          });
        },
        { rootMargin: "0px 0px -8% 0px" }
      )
    : null;

function reveal(root = document) {
  root.querySelectorAll("[data-reveal]:not(.is-visible)").forEach((node) => {
    if (revealObserver) revealObserver.observe(node);
    else node.classList.add("is-visible");
  });
}

function initSliders() {
  document.querySelectorAll("[data-slider]").forEach((slider) => {
    const slides = [...slider.querySelectorAll(".slider__track img")];
    const current = slider.querySelector("[data-slider-current]");
    const total = slider.querySelector("[data-slider-total]");
    let index = 0;
    total.textContent = String(slides.length).padStart(2, "0");

    const show = (next) => {
      index = (next + slides.length) % slides.length;
      slides.forEach((slide, i) => slide.classList.toggle("is-active", i === index));
      current.textContent = String(index + 1).padStart(2, "0");
      const ahead = slides[(index + 1) % slides.length];
      if (ahead.loading === "lazy") ahead.loading = "eager";
    };

    slider.querySelector("[data-slider-prev]").addEventListener("click", () => show(index - 1));
    slider.querySelector("[data-slider-next]").addEventListener("click", () => show(index + 1));

    const track = slider.querySelector(".slider__track");
    let startX = null;
    track.addEventListener("pointerdown", (event) => {
      startX = event.clientX;
    });
    track.addEventListener("pointerup", (event) => {
      if (startX === null) return;
      const delta = event.clientX - startX;
      startX = null;
      if (Math.abs(delta) > 40) show(index + (delta < 0 ? 1 : -1));
    });
    track.addEventListener("pointercancel", () => {
      startX = null;
    });
  });
}

const SHAPE_LABELS = {
  classic: "Классические",
  square: "Квадратные",
  aviator: "Авиаторы",
  round: "Круглые",
  pantos: "Панто",
  nerd: "Интеллектуальные (Nerd)",
  "cat-eye": "Кошачий глаз",
  "cat eye": "Кошачий глаз",
  oval: "Овальные",
  rectangle: "Прямоугольные",
  geometric: "Геометрические",
  rhombus: "Геометрические (ромб)",
  "flat-top": "Флэт-топ",
  mask: "Маска",
  shades: "Шейды",
  butterfly: "Бабочка",
  browline: "Броулайнер",
  clubmaster: "Клабмастер",
  wayfarer: "Вайфарер",
  navigator: "Навигатор",
  oversize: "Оверсайз",
  narrow: "Узкие",
  octagon: "Октагон",
  drop: "Капля",
  trapeciya: "Трапеция",
  sport: "Спортивные",
  sporty: "Спортивные"
};

const BOUTIQUE_NAMES = {
  moyka: "Мойка, 58",
  petrovsky: "Петровский, 22"
};

const FEATURED_BRAND_CHIPS = [
  "Cartier",
  "Gucci",
  "Saint Laurent",
  "Matsuda",
  "MYKITA",
  "Dita",
  "Linda Farrow",
  "Prada",
  "Miu Miu",
  "Cazal",
  "Kuboraum",
  "John Dalia",
  "Kaleos Eyehunters",
  "RETROSUPERFUTURE",
  "LeSpecs"
];

function formatShape(shape) {
  const key = String(shape || "").trim().toLowerCase();
  return SHAPE_LABELS[key] || shape;
}

function getBaseModelFamily(product) {
  const m = String(product.model || "").trim();
  const parts = m.split(/\s+/);
  if (parts.length <= 1) return `${product.brand}::${m}`;
  return `${product.brand}::${parts.slice(0, -1).join(" ")}`;
}

function fallbackSvgHtml(product) {
  const isSun = product.type === "Солнцезащитные очки";
  return `
    <div class="product__fallback">
      <svg viewBox="0 0 180 70" fill="none" stroke-width="1.4" aria-hidden="true">
        <rect x="14" y="16" width="60" height="40" rx="${isSun ? "8" : "18"}" ${isSun ? 'fill="rgba(184,149,95,0.10)"' : ""} />
        <rect x="106" y="16" width="60" height="40" rx="${isSun ? "8" : "18"}" ${isSun ? 'fill="rgba(184,149,95,0.10)"' : ""} />
        <path d="M74 30 C84 22, 96 22, 106 30" />
        <path d="M4 32 L14 26 M166 26 L176 32" />
      </svg>
      <span>${escapeHtml(product.brand)} · ${escapeHtml(product.model)}</span>
    </div>`;
}

function productHtml(product, order) {
  const delay = Math.min(order, 11) * 0.04;
  const boutiques = (product.boutiques || [])
    .map((b) => `<span class="product__badge">${escapeHtml(BOUTIQUE_NAMES[b] || b)}</span>`)
    .join("");
  const mediaInner = product.photo
    ? `<img src="${escapeHtml(product.photo)}?v=11" alt="${escapeHtml(product.title)}" loading="lazy" />`
    : fallbackSvgHtml(product);

  return `
    <article
      class="product"
      tabindex="0"
      role="button"
      aria-label="Открыть карточку: ${escapeHtml(product.title)}"
      data-sku="${escapeHtml(product.sku)}"
      style="animation-delay:${delay.toFixed(2)}s"
    >
      <div class="product__media">
        ${mediaInner}
        ${boutiques ? `<div class="product__badges">${boutiques}</div>` : ""}
      </div>
      <p class="product__brand">${escapeHtml(product.brand)}</p>
      <h3 class="product__title">${escapeHtml(product.model || product.title.replace(product.brand, "").trim())}</h3>
      <div class="product__meta">
        <span>${escapeHtml(product.type)}</span>
        ${product.price ? `<b>${priceFormat.format(product.price)} ₽</b>` : ""}
      </div>
    </article>`;
}

async function initCatalog() {
  const grid = document.getElementById("catalog-grid");
  const tabs = document.getElementById("catalog-filters");
  const searchInput = document.getElementById("catalog-search");
  const searchClear = document.getElementById("catalog-search-clear");
  const priceMinInput = document.getElementById("filter-price-min");
  const priceMaxInput = document.getElementById("filter-price-max");
  const selBoutique = document.getElementById("filter-boutique");
  const selBrand = document.getElementById("filter-brand");
  const selShape = document.getElementById("filter-shape");
  const selAudience = document.getElementById("filter-audience");
  const selRim = document.getElementById("filter-rim");
  const selSort = document.getElementById("filter-sort");
  const brandChipsWrap = document.getElementById("catalog-brand-chips");
  const countNode = document.getElementById("catalog-count");
  const resetBtn = document.getElementById("catalog-reset");
  const moreWrap = document.getElementById("catalog-more-wrap");
  const moreBtn = document.getElementById("catalog-more-btn");

  const modal = document.getElementById("product-modal");
  const modalBody = document.getElementById("product-modal-body");

  let products = [];
  const bySku = new Map();
  const byFamily = new Map();

  try {
    const response = await fetch("assets/data/catalog.json?v=11");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    products = (await response.json()).products || [];
  } catch (error) {
    console.error("Каталог не загрузился", error);
    grid.innerHTML = "";
    return;
  }

  // Индексируем каталог по SKU и группируем одноимённые модели по базовому коду (только для блока «Другие цвета этой модели» внутри модалки)
  products.forEach((p) => {
    const fam = getBaseModelFamily(p);
    if (!byFamily.has(fam)) byFamily.set(fam, []);
    byFamily.get(fam).push(p);
    bySku.set(p.sku, p);
  });

  // Заполняем селект брендов, форм и границы цены
  const brandCounts = new Map();
  const shapeCounts = new Map();
  let catalogMinPrice = Infinity;
  let catalogMaxPrice = 0;
  products.forEach((p) => {
    if (p.brand) brandCounts.set(p.brand, (brandCounts.get(p.brand) || 0) + 1);
    (p.shapes || []).forEach((s) => {
      const key = String(s).trim().toLowerCase();
      if (key) shapeCounts.set(key, (shapeCounts.get(key) || 0) + 1);
    });
    if (p.price && p.price > 0) {
      if (p.price < catalogMinPrice) catalogMinPrice = p.price;
      if (p.price > catalogMaxPrice) catalogMaxPrice = p.price;
    }
  });

  if (priceMinInput && Number.isFinite(catalogMinPrice)) {
    priceMinInput.placeholder = priceFormat.format(catalogMinPrice);
  }
  if (priceMaxInput && catalogMaxPrice > 0) {
    priceMaxInput.placeholder = priceFormat.format(catalogMaxPrice);
  }

  if (selBrand) {
    const sortedBrands = [...brandCounts.entries()].sort((a, b) => a[0].localeCompare(b[0], "ru"));
    selBrand.innerHTML =
      `<option value="">Все бренды (${sortedBrands.length})</option>` +
      sortedBrands
        .map(([b, c]) => `<option value="${escapeHtml(b)}">${escapeHtml(b)} (${c})</option>`)
        .join("");
  }

  if (selShape) {
    const sortedShapes = [...shapeCounts.entries()].sort((a, b) => b[1] - a[1]);
    selShape.innerHTML =
      `<option value="">Любая форма</option>` +
      sortedShapes
        .map(([s, c]) => `<option value="${escapeHtml(s)}">${escapeHtml(formatShape(s))} (${c})</option>`)
        .join("");
  }

  if (brandChipsWrap) {
    const availableFeatured = FEATURED_BRAND_CHIPS.filter((b) => brandCounts.has(b));
    brandChipsWrap.innerHTML =
      `<button type="button" class="catalog-chip is-active" data-chip-brand="">Все бренды</button>` +
      availableFeatured
        .map((b) => `<button type="button" class="catalog-chip" data-chip-brand="${escapeHtml(b)}">${escapeHtml(b)}</button>`)
        .join("");
  }

  const PAGE_SIZE = 16;
  const state = {
    type: "",
    q: "",
    priceMin: null,
    priceMax: null,
    boutique: "",
    brand: "",
    shape: "",
    audience: "",
    rim: "",
    sort: "featured",
    visibleCount: PAGE_SIZE
  };

  function matchesFilters(item, ignoreType = false) {
    if (!ignoreType && state.type && item.type !== state.type) return false;
    const price = item.price || 0;
    if (state.priceMin !== null && price < state.priceMin) return false;
    if (state.priceMax !== null && price > state.priceMax) return false;
    if (state.boutique && !(item.boutiques || []).includes(state.boutique)) return false;
    if (state.brand && item.brand !== state.brand) return false;
    if (state.shape) {
      const itemShapes = (item.shapes || []).map((s) => String(s).trim().toLowerCase());
      if (!itemShapes.includes(state.shape)) return false;
    }
    if (state.audience && String(item.audience || "").toLowerCase() !== state.audience) return false;
    if (state.rim) {
      const r = String(item.rim || "").toLowerCase();
      if (state.rim === "безободковая") {
        if (r !== "безободковая" && r !== "винтовая") return false;
      } else if (state.rim === "полуободковая") {
        if (r !== "полуободковая" && r !== "лесочная") return false;
      } else if (r !== state.rim) {
        return false;
      }
    }
    if (state.q) {
      const q = state.q.toLowerCase();
      const shapeRu = (item.shapes || []).map(formatShape).join(" ");
      const varHay = (item.variants || [])
        .map((v) => `${v.model || ""} ${v.modelRaw || ""} ${v.sku || ""} ${v.color || ""}`)
        .join(" ");
      const hay = `${item.brand || ""} ${item.model || ""} ${item.modelRaw || ""} ${item.sku || ""} ${item.color || ""} ${item.material || ""} ${item.type || ""} ${item.rim || ""} ${shapeRu} ${varHay}`.toLowerCase();
      const words = q.split(/\s+/).filter(Boolean);
      for (const w of words) {
        if (!hay.includes(w)) return false;
      }
    }
    return true;
  }

  function hasActiveFilters() {
    return Boolean(
      state.type ||
        state.q ||
        state.priceMin !== null ||
        state.priceMax !== null ||
        state.boutique ||
        state.brand ||
        state.shape ||
        state.audience ||
        state.rim ||
        state.sort !== "featured"
    );
  }

  function syncBrandChips() {
    if (!brandChipsWrap) return;
    brandChipsWrap.querySelectorAll("[data-chip-brand]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.chipBrand === state.brand);
    });
  }

  function updateTabCounts() {
    const baseList = products.filter((item) => matchesFilters(item, true));
    const counts = {
      "": baseList.length,
      Оправы: baseList.filter((i) => i.type === "Оправы").length,
      "Солнцезащитные очки": baseList.filter((i) => i.type === "Солнцезащитные очки").length
    };
    const labels = {
      "": "Все",
      Оправы: "Оправы",
      "Солнцезащитные очки": "Солнцезащитные"
    };
    tabs.querySelectorAll("[data-type]").forEach((btn) => {
      const t = btn.dataset.type;
      btn.textContent = `${labels[t] || t} (${counts[t] ?? 0})`;
    });
  }

  function render() {
    updateTabCounts();
    syncBrandChips();

    if (searchClear) searchClear.hidden = !state.q;
    if (resetBtn) resetBtn.hidden = !hasActiveFilters();

    const filtered = products.filter((item) => matchesFilters(item, false));

    filtered.sort((a, b) => {
      const aHasPhoto = a.photo ? 0 : 1;
      const bHasPhoto = b.photo ? 0 : 1;
      if (state.sort === "price-desc") {
        if (aHasPhoto !== bHasPhoto && !state.brand && !state.q) return aHasPhoto - bHasPhoto;
        return (b.price || 0) - (a.price || 0);
      }
      if (state.sort === "price-asc") {
        if (aHasPhoto !== bHasPhoto && !state.brand && !state.q) return aHasPhoto - bHasPhoto;
        return (a.price || 0) - (b.price || 0);
      }
      if (state.sort === "brand-asc") {
        if (aHasPhoto !== bHasPhoto && !state.brand && !state.q) return aHasPhoto - bHasPhoto;
        const cmp = String(a.brand || "").localeCompare(String(b.brand || ""), "ru");
        if (cmp !== 0) return cmp;
        return String(a.model || "").localeCompare(String(b.model || ""), "ru");
      }
      // featured: сначала модели с фото, затем представленные сразу в двух бутиках, затем по убыванию цены
      if (aHasPhoto !== bHasPhoto) return aHasPhoto - bHasPhoto;
      const bBout = (b.boutiques || []).length;
      const aBout = (a.boutiques || []).length;
      if (bBout !== aBout) return bBout - aBout;
      return (b.price || 0) - (a.price || 0);
    });

    const total = filtered.length;
    const slice = filtered.slice(0, state.visibleCount);

    if (countNode) {
      countNode.textContent =
        total === 0
          ? "Модели не найдены"
          : `Показано ${slice.length} из ${priceFormat.format(total)} моделей`;
    }

    if (total === 0) {
      grid.innerHTML = `
        <div class="catalog-empty">
          <p>По вашему запросу ничего не найдено</p>
          <button type="button" class="btn btn--ink-outline" data-empty-reset>Сбросить фильтры</button>
        </div>`;
      const emptyReset = grid.querySelector("[data-empty-reset]");
      if (emptyReset) emptyReset.addEventListener("click", resetAllFilters);
    } else {
      grid.innerHTML = slice.map(productHtml).join("");
    }

    if (moreWrap && moreBtn) {
      const rem = total - slice.length;
      if (rem > 0) {
        moreWrap.hidden = false;
        moreBtn.textContent = `Показать ещё (${Math.min(PAGE_SIZE, rem)} из ${priceFormat.format(rem)})`;
      } else {
        moreWrap.hidden = true;
      }
    }
  }

  function resetAllFilters() {
    state.type = "";
    state.q = "";
    state.priceMin = null;
    state.priceMax = null;
    state.boutique = "";
    state.brand = "";
    state.shape = "";
    state.audience = "";
    state.rim = "";
    state.sort = "featured";
    state.visibleCount = PAGE_SIZE;

    if (searchInput) searchInput.value = "";
    if (priceMinInput) priceMinInput.value = "";
    if (priceMaxInput) priceMaxInput.value = "";
    if (selBoutique) selBoutique.value = "";
    if (selBrand) selBrand.value = "";
    if (selShape) selShape.value = "";
    if (selAudience) selAudience.value = "";
    if (selRim) selRim.value = "";
    if (selSort) selSort.value = "featured";
    tabs.querySelectorAll("[data-type]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.type === "");
    });
    render();
  }

  // Обработчики табов и фильтров
  tabs.querySelectorAll("[data-type]").forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.querySelectorAll("[data-type]").forEach((item) => {
        item.classList.toggle("is-active", item === tab);
      });
      state.type = tab.dataset.type;
      state.visibleCount = PAGE_SIZE;
      render();
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      state.q = searchInput.value.trim();
      state.visibleCount = PAGE_SIZE;
      render();
    });
  }

  if (searchClear) {
    searchClear.addEventListener("click", () => {
      state.q = "";
      if (searchInput) {
        searchInput.value = "";
        searchInput.focus();
      }
      state.visibleCount = PAGE_SIZE;
      render();
    });
  }

  const bindPriceInput = (el, key) => {
    if (!el) return;
    el.addEventListener("input", () => {
      const digits = el.value.replace(/\D+/g, "");
      if (!digits) {
        state[key] = null;
        el.value = "";
      } else {
        const num = parseInt(digits, 10);
        state[key] = Number.isFinite(num) ? num : null;
        el.value = Number.isFinite(num) ? priceFormat.format(num) : "";
      }
      state.visibleCount = PAGE_SIZE;
      render();
    });
  };

  bindPriceInput(priceMinInput, "priceMin");
  bindPriceInput(priceMaxInput, "priceMax");

  const bindSelect = (el, key) => {
    if (!el) return;
    el.addEventListener("change", () => {
      state[key] = el.value;
      state.visibleCount = PAGE_SIZE;
      render();
    });
  };

  bindSelect(selBoutique, "boutique");
  bindSelect(selBrand, "brand");
  bindSelect(selShape, "shape");
  bindSelect(selAudience, "audience");
  bindSelect(selRim, "rim");
  bindSelect(selSort, "sort");

  if (brandChipsWrap) {
    brandChipsWrap.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-chip-brand]");
      if (!chip) return;
      const b = chip.dataset.chipBrand;
      state.brand = state.brand === b && b !== "" ? "" : b;
      if (selBrand) selBrand.value = state.brand;
      state.visibleCount = PAGE_SIZE;
      render();
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", resetAllFilters);
  }

  if (moreBtn) {
    moreBtn.addEventListener("click", () => {
      state.visibleCount += PAGE_SIZE;
      render();
    });
  }

  // ---------- Модальное окно карточки товара ----------

  function closeProductModal() {
    if (!modal) return;
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
  }

  function openProductModal(sku) {
    const product = bySku.get(sku);
    if (!product || !modal || !modalBody) return;

    const hasMoyka = (product.boutiques || []).includes("moyka");
    const hasPetrovsky = (product.boutiques || []).includes("petrovsky");
    const preferredBoutique = hasMoyka ? "moyka" : hasPetrovsky ? "petrovsky" : "moyka";

    const fam = getBaseModelFamily(product);
    const siblings = (byFamily.get(fam) || []).filter((s) => s.model !== product.model || s.sku === product.sku);
    const showVariants = siblings.length > 1;

    const specs = [
      ["Артикул / модель", product.modelRaw || product.model],
      ["Категория", product.type],
      ["Конструкция", product.rim],
      ["Форма", (product.shapes || []).map(formatShape).join(", ")],
      ["Материал", product.material],
      ["Цвет", product.color],
      ["Линзы", product.lens],
      ["Размер", product.size],
      ["Кому", product.audience],
      ["Особенности", product.note]
    ].filter(([, val]) => val && String(val).trim() !== "");

    const mediaHtml = product.photo
      ? `<img src="${escapeHtml(product.photo)}?v=11" alt="${escapeHtml(product.title)}" />`
      : fallbackSvgHtml(product);

    modalBody.innerHTML = `
      <div class="pm">
        <div class="pm__media">
          <span class="pm__type-badge">${escapeHtml(product.type)}</span>
          ${mediaHtml}
        </div>
        <div class="pm__body">
          <p class="pm__brand">${escapeHtml(product.brand)}</p>
          <h2 class="pm__title" id="pm-title">${escapeHtml(product.title)}</h2>
          ${product.price ? `<p class="pm__price">${priceFormat.format(product.price)} ₽</p>` : ""}

          <p class="pm__section-label">Наличие в бутиках Санкт-Петербурга</p>
          <div class="pm__boutiques">
            <div class="pm__boutique ${hasMoyka ? "is-available" : ""}">
              <div class="pm__boutique-head">
                <b>REFACED Мойка</b>
                <span class="pm__dot"></span>
              </div>
              <p>наб. реки Мойки, 58</p>
              <span class="pm__boutique-status">${hasMoyka ? "В наличии" : "Нет в наличии"}</span>
            </div>
            <div class="pm__boutique ${hasPetrovsky ? "is-available" : ""}">
              <div class="pm__boutique-head">
                <b>REFACED Петровский</b>
                <span class="pm__dot"></span>
              </div>
              <p>Петровский пр., 22, корп. 2</p>
              <span class="pm__boutique-status">${hasPetrovsky ? "В наличии" : "Нет в наличии"}</span>
            </div>
          </div>

          ${
            showVariants
              ? `<p class="pm__section-label">Другие цвета этой модели (${siblings.length})</p>
                 <div class="pm__variants">
                   ${siblings
                     .map(
                       (sib) =>
                         `<button type="button" class="pm__variant ${sib.sku === product.sku ? "is-active" : ""}" data-pm-sku="${escapeHtml(sib.sku)}">${escapeHtml(sib.model)}</button>`
                     )
                     .join("")}
                 </div>`
              : ""
          }

          <p class="pm__section-label">Характеристики</p>
          <dl class="pm__specs">
            ${specs
              .map(
                ([dt, dd]) => `
              <div class="pm__spec-row">
                <dt>${escapeHtml(dt)}</dt>
                <dd>${escapeHtml(dd)}</dd>
              </div>`
              )
              .join("")}
          </dl>

          <div class="pm__actions">
            <a
              href="#booking"
              class="btn btn--brass"
              data-pm-book="${escapeHtml(preferredBoutique)}"
              data-goal="booking_open"
            >Записаться на примерку</a>
            <a href="tel:+78005004043" class="pm__phone" data-goal="phone_click">
              Бронь по телефону: <b>8 (800) 500-40-43</b>
            </a>
          </div>
        </div>
      </div>`;

    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    modalBody.querySelectorAll("[data-pm-sku]").forEach((btn) => {
      btn.addEventListener("click", () => openProductModal(btn.dataset.pmSku));
    });

    const bookBtn = modalBody.querySelector("[data-pm-book]");
    if (bookBtn) {
      bookBtn.addEventListener("click", () => {
        selectBoutique(bookBtn.dataset.pmBook);
        closeProductModal();
      });
    }
  }

  grid.addEventListener("click", (event) => {
    const card = event.target.closest(".product[data-sku]");
    if (!card) return;
    openProductModal(card.dataset.sku);
  });

  grid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".product[data-sku]");
    if (!card) return;
    event.preventDefault();
    openProductModal(card.dataset.sku);
  });

  if (modal) {
    modal.querySelectorAll("[data-pm-close]").forEach((el) => {
      el.addEventListener("click", closeProductModal);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && modal.classList.contains("is-open")) {
        closeProductModal();
      }
    });
  }

  resetAllFilters();
}

function initTrustCarousel() {
  const track = document.querySelector("[data-trust-track]");
  if (!track) return;
  const prevBtn = document.querySelector("[data-trust-prev]");
  const nextBtn = document.querySelector("[data-trust-next]");

  const getStep = () => {
    const firstCard = track.querySelector(".trust-card");
    if (!firstCard) return 320;
    const gap = parseFloat(getComputedStyle(track).columnGap || getComputedStyle(track).gap || "24") || 24;
    return firstCard.getBoundingClientRect().width + gap;
  };

  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      track.scrollBy({ left: -getStep(), behavior: "smooth" });
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      track.scrollBy({ left: getStep(), behavior: "smooth" });
    });
  }

  let isDown = false;
  let startX = 0;
  let startScroll = 0;

  track.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    isDown = true;
    startX = e.pageX;
    startScroll = track.scrollLeft;
    track.classList.add("is-dragging");
  });

  window.addEventListener("mouseup", () => {
    if (!isDown) return;
    isDown = false;
    track.classList.remove("is-dragging");
  });

  track.addEventListener("mousemove", (e) => {
    if (!isDown) return;
    e.preventDefault();
    const walk = e.pageX - startX;
    track.scrollLeft = startScroll - walk;
  });
}

function initHeroSwitcher() {
  const hero = document.querySelector(".hero[data-hero-mode]");
  const switcher = document.querySelector("[data-hero-switcher]");
  if (!hero || !switcher) return;

  const items = hero.querySelectorAll("[data-hero-item]");
  const buttons = switcher.querySelectorAll("[data-hero-set]");

  const setMode = (mode) => {
    hero.dataset.heroMode = mode;
    items.forEach((el) => {
      const isCurrent = el.dataset.heroItem === mode;
      el.classList.toggle("is-active", isCurrent);
      if (el.tagName === "VIDEO") {
        if (isCurrent) {
          el.play().catch(() => {});
        } else {
          el.pause();
        }
      }
    });
    buttons.forEach((btn) => {
      const active = btn.dataset.heroSet === mode;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  };

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.heroSet));
  });

  const urlMode = new URLSearchParams(window.location.search).get("hero");
  if (urlMode === "photo" || urlMode === "video" || urlMode === "video2") {
    setMode(urlMode);
  } else {
    setMode(hero.dataset.heroMode || "video");
  }
}

function initBgSwitcher() {
  const root = document.documentElement;
  const switcher = document.querySelector("[data-bg-switcher]");
  const validModes = ["passepartout", "gradient", "monolith"];

  const setBgMode = (mode) => {
    const next = validModes.includes(mode) ? mode : "passepartout";
    root.dataset.bgMode = next;
    if (switcher) {
      switcher.querySelectorAll("[data-bg-set]").forEach((btn) => {
        const active = btn.dataset.bgSet === next;
        btn.classList.toggle("is-active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }
  };

  if (switcher) {
    switcher.querySelectorAll("[data-bg-set]").forEach((btn) => {
      btn.addEventListener("click", () => setBgMode(btn.dataset.bgSet));
    });
  }

  const urlBg = new URLSearchParams(window.location.search).get("bg");
  if (validModes.includes(urlBg)) {
    setBgMode(urlBg);
  } else {
    setBgMode(root.dataset.bgMode || "passepartout");
  }
}

function initBookingLinks() {
  document.querySelectorAll("[data-book]").forEach((link) => {
    link.addEventListener("click", () => selectBoutique(link.dataset.book));
  });
}

initMetrika();
bindGoals();
initHeader();
initMenu();
initHeroSwitcher();
initBgSwitcher();
initSliders();
initTrustCarousel();
initCatalog();
initBookingLinks();
mountBooking(document.getElementById("booking-root"));
reveal();
document.getElementById("year").textContent = new Date().getFullYear();

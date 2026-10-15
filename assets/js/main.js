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

function productHtml(product, order) {
  return `
    <article class="product" style="animation-delay:${order * 0.06}s">
      <div class="product__media">
        <img src="${escapeHtml(product.photo)}" alt="${escapeHtml(product.title)}" loading="lazy" onerror="this.remove()" />
      </div>
      <p class="product__brand">${escapeHtml(product.brand)}</p>
      <h3 class="product__title">${escapeHtml(product.title.replace(product.brand, "").trim())}</h3>
      <div class="product__meta">
        <span>${escapeHtml(product.type)}</span>
        ${product.price ? `<b>${priceFormat.format(product.price)} ₽</b>` : ""}
      </div>
    </article>`;
}

async function initCatalog() {
  const grid = document.getElementById("catalog-grid");
  const tabs = document.getElementById("catalog-filters");
  let products = [];
  try {
    const response = await fetch("assets/data/catalog.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    products = (await response.json()).products || [];
  } catch (error) {
    console.error("Каталог не загрузился", error);
    grid.innerHTML = "";
    return;
  }

  const render = (type) => {
    const list = type ? products.filter((item) => item.type === type) : products;
    grid.innerHTML = list.map(productHtml).join("");
  };

  tabs.querySelectorAll("[data-type]").forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.querySelectorAll("[data-type]").forEach((item) => {
        item.classList.toggle("is-active", item === tab);
      });
      render(tab.dataset.type);
    });
  });
  render("");
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
initSliders();
initCatalog();
initBookingLinks();
mountBooking(document.getElementById("booking-root"));
reveal();
document.getElementById("year").textContent = new Date().getFullYear();

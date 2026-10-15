// Запись на диагностику: бутик → дата → время → имя/телефон.
// Логика — из Mini App (optics-bot/webapp/static/booking.js), без Telegram.

import { DEMO, getBoutiques, getSlots, createBooking } from "./booking-api.js";
import { reachGoal } from "./metrika.js";

const WEEKDAYS = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

const state = {
  boutiques: [],
  boutiqueId: null,
  dates: [],
  date: null,
  time: null,
  name: "",
  phone: "",
  consent: false,
  busy: false,
  error: "",
  success: null,
};

let root = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function dayLabel(iso) {
  const day = new Date(iso + "T12:00:00");
  return {
    weekday: WEEKDAYS[day.getDay()],
    day: String(day.getDate()),
    month: MONTHS[day.getMonth()],
  };
}

function humanDate(iso) {
  const label = dayLabel(iso);
  return `${label.day} ${label.month}, ${label.weekday}`;
}

function phoneDigits(value) {
  return String(value).replace(/\D/g, "");
}

export async function mountBooking(element) {
  root = element;
  try {
    state.boutiques = await getBoutiques();
    if (!state.boutiqueId) state.boutiqueId = state.boutiques[0]?.id || null;
    await loadSlots();
  } catch (error) {
    console.error(error);
    root.innerHTML = `<p class="booking__status">Не удалось загрузить расписание. Позвоните нам — запишем по телефону.</p>`;
  }
}

// «Записаться сюда» в карточке бутика
export function selectBoutique(boutiqueId) {
  if (!state.boutiques.some((item) => item.id === boutiqueId)) {
    state.boutiqueId = boutiqueId;
    return;
  }
  if (state.boutiqueId === boutiqueId && !state.success) return;
  state.boutiqueId = boutiqueId;
  state.date = null;
  state.time = null;
  state.success = null;
  loadSlots();
}

async function loadSlots() {
  if (!state.boutiqueId) return;
  state.error = "";
  state.dates = await getSlots(state.boutiqueId);
  if (!state.dates.some((item) => item.date === state.date)) {
    state.date = state.dates[0]?.date || null;
    state.time = null;
  }
  render();
}

function selectedDate() {
  return state.dates.find((item) => item.date === state.date) || null;
}

function stepLabel(number, title) {
  return `<div class="step__label"><i>${number}</i>${escapeHtml(title)}</div>`;
}

function renderSuccess() {
  const booking = state.success;
  root.innerHTML = `
    <div class="booking__success">
      <p class="eyebrow">Запись подтверждена</p>
      <h3>До встречи <em>в&nbsp;REFACED</em></h3>
      <p class="booking__when">${escapeHtml(booking.boutiqueName)}<br>${escapeHtml(
        humanDate(booking.date)
      )}, ${escapeHtml(booking.time)}</p>
      <p>${escapeHtml(booking.name)} · ${escapeHtml(booking.phone)}</p>
      ${DEMO ? `<p class="booking__empty">Демо-режим: запись не отправлена.</p>` : ""}
      <button class="btn btn--line" type="button" id="booking-again">Записаться ещё раз</button>
    </div>`;
  root.querySelector("#booking-again").onclick = () => {
    state.success = null;
    state.time = null;
    loadSlots();
  };
}

function render() {
  if (state.success) {
    renderSuccess();
    return;
  }

  const times = selectedDate()?.times || [];
  const month = state.date ? dayLabel(state.date).month : "";
  root.innerHTML = `
    <div class="step">
      ${stepLabel("01", "Бутик")}
      <div class="places">
        ${state.boutiques
          .map(
            (item) => `<button type="button" class="place${
              item.id === state.boutiqueId ? " is-active" : ""
            }" data-boutique="${escapeHtml(item.id)}"><b>${escapeHtml(
              item.short || item.name
            )}</b><span>${escapeHtml(item.address)}</span></button>`
          )
          .join("")}
      </div>
    </div>

    <div class="step">
      ${stepLabel("02", month ? `Дата · ${month}` : "Дата")}
      ${
        state.dates.length
          ? `<div class="days">${state.dates
              .map((item) => {
                const label = dayLabel(item.date);
                return `<button type="button" class="day${
                  item.date === state.date ? " is-active" : ""
                }" data-date="${item.date}"><small>${label.weekday}</small><b>${label.day}</b></button>`;
              })
              .join("")}</div>`
          : `<p class="booking__empty">На ближайшие дни свободного времени нет — позвоните нам.</p>`
      }
    </div>

    <div class="step">
      ${stepLabel("03", "Время")}
      ${
        times.length
          ? `<div class="times">${times
              .map(
                (item) => `<button type="button" class="time${
                  item.time === state.time ? " is-active" : ""
                }" data-time="${item.time}">${escapeHtml(item.time)}</button>`
              )
              .join("")}</div>`
          : `<p class="booking__empty">Выберите дату.</p>`
      }
    </div>

    <div class="step">
      ${stepLabel("04", "Контакты")}
      <div class="fields">
        <label class="field">
          <span>Имя</span>
          <input type="text" id="booking-name" autocomplete="name" placeholder="Как к вам обращаться" value="${escapeHtml(state.name)}" />
        </label>
        <label class="field">
          <span>Телефон</span>
          <input type="tel" id="booking-phone" autocomplete="tel" inputmode="tel" placeholder="+7" value="${escapeHtml(state.phone)}" />
        </label>
      </div>
      <label class="consent">
        <input type="checkbox" id="booking-consent" ${state.consent ? "checked" : ""} />
        <span>Согласен на обработку персональных данных</span>
      </label>
    </div>

    ${state.error ? `<p class="booking__error">${escapeHtml(state.error)}</p>` : ""}

    <button class="btn btn--brass booking__submit" type="button" id="booking-submit" ${state.busy ? "disabled" : ""}>
      ${state.busy ? "Записываем…" : "Записаться"}
    </button>`;

  root.querySelectorAll("[data-boutique]").forEach((button) => {
    button.onclick = () => selectBoutique(button.dataset.boutique);
  });
  root.querySelectorAll("[data-date]").forEach((button) => {
    button.onclick = () => {
      state.date = button.dataset.date;
      state.time = null;
      render();
    };
  });
  root.querySelectorAll("[data-time]").forEach((button) => {
    button.onclick = () => {
      state.time = button.dataset.time;
      render();
    };
  });
  const name = root.querySelector("#booking-name");
  const phone = root.querySelector("#booking-phone");
  const consent = root.querySelector("#booking-consent");
  name.oninput = () => (state.name = name.value);
  phone.oninput = () => (state.phone = phone.value);
  consent.onchange = () => (state.consent = consent.checked);
  root.querySelector("#booking-submit").onclick = submit;
}

async function submit() {
  state.error = "";
  if (!state.boutiqueId || !state.date || !state.time) {
    state.error = "Выберите бутик, дату и время.";
  } else if (!state.name.trim()) {
    state.error = "Укажите имя.";
  } else if (phoneDigits(state.phone).length < 10) {
    state.error = "Проверьте номер телефона.";
  } else if (!state.consent) {
    state.error = "Нужно согласие на обработку персональных данных.";
  }
  if (state.error) {
    render();
    return;
  }

  state.busy = true;
  render();
  try {
    const result = await createBooking({
      boutiqueId: state.boutiqueId,
      date: state.date,
      time: state.time,
      name: state.name.trim(),
      phone: state.phone.trim(),
    });
    state.busy = false;
    if (!result.ok) {
      state.error = result.message || "Это время уже заняли. Выберите другое.";
      await loadSlots();
      return;
    }
    state.success = result.booking;
    reachGoal("booking_submit");
    render();
  } catch (error) {
    console.error(error);
    state.busy = false;
    state.error = "Сеть недоступна. Попробуйте ещё раз.";
    render();
  }
}

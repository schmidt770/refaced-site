// Яндекс Метрика. Пока номера счётчика нет, цели только пишутся в консоль.
// [PLACEHOLDER: пользователь] номер счётчика.

const COUNTER_ID = null;

export function initMetrika() {
  if (!COUNTER_ID) return;
  window.ym =
    window.ym ||
    function () {
      (window.ym.a = window.ym.a || []).push(arguments);
    };
  window.ym.l = Date.now();
  const script = document.createElement("script");
  script.async = true;
  script.src = "https://mc.yandex.ru/metrika/tag.js";
  document.head.append(script);
  window.ym(COUNTER_ID, "init", {
    clickmap: true,
    trackLinks: true,
    accurateTrackBounce: true,
    webvisor: true,
  });
}

export function reachGoal(name) {
  if (COUNTER_ID && window.ym) window.ym(COUNTER_ID, "reachGoal", name);
  else console.debug("[metrika] goal", name);
}

// Цели из разметки: data-goal="phone_click" | "map_click" | "booking_open"
export function bindGoals(root = document) {
  root.addEventListener("click", (event) => {
    const node = event.target.closest("[data-goal]");
    if (node) reachGoal(node.dataset.goal);
  });
}

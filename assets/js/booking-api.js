// Источник данных записи. Сейчас демо: слоты строятся в браузере по шаблону
// недели из Mini App (optics-bot/data/schedule_template.csv), запись никуда
// не уходит. На этапе 2 функции станут запросами к серверу — интерфейс тот же.

export const DEMO = true;

const BOUTIQUES = [
  { id: "moyka", name: "REFACED Мойка", short: "Мойка", address: "наб. реки Мойки, 58" },
  { id: "petrovsky", name: "REFACED Петровский", short: "Петровский", address: "Петровский пр., 22, корп. 2" },
];

// День недели (0 — воскресенье) → часы приёма. Воскресенье выходной.
const TEMPLATE = {
  moyka: { days: [1, 2, 3, 4, 5, 6], from: "11:00", to: "19:00", step: 30 },
  petrovsky: { days: [1, 2, 3, 4, 5, 6], from: "11:00", to: "19:00", step: 30 },
};

const DAYS_AHEAD = 14;

function toMinutes(time) {
  const [h, m] = time.split(":").map(Number);
  return h * 60 + m;
}

function toTime(minutes) {
  const h = String(Math.floor(minutes / 60)).padStart(2, "0");
  const m = String(minutes % 60).padStart(2, "0");
  return `${h}:${m}`;
}

function isoDate(day) {
  const y = day.getFullYear();
  const m = String(day.getMonth() + 1).padStart(2, "0");
  const d = String(day.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export async function getBoutiques() {
  return BOUTIQUES;
}

export async function getSlots(boutiqueId) {
  const rule = TEMPLATE[boutiqueId];
  if (!rule) return [];
  const now = new Date();
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const dates = [];
  for (let offset = 0; offset < DAYS_AHEAD; offset += 1) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
    if (!rule.days.includes(day.getDay())) continue;
    const times = [];
    for (let t = toMinutes(rule.from); t < toMinutes(rule.to); t += rule.step) {
      if (offset === 0 && t <= nowMinutes) continue;
      times.push({ time: toTime(t) });
    }
    if (times.length) dates.push({ date: isoDate(day), times });
  }
  return dates;
}

export async function createBooking(payload) {
  const boutique = BOUTIQUES.find((item) => item.id === payload.boutiqueId);
  return {
    ok: true,
    booking: { ...payload, boutiqueName: boutique ? boutique.name : "" },
  };
}

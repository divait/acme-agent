// Human-readable rendering of canonical slot values for the profile panel. Pure, no DOM.

const WORDS = {
  en: {
    yes: "Yes", no: "No",
    roles: { crew_member: "Crew member", kitchen: "Kitchen team", delivery_rider: "Delivery rider" },
    days: { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" },
    shifts: { morning: "Mornings", afternoon: "Afternoons", night: "Nights" },
    hours: (n) => `${n} h/week`,
    months: (n) => `${n} ${n === 1 ? "month" : "months"}`,
  },
  es: {
    yes: "Sí", no: "No",
    roles: { crew_member: "Equipo de sala", kitchen: "Equipo de cocina", delivery_rider: "Repartidor" },
    days: { mon: "lun", tue: "mar", wed: "mié", thu: "jue", fri: "vie", sat: "sáb", sun: "dom" },
    shifts: { morning: "Mañanas", afternoon: "Tardes", night: "Noches" },
    hours: (n) => `${n} h/semana`,
    months: (n) => `${n} ${n === 1 ? "mes" : "meses"}`,
  },
};
const SHIFT_ORDER = ["morning", "afternoon", "night"];
const DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

// The server sends strings as they are and everything else as JSON text.
function parseJson(value) {
  try { return JSON.parse(value); } catch { return value; }
}

function pairs(value) {
  const data = typeof value === "string" && value.trim().startsWith("[") ? parseJson(value) : value;
  const items = Array.isArray(data) ? data : String(data).split(",");
  return items.map((it) => {
    if (it && typeof it === "object") return [String(it.day), String(it.shift)];
    const [d, s] = String(it).trim().toLowerCase().split(":");
    return [d, s];
  });
}

function availability(value, w) {
  const byShift = new Map();
  for (const [day, shift] of pairs(value)) {
    if (!DAY_ORDER.includes(day) || !SHIFT_ORDER.includes(shift)) return String(value);
    byShift.set(shift, [...(byShift.get(shift) || []), day]);
  }
  return SHIFT_ORDER.filter((s) => byShift.has(s))
    .map((s) => {
      const days = DAY_ORDER.filter((d) => byShift.get(s).includes(d));
      return `${w.shifts[s]}: ${days.map((d) => w.days[d]).join(", ")}`;
    })
    .join(" · ");
}

function date(value, lang) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value).trim());
  if (!m) return String(value);
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", year: "numeric" }).format(d);
}

function languages(value, lang) {
  const data = typeof value === "string" && value.trim().startsWith("[") ? parseJson(value) : value;
  const codes = Array.isArray(data) ? data : String(data).split(",");
  let names = null;
  try { names = new Intl.DisplayNames(lang, { type: "language" }); } catch { /* fall back to codes */ }
  return codes
    .map((c) => String(c).trim())
    .filter(Boolean)
    .map((c) => {
      try { return names?.of(c) || c; } catch { return c; }
    })
    .join(", ");
}

export function formatValue(slot, value, lang) {
  const w = WORDS[lang] || WORDS.en;
  const text = String(value);
  const number = /^\d+$/.test(text.trim()) ? Number(text) : null;
  switch (slot) {
    case "consent_recording":
    case "right_to_work":
    case "is_18_or_over":
    case "driving_licence":
    case "own_vehicle": {
      const t = text.trim().toLowerCase();
      if (t === "true" || t === "yes") return w.yes;
      if (t === "false" || t === "no") return w.no;
      return text;
    }
    case "role":
      return w.roles[text.trim()] || text;
    case "availability":
      return availability(value, w);
    case "start_date":
      return date(value, lang);
    case "weekly_hours":
      return number === null ? text : w.hours(number);
    case "experience_months":
      return number === null ? text : w.months(number);
    case "languages":
      return languages(value, lang);
    default:
      return text;
  }
}

const DECLINED_LINE = {
  en: "Thank you for your time. Nothing from this conversation has been stored. You can contact the hiring team at any time.",
  es: "Gracias por tu tiempo. No se ha guardado nada de esta conversación. Puedes contactar con el equipo de selección cuando quieras.",
};

// The candidate's closing line; null means keep the default "we will review" text.
export function declinedLine(reason, lang) {
  return reason === "declined_consent" ? DECLINED_LINE[lang] || DECLINED_LINE.en : null;
}

// First-visit default for the language selector, from a navigator.language string.
export function pickDefaultLanguage(navLang) {
  return String(navLang || "").toLowerCase().startsWith("es") ? "es" : "en";
}

// Levels are RMS values in 0..1. Above the thresholds the orb shows who is speaking;
// Ana wins over the microphone (her voice can leak into it).
export const ORB_AGENT_THRESHOLD = 0.02;
export const ORB_MIC_THRESHOLD = 0.04;

export function orbState(agentLevel, micLevel) {
  if (agentLevel > ORB_AGENT_THRESHOLD) return "agent";
  if (micLevel > ORB_MIC_THRESHOLD) return "candidate";
  return "idle";
}

// Orb size boost in 0..1 for the active speaker's level (speech RMS rarely exceeds ~0.3).
export function orbIntensity(level) {
  const v = Number(level);
  return Number.isFinite(v) ? Math.max(0, Math.min(1, v * 3.5)) : 0;
}

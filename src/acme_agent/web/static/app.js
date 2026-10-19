// Acme Burgers voice screening client. Plain ES module, no dependencies.
// Server contract: docs/TECHNICAL_DESIGN.md section 2 (JSON control frames + binary PCM audio).

import { declinedLine, formatValue, orbIntensity, orbState, pickDefaultLanguage } from "./format.js";

export { declinedLine, formatValue, orbIntensity, orbState, pickDefaultLanguage };

// Bump with any worklet change: the worklet URLs carry it, so a new app.js never loads stale worklets.
const APP_VERSION = "2";
const CAPTURE_RATE = 16000;
const PLAY_RATE = 24000;
const MAX_BUFFERED = 256 * 1024; // drop mic frames if the socket is this far behind

const LANG_KEY = "acme_lang";
const LOCALES = { es: "es-ES", en: "en-US" };

function initialLang() {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === "es" || saved === "en") return saved;
  } catch { /* storage unavailable */ }
  return pickDefaultLanguage(navigator.language);
}

let lang = initialLang();

const STRINGS = {
  en: {
    demo: "Demo, fictional company",
    languageLabel: "Interview language",
    landingTitle: "Talk to Ana about your application",
    landingIntro:
      "Ana is Acme Burgers' voice assistant. She will ask a few short questions about the role, your contact details, availability and experience. It takes about five minutes. Please allow microphone access when your browser asks, and find a quiet spot.",
    landingPrivacy:
      "Privacy: the transcript and your details are stored only if you give consent during the conversation. No audio is stored.",
    start: "Start interview",
    connecting: "Connecting... Ana will greet you in a few seconds.",
    captions: "Conversation",
    you: "You",
    ana: "Ana",
    textLabel: "Type an answer instead",
    textPlaceholder: "Type an answer if you cannot speak",
    send: "Send",
    end: "End interview",
    liveTitle: "Live interview",
    showConvo: "Show conversation",
    hideConvo: "Hide conversation",
    typeBtn: "Type",
    orbAgent: "Ana is speaking...",
    orbCandidate: "I am listening...",
    orbIdle: "Waiting for you...",
    profile: "Your application",
    processing: "Processing... we are preparing your summary.",
    summaryTitle: "Thank you, interview finished",
    summaryNeutral:
      "Thank you. A person from the Acme Burgers hiring team will review your application and contact you.",
    demoPanel: "Demo: recruiter view",
    profileTitle: "Candidate profile",
    complete: "Interview complete",
    incomplete: "Interview incomplete",
    endReasonLabel: "How it ended",
    toneLabel: "Tone",
    endReasons: {
      completed: "Completed",
      abandoned: "Ended early by the candidate",
      escalated: "Escalated to a recruiter",
      declined_consent: "Declined consent",
    },
    tone: {
      negative: "negative",
      neutral: "neutral",
      positive: "positive",
      improving: "improving",
      stable: "stable",
      worsening: "worsening",
      average: "average",
      trend: "trend",
      signals: "frustration signals",
    },
    nextSteps: "Recruiter next steps",
    candidateQuestions: "Candidate questions",
    again: "Start a new interview",
    errorTitle: "Something went wrong",
    slotState: { empty: "pending", filled: "filled", invalid: "needs correction", unresolved: "unresolved" },
    errors: {
      mic_denied:
        "Microphone access was blocked. Allow the microphone for this site in your browser settings, then start a new interview.",
      mic_missing: "No microphone was found. Connect one and start a new interview.",
      mic_error: "The microphone could not be started. Check that no other app is using it, then start a new interview.",
      audio_unsupported: "This browser cannot capture audio. Try a recent Chrome, Edge, Firefox or Safari.",
      server_down: "We could not reach the interview service. Check your connection and start a new interview in a moment.",
      busy: "Too many interviews were started just now. Wait a minute and start a new interview.",
      lost: "The connection was lost and the interview ended. Start a new interview to try again.",
      rejected: "The interview could not be opened (the link may have been used already). Start a new interview.",
      server: "The interview had a problem.",
      session_failed: "Something went wrong with the interview. We are saving your answers so far.",
      session_failed_unsaved: "Something went wrong with the interview and it could not be saved.",
    },
    slots: {
      consent_recording: "Consent to record",
      role: "Role",
      full_name: "Full name",
      phone: "Phone",
      email: "Email",
      preferred_store_id: "Preferred store",
      availability: "Availability",
      weekly_hours: "Hours per week",
      start_date: "Start date",
      right_to_work: "Right to work",
      is_18_or_over: "18 or over",
      driving_licence: "Driving licence",
      own_vehicle: "Own vehicle",
      experience_months: "Experience (months)",
      experience_summary: "Experience summary",
      languages: "Languages",
    },
  },
  es: {
    demo: "Demo, empresa ficticia",
    languageLabel: "Idioma de la entrevista",
    landingTitle: "Habla con Ana sobre tu candidatura",
    landingIntro:
      "Ana es la asistente de voz de Acme Burgers. Te hará unas preguntas breves sobre el puesto, tus datos de contacto, tu disponibilidad y tu experiencia. Dura unos cinco minutos. Permite el acceso al micrófono cuando el navegador lo pida y busca un sitio tranquilo.",
    landingPrivacy:
      "Privacidad: la transcripción y tus datos solo se guardan si das tu consentimiento durante la conversación. No se guarda el audio.",
    start: "Empezar entrevista",
    connecting: "Conectando... Ana te saludará en unos segundos.",
    captions: "Conversación",
    you: "Tú",
    ana: "Ana",
    textLabel: "Escribe una respuesta",
    textPlaceholder: "Escribe una respuesta si no puedes hablar",
    send: "Enviar",
    end: "Terminar entrevista",
    liveTitle: "Entrevista en directo",
    showConvo: "Mostrar conversación",
    hideConvo: "Ocultar conversación",
    typeBtn: "Escribir",
    orbAgent: "Ana está hablando...",
    orbCandidate: "Te escucho...",
    orbIdle: "Esperando tu respuesta...",
    profile: "Tu candidatura",
    processing: "Procesando... estamos preparando tu resumen.",
    summaryTitle: "Gracias, entrevista terminada",
    summaryNeutral:
      "Gracias. Una persona del equipo de selección de Acme Burgers revisará tu candidatura y se pondrá en contacto contigo.",
    demoPanel: "Demo: vista del reclutador",
    profileTitle: "Perfil del candidato",
    complete: "Entrevista completa",
    incomplete: "Entrevista incompleta",
    endReasonLabel: "Cómo terminó",
    toneLabel: "Tono",
    endReasons: {
      completed: "Completada",
      abandoned: "Terminada antes por el candidato",
      escalated: "Derivada a un reclutador",
      declined_consent: "Rechazó el consentimiento",
    },
    tone: {
      negative: "negativo",
      neutral: "neutral",
      positive: "positivo",
      improving: "mejorando",
      stable: "estable",
      worsening: "empeorando",
      average: "promedio",
      trend: "tendencia",
      signals: "señales de frustración",
    },
    nextSteps: "Próximos pasos para el reclutador",
    candidateQuestions: "Preguntas del candidato",
    again: "Empezar una nueva entrevista",
    errorTitle: "Algo ha salido mal",
    slotState: { empty: "pendiente", filled: "completado", invalid: "hay que corregirlo", unresolved: "sin resolver" },
    errors: {
      mic_denied:
        "Se bloqueó el acceso al micrófono. Permite el micrófono para este sitio en los ajustes del navegador y empieza una nueva entrevista.",
      mic_missing: "No se encontró ningún micrófono. Conecta uno y empieza una nueva entrevista.",
      mic_error: "No se pudo iniciar el micrófono. Comprueba que ninguna otra aplicación lo esté usando y empieza una nueva entrevista.",
      audio_unsupported: "Este navegador no puede capturar audio. Prueba con una versión reciente de Chrome, Edge, Firefox o Safari.",
      server_down: "No hemos podido conectar con el servicio de entrevistas. Revisa tu conexión y empieza una nueva entrevista en un momento.",
      busy: "Se han iniciado demasiadas entrevistas. Espera un minuto y empieza una nueva.",
      lost: "Se perdió la conexión y la entrevista terminó. Empieza una nueva entrevista para intentarlo otra vez.",
      rejected: "No se pudo abrir la entrevista (puede que el enlace ya se haya usado). Empieza una nueva entrevista.",
      server: "La entrevista tuvo un problema.",
      session_failed: "Algo ha fallado en la entrevista. Estamos guardando tus respuestas hasta ahora.",
      session_failed_unsaved: "Algo ha fallado en la entrevista y no se ha podido guardar.",
    },
    slots: {
      consent_recording: "Consentimiento de grabación",
      role: "Puesto",
      full_name: "Nombre completo",
      phone: "Teléfono",
      email: "Correo electrónico",
      preferred_store_id: "Tienda preferida",
      availability: "Disponibilidad",
      weekly_hours: "Horas por semana",
      start_date: "Fecha de inicio",
      right_to_work: "Permiso de trabajo",
      is_18_or_over: "Mayor de 18",
      driving_licence: "Carné de conducir",
      own_vehicle: "Vehículo propio",
      experience_months: "Experiencia (meses)",
      experience_summary: "Resumen de experiencia",
      languages: "Idiomas",
    },
  },
};
let T = STRINGS[lang];

// Same order as the server's slot list; rider-only slots stay hidden until activated.
const SLOT_ORDER = [
  "consent_recording", "role", "full_name", "phone", "email", "preferred_store_id",
  "availability", "weekly_hours", "start_date", "right_to_work", "is_18_or_over",
  "driving_licence", "own_vehicle", "experience_months", "experience_summary", "languages",
];
// Optional slots Ana never asks: shown only once a candidate volunteers them.
const OPTIONAL_HIDDEN = new Set(["email", "experience_summary", "languages"]);
const RIDER_ONLY = new Set(["driving_licence", "own_vehicle"]);
const MARKS = { empty: "·", filled: "✓", invalid: "!", unresolved: "?" };

const $ = (id) => document.getElementById(id);
const VIEWS = ["landing", "connecting", "live", "processing", "summary", "error"];
const DRAIN_CAP_MS = 15000; // longest we keep the speaker context open for Ana's last words

let page = "landing";
let session = null; // one object per interview; ids are single-use, never reused

function show(view) {
  page = view;
  for (const v of VIEWS) $(v).hidden = v !== view;
  // Keep keyboard and screen-reader focus on something visible after each view change.
  const target =
    view === "connecting" ? $("connecting-text")
    : view === "live" ? $("live-title")
    : view === "summary" || view === "error" ? $(view).querySelector("h1")
    : null;
  if (target) {
    target.tabIndex = -1;
    target.focus();
  }
}

function setLang(next) {
  lang = next;
  T = STRINGS[lang];
  try { localStorage.setItem(LANG_KEY, lang); } catch { /* storage unavailable */ }
  applyStaticText();
}

function applyStaticText() {
  document.documentElement.lang = lang;
  for (const code of ["es", "en"]) $(`lang-${code}`).checked = code === lang;
  $("lang-legend").textContent = T.languageLabel;
  const set = (id, text) => { $(id).textContent = text; };
  set("demo-tag", T.demo);
  set("landing-title", T.landingTitle);
  set("landing-intro", T.landingIntro);
  set("landing-privacy", T.landingPrivacy);
  set("start", T.start);
  set("connecting-text", T.connecting);
  set("captions-title", T.captions);
  set("live-title", T.liveTitle);
  syncControls();
  renderOrbStatus();
  set("text-label", T.textLabel);
  set("text-send", T.send);
  set("end", T.end);
  set("profile-title", T.profile);
  set("processing-text", T.processing);
  set("summary-title", T.summaryTitle);
  set("summary-neutral", T.summaryNeutral);
  set("demo-label", T.demoPanel);
  set("final-profile-title", T.profileTitle);
  set("end-reason-label", T.endReasonLabel);
  set("tone-label", T.toneLabel);
  set("steps-title", T.nextSteps);
  set("questions-title", T.candidateQuestions);
  set("again-summary", T.again);
  set("again-error", T.again);
  set("error-title", T.errorTitle);
  $("text-input").placeholder = T.textPlaceholder;
}

// ---- orb --------------------------------------------------------------------------------

const ORB_HOLD_MS = 500; // keep a speaker state this long after the level drops
const LEVEL_STALE_MS = 400; // a worklet that stopped reporting counts as silent
const reducedMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
let orb = { state: "idle", agent: 0, mic: 0, agentAt: 0, micAt: 0, activeAt: 0 };

function renderOrbStatus() {
  const text = { agent: T.orbAgent, candidate: T.orbCandidate, idle: T.orbIdle }[orb.state];
  const el = $("orb-status");
  if (el.textContent !== text) el.textContent = text; // live region: only on state changes
}

function orbReset() {
  orb = { state: "idle", agent: 0, mic: 0, agentAt: 0, micAt: 0, activeAt: 0 };
  updateOrb();
}

function onLevel(kind, level) {
  const now = performance.now();
  if (kind === "agent") { orb.agent = level; orb.agentAt = now; } else { orb.mic = level; orb.micAt = now; }
  updateOrb();
}

function updateOrb() {
  const now = performance.now();
  const agent = now - orb.agentAt < LEVEL_STALE_MS ? orb.agent : 0;
  const mic = now - orb.micAt < LEVEL_STALE_MS ? orb.mic : 0;
  let state = orbState(agent, mic);
  if (state !== "idle") orb.activeAt = now;
  else if (orb.state !== "idle" && now - orb.activeAt < ORB_HOLD_MS) state = orb.state;
  const el = $("orb");
  if (state !== orb.state) {
    orb.state = state;
    el.dataset.state = state;
    renderOrbStatus();
  }
  const level = state === "agent" ? agent : state === "candidate" ? mic : 0;
  const lvl = reducedMotion && reducedMotion.matches ? 0 : orbIntensity(level);
  el.style.setProperty("--lvl", lvl.toFixed(3));
}

function syncControls() {
  const convo = !$("convo").hidden;
  $("toggle-convo").textContent = convo ? T.hideConvo : T.showConvo;
  $("toggle-convo").setAttribute("aria-expanded", String(convo));
  $("toggle-type").textContent = T.typeBtn;
  $("toggle-type").setAttribute("aria-expanded", String(!$("text-form").hidden));
}

function resetPanels() {
  $("convo").hidden = true;
  $("text-form").hidden = true;
  syncControls();
}

// ---- captions ---------------------------------------------------------------------------

let stick = true;
function scrollCaptions() {
  const box = $("captions");
  if (stick) box.scrollTop = box.scrollHeight;
}

function addTurn(speaker) {
  const el = document.createElement("p");
  el.className = `turn ${speaker}`;
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = speaker === "agent" ? T.ana : T.you;
  const txt = document.createElement("span");
  txt.className = "txt";
  el.append(who, txt);
  $("captions").append(el);
  return el;
}

function onTranscript(msg) {
  const open = session.open;
  let el = open[msg.speaker];
  if (!el) {
    el = addTurn(msg.speaker);
    open[msg.speaker] = el;
  }
  el.querySelector(".txt").textContent = msg.text;
  if (msg.final) {
    el.classList.remove("partial");
    open[msg.speaker] = null;
    // Screen readers hear only finished turns, never the partial rewrites.
    const live = document.createElement("p");
    live.textContent = `${msg.speaker === "agent" ? T.ana : T.you}: ${msg.text}`;
    $("captions-live").replaceChildren(live);
  } else {
    el.classList.add("partial");
  }
  scrollCaptions();
}

// ---- profile panel ----------------------------------------------------------------------

function buildProfile() {
  const list = $("slots");
  list.replaceChildren();
  for (const name of SLOT_ORDER) {
    const li = document.createElement("li");
    li.id = `slot-${name}`;
    li.dataset.status = "empty";
    li.hidden = RIDER_ONLY.has(name) || OPTIONAL_HIDDEN.has(name);
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = MARKS.empty;
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = T.slots[name];
    const state = document.createElement("span");
    state.className = "sr-only";
    state.textContent = ` (${T.slotState.empty})`;
    label.append(state);
    const value = document.createElement("span");
    value.className = "value";
    li.append(mark, label, value);
    list.append(li);
  }
  setProgress(0);
}

function setProgress(p) {
  const pct = Math.round(Math.max(0, Math.min(1, p)) * 100);
  $("bar").style.width = `${pct}%`;
  $("progress").setAttribute("aria-valuenow", String(pct));
}

function onSlot(msg) {
  const li = $(`slot-${msg.name}`);
  if (!li) return;
  li.hidden = OPTIONAL_HIDDEN.has(msg.name) && msg.status !== "filled";
  li.dataset.status = msg.status;
  if (session && msg.status === "filled" && msg.value) {
    session.slotValues[msg.name] = { value: msg.value, display: msg.display ?? null };
  }
  li.querySelector(".mark").textContent = MARKS[msg.status] || MARKS.empty;
  li.querySelector(".label .sr-only").textContent = ` (${T.slotState[msg.status]})`;
  li.querySelector(".value").textContent =
    msg.status === "filled" && msg.value ? (msg.display ?? formatValue(msg.name, msg.value, lang)) : "";
  if (msg.name === "role" && msg.status === "filled") {
    const rider = /rider/i.test(msg.value || "");
    for (const r of RIDER_ONLY) {
      const row = $(`slot-${r}`);
      // A role that is not rider hides the rider rows again, even if already answered.
      row.hidden = !rider;
    }
  }
  if (typeof msg.progress === "number") setProgress(msg.progress);
}

// ---- summary ----------------------------------------------------------------------------

function listInto(id, items) {
  const ul = $(id);
  ul.replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = String(item);
    ul.append(li);
  }
  ul.hidden = items.length === 0;
}

function toneSummary(sent) {
  if (!sent || typeof sent !== "object") return "";
  const parts = [];
  if (typeof sent.avg === "number") {
    const level = sent.avg <= -0.2 ? "negative" : sent.avg >= 0.2 ? "positive" : "neutral";
    parts.push(`${T.tone.average}: ${T.tone[level]}`);
  }
  if (typeof sent.trend === "string" && Object.hasOwn(T.tone, sent.trend)) {
    parts.push(`${T.tone.trend}: ${T.tone[sent.trend]}`);
  }
  if (typeof sent.frustration_events === "number") {
    parts.push(`${sent.frustration_events} ${T.tone.signals}`);
  }
  return parts.join(" · ");
}

const asText = (v) => (typeof v === "string" ? v : JSON.stringify(v));

// Every active slot with its readable value; the final frame wins, live values are the fallback.
function renderFinalProfile(final) {
  const live = session?.slotValues ?? {};
  const framed = final && typeof final === "object" ? final : null;
  const rider = /rider/i.test(framed?.role?.value ?? live.role?.value ?? "");
  const list = $("final-profile");
  list.replaceChildren();
  for (const name of SLOT_ORDER) {
    if (name === "consent_recording") continue;
    const entry = framed ? framed[name] : null;
    if (framed ? !entry : RIDER_ONLY.has(name) && !rider) continue;
    const fromFrame = entry && entry.status === "filled" && entry.value !== null && entry.value !== undefined;
    const fallback = !fromFrame && live[name];
    let text = "";
    if (fromFrame) text = entry.display ?? formatValue(name, asText(entry.value), lang);
    else if (fallback) text = fallback.display ?? formatValue(name, fallback.value, lang);
    const optional = entry ? entry.required === false : OPTIONAL_HIDDEN.has(name);
    if (!text && optional) continue;
    const li = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = T.slots[name];
    const value = document.createElement("span");
    value.textContent = text || "—";
    li.append(label, ": ", value);
    list.append(li);
  }
}

function onCompleted(msg) {
  // The candidate always sees the same neutral line; the outcome is only in the demo panel.
  const summary = msg.summary && typeof msg.summary === "object" ? msg.summary : {};
  $("summary-neutral").textContent = declinedLine(session.endReason, lang) ?? T.summaryNeutral;
  const complete = $("complete-line");
  complete.dataset.complete = String(msg.complete === true);
  complete.textContent = msg.complete === true ? T.complete : T.incomplete;
  renderFinalProfile(msg.profile);
  const declined = msg.end_reason === "declined_consent"; // nothing was stored: no profile to show
  $("final-profile").hidden = declined;
  $("final-profile-title").hidden = declined;
  const endReason = typeof msg.end_reason === "string" ? msg.end_reason : "";
  $("end-reason").textContent = Object.hasOwn(T.endReasons, endReason) ? T.endReasons[endReason] : endReason;
  $("end-reason-row").hidden = !endReason;
  $("tone").textContent = toneSummary(msg.sentiment);
  $("tone-row").hidden = !$("tone").textContent;
  const headline = $("summary-headline");
  headline.textContent = typeof summary.headline === "string" ? summary.headline : "";
  headline.hidden = !headline.textContent;
  listInto("summary-points", Array.isArray(summary.key_points) ? summary.key_points : []);
  const list = (v) => (Array.isArray(v) ? v : []);
  listInto("summary-steps", list(summary.recruiter_next_steps));
  listInto("summary-questions", list(summary.candidate_questions));
  for (const [title, id] of [["steps-title", "summary-steps"], ["questions-title", "summary-questions"]]) {
    $(title).hidden = $(id).hidden;
  }
  // Ana may still be saying goodbye: keep the speaker open until it drains.
  finishSession({ drain: !session.userEnded });
  show("summary");
}

// ---- errors -----------------------------------------------------------------------------

function fail(key, detail) {
  if (page === "summary" || page === "error") return;
  finishSession();
  $("error-text").textContent = detail || T.errors[key] || T.errors.server;
  show("error");
}

// ---- audio ------------------------------------------------------------------------------

function makeContext(rate) {
  const opts = { latencyHint: "interactive" };
  let ctx;
  try {
    ctx = rate ? new AudioContext({ ...opts, sampleRate: rate }) : new AudioContext(opts);
  } catch {
    ctx = new AudioContext(opts); // unsupported rate: the worklets resample from the real one
  }
  ctx.resume().catch(() => {}); // a suspended context is retried by the browser on user gesture
  return ctx;
}

function openAudioContexts() {
  // Created inside the click handler so autoplay policies allow them to run.
  return { capture: makeContext(CAPTURE_RATE), play: makeContext(PLAY_RATE) };
}

async function startRecorder(s) {
  s.stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  await s.capture.audioWorklet.addModule(`pcm-recorder.js?v=${APP_VERSION}`);
  let source;
  try {
    source = s.capture.createMediaStreamSource(s.stream);
  } catch (err) {
    if (!err || err.name !== "NotSupportedError") throw err;
    // Firefox refuses a context whose rate differs from the microphone's: use the default
    // rate once, the recorder worklet resamples to 16 kHz anyway.
    await s.capture.close().catch(() => {});
    s.capture = makeContext(null);
    await s.capture.audioWorklet.addModule(`pcm-recorder.js?v=${APP_VERSION}`);
    source = s.capture.createMediaStreamSource(s.stream);
  }
  const node = new AudioWorkletNode(s.capture, "pcm-recorder", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
  node.port.postMessage({ levels: true });
  node.port.onmessage = (e) => {
    if (!(e.data instanceof ArrayBuffer)) {
      if (e.data && typeof e.data.level === "number" && !s.done) onLevel("mic", e.data.level);
      return;
    }
    const ws = s.ws;
    if (ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < MAX_BUFFERED && s.started) {
      ws.send(e.data);
    }
  };
  const mute = s.capture.createGain();
  mute.gain.value = 0; // keeps the graph pulled without echoing the mic
  source.connect(node).connect(mute).connect(s.capture.destination);
}

async function startPlayer(s) {
  await s.play.audioWorklet.addModule(`pcm-player.js?v=${APP_VERSION}`);
  s.player = new AudioWorkletNode(s.play, "pcm-player", { numberOfInputs: 0, outputChannelCount: [1] });
  s.player.connect(s.play.destination);
  s.player.port.postMessage({ levels: true });
  s.player.port.onmessage = (e) => {
    if (e.data && typeof e.data.level === "number" && !s.done) onLevel("agent", e.data.level);
  };
}

function playChunk(s, buf) {
  // PCM16 samples are 2 bytes; carry an odd trailing byte over to the next frame.
  let bytes = new Uint8Array(buf);
  if (s.carry !== null) {
    const joined = new Uint8Array(bytes.length + 1);
    joined[0] = s.carry;
    joined.set(bytes, 1);
    bytes = joined;
    s.carry = null;
  }
  if (bytes.length % 2 === 1) {
    s.carry = bytes[bytes.length - 1];
    bytes = bytes.subarray(0, bytes.length - 1);
  }
  if (bytes.length === 0) return;
  const copy = bytes.slice().buffer;
  s.player.port.postMessage(copy, [copy]);
}

// ---- session ----------------------------------------------------------------------------

function wsUrlFor(body) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  try {
    const u = new URL(body.ws_url);
    if ((u.protocol === "ws:" || u.protocol === "wss:") && u.host === location.host) return u.href;
  } catch {
    // relative or malformed: build from the page location below
  }
  return `${proto}//${location.host}/ws/interview/${encodeURIComponent(body.conversation_id)}`;
}

function closePlay(s) {
  clearTimeout(s.drainTimer);
  if (s.play && s.play.state !== "closed") s.play.close().catch(() => {});
}

function finishSession({ drain = false } = {}) {
  const s = session;
  if (!s || s.done) return;
  s.done = true;
  if (!drain) orbReset();
  if (s.ws) {
    s.ws.onclose = null;
    s.ws.onerror = null;
    try { s.ws.close(); } catch { /* already closed */ }
  }
  if (s.stream) for (const t of s.stream.getTracks()) t.stop();
  if (s.capture && s.capture.state !== "closed") s.capture.close().catch(() => {});
  if (drain && s.player && s.play && s.play.state !== "closed") {
    // Close the speaker only once the buffered audio has played out (or after the cap).
    s.player.port.onmessage = (e) => {
      if (e.data && e.data.drained) closePlay(s);
      else if (e.data && typeof e.data.level === "number") onLevel("agent", e.data.level);
    };
    s.drainTimer = setTimeout(() => closePlay(s), DRAIN_CAP_MS);
    s.player.port.postMessage({ query: "drain" });
  } else {
    closePlay(s);
  }
}

function sendJson(obj) {
  const ws = session && session.ws;
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function agentSpoke() {
  if (page === "connecting") show("live");
}

function onMessage(ev) {
  const s = session;
  if (typeof ev.data !== "string") {
    agentSpoke();
    if (s.player) playChunk(s, ev.data);
    return;
  }
  let msg;
  try { msg = JSON.parse(ev.data); } catch { return; }
  switch (msg.type) {
    case "transcript":
      if (msg.speaker === "agent") agentSpoke();
      onTranscript(msg);
      break;
    case "interrupted":
      if (s.player) s.player.port.postMessage({ flush: true });
      s.carry = null;
      break;
    case "slot":
      onSlot(msg);
      break;
    case "ended":
      s.ended = true;
      s.endReason = msg.reason;
      // Model-ended interviews keep playing Ana's closing words; only a user End cuts audio.
      if (s.player && s.userEnded) s.player.port.postMessage({ flush: true });
      if (page === "connecting" || page === "live") show("processing");
      break;
    case "completed":
      onCompleted(msg);
      break;
    case "error":
      fail(
        Object.hasOwn(T.errors, msg.code) ? msg.code : "server",
        Object.hasOwn(T.errors, msg.code) || !msg.message ? null : String(msg.message),
      );
      break;
    default: // state, faq, pong: nothing to render
  }
}

async function startInterview() {
  $("start").disabled = true;
  $("end").disabled = false;
  const s = {
    ws: null, stream: null, capture: null, play: null, player: null,
    started: false, ended: false, userEnded: false, done: false, drainTimer: 0, carry: null, open: { agent: null, candidate: null }, slotValues: {},
  };
  session = s;
  $("captions").replaceChildren();
  $("captions-live").replaceChildren();
  stick = true;
  buildProfile();
  resetPanels();
  orbReset();
  show("connecting");
  try {
    if (!window.AudioContext || !navigator.mediaDevices || !window.AudioWorkletNode) {
      fail("audio_unsupported");
      return;
    }
    Object.assign(s, openAudioContexts());

    let body;
    try {
      const res = await fetch("/api/interviews", { method: "POST" });
      if (res.status === 429) { fail("busy"); return; }
      if (!res.ok) throw new Error("status " + res.status);
      body = await res.json();
    } catch {
      fail("server_down");
      return;
    }
    if (s.done) return;

    try {
      await startPlayer(s);
      await startRecorder(s);
    } catch (err) {
      const name = err && err.name;
      if (name === "NotAllowedError" || name === "SecurityError") fail("mic_denied");
      else if (name === "NotFoundError" || name === "OverconstrainedError") fail("mic_missing");
      else fail("mic_error");
      return;
    }
    if (s.done) return;

    const ws = new WebSocket(wsUrlFor(body));
    ws.binaryType = "arraybuffer";
    s.ws = ws;
    ws.onopen = () => {
      s.started = true;
      ws.send(JSON.stringify({ type: "start", locale: LOCALES[lang] }));
    };
    ws.onmessage = onMessage;
    ws.onclose = (ev) => {
      if (s.done) return;
      fail(!s.started ? "rejected" : ev.code === 1008 || ev.code === 4409 ? "rejected" : "lost");
    };
    ws.onerror = () => {
      if (!s.started) fail("server_down");
    };
  } catch {
    fail("server");
  }
}

// ---- wiring -----------------------------------------------------------------------------

function reset() {
  finishSession();
  if (session) closePlay(session);
  session = null;
  orbReset();
  $("start").disabled = false;
  show("landing");
  $("start").focus();
}

function init() {
  resetPanels();
  applyStaticText();
  buildProfile();
  for (const code of ["es", "en"]) {
    $(`lang-${code}`).addEventListener("change", (ev) => {
      if (!ev.target.checked) return;
      setLang(code);
      buildProfile();
    });
  }
  $("start").addEventListener("click", startInterview);
  $("again-summary").addEventListener("click", reset);
  $("again-error").addEventListener("click", reset);
  $("end").addEventListener("click", () => {
    if (session) session.userEnded = true;
    if (session && session.player) session.player.port.postMessage({ flush: true });
    sendJson({ type: "end" });
    $("end").disabled = true;
  });
  $("toggle-convo").addEventListener("click", () => {
    $("convo").hidden = !$("convo").hidden;
    syncControls();
    if (!$("convo").hidden) scrollCaptions();
  });
  $("toggle-type").addEventListener("click", () => {
    $("text-form").hidden = !$("text-form").hidden;
    syncControls();
    if (!$("text-form").hidden) $("text-input").focus();
  });
  $("text-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("text-input");
    const text = input.value.trim();
    if (!text || page !== "live") return;
    sendJson({ type: "text", text });
    input.value = "";
  });
  const box = $("captions");
  box.addEventListener("scroll", () => {
    stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  });
  window.addEventListener("pagehide", () => {
    if (session && !session.done && (page === "live" || page === "connecting")) sendJson({ type: "end" });
  });
  show("landing");
}

init();

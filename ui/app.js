/* Ordnungsliebe – Oberfläche. Ohne Build-Schritt, reines JavaScript. */
"use strict";

/* ===================== Grundlagen ===================== */

const $app = document.getElementById("app");
const $modal = document.getElementById("modal-root");
const $toast = document.getElementById("toast");

const S = {
  state: null,          // app_state vom Programm
  route: "loading",
  params: {},
  actions: {},
  setup: { step: 1 },
  cur: null,            // aktuelles Dokument in der Einzelprüfung
  batch: null,
  struct: null,
  dl: null,             // Download-Fortschritt
};

function esc(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function hasBridge() { return !!(window.pywebview && window.pywebview.api); }

async function call(name, ...args) {
  let res;
  if (hasBridge()) {
    res = await window.pywebview.api[name](...args);
  } else {
    const r = await fetch("/api/" + name, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args),
    });
    res = await r.json();
  }
  if (!res || !res.ok) throw new Error((res && res.error) || "Unbekannter Fehler");
  return res.data;
}

async function tryCall(name, ...args) {
  try { return await call(name, ...args); }
  catch (e) { toast(e.message); return undefined; }
}

let toastTimer = null;
function toast(text, action) {
  $toast.innerHTML = esc(text) + (action ? ` <button type="button" id="toast-act">${esc(action.label)}</button>` : "");
  $toast.classList.add("show");
  if (action) document.getElementById("toast-act").onclick = () => { $toast.classList.remove("show"); action.fn(); };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $toast.classList.remove("show"), action ? 7000 : 3500);
}

/* Klicks und Eingaben laufen über data-act / data-input */
document.addEventListener("click", (ev) => {
  const el = ev.target.closest("[data-act]");
  if (!el || el.disabled) return;
  const fn = (el.closest("#modal-root") ? S.modalActions : S.actions)[el.dataset.act];
  if (fn) { ev.preventDefault(); fn(el, ev); }
});
document.addEventListener("input", (ev) => {
  const el = ev.target.closest("[data-input]");
  if (!el) return;
  const fn = (el.closest("#modal-root") ? S.modalActions : S.actions)[el.dataset.input];
  if (fn) fn(el, ev);
});
document.addEventListener("change", (ev) => {
  const el = ev.target.closest("[data-change]");
  if (!el) return;
  const fn = (el.closest("#modal-root") ? S.modalActions : S.actions)[el.dataset.change];
  if (fn) fn(el, ev);
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && $modal.innerHTML) closeModal(null);
});

function go(route, params) {
  S.route = route;
  S.params = params || {};
  window.scrollTo(0, 0);
  render();
}

function render() {
  const fn = SCREENS[S.route] || SCREENS.home;
  S.actions = {};
  fn();
}

function setHTML(html) { $app.innerHTML = html; }

function applyLook() {
  const s = S.state && S.state.settings;
  if (!s) return;
  document.documentElement.dataset.size = s.font_size || "gross";
  document.documentElement.dataset.theme = s.theme || "auto";
}

async function refreshState() {
  S.state = await call("app_state");
  applyLook();
  return S.state;
}

/* ===================== Symbole ===================== */

const I = {
  logo: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 16.5s-3-1.8-3-3.6a1.5 1.5 0 0 1 3-.6 1.5 1.5 0 0 1 3 .6c0 1.8-3 3.6-3 3.6z"/></svg>`,
  folder: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>`,
  doc: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h4"/></svg>`,
  layers: (s = 28) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/></svg>`,
  clock: (s = 28) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>`,
  sliders: (s = 28) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>`,
  lock: (s = 20) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>`,
  check: (s = 22, w = 2.4) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`,
  x: (s = 22) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>`,
  left: (s = 22) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>`,
  right: (s = 22) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>`,
  prev: (s = 20) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>`,
  next: (s = 20) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>`,
  chev: (s = 22) => `<svg class="chev" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>`,
  undo: (s = 18) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>`,
  shield: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>`,
  plus: (s = 20) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`,
  search: (s = 20) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>`,
  cloud: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 18a4.5 4.5 0 0 1-.6-9 6 6 0 0 1 11.6 1.5A3.75 3.75 0 0 1 17.25 18z"/><path d="M12 11v5M9.5 13.5L12 16l2.5-2.5"/></svg>`,
  scissors: (s = 26) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4L8.12 15.88M14.47 14.48L20 20M8.12 8.12L12 12"/></svg>`,
  trash: (s = 22) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>`,
  equal: (s = 26) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 9h14M5 15h14"/></svg>`,
  warn: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l9.5 17h-19z"/><path d="M12 10v4M12 17.5v.5"/></svg>`,
};

/* ===================== Bausteine ===================== */

function topbar(backLabel, backAct, info) {
  return `<header class="topbar">
    <button type="button" class="back" data-act="${backAct}">${I.left()} ${esc(backLabel)}</button>
    <div class="info">${info || ""}</div>
  </header>`;
}

function dots(n, cur) {
  if (n < 2 || n > 10) return "";
  let h = '<div class="dots" aria-hidden="true">';
  for (let i = 0; i < n; i++) h += `<span class="${i <= cur ? "on" : ""}"></span>`;
  return h + "</div>";
}

function minutesText(n) {
  const m = Math.max(1, Math.round((n * 20) / 60));
  return m === 1 ? "etwa 1 Minute" : `etwa ${m} Minuten`;
}

function plural(n, one, many) { return `${n.toLocaleString("de-DE")} ${n === 1 ? one : many}`; }

function durationText(min) {
  if (min < 90) return min <= 1 ? "1 Minute" : `${min} Minuten`;
  const h = Math.round(min / 60);
  if (h < 36) return `${h} Stunden`;
  return `${Math.round(h / 24)} Tage`;
}

function splitName(name) {
  const i = name.lastIndexOf(".");
  return i > 0 ? [name.slice(0, i), name.slice(i)] : [name, ""];
}

function confBox(item) {
  const s = item.suggestion || {};
  const c = s.confidence || 0;
  const on = Math.max(1, Math.round(c * 5));
  const bars = [0, 1, 2, 3, 4].map((i) => `<span class="${i < on ? "on" : ""}"></span>`).join("");
  let text, cls;
  if (s.is_new_folder) { text = "Dafür lege ich einen neuen Ordner an – bitte kurz prüfen."; cls = "lo"; }
  else if (item.excluded && item.excluded.length) { text = "Das ist mein nächster Vorschlag – passt er?"; cls = "lo"; }
  else if (c >= 0.85) { text = "Hier bin ich mir ziemlich sicher."; cls = "hi"; }
  else { text = "Hier bin ich mir nicht ganz sicher – bitte kurz prüfen."; cls = "lo"; }
  return `<div class="conf ${cls}"><div class="bars" aria-hidden="true">${bars}</div><span>${esc(text)}</span></div>`;
}

/* ===================== Dialoge ===================== */

S.modalActions = {};
let modalResolve = null;

function openModal(html, actions, wide) {
  S.modalActions = actions || {};
  $modal.innerHTML = `<div class="modal-back" data-act="__backdrop"><div class="modal${wide ? " wide" : ""}" role="dialog" aria-modal="true">${html}</div></div>`;
  S.modalActions.__backdrop = (el, ev) => { if (ev.target === el) closeModal(null); };
  const first = $modal.querySelector("input, button:not([data-act='__backdrop'])");
  if (first) first.focus();
  return new Promise((res) => { modalResolve = res; });
}

function closeModal(value) {
  $modal.innerHTML = "";
  S.modalActions = {};
  const r = modalResolve;
  modalResolve = null;
  if (r) r(value);
}

function confirmDialog(title, text, okLabel, danger) {
  return openModal(`<h2>${esc(title)}</h2><p class="lead">${esc(text)}</p>
    <div class="btns"><button type="button" class="btn" data-act="no">Abbrechen</button>
    <button type="button" class="btn ${danger ? "danger" : "primary"}" data-act="yes">${esc(okLabel)}</button></div>`,
    { no: () => closeModal(false), yes: () => closeModal(true) });
}

async function pickFolder(origin, current) {
  const list = (await tryCall("folders", origin)) || [];
  let filter = "";
  const allowNew = true;
  const draw = () => {
    const f = filter.toLowerCase();
    const items = list.filter((x) => !f || x.display.toLowerCase().includes(f));
    const ul = $modal.querySelector(".folderlist");
    ul.innerHTML = items.map((x) => `<li><button type="button" class="${x.path === current ? "on" : ""}" data-act="pick" data-path="${esc(x.path)}">${I.folder(22)} ${esc(x.display)}</button></li>`).join("")
      || `<li class="muted small" style="padding:0.75rem">Kein passender Ordner.</li>`;
  };
  const p = openModal(`<h2>In welchen Ordner?</h2>
    <input class="text" type="search" placeholder="Ordner suchen …" aria-label="Ordner suchen" data-input="filter">
    <ul class="folderlist"></ul>
    ${allowNew ? `<div class="stack g8"><span class="label">Oder neuen Ordner anlegen</span>
      <div class="row g8"><input class="text" id="newfolder" value="${esc(current ? current + "/" : "")}" placeholder="z. B. Versicherungen/Haftpflicht" aria-label="Neuer Ordner">
      <button type="button" class="btn" data-act="new">Anlegen</button></div>
      <span class="tiny muted">Unterordner mit „/“ trennen – z. B. „Arbeit/Gehalt/Entgeltnachweise“. Ich merke mir, dass solche Dokumente künftig dorthin gehören.</span></div>` : ""}
    <div class="btns"><button type="button" class="btn" data-act="cancel">Abbrechen</button></div>`, {
    filter: (el) => { filter = el.value; draw(); },
    pick: (el) => closeModal(el.dataset.path),
    new: () => { const v = document.getElementById("newfolder").value.trim(); if (v) closeModal(v); },
    cancel: () => closeModal(null),
  });
  draw();
  return p;
}


/* Eingebaute Ordnerauswahl (funktioniert ohne das Windows-Ordnerfenster) */
async function browseFolder(start, title, allowCreate) {
  let cur = null;
  const load = async (path) => {
    let r;
    try { r = await call("list_dir", path || ""); }
    catch (e) { if (path) return load(""); toast(e.message); return; }
    cur = r;
    const box = $modal.querySelector(".fb-body");
    if (!box) return;
    const crumb = r.path ? esc(r.display) : "Wo liegt der Ordner?";
    $modal.querySelector(".fb-where").innerHTML = `${r.path ? I.folder(22) : ""} <span>${crumb}</span>`;
    const items = r.dirs.map((d) => `<li><button type="button" data-act="open" data-path="${esc(d.path)}">${I.folder(22)} <span class="grow">${esc(d.name)}</span>${I.next(18)}</button></li>`).join("");
    box.innerHTML = (r.path ? `<li><button type="button" data-act="up">${I.prev(18)} <span class="muted">Eine Ebene zurück</span></button></li>` : "")
      + (items || `<li class="muted small" style="padding:0.75rem 0.875rem">Hier sind keine weiteren Ordner.</li>`);
    $modal.querySelector("[data-act=choose]").disabled = !r.path;
    const mk = $modal.querySelector(".fb-new");
    if (mk) mk.style.display = r.path ? "" : "none";
  };
  const p = openModal(`<h2>${esc(title)}</h2>
    <p class="small muted">Klicke dich zum richtigen Ordner durch und wähle ihn dann aus.</p>
    <div class="row g10 value fb-where" style="font-size:1.125rem"></div>
    <ul class="folderlist fb-body" style="max-height:24rem"><li><div class="spinner small" style="margin:1rem"></div></li></ul>
    ${allowCreate ? `<div class="row g8 fb-new"><input class="text" id="fb-name" placeholder="Neuen Ordner hier anlegen, z. B. Scans" aria-label="Name für neuen Ordner">
      <button type="button" class="btn" data-act="mkdir">Anlegen</button></div>` : ""}
    <div class="row between wrapflex g12"><button type="button" class="btn link small" data-act="native">Windows-Ordnerfenster öffnen</button>
      <div class="row g12"><button type="button" class="btn" data-act="cancel">Abbrechen</button>
      <button type="button" class="btn primary" data-act="choose" disabled>Diesen Ordner wählen</button></div></div>`, {
    open: (el) => load(el.dataset.path),
    up: () => load(cur && cur.parent !== null ? cur.parent : ""),
    cancel: () => closeModal(null),
    choose: () => { if (cur && cur.path) closeModal({ path: cur.path, display: cur.display }); },
    mkdir: async () => {
      const name = document.getElementById("fb-name").value.trim();
      if (!name || !cur || !cur.path) return;
      const r = await tryCall("make_dir", cur.path, name);
      if (r) { document.getElementById("fb-name").value = ""; await load(r.path); toast(`Ordner „${name}“ angelegt.`); }
    },
    native: async () => {
      const r = await tryCall("choose_folder", cur && cur.path ? cur.path : "");
      if (r) closeModal(r);
    },
  }, true);
  await load(start || "");
  return p;
}

/* ===================== Ereignisse vom Programm ===================== */

const HANDLERS = {
  queue(payload) {
    if (!S.state) return;
    S.state.queue = payload;
    if (S.route === "home") render();
    else if (S.route === "single") singleOnQueue();
    else if (S.route === "reorg" && S.state.reorg && S.state.reorg.phase === "review") refreshReorg();
  },
  download(p) {
    S.dl = p;
    if (S.state) S.state.model = p;
    updateDownloadUI();
  },
  ai(p) {
    if (!S.state) return;
    S.state.ai = p;
    if (S.route === "home") render();
  },
  reorg(p) {
    if (!S.state) return;
    S.state.reorg = p;
    if (S.route === "reorg") render();
    else if (S.route === "home") render();
  },
  reorg_item_done() { /* über queue abgedeckt */ },
  scanfinder(p) {
    S.setup.finder = p;
    if (p.state === "found") {
      S.setup.inbox = { path: p.folder, display: p.display, count: null };
      toast(`Gefunden: „${p.file}“ in ${p.display}`);
    }
    if (S.route === "setup") render();
  },
  keeplocal(p) {
    S.keepLocal = p;
    const el = document.getElementById("keeplocal-progress");
    if (el) el.textContent = p.finished ? "Alle Dateien sind jetzt auf diesem Computer." : `Lade herunter … ${p.done} von ${p.total}`;
  },
};

window.onBackendEvent = (name, payload) => {
  const h = HANDLERS[name];
  if (h) { try { h(payload); } catch (e) { console.error(e); } }
};

/* Entwicklungsmodus im Browser: Ereignisse abholen */
function startDevPolling() {
  setInterval(async () => {
    try {
      const r = await fetch("/events");
      const list = await r.json();
      list.forEach(([n, p]) => window.onBackendEvent(n, p));
    } catch (e) { /* still */ }
  }, 400);
}

/* ===================== Bildschirme ===================== */

const SCREENS = {};

/* ---------- Startseite ---------- */
SCREENS.home = () => {
  const st = S.state;
  const q = (st.queue.by_origin && st.queue.by_origin.inbox) || { total: 0, working: 0, batch: 0, ready: 0 };
  const ai = st.ai || {};
  let pill = `<span class="dot"></span> Scan-Ordner wird beobachtet`;
  if (ai.state === "starting") pill = `<span class="dot busy"></span> Die KI wird gestartet …`;
  else if (ai.state === "error") pill = `<span class="dot off"></span> Die KI konnte nicht starten`;

  const n = q.total;
  let sub = n === 1 ? "1 neues Dokument wartet darauf, einsortiert zu werden." : `${n} neue Dokumente warten darauf, einsortiert zu werden.`;
  let hero;
  if (n === 0) {
    sub = "Alles ist einsortiert. Neue Scans erscheinen hier von selbst.";
    hero = `<div class="hero calm"><div class="hero-icon">${I.check(40, 2.2)}</div>
      <div class="stack g4 grow"><span class="hero-title">Alles erledigt</span>
      <span class="hero-sub">Lege einfach neue Dokumente in den Scanner – ich kümmere mich darum.</span></div></div>`;
  } else if (q.ready === 0) {
    hero = `<div class="hero calm"><div class="hero-icon" style="background:var(--tint);color:var(--violet)"><div class="spinner small"></div></div>
      <div class="stack g4 grow"><span class="hero-title">Ich lese gerade ${plural(n, "Dokument", "Dokumente")}</span>
      <span class="hero-sub">Das dauert einen Moment. Du kannst so lange etwas anderes machen.</span></div></div>`;
  } else {
    hero = `<button type="button" class="hero" data-act="startReview">
      <div class="hero-icon">${I.doc(40)}<span class="badge">${n}</span></div>
      <div class="stack g4 grow" style="flex-basis:20rem"><span class="hero-title">Neue Dokumente einsortieren</span>
      <span class="hero-sub">Dauert ${minutesText(n)}. Du entscheidest bei jedem Dokument.</span></div>
      <div class="hero-go">Los geht's ${I.right()}</div></button>`;
  }

  const rp = (st.reorg && st.reorg.phase) || "";
  const rs = st.reorg || {};
  const reorgBanner = rp === "paused"
    ? `<div class="notice info">${I.layers(24)}<div class="grow"><b>Die Neuordnung ist pausiert.</b>
       ${rs.total ? `Stand: ${rs.done.toLocaleString("de-DE")} von ${rs.total.toLocaleString("de-DE")}. ` : ""}Es geht genau dort weiter, wo sie stand.</div>
       <button type="button" class="btn small violet" data-act="resumeReorg">Weitermachen</button></div>`
    : ["backup", "reading", "structure", "structure_review", "review"].includes(rp)
    ? `<div class="notice info">${I.layers(24)}<div class="grow"><b>Die Neuordnung deiner Ablage läuft noch.</b>
       Du kannst jederzeit weitermachen.</div><button type="button" class="btn small violet" data-act="reorg">Weitermachen</button></div>` : "";

  setHTML(`<div class="screen">
    <header class="home-head"><div class="brand"><div class="logo">${I.logo()}</div><span class="brand-name">Ordnungsliebe</span></div>
    <div class="pill">${pill}</div></header>
    <main class="wrap">
      <div class="stack g10"><h1 class="title xl">Hallo! Was möchtest du heute tun?</h1><p class="lead">${esc(sub)}</p></div>
      ${reorgBanner}
      ${hero}
      <div class="tiles">
        <button type="button" class="tile" data-act="reorg"><div class="icon-box">${I.layers()}</div>
          <span class="tile-title">Ablage neu ordnen</span><span class="tile-text">Bestehende Ordner aufräumen und übersichtlich sortieren.</span></button>
        <button type="button" class="tile" data-act="history"><div class="icon-box">${I.clock()}</div>
          <span class="tile-title">Verlauf</span><span class="tile-text">Sehen, was wohin kam – und es rückgängig machen.</span></button>
        <button type="button" class="tile" data-act="settings"><div class="icon-box">${I.sliders()}</div>
          <span class="tile-title">Einstellungen</span><span class="tile-text">Scan-Ordner, Ablageort und Programm anpassen.</span></button>
      </div>
      <div class="privacy">${I.lock()} Alles bleibt auf diesem Computer. Deine Dokumente gehen nie ins Internet.</div>
    </main></div>`);

  S.actions = {
    startReview: () => startReview("inbox"),
    reorg: () => go("reorg"),
    resumeReorg: async () => { const r = await tryCall("reorg_resume"); if (r) { S.state.reorg = r; go("reorg"); } },
    history: () => go("history"),
    settings: () => go("settings"),
  };
};

async function startReview(origin) {
  const ov = await tryCall("overview", origin);
  if (!ov) return;
  if (ov.batch > 0) go("batch", { origin });
  else go("single", { origin });
}

function backTo(origin) {
  return origin === "reorg" ? ["Zur Neuordnung", () => go("reorg")] : ["Zur Startseite", () => go("home")];
}

/* ---------- Sammelliste ---------- */
SCREENS.batch = () => {
  const origin = S.params.origin || "inbox";
  const [backLabel, backFn] = backTo(origin);
  setHTML(`<div class="screen">${topbar(backLabel, "back", "Schritt 1 von 2 · Sichere Vorschläge")}
    <main class="wrap narrow"><div class="waiting"><div class="spinner"></div></div></main></div>`);
  S.actions = { back: backFn };
  call("batch", origin).then((items) => {
    if (S.route !== "batch") return;
    if (!items.length) { go("single", { origin }); return; }
    S.batch = { items, off: new Set(), origin };
    drawBatch();
  }).catch((e) => toast(e.message));
};

function drawBatch() {
  const { items, off, origin } = S.batch;
  const [backLabel, backFn] = backTo(origin);
  const ov = (S.state.queue.by_origin && S.state.queue.by_origin[origin]) || {};
  const checked = items.length - off.size;
  const rest = Math.max(0, (ov.total || items.length) - checked);
  const rows = items.map((it) => {
    const s = it.suggestion;
    const isOff = off.has(it.id);
    return `<li class="${isOff ? "off" : ""}"><label>
      <input type="checkbox" ${isOff ? "" : "checked"} data-change="toggle" data-id="${esc(it.id)}">
      <div class="mini" aria-hidden="true"><span></span><span></span><span></span><span style="width:75%"></span></div>
      <div class="stack g4 grow" style="flex-basis:16rem"><span style="font-size:1.1875rem;font-weight:600;overflow-wrap:anywhere">${esc(s.filename)}</span>
      <span class="small muted">${esc(s.summary || it.name)}</span></div>
      <div class="foldertag">${I.folder(18)} ${esc(s.folder_display)}</div></label></li>`;
  }).join("");
  setHTML(`<div class="screen">${topbar(backLabel, "back", "Schritt 1 von 2 · Sichere Vorschläge")}
    <main class="wrap narrow">
      <div class="stack g10"><h1 class="title">${items.length === 1 ? "Bei diesem Dokument bin ich mir sicher" : `Bei diesen ${items.length} Dokumenten bin ich mir sicher`}</h1>
      <p class="lead">Schau kurz drüber. Passt etwas nicht, nimm einfach den Haken weg – dann zeige ich dir das Dokument gleich einzeln.</p></div>
      <ul class="biglist">${rows}</ul>
      <div class="footbar"><span class="muted" style="flex:1 1 17rem">${rest ? `Danach: ${plural(rest, "Dokument, das", "Dokumente, die")} ich dir einzeln zeige.` : "Danach bist du fertig."}</span>
        <button type="button" class="btn primary tall" data-act="go" ${checked ? "" : "disabled"}>${I.check()} ${checked === 1 ? "1 Dokument einsortieren" : `${checked} Dokumente einsortieren`}</button>
        ${checked === 0 ? `<button type="button" class="btn tall" data-act="goSingle">Einzeln anschauen</button>` : ""}</div>
    </main></div>`);
  S.actions = {
    back: backFn,
    toggle: (el) => { const id = el.dataset.id; if (el.checked) off.delete(id); else off.add(id); drawBatch(); },
    goSingle: async () => { await tryCall("decline_batch", [...off]); go("single", { origin }); },
    go: async (el) => {
      el.disabled = true;
      el.innerHTML = `<div class="spinner small"></div> Wird einsortiert …`;
      const ids = items.filter((i) => !off.has(i.id)).map((i) => i.id);
      if (off.size) await tryCall("decline_batch", [...off]);
      const n = await tryCall("confirm_batch", ids);
      await refreshState();
      if (n !== undefined) toast(`${plural(n, "Dokument", "Dokumente")} einsortiert.`);
      go("single", { origin });
    },
  };
}

/* ---------- Einzelprüfung ---------- */
SCREENS.single = () => {
  const origin = S.params.origin || "inbox";
  S.cur = { origin, item: null, page: 0, loading: true };
  drawSingle();
  loadNextSingle();
};

async function loadNextSingle() {
  const origin = S.cur.origin;
  try {
    const item = await call("next_single", origin);
    if (S.route !== "single") return;
    S.cur = { origin, item, page: 0, loading: false, preview: null, editName: false, thumbs: null, dupPreview: null };
    drawSingle();
    if (item) loadPreview();
  } catch (e) { toast(e.message); }
}

function singleOnQueue() {
  const c = S.cur;
  if (!c) return;
  if (c.waitingFor) {
    call("item", c.waitingFor).then((it) => {
      if (it.status === "ready" || it.status === "error") {
        c.item = it; c.waitingFor = null; c.editName = false; drawSingle(); loadPreview();
      }
    }).catch(() => { c.waitingFor = null; loadNextSingle(); });
  } else if (!c.item && !c.loading) {
    loadNextSingle();
  } else if (!c.item) {
    drawSingle();
  }
}

async function loadPreview() {
  const c = S.cur;
  if (!c || !c.item) return;
  const id = c.item.id;
  if (c.item.stage === "stack") {
    const thumbs = await tryCall("thumbs", id);
    if (S.cur && S.cur.item && S.cur.item.id === id) { S.cur.thumbs = thumbs || []; drawSingle(); }
    return;
  }
  const pv = await tryCall("preview", id, c.page);
  if (!S.cur || !S.cur.item || S.cur.item.id !== id) return;
  S.cur.preview = pv;
  if (c.item.stage === "duplicate" && c.item.dup) {
    const other = await tryCall("preview_path", c.item.dup.path, 0);
    if (S.cur && S.cur.item && S.cur.item.id === id) S.cur.dupPreview = other;
  }
  drawSingle();
}

function previewHTML(pv, zoomable) {
  if (!pv) return `<div class="paper" style="cursor:default"><div class="spinner"></div></div>`;
  if (pv.type === "email") {
    const v = pv.view;
    return `<div class="mail"><dl><dt>Von</dt><dd>${esc(v.from)}</dd><dt>An</dt><dd>${esc(v.to)}</dd>
      <dt>Datum</dt><dd>${esc(v.date)}</dd><dt>Betreff</dt><dd><b>${esc(v.subject)}</b></dd></dl>
      <div class="body">${esc(v.body)}</div>
      ${v.attachments && v.attachments.length ? `<div class="small muted">Anhänge: ${v.attachments.map(esc).join(", ")}</div>` : ""}</div>`;
  }
  if (pv.type === "text") return `<div class="paper text">${esc(pv.text || "Keine Vorschau verfügbar.")}</div>`;
  return `<button type="button" class="paper" ${zoomable ? 'data-act="zoom"' : ""} aria-label="Vorschau vergrößern"><img src="${pv.data}" alt="Vorschau Seite ${pv.page + 1}"></button>`;
}

function pagerHTML(pv) {
  if (!pv || pv.type !== "image") return "";
  return `<div class="pager">
    <button type="button" class="iconbtn" data-act="prevPage" aria-label="Vorherige Seite" ${pv.page <= 0 ? "disabled" : ""}>${I.prev()}</button>
    <span class="small muted">Seite ${pv.page + 1} von ${pv.page_count}</span>
    <button type="button" class="iconbtn" data-act="nextPage" aria-label="Nächste Seite" ${pv.page >= pv.page_count - 1 ? "disabled" : ""}>${I.next()}</button>
    <button type="button" class="btn small" data-act="zoom">Vergrößern</button></div>`;
}

function drawSingle() {
  const c = S.cur;
  const origin = c.origin;
  const [backLabel, backFn] = backTo(origin);
  const ov = (S.state.queue.by_origin && S.state.queue.by_origin[origin]) || { total: 0, working: 0 };
  const info = c.item ? `${ov.total === 1 ? "Noch 1 Dokument" : `Noch ${ov.total} Dokumente`}` : "";
  S.actions = { back: backFn };

  if (!c.item) {
    let body;
    if (c.loading) body = `<div class="spinner"></div>`;
    else if (ov.working > 0) {
      body = `<div class="spinner"></div><h1 class="title">Ich schaue mir gerade ${plural(ov.working, "Dokument", "Dokumente")} an …</h1>
        <p class="lead">Gleich geht es weiter. Das Fenster kannst du offen lassen.</p>`;
    } else {
      body = `<div class="big-icon">${I.check(40, 2.4)}</div><h1 class="title">${origin === "reorg" ? "Alle Dokumente sind zugeordnet!" : "Alles einsortiert!"}</h1>
        <p class="lead">${origin === "reorg" ? "Jetzt nur noch abschließen – dann räume ich leere Ordner auf." : "Neue Scans erscheinen auf der Startseite von selbst."}</p>
        <button type="button" class="btn primary tall shadow" data-act="back">${origin === "reorg" ? "Zur Neuordnung" : "Zur Startseite"}</button>`;
    }
    setHTML(`<div class="screen">${topbar(backLabel, "back", "")}<div class="waiting">${body}</div></div>`);
    return;
  }

  const it = c.item;
  if (it.stage === "stack") return drawStack();
  if (it.stage === "duplicate") return drawDuplicate();

  let right;
  if (c.waitingFor || it.status === "waiting" || it.status === "analyzing") {
    right = `<div class="waiting" style="padding:2rem 0"><div class="spinner"></div>
      <h2 class="suggest-title">${esc(c.waitMsg || "Ich suche einen anderen Ordner …")}</h2><p class="lead">Einen Moment bitte.</p></div>`;
  } else if (it.status === "error") {
    right = `<div class="stack g8"><span class="eyebrow">Hoppla</span><h1 class="suggest-title">Dieses Dokument konnte ich nicht lesen</h1></div>
      <div class="notice warn">${I.warn()}<div>${esc(it.error || "Unbekannter Fehler")}</div></div>
      <div class="stack g12 mt-auto"><button type="button" class="btn primary big" data-act="retry">Noch einmal versuchen</button>
      <button type="button" class="btn tall" data-act="notDoc">Das ist kein Dokument (z. B. ein Foto)</button>
      <div class="row g12 wrapflex"><button type="button" class="btn tall" style="flex:2 1 15rem" data-act="manual">Selbst einen Ordner wählen</button>
      <button type="button" class="btn link tall" style="flex:1 1 8rem" data-act="skip">Später</button></div></div>`;
  } else {
    const s = it.suggestion;
    const [stem, ext] = splitName(s.filename);
    right = `<div class="stack g8"><span class="eyebrow">Mein Vorschlag</span><h1 class="suggest-title">${esc(s.summary || stem)}</h1></div>
      ${confBox(it)}
      ${s.reason ? `<p class="small muted" style="margin-top:-0.5rem"><b style="color:var(--text-2)">Warum:</b> ${esc(s.reason)}</p>` : ""}
      <div class="card stack g20">
        <div class="stack g10"><span class="label">Ordner</span>
          <div class="row g12 wrapflex"><div class="value grow" style="flex-basis:15rem"><span style="color:var(--violet)">${I.folder()}</span> ${esc(s.folder_display)}
            ${s.is_new_folder ? '<span class="tag new">Neuer Ordner</span>' : ""}</div>
            <button type="button" class="btn small violet" data-act="pickFolder">Ändern</button></div>
          ${s.alt_folder ? `<div class="row g10 wrapflex small muted">Oder vielleicht: <button type="button" class="btn chip" data-act="useAlt">${esc(s.alt_display)}</button></div>` : ""}
        </div>
        <hr class="hr">
        <div class="stack g10"><span class="label">Dateiname</span>
          ${c.editName
            ? `<div class="row g8"><input class="text" id="fname" value="${esc(stem)}" aria-label="Dateiname"><span class="ext">${esc(ext)}</span>
               <button type="button" class="btn small" data-act="saveName">Übernehmen</button></div>`
            : `<div class="row g12 wrapflex"><div class="value grow" style="flex-basis:15rem">${esc(stem)}<span class="ext">${esc(ext)}</span></div>
               <button type="button" class="btn small violet" data-act="editName">Ändern</button></div>`}
        </div>
      </div>
      ${it.hint ? `<div class="small muted">Dein Hinweis: „${esc(it.hint)}“</div>` : ""}
      ${hintBox(c)}
      <div class="stack g12 mt-auto">
        <button type="button" class="btn primary big shadow" data-act="confirm">${I.check(26, 2.6)} Passt so – einsortieren</button>
        <div class="row g12 wrapflex">
          <button type="button" class="btn tall" style="flex:2 1 15rem" data-act="reject">${I.x()} Passt nicht – neuer Vorschlag</button>
          <button type="button" class="btn link tall" style="flex:1 1 8rem" data-act="skip">Später</button>
        </div>
      </div>`;
  }

  setHTML(`<div class="screen">${topbar(backLabel, "back", `<span>${esc(info)}</span>`)}
    <main class="review">
      <section class="preview-col" aria-label="Vorschau">${previewHTML(c.preview, true)}${pagerHTML(c.preview)}
        <span class="tiny muted" style="overflow-wrap:anywhere">${esc(it.name)}</span></section>
      <section aria-label="Vorschlag">${right}</section>
    </main></div>`);

  Object.assign(S.actions, {
    zoom: () => zoomPreview(),
    prevPage: () => { c.page = Math.max(0, c.page - 1); loadPreview(); },
    nextPage: () => { c.page = c.page + 1; loadPreview(); },
    editName: () => { c.editName = true; drawSingle(); const f = document.getElementById("fname"); if (f) { f.focus(); f.select(); } },
    saveName: () => {
      const v = document.getElementById("fname").value.trim();
      if (v) { const [, ext] = splitName(it.suggestion.filename); it.suggestion.filename = v + ext; }
      c.editName = false; drawSingle();
    },
    useAlt: () => {
      const s = it.suggestion;
      [s.folder, s.alt_folder] = [s.alt_folder, s.folder];
      [s.folder_display, s.alt_display] = [s.alt_display, s.folder_display];
      s.is_new_folder = false;
      drawSingle();
    },
    pickFolder: async () => {
      const f = await pickFolder(origin, it.suggestion.folder);
      if (f) {
        it.suggestion.folder = f;
        it.suggestion.folder_display = f.split("/").join(" › ");
        it.suggestion.is_new_folder = false;
        drawSingle();
      }
    },
    manual: async () => {
      const f = await pickFolder(origin, "");
      if (!f) return;
      const res = await tryCall("confirm", it.id, f, it.name.replace(/\.[^.]+$/, ""));
      if (res) { toast(`Abgelegt in ${res.folder_display}`); loadNextSingle(); }
    },
    confirm: async (el) => {
      if (c.editName) S.actions.saveName();
      el.disabled = true;
      const s = it.suggestion;
      const res = await tryCall("confirm", it.id, s.folder, s.filename);
      if (res) {
        toast(res.rechecked ? `Abgelegt in ${res.folder_display}. Ich passe ${plural(res.rechecked, "ähnlichen Vorschlag", "ähnliche Vorschläge")} an.` : `Abgelegt in ${res.folder_display}`);
        loadNextSingle();
      } else el.disabled = false;
    },
    reject: async () => {
      await tryCall("reject", it.id);
      c.waitMsg = "Ich suche einen anderen Ordner …";
      c.waitingFor = it.id;
      drawSingle();
    },
    skip: async () => { await tryCall("skip", it.id); loadNextSingle(); },
    retry: async () => { await tryCall("retry", it.id); c.waitMsg = "Ich versuche es noch einmal …"; c.waitingFor = it.id; drawSingle(); },
    hintToggle: () => { c.hintOpen = !c.hintOpen; drawSingle(); if (c.hintOpen) { const f = document.getElementById("hint"); if (f) f.focus(); } },
    hintText: (el) => { c.hintText = el.value; },
    hintChip: (el) => {
      c.hintText = el.dataset.text;
      drawSingle();
      const f = document.getElementById("hint");
      if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); }
    },
    hintSend: async (el) => {
      const text = (c.hintText || "").trim();
      if (!text) { toast("Schreib kurz, was ich beachten soll."); return; }
      el.disabled = true;
      if (await tryCall("give_hint", it.id, text)) {
        c.hintText = ""; c.hintOpen = false;
        c.waitMsg = "Ich schaue mir das Dokument mit deinem Hinweis noch einmal an …";
        c.waitingFor = it.id;
        drawSingle();
      } else el.disabled = false;
    },
    notDoc: async () => {
      if (await tryCall("not_document", it.id)) {
        toast("Bleibt, wo es ist – ich schlage es nicht mehr vor. Im Verlauf kannst du das zurücknehmen.");
        loadNextSingle();
      }
    },
  });
}

const HINT_CHIPS = [
  ["Ist privat", "Das ist ein privates Dokument."],
  ["Ist beruflich", "Das ist ein berufliches Dokument."],
  ["Gehört zu …", "Das gehört zu "],
  ["Datum stimmt nicht", "Das Datum im Dateinamen stimmt nicht – nimm das Datum, das im Dokument steht."],
  ["Anderer Absender", "Der Absender ist eigentlich "],
];

function hintBox(c) {
  const open = !!c.hintOpen;
  return `<div class="disclosure ${open ? "open" : ""}">
    <button type="button" data-act="hintToggle" aria-expanded="${open}">Hinweis für die KI ${I.chev()}</button>
    ${open ? `<div>
      <div class="row g8 wrapflex">
        <button type="button" class="btn chip" data-act="notDoc">Ist ein Foto, kein Dokument</button>
        ${HINT_CHIPS.map(([l, t]) => `<button type="button" class="btn chip" data-act="hintChip" data-text="${esc(t)}">${esc(l)}</button>`).join("")}
      </div>
      <label class="sr-only" for="hint">Hinweis für die KI</label>
      <input class="text" id="hint" data-input="hintText" value="${esc(c.hintText || "")}" placeholder="z. B. „Rechnungen von Amazon gehören zu Einkäufe“" maxlength="500">
      <div class="row between wrapflex g12"><span class="tiny muted">Ich merke mir den Hinweis auch für ähnliche Dokumente.</span>
        <button type="button" class="btn violet" data-act="hintSend">Neuer Vorschlag mit Hinweis</button></div>
    </div>` : ""}
  </div>`;
}

function zoomPreview() {
  const c = S.cur;
  if (!c || !c.item || !c.preview || c.preview.type !== "image") return;
  const id = c.item.id;
  let page = c.page;
  const draw = async () => {
    const pv = await tryCall("preview", id, page);
    if (!pv) return;
    const box = $modal.querySelector(".zoom-body");
    if (!box) return;
    box.innerHTML = `<img class="zoom-img" src="${pv.data}" alt="Seite ${pv.page + 1}">`;
    $modal.querySelector(".zoom-info").textContent = `Seite ${pv.page + 1} von ${pv.page_count}`;
    $modal.querySelector("[data-act=zp]").disabled = pv.page <= 0;
    $modal.querySelector("[data-act=zn]").disabled = pv.page >= pv.page_count - 1;
  };
  openModal(`<div class="row between g12"><h2>Vorschau</h2><button type="button" class="iconbtn" data-act="close" aria-label="Schließen">${I.x()}</button></div>
    <div class="zoom-body"><div class="spinner"></div></div>
    <div class="row g12" style="justify-content:center"><button type="button" class="iconbtn" data-act="zp" aria-label="Vorherige Seite">${I.prev()}</button>
    <span class="zoom-info small muted"></span><button type="button" class="iconbtn" data-act="zn" aria-label="Nächste Seite">${I.next()}</button></div>`,
    { close: () => closeModal(null), zp: () => { page = Math.max(0, page - 1); draw(); }, zn: () => { page += 1; draw(); } }, true);
  draw();
}

/* ---------- Scan-Stapel ---------- */
function drawStack() {
  const c = S.cur;
  const it = c.item;
  const [backLabel, backFn] = backTo(c.origin);
  if (!c.starts) c.starts = new Set(it.starts || [1]);
  const n = it.page_count;
  const thumbs = c.thumbs;
  const groups = [];
  let cur = [];
  for (let p = 1; p <= n; p++) {
    if (p > 1 && c.starts.has(p)) { groups.push(cur); cur = []; }
    cur.push(p);
  }
  groups.push(cur);
  const count = groups.length;
  const html = groups.map((pages, gi) => {
    const inner = pages.map((p, pi) => `<div class="row">
        <div class="stack g8" style="align-items:center">
          ${thumbs ? `<img class="thumb" src="${thumbs[p - 1] || ""}" alt="Seite ${p}">` : `<div class="thumb" style="height:8rem"></div>`}
          <span class="tiny muted">Seite ${p}</span></div>
        ${pi < pages.length - 1 ? `<button type="button" class="cutadd" data-act="cut" data-p="${p + 1}" aria-label="Vor Seite ${p + 1} trennen" title="Hier trennen">${I.plus(18)}</button>` : ""}
      </div>`).join("");
    return `<div class="row" style="align-items:stretch">
      <div class="group"><span style="font-size:1.0625rem;font-weight:700">Dokument ${gi + 1} <span class="muted" style="font-weight:500">· ${plural(pages.length, "Seite", "Seiten")}</span></span>
        <div class="row">${inner}</div></div>
      ${gi < groups.length - 1 ? `<button type="button" class="cut" data-act="join" data-p="${groups[gi + 1][0]}" aria-label="Trennung entfernen" title="Trennung entfernen"><i></i>${I.scissors()}<i></i></button>` : ""}
    </div>`;
  }).join("");
  setHTML(`<div class="screen">${topbar(backLabel, "back", `Datei: ${esc(it.name)} · ${plural(n, "Seite", "Seiten")}`)}
    <main class="wrap wide">
      <div class="stack g10"><h1 class="title">${count === 1 ? "Diese Datei enthält ein einzelnes Dokument" : `In dieser Datei stecken wohl ${count} Dokumente`}</h1>
      <p class="lead" style="max-width:52rem">Ich habe sie an den markierten Stellen getrennt. Klicke zwischen zwei Seiten, um eine Trennung hinzuzufügen – oder auf eine Schere, um sie wieder zu entfernen.</p></div>
      <div class="pages">${html}</div>
      <div class="footbar"><span class="muted" style="flex:1 1 18rem">Danach schlage ich für jedes Dokument einzeln Ordner und Namen vor.</span>
        <div class="row g12 wrapflex"><button type="button" class="btn tall" data-act="single">Ist doch nur ein Dokument</button>
        <button type="button" class="btn primary tall" data-act="split" ${count < 2 ? "disabled" : ""}>${I.check()} So trennen</button></div></div>
    </main></div>`);
  S.actions = {
    back: backFn,
    cut: (el) => { c.starts.add(+el.dataset.p); drawStack(); },
    join: (el) => { c.starts.delete(+el.dataset.p); drawStack(); },
    single: async () => { await tryCall("not_stack", it.id); c.waitingFor = it.id; c.item.stage = "doc"; c.item.status = "waiting"; drawSingle(); },
    split: async (el) => {
      el.disabled = true;
      const n2 = await tryCall("split", it.id, [...c.starts]);
      if (n2) toast(`In ${n2} Dokumente aufgeteilt.`);
      loadNextSingle();
    },
  };
}

/* ---------- Doppeltes Dokument ---------- */
function drawDuplicate() {
  const c = S.cur;
  const it = c.item;
  const d = it.dup || {};
  const [backLabel, backFn] = backTo(c.origin);
  const pv = (p) => p && p.type === "image" ? `<img src="${p.data}" alt="">` : `<div class="spinner"></div>`;
  setHTML(`<div class="screen">${topbar(backLabel, "back", "")}
    <main class="wrap" style="max-width:67.5rem">
      <div class="stack g10"><h1 class="title">Dieses Dokument hast du schon abgelegt</h1>
      <p class="lead">${d.reason === "identisch" ? "Die neue Datei ist genau gleich wie eine Datei in deiner Ablage." : "Der neue Scan hat denselben Inhalt wie ein Dokument, das bereits in deiner Ablage liegt."}</p></div>
      <div class="compare">
        <figure><span class="tag new" style="align-self:flex-start">Neuer Scan</span><div class="pv">${pv(c.preview)}</div>
          <figcaption class="stack g4"><span style="font-size:1.125rem;font-weight:600;overflow-wrap:anywhere">${esc(it.name)}</span></figcaption></figure>
        <div class="stack g8" style="align-items:center;color:var(--ok)"><div class="icon-box" style="background:var(--ok-bg);color:var(--ok);border-radius:50%">${I.equal()}</div>
          <span class="tiny" style="font-weight:600">Gleicher Inhalt</span></div>
        <figure><span class="tag" style="align-self:flex-start;background:var(--divider);color:var(--text-2)">Schon in deiner Ablage</span><div class="pv">${pv(c.dupPreview)}</div>
          <figcaption class="stack g4"><span style="font-size:1.125rem;font-weight:600;overflow-wrap:anywhere">${esc(d.name)}</span>
          <span class="small muted">${esc(d.folder_display || "")}${d.date ? " · abgelegt am " + esc(d.date) : ""}</span></figcaption></figure>
      </div>
      <div class="footbar" style="flex-direction:column;align-items:stretch">
        <div class="row between g12 wrapflex"><span style="font-size:1.125rem;font-weight:600">Was soll mit dem neuen Scan passieren?</span>
          <div class="row g12 wrapflex"><button type="button" class="btn tall" data-act="keep">Trotzdem ablegen</button>
          <button type="button" class="btn primary tall" data-act="trash">${I.trash()} Zur Seite legen</button></div></div>
        <span class="small muted">Ich bewahre den Scan noch 30 Tage auf. Im Verlauf kannst du ihn jederzeit zurückholen.</span></div>
    </main></div>`);
  S.actions = {
    back: backFn,
    keep: async () => { await tryCall("dup_keep", it.id); c.waitingFor = it.id; c.item.stage = "doc"; c.item.status = "waiting"; c.preview = null; drawSingle(); loadPreview(); },
    trash: async () => { if (await tryCall("dup_trash", it.id)) toast("Zur Seite gelegt – im Verlauf kannst du ihn zurückholen."); loadNextSingle(); },
  };
}

/* ---------- Verlauf ---------- */
SCREENS.history = () => {
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Verlauf")}<main class="wrap narrow"><div class="waiting"><div class="spinner"></div></div></main></div>`);
  S.actions = { back: () => go("home") };
  call("history_view").then((h) => { if (S.route === "history") drawHistory(h); }).catch((e) => toast(e.message));
};

function drawHistory(h) {
  const days = h.days.map((d) => `<div class="stack g10"><h2 class="h2">${esc(d.label)}</h2><ul class="hist">
    ${d.entries.map((e) => `<li><span class="time">${esc(e.time)}</span>
      <div class="stack g4 grow" style="flex-basis:18rem"><span class="name ${e.undone ? "struck" : ""}">${esc(e.name)}</span>
      <span class="tiny muted">${e.undone && e.action !== "ignore" ? "zurück im Scan-Ordner" : esc(e.where)}</span></div>
      ${e.undone ? `<span class="row g8" style="color:var(--ok);font-weight:600">${I.check(20)} ${e.action === "ignore" ? "Wird wieder vorgeschlagen" : "Zurückgelegt"}</span>`
        : e.undoable ? `<button type="button" class="btn small violet" data-act="undo" data-id="${esc(e.id)}">${I.undo()} ${e.action === "trash" ? "Zurückholen" : e.action === "ignore" ? "Doch vorschlagen" : "Rückgängig"}</button>` : ""}
    </li>`).join("")}</ul></div>`).join("");
  const reorgs = h.reorgs.map((g) => `<div class="stack g10"><h2 class="h2">${esc(g.label)} · Ablage neu geordnet${g.cancelled ? " (abgebrochen)" : ""}</h2>
    <div class="card row g20 wrapflex"><div class="icon-box">${I.layers(26)}</div>
      <div class="stack g4 grow" style="flex-basis:20rem"><span style="font-size:1.1875rem;font-weight:600">${plural(g.count, "Dokument", "Dokumente")} neu einsortiert</span>
      <span class="tiny muted">${g.undone ? "Diese Neuordnung wurde rückgängig gemacht."
        : g.undo_failed ? `${plural(g.undo_failed, "Dokument wurde", "Dokumente wurden")} inzwischen verändert oder verschoben und blieben, wo sie sind. Du kannst es noch einmal versuchen.`
        : "Die alte Ordnung lässt sich jederzeit komplett wiederherstellen."}</span></div>
      ${g.undone ? "" : `<button type="button" class="btn small danger" data-act="undoReorg" data-id="${esc(g.id)}">Gesamte Neuordnung rückgängig machen</button>`}
    </div></div>`).join("");
  const empty = !h.days.length && !h.reorgs.length;
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Verlauf")}
    <main class="wrap narrow">
      <div class="stack g8"><h1 class="title">Was wohin gekommen ist</h1>
      <p class="lead">Hat sich etwas falsch angefühlt? Mit „Rückgängig“ kommt das Dokument zurück in den Scan-Eingang.</p></div>
      ${empty ? `<div class="card"><p class="lead">Hier ist noch nichts. Sobald du Dokumente einsortierst, erscheinen sie hier.</p></div>` : ""}
      ${days}${reorgs}
    </main></div>`);
  S.actions = {
    back: () => go("home"),
    undo: async (el) => {
      el.disabled = true;
      const r = await tryCall("undo", el.dataset.id);
      if (r) toast(r.ignore ? "Wird wieder vorgeschlagen." : "Liegt wieder im Scan-Ordner.");
      const h2 = await tryCall("history_view");
      if (h2) drawHistory(h2);
    },
    undoReorg: async (el) => {
      const ok = await confirmDialog("Gesamte Neuordnung rückgängig machen?",
        "Alle Dokumente kommen zurück an ihren alten Platz und bekommen ihren alten Namen. Dokumente, die du seitdem neu einsortiert hast, bleiben, wo sie sind.",
        "Ja, rückgängig machen", true);
      if (!ok) return;
      el.disabled = true;
      el.innerHTML = `<div class="spinner small"></div> Wird zurückgesetzt …`;
      const r = await tryCall("undo_reorg", el.dataset.id);
      if (r) toast(r.failed ? `${r.ok} zurückgesetzt. ${r.failed} wurden inzwischen verändert und blieben, wo sie sind.` : "Die alte Ordnung ist wiederhergestellt.");
      const h2 = await tryCall("history_view");
      if (h2) drawHistory(h2);
    },
  };
}

/* ---------- Einstellungen ---------- */
function loadHints() {
  call("hints_view").then((h) => {
    const box = document.getElementById("hints-card");
    if (!box || S.route !== "settings") return;
    const rows = h.hints.map((x) => `<div class="stack g8" style="border-top:1px solid var(--divider);padding-top:0.875rem">
        <div class="row g8"><input class="text" value="${esc(x.text)}" data-change="hintEdit" data-id="${esc(x.id)}" aria-label="Hinweis" maxlength="500">
          <button type="button" class="xbtn" data-act="hintDel" data-id="${esc(x.id)}" aria-label="Hinweis löschen" title="Löschen">${I.x(18)}</button></div>
        <div class="row between wrapflex g8"><span class="tiny muted">${x.source ? "Gemerkt bei „" + esc(x.source) + "“" : "Eigene Regel"}</span>
          <div class="row g8"><span class="tiny muted">Gilt für</span><div class="seg" role="group" style="min-width:20rem">
            <button type="button" style="min-height:2.5rem;font-size:0.9375rem" aria-pressed="${x.scope === "aehnlich"}" data-act="hintScope" data-id="${esc(x.id)}" data-val="aehnlich">Ähnliche Dokumente</button>
            <button type="button" style="min-height:2.5rem;font-size:0.9375rem" aria-pressed="${x.scope === "alle"}" data-act="hintScope" data-id="${esc(x.id)}" data-val="alle">Alle Dokumente</button></div></div></div>
      </div>`).join("");
    box.innerHTML = `<h2 style="font-size:1.3125rem">Das habe ich mir gemerkt</h2>
      <p class="small muted">Diese Hinweise gebe ich der KI mit. Du kannst sie ändern (einfach hineinklicken) oder löschen.</p>
      ${rows || `<p class="muted">Noch keine Hinweise. Du kannst sie in der Einzelprüfung unter „Hinweis für die KI“ geben – oder hier eine Regel anlegen.</p>`}
      <div class="row g8 wrapflex" style="border-top:1px solid var(--divider);padding-top:1rem">
        <input class="text grow" style="flex:1 1 20rem" data-input="ruleText" placeholder="Neue Regel, z. B. „Rechnungen von Amazon gehören zu Einkäufe“" aria-label="Neue Regel" maxlength="500">
        <button type="button" class="btn" data-act="ruleAdd">${I.plus()} Regel hinzufügen</button></div>
      ${h.ignored ? `<div class="row between wrapflex g12" style="border-top:1px solid var(--divider);padding-top:1rem">
        <span>${plural(h.ignored, "Datei ist", "Dateien sind")} als „kein Dokument“ markiert und ${h.ignored === 1 ? "wird" : "werden"} nicht mehr vorgeschlagen.</span>
        <button type="button" class="btn small" data-act="ignoredClear">Wieder vorschlagen</button></div>` : ""}`;
  }).catch((e) => toast(e.message));
}

SCREENS.settings = () => {
  if (!S.params.fresh) { refreshState().then(() => { if (S.route === "settings") go("settings", { fresh: true }); }); }
  setTimeout(loadHints, 0);
  const s = S.state.settings;
  const seg = (key, opts) => `<div class="seg" role="group">${opts.map(([v, l]) => `<button type="button" aria-pressed="${s[key] === v}" data-act="seg" data-key="${key}" data-val="${v}">${l}</button>`).join("")}</div>`;
  const hints = {
    wenig: "Nur Dokumente, bei denen ich mir ganz sicher bin. Du prüfst mehr einzeln.",
    mittel: "Ausgewogen: Sichere Vorschläge gesammelt, alles andere einzeln.",
    viel: "Möglichst viele gesammelt. Geht schneller, du solltest aber genauer hinschauen.",
  };
  const m = S.state.model || {};
  const lb = S.state.last_backup;
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Änderungen werden sofort gespeichert")}
    <main class="wrap wide" style="gap:1.5rem">
      <h1 class="title">Einstellungen</h1>
      <div class="settings-grid">
        <section class="card stack g16"><h2 style="font-size:1.3125rem">Ordner</h2>
          <div class="row g12 wrapflex"><div class="stack g4 grow" style="flex-basis:14rem"><span class="tiny muted">Scan-Ordner</span><span class="value" style="font-size:1.125rem">${esc(s.inbox_display)}</span></div>
            <button type="button" class="btn small violet" data-act="chooseInbox">Ändern</button></div>
          <hr class="hr">
          <div class="row g12 wrapflex"><div class="stack g4 grow" style="flex-basis:14rem"><span class="tiny muted">Ablage</span><span class="value" style="font-size:1.125rem">${esc(s.library_display)}</span></div>
            <button type="button" class="btn small violet" data-act="chooseLib">Ändern</button></div>
        </section>
        <section class="card stack g16"><h2 style="font-size:1.3125rem">Darstellung</h2>
          <div class="stack g10"><span class="tiny muted">Schriftgröße</span>${seg("font_size", [["normal", "Normal"], ["gross", "Groß"], ["sehr", "Sehr groß"]])}</div>
          <div class="stack g10"><span class="tiny muted">Hell oder dunkel</span>${seg("theme", [["auto", "Wie Windows"], ["hell", "Hell"], ["dunkel", "Dunkel"]])}</div>
        </section>
        <section class="card stack g16"><h2 style="font-size:1.3125rem">Vorschläge</h2>
          <div class="stack g10"><span class="tiny muted">Wie viele Dokumente darf ich dir gesammelt zum Abhaken zeigen?</span>
          ${seg("batch_level", [["wenig", "Wenige"], ["mittel", "Ausgewogen"], ["viel", "Viele"]])}
          <span class="tiny muted">${esc(hints[s.batch_level] || "")}</span></div>
        </section>
        <section class="card stack g16"><h2 style="font-size:1.3125rem">KI und Sicherungen</h2>
          <div class="row g12 wrapflex"><div class="stack g4 grow" style="flex-basis:14rem"><span class="tiny muted">KI</span>
            <span style="font-size:1.125rem;font-weight:600">${esc(m.label || "–")} · hat sich ${plural(S.state.memory_count, "Entscheidung", "Entscheidungen")} gemerkt</span></div>
            <button type="button" class="btn small violet" data-act="models">Andere KI wählen</button></div>
          <hr class="hr">
          <div class="row g12 wrapflex"><div class="stack g4 grow" style="flex-basis:14rem"><span class="tiny muted">Letzte Sicherung</span>
            <span style="font-size:1.125rem;font-weight:600">${lb ? esc(new Date(lb.ts * 1000).toLocaleDateString("de-DE", { day: "numeric", month: "long" })) + " · " + plural(lb.count, "Datei", "Dateien") : "Noch keine"}</span></div>
            <button type="button" class="btn small violet" data-act="backups">Sicherungen verwalten</button></div>
          <button type="button" class="textbtn" style="align-self:flex-start" data-act="forget">Gelerntes vergessen und neu anfangen …</button>
        </section>
      </div>
      <section class="card stack g16" id="hints-card"><h2 style="font-size:1.3125rem">Das habe ich mir gemerkt</h2>
        <div class="waiting" style="padding:1rem"><div class="spinner small"></div></div></section>
      <p class="tiny muted">Ordnungsliebe ${esc(S.state.version)}</p>
    </main></div>`);
  S.actions = {
    back: () => go("home"),
    seg: async (el) => {
      const ch = {}; ch[el.dataset.key] = el.dataset.val;
      const r = await tryCall("save_settings", ch);
      if (r) { await refreshState(); render(); }
    },
    chooseInbox: async () => {
      const f = await browseFolder(s.inbox_dir, "Welcher Ordner ist dein Scan-Ordner?", true);
      if (f) { await tryCall("save_settings", { inbox_dir: f.path }); await refreshState(); render(); }
    },
    chooseLib: async () => {
      const f = await browseFolder(s.library_dir, "Welcher Ordner ist deine Ablage?", false);
      if (!f) return;
      const ok = await confirmDialog("Ablage ändern?", `Neue Dokumente kommen ab jetzt nach „${f.display}“. Bereits abgelegte Dokumente bleiben, wo sie sind.`, "Ablage ändern");
      if (ok) { await tryCall("save_settings", { library_dir: f.path }); await refreshState(); render(); }
    },
    models: () => modelDialog(),
    backups: () => backupsDialog(),
    hintEdit: async (el) => {
      const v = el.value.trim();
      if (!v) return;
      if (await tryCall("hint_update", el.dataset.id, v, null)) toast("Gespeichert.");
    },
    hintScope: async (el) => { if (await tryCall("hint_update", el.dataset.id, null, el.dataset.val)) loadHints(); },
    hintDel: async (el) => { if (await tryCall("hint_delete", el.dataset.id)) loadHints(); },
    ruleText: (el) => { S.ruleText = el.value; },
    ruleAdd: async () => {
      const v = (S.ruleText || "").trim();
      if (!v) { toast("Bitte eine Regel eingeben."); return; }
      if (await tryCall("hint_add_rule", v)) { S.ruleText = ""; loadHints(); toast("Regel gespeichert."); }
    },
    ignoredClear: async () => {
      const ok = await confirmDialog("Wieder vorschlagen?", "Alle Dateien, die du als „kein Dokument“ markiert hast, schlage ich wieder zum Einsortieren vor.", "Ja, wieder vorschlagen");
      if (ok && (await tryCall("ignored_clear")) !== undefined) { toast("Erledigt."); loadHints(); }
    },
    forget: async () => {
      const ok = await confirmDialog("Gelerntes vergessen?", "Ordnungsliebe vergisst alle bisherigen Entscheidungen und schlägt wieder ohne Erfahrung vor. Deine Dokumente bleiben unverändert.", "Ja, vergessen", true);
      if (ok && await tryCall("reset_memory")) { toast("Erledigt – ich fange neu an zu lernen."); await refreshState(); render(); }
    },
  };
};

async function modelDialog() {
  const hw = await tryCall("hardware");
  if (!hw) return;
  const cur = S.state.model.model_id;
  let sel = cur;
  const draw = () => {
    const body = $modal.querySelector(".mlist");
    body.innerHTML = hw.models.map((m) => `<button type="button" class="choice ${m.id === sel ? "on" : ""}" data-act="sel" data-id="${m.id}">
      <input type="radio" name="m" ${m.id === sel ? "checked" : ""} tabindex="-1" aria-hidden="true">
      <div class="stack g4 grow"><span style="font-size:1.1875rem;font-weight:600">${esc(m.label)} <span class="tiny muted">· ${String(m.size_gb).replace(".", ",")} GB</span></span>
      <span class="small muted">${esc(m.description)}${!m.gpu_ok && !m.ram_ok ? " Für diesen Computer zu groß." : !m.gpu_ok ? " Läuft hier ohne Grafikkarte – langsamer." : ""}</span></div>
      ${m.installed ? '<span class="tag ok">Bereit</span>' : ""}${m.id === hw.recommended ? '<span class="tag accent">Empfohlen</span>' : ""}</button>`).join("");
  };
  openModal(`<h2>Welche KI soll ich verwenden?</h2>
    <p class="small muted">${hw.hardware.gpu_name ? "Grafikkarte: " + esc(hw.hardware.gpu_name) + " · " : ""}${String(hw.hardware.ram_gb).replace(".", ",")} GB Arbeitsspeicher · ${String(hw.free_disk_gb).replace(".", ",")} GB frei</p>
    <div class="stack g10 mlist"></div>
    <div id="dl-box"></div>
    <div class="btns"><button type="button" class="btn" data-act="cancel">Schließen</button><button type="button" class="btn primary" data-act="use">Diese KI verwenden</button></div>`, {
    sel: (el) => { sel = el.dataset.id; draw(); },
    cancel: () => closeModal(null),
    use: async () => {
      if (sel === cur) { closeModal(null); return; }
      const r = await tryCall("change_model", sel);
      if (r) { await refreshState(); updateDownloadUI(); toast(r.installed ? "Die neue KI ist bereit." : "Die neue KI wird heruntergeladen …"); }
    },
  });
  draw();
}

async function backupsDialog() {
  const list = (await tryCall("backups_list")) || [];
  const draw = (items) => items.length ? items.map((b) => `<div class="card row g12 wrapflex" style="padding:1rem 1.25rem">
      <div class="stack g4 grow" style="flex-basis:14rem"><span style="font-weight:600">${esc(b.label)}</span>
      <span class="tiny muted">${plural(b.count, "Datei", "Dateien")} · ${b.size_mb} MB${b.exists ? "" : " · nicht mehr vorhanden"}</span></div>
      ${b.exists ? `<button type="button" class="btn small" data-act="open" data-path="${esc(b.path)}">Ordner öffnen</button>
      <button type="button" class="btn small danger" data-act="del" data-id="${esc(b.id)}">Löschen</button>` : ""}</div>`).join("")
    : `<p class="lead">Es gibt noch keine Sicherungen. Vor jeder Neuordnung lege ich automatisch eine an.</p>`;
  openModal(`<h2>Sicherungen</h2><p class="small muted">Vor jeder Neuordnung sichere ich deine komplette Ablage. Ältere Sicherungen kannst du löschen, um Platz zu sparen.</p>
    <div class="stack g10" id="bl">${draw(list)}</div>
    <div class="btns"><button type="button" class="btn" data-act="close">Schließen</button></div>`, {
    close: () => closeModal(null),
    open: (el) => tryCall("open_folder", el.dataset.path),
    del: async (el) => {
      el.disabled = true;
      await tryCall("delete_backup", el.dataset.id);
      const l2 = (await tryCall("backups_list")) || [];
      const box = document.getElementById("bl");
      if (box) box.innerHTML = draw(l2);
      refreshState();
    },
  });
}

function updateDownloadUI() {
  const p = S.dl || (S.state && S.state.model) || {};
  const pct = p.percent || 0;
  const bar = document.getElementById("dl-bar");
  if (bar) bar.style.width = pct + "%";
  const txt = document.getElementById("dl-text");
  if (txt) txt.textContent = downloadText(p);
  const pc = document.getElementById("dl-pct");
  if (pc) pc.textContent = Math.round(pct) + " %";
  const box = document.getElementById("dl-box");
  if (box && p.state === "running") box.innerHTML = `<div class="stack g8"><div class="progress"><div style="width:${pct}%"></div></div><span class="small muted">${esc(downloadText(p))}</span></div>`;
  if (S.route === "setup" && S.setup.step === 2) {
    const done = p.state === "done" || p.installed;
    const btn = document.getElementById("next2");
    if (btn) btn.disabled = !done;
    const pause = document.getElementById("pause2");
    if (pause) pause.textContent = p.state === "paused" ? "Fortsetzen" : "Pausieren";
    if (done && !S.setup.dlDoneDrawn) { S.setup.dlDoneDrawn = true; render(); }
    if (p.state === "error") render();
  }
}

function downloadText(p) {
  if (p.state === "done" || p.installed) return "Fertig – die KI ist bereit.";
  if (p.state === "error") return p.error || "Der Download ist abgebrochen.";
  if (p.state === "paused") return "Pausiert.";
  const gb = (b) => (b / 1e9).toFixed(1).replace(".", ",");
  let t = p.total ? `${gb(p.done)} von ${gb(p.total)} GB` : "Wird vorbereitet …";
  if (p.seconds_left) {
    const m = Math.ceil(p.seconds_left / 60);
    t += m <= 1 ? " · noch etwa 1 Minute" : ` · noch etwa ${m} Minuten`;
  }
  return t;
}

/* ---------- Einrichtung ---------- */
const STEPS = ["Willkommen", "KI vorbereiten", "Scan-Ordner", "Ablage", "Fertig"];

function stepsHTML(cur) {
  return `<ol class="steps" aria-label="Fortschritt der Einrichtung">${STEPS.map((s, i) => {
    const n = i + 1;
    return `<li class="${n < cur ? "done" : n === cur ? "cur" : ""}" ${n === cur ? 'aria-current="step"' : ""}><span></span>${n} · ${s}</li>`;
  }).join("")}</ol>`;
}

SCREENS.setup = () => {
  const st = S.setup;
  const step = st.step;
  S.actions = {
    next: () => { st.step++; render(); },
    prev: () => { st.step--; render(); },
  };
  let body = "";

  if (step === 1) {
    const feat = (icon, t, d) => `<li><div class="icon-box s">${icon}</div><div class="stack g4"><span style="font-size:1.1875rem;font-weight:600">${t}</span><span class="muted">${d}</span></div></li>`;
    body = `<section class="card big stack g28">
      <div class="stack g20" style="align-items:flex-start"><div class="logo big">${I.logo(38)}</div>
        <h1 class="title xl">Willkommen bei Ordnungsliebe</h1>
        <p class="lead" style="font-size:1.25rem">Ordnungsliebe sortiert deine Dokumente in passende Ordner und gibt ihnen Namen, die man auf einen Blick versteht. Du behältst dabei immer die Kontrolle.</p></div>
      <ul class="features">
        ${feat(I.folder(), "Schlägt Ordner und Namen vor", "Nichts wird verschoben, bevor du zugestimmt hast.")}
        ${feat(I.check(24, 2), "Lernt aus deinen Entscheidungen", "Je öfter du es benutzt, desto treffsicherer wird es.")}
        ${feat(I.lock(24), "Bleibt auf deinem Computer", "Deine Dokumente gehen nie ins Internet.")}
      </ul>
      <div class="actions" style="align-items:center"><span class="muted">Die Einrichtung dauert etwa 10 Minuten.</span>
        <button type="button" class="btn primary tall shadow" data-act="next">Los geht's ${I.right()}</button></div></section>`;
  }

  if (step === 2) {
    if (!st.hw) {
      call("hardware").then(async (hw) => {
        st.hw = hw;
        const fake = S.state.fake_ai;
        const model = S.state.model || {};
        const chosen = model.installed ? model.model_id : hw.recommended;
        if (!fake && !(model.installed)) {
          if (hw.enough_disk) {
            const r = await tryCall("start_download", chosen);
            if (r) S.dl = r;
          }
        } else {
          S.dl = { state: "done", percent: 100, installed: true };
          if (!model.model_id) await tryCall("start_download", chosen);
        }
        render();
      }).catch((e) => toast(e.message));
      body = `<section class="card big"><div class="waiting"><div class="spinner"></div><p class="lead">Ich schaue mir deinen Computer an …</p></div></section>`;
    } else {
      const hw = st.hw;
      const p = S.dl || {};
      const done = p.state === "done" || p.installed;
      const spec = hw.models.find((m) => m.id === (S.state.model.model_id || hw.recommended)) || hw.models[0];
      const hwNote = hw.gpu
        ? `<div class="notice ok">${I.check(26, 2.2)}<div><b>Dein Computer ist gut gerüstet</b>Ich verwende die KI „${esc(spec.label)}“. ${esc(spec.description)}</div></div>`
        : `<div class="notice warn">${I.warn()}<div><b>Ohne starke Grafikkarte geht es etwas langsamer</b>Ich verwende die KI „${esc(spec.label)}“. Pro Dokument dauert es dann eine Weile länger – das Ergebnis ist trotzdem gut.</div></div>`;
      const disk = hw.enough_disk ? "" : `<div class="notice warn">${I.warn()}<div><b>Zu wenig Platz</b>Für die KI werden etwa ${String(spec.size_gb).replace(".", ",")} GB benötigt, frei sind ${String(hw.free_disk_gb).replace(".", ",")} GB. Bitte mach etwas Platz frei und starte dann neu.</div></div>`;
      body = `<section class="card big stack g28">
        <div class="stack g10"><h1 class="title">Die Ordnungs-KI wird vorbereitet</h1>
        <p class="lead">Das passiert nur ein einziges Mal. Danach arbeitet Ordnungsliebe komplett ohne Internet.</p></div>
        ${hwNote}${disk}
        <div class="stack g12">
          <div class="row between g12 wrapflex"><span style="font-size:1.125rem;font-weight:600">${done ? "Fertig!" : p.state === "error" ? "Unterbrochen" : "Wird heruntergeladen …"}</span>
          <span id="dl-pct" style="font-size:1.125rem;font-weight:700;color:var(--violet-strong)">${Math.round(done ? 100 : p.percent || 0)} %</span></div>
          <div class="progress" role="progressbar" aria-label="Download-Fortschritt" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(done ? 100 : p.percent || 0)}"><div id="dl-bar" style="width:${done ? 100 : p.percent || 0}%"></div></div>
          <span class="muted" id="dl-text">${esc(downloadText(done ? { state: "done" } : p))}</span>
        </div>
        <p class="muted">Du kannst den Computer währenddessen ganz normal benutzen. Wird die Verbindung unterbrochen, geht es später an derselben Stelle weiter.</p>
        <div class="actions">
          <div class="row g12 wrapflex">${done ? "" : `<button type="button" class="btn" id="pause2" data-act="pause">${p.state === "paused" || p.state === "error" ? "Fortsetzen" : "Pausieren"}</button>`}
          <button type="button" class="btn link" data-act="models">Andere KI wählen</button></div>
          <button type="button" class="btn primary" id="next2" data-act="next" ${done ? "" : "disabled"}>Weiter ${I.right()}</button></div>
      </section>`;
      S.actions.pause = async () => {
        const cur = S.dl || {};
        if (cur.state === "paused" || cur.state === "error") { const r = await tryCall("start_download", S.state.model.model_id || hw.recommended); if (r) S.dl = r; }
        else await tryCall("pause_download");
        render();
      };
      S.actions.models = async () => { await modelDialog(); await refreshState(); render(); };
    }
  }

  if (step === 3) {
    if (!st.inbox) {
      call("suggest_inbox").then((r) => { st.inbox = r; render(); }).catch((e) => toast(e.message));
    }
    const inbox = st.inbox;
    const f = st.finder || {};
    let finder;
    if (f.state === "waiting") finder = `<div class="row g12"><div class="spinner small"></div><span>Ich warte auf deinen Test-Scan … Scanne jetzt eine beliebige Seite.</span></div>
      <button type="button" class="btn small" style="align-self:flex-start" data-act="stopFind">Abbrechen</button>`;
    else if (f.state === "timeout") finder = `<p class="muted">Ich habe leider keinen neuen Scan gefunden. Vielleicht speichert dein Scanner in einem anderen Ordner – wähle ihn dann bitte oben aus, oder versuche es noch einmal.</p>
      <button type="button" class="btn small violet" style="align-self:flex-start" data-act="find">${I.search()} Noch einmal suchen</button>`;
    else finder = `<p style="color:var(--text-2)">Kein Problem. Scanne jetzt einfach eine beliebige Seite. Ich suche die neue Datei auf deinem Computer und schlage dir den richtigen Ordner vor.</p>
      <button type="button" class="btn violet" style="align-self:flex-start;height:3.25rem" data-act="find">${I.search()} Nach meinem Test-Scan suchen</button>`;
    body = `<section class="card big stack g24">
      <div class="stack g10"><h1 class="title">Wo legt dein Scanner die Dateien ab?</h1>
      <p class="lead">Diesen Ordner behalte ich im Blick. Alles, was dort neu landet, schlage ich dir zum Einsortieren vor.</p></div>
      <div class="stack g10"><span class="label">Scan-Ordner</span>
        <div class="row g12 wrapflex"><div class="pathbox"><span style="color:var(--violet)">${I.folder()}</span>${inbox ? esc(inbox.display) : '<div class="spinner small"></div>'}</div>
        <button type="button" class="btn tall violet" data-act="choose">Anderen Ordner wählen …</button></div>
        ${inbox && inbox.count ? `<div class="row g10" style="color:var(--ok-text)">${I.check(20)} Darin liegen schon ${plural(inbox.count, "Dokument", "Dokumente")}. Um die kümmern wir uns gleich zuerst.</div>`
          : inbox && inbox.exists === false ? `<div class="small muted">Diesen Ordner lege ich für dich an. Stelle deinen Scanner so ein, dass er dort speichert.</div>` : ""}
      </div>
      <div class="disclosure ${st.helpOpen ? "open" : ""}"><button type="button" data-act="help" aria-expanded="${!!st.helpOpen}">Ich weiß nicht, wo mein Scanner speichert ${I.chev()}</button>
        ${st.helpOpen ? `<div>${finder}</div>` : ""}</div>
      <div class="actions"><button type="button" class="btn" data-act="prev">Zurück</button>
        <button type="button" class="btn primary" data-act="next" ${inbox ? "" : "disabled"}>Weiter ${I.right()}</button></div></section>`;
    Object.assign(S.actions, {
      choose: async () => {
        const r = await browseFolder(inbox && inbox.exists ? inbox.path : "", "Welcher Ordner ist dein Scan-Ordner?", true);
        if (r) { const info = await tryCall("inbox_info", r.path); st.inbox = { path: r.path, display: r.display, count: info ? info.count : 0, exists: true }; render(); }
      },
      help: () => { st.helpOpen = !st.helpOpen; render(); },
      find: async () => { st.finder = { state: "waiting" }; render(); await tryCall("find_scan_start"); },
      stopFind: async () => { await tryCall("find_scan_stop"); st.finder = null; render(); },
      next: () => { tryCall("find_scan_stop"); st.step++; render(); },
    });
  }

  if (step === 4) {
    if (!st.roots) {
      call("cloud_roots").then((r) => {
        st.roots = r;
        if (!st.lib && r.length) { st.lib = { path: r[0].path, display: r[0].display }; loadLibInfo(); }
        render();
      }).catch((e) => toast(e.message));
    }
    const roots = st.roots || [];
    const opts = roots.map((r) => ({ id: r.path, title: r.title, sub: r.display, found: true }));
    if (st.lib && !roots.some((r) => r.path === st.lib.path)) opts.push({ id: st.lib.path, title: "Eigener Ordner", sub: st.lib.display, found: false });
    const li = st.libInfo;
    const optsHTML = opts.map((o) => `<button type="button" class="choice ${st.lib && st.lib.path === o.id ? "on" : ""}" data-act="pickRoot" data-path="${esc(o.id)}">
        <input type="radio" name="ablage" ${st.lib && st.lib.path === o.id ? "checked" : ""} tabindex="-1" aria-hidden="true">
        <div class="stack g4 grow"><span style="font-size:1.1875rem;font-weight:600">${esc(o.title)}</span><span class="muted">${esc(o.sub)}</span></div>
        ${o.found ? '<span class="tag ok">Gefunden</span>' : ""}</button>`).join("");
    body = `<section class="card big stack g24">
      <div class="stack g10"><h1 class="title">Wo sollen deine Dokumente hin?</h1>
      <p class="lead">In diesem Ordner lege ich alles ab. Wenn dort schon Dokumente liegen, kann ich sie später auch aufräumen.</p></div>
      <div class="stack g12" role="radiogroup" aria-label="Ablageort">${st.roots ? optsHTML : '<div class="spinner"></div>'}
        <button type="button" class="choice" data-act="chooseLib"><span style="width:1.5rem;color:var(--violet)">${I.folder()}</span>
        <div class="stack g4 grow"><span style="font-size:1.1875rem;font-weight:600">Anderer Ordner …</span><span class="muted">Zum Beispiel ein Ordner auf diesem Computer oder auf einem Netzlaufwerk</span></div></button></div>
      ${li && li.ok ? `<div class="small muted">${li.count ? `Darin liegen ${plural(li.count, "Dokument", "Dokumente")}.` : "Der Ordner ist noch leer."}</div>` : ""}
      ${li && li.cloud_only ? `<div class="notice warn">${I.cloud()}<div class="stack g10" style="width:100%"><span>${plural(li.cloud_only, "Datei liegt", "Dateien liegen")} nur in der Cloud und nicht auf diesem Computer. Damit ich sie lesen kann, lade ich sie einmal herunter (etwa ${li.cloud_mb} MB).</span>
        <label class="row g12" style="font-weight:600;min-height:2.75rem;cursor:pointer"><input type="checkbox" ${st.keepLocal !== false ? "checked" : ""} data-change="keepLocal" style="width:1.375rem;height:1.375rem;accent-color:var(--accent)"> Ja, Dateien auf diesem Computer behalten</label></div></div>` : ""}
      <div class="actions"><button type="button" class="btn" data-act="prev">Zurück</button>
        <button type="button" class="btn primary" data-act="next" ${st.lib ? "" : "disabled"}>Weiter ${I.right()}</button></div></section>`;
    Object.assign(S.actions, {
      pickRoot: (el) => { const o = opts.find((x) => x.id === el.dataset.path); st.lib = { path: o.id, display: o.sub }; st.libInfo = null; loadLibInfo(); render(); },
      chooseLib: async () => {
        const r = await browseFolder(st.lib ? st.lib.path : "", "Welcher Ordner ist deine Ablage?", false);
        if (r) { st.lib = { path: r.path, display: r.display }; st.libInfo = null; loadLibInfo(); render(); }
      },
      keepLocal: (el) => { st.keepLocal = el.checked; },
      next: () => {
        if (st.inbox && st.lib) {
          const norm = (x) => x.replace(/[\\/]+$/, "").toLowerCase() + "/";
          const a = norm(st.inbox.path.replace(/\\/g, "/")), b = norm(st.lib.path.replace(/\\/g, "/"));
          if (a.startsWith(b) || b.startsWith(a)) { toast("Scan-Ordner und Ablage müssen getrennte Ordner sein – keiner darf im anderen liegen."); return; }
        }
        st.step++; render();
      },
    });
  }

  if (step === 5) {
    const li = st.libInfo || {};
    body = `<section class="card big stack g28">
      <div class="row g20 wrapflex"><div class="icon-box" style="width:4.75rem;height:4.75rem;border-radius:50%;background:var(--ok-bg);color:var(--ok)">${I.check(40, 2.4)}</div>
        <div class="stack g4 grow" style="flex-basis:22rem"><h1 class="title">Alles bereit!</h1><p class="lead">Wie möchtest du anfangen?</p></div></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(18.75rem,1fr));gap:1rem">
        <button type="button" class="choice-card ${li.count ? "rec" : ""}" data-act="finish" data-choice="reorg">
          <div class="row between g12"><div class="icon-box s">${I.layers(26)}</div>${li.count ? '<span class="tag accent">Empfohlen</span>' : ""}</div>
          <span style="font-size:1.3125rem;font-weight:700">Erst die Ablage aufräumen</span>
          <span class="muted">${li.count ? `In deiner Ablage liegen ${plural(li.count, "Dokument", "Dokumente")}. Ich schlage dir eine übersichtliche Ordnung vor – vorher mache ich eine Sicherung.` : "Ich schlage dir eine übersichtliche Ordnung für deine Ablage vor – vorher mache ich eine Sicherung."}</span></button>
        <button type="button" class="choice-card ${li.count ? "" : "rec"}" data-act="finish" data-choice="direct">
          <div class="row between g12"><div class="icon-box s">${I.doc(26)}</div>${li.count ? "" : '<span class="tag accent">Empfohlen</span>'}</div>
          <span style="font-size:1.3125rem;font-weight:700">Direkt mit neuen Scans loslegen</span>
          <span class="muted">Die bestehende Ablage bleibt, wie sie ist. Aufräumen kannst du jederzeit später.</span></button>
      </div>
      <dl style="margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(12.5rem,1fr));gap:0.75rem;border-top:1px solid var(--divider);padding-top:1.375rem">
        <div class="stack g4"><dt class="tiny muted">Scan-Ordner</dt><dd style="margin:0;font-weight:600">${esc(st.inbox ? st.inbox.display : "")}</dd></div>
        <div class="stack g4"><dt class="tiny muted">Ablage</dt><dd style="margin:0;font-weight:600">${esc(st.lib ? st.lib.display : "")}</dd></div>
        <div class="stack g4"><dt class="tiny muted">KI</dt><dd style="margin:0;font-weight:600">${esc((S.state.model && S.state.model.label) || "Bereit")}, offline bereit</dd></div>
      </dl>
      <div class="row between wrapflex g12"><span class="muted small">Alles lässt sich später unter „Einstellungen“ ändern.</span>
        <button type="button" class="btn" data-act="prev">Zurück</button></div></section>`;
    S.actions.finish = async (el) => {
      el.disabled = true;
      const choice = el.dataset.choice;
      if (li.cloud_only && st.keepLocal !== false) await tryCall("keep_local", st.lib.path);
      const r = await tryCall("finish_setup", st.inbox.path, st.lib.path, choice);
      if (!r) { el.disabled = false; return; }
      await refreshState();
      go(choice === "reorg" ? "reorg" : "home");
    };
  }

  setHTML(`<div class="wizard"><div class="wizard-inner">
    <div class="row g12"><div class="logo" style="width:2.5rem;height:2.5rem;border-radius:0.6875rem">${I.logo(22)}</div><span style="font-size:1.25rem;font-weight:700">Ordnungsliebe einrichten</span></div>
    ${stepsHTML(step)}${body}</div></div>`);
};

function loadLibInfo() {
  const st = S.setup;
  if (!st.lib) return;
  const path = st.lib.path;
  call("library_info", path).then((r) => {
    if (S.setup.lib && S.setup.lib.path === path) { st.libInfo = r; if (S.route === "setup") render(); }
  }).catch(() => {});
}

/* ---------- Neuordnung ---------- */
function refreshReorg() {
  call("reorg_status").then((r) => { S.state.reorg = r; if (S.route === "reorg") render(); }).catch(() => {});
}

SCREENS.reorg = () => {
  const r = S.state.reorg || {};
  const phase = r.phase || "";
  if (["backup", "reading", "structure"].includes(phase)) return drawReorgProgress(r);
  if (phase === "paused") return drawReorgPaused(r);
  if (phase === "structure_review") return drawStructure();
  if (phase === "review") return drawReorgHub(r);
  if (phase === "done" && S.reorgJustDone) return drawReorgDone(r);
  return drawReorgIntro(r);
};

function drawReorgIntro(r) {
  S.reorgMode = S.reorgMode || "neu";
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen")}
    <main class="wrap narrow"><div class="waiting"><div class="spinner"></div></div></main></div>`);
  S.actions = { back: () => go("home") };
  call("library_overview").then((li) => {
    if (S.route !== "reorg") return;
    const opt = (id, title, text) => `<button type="button" class="choice ${S.reorgMode === id ? "on" : ""}" data-act="mode" data-id="${id}" style="align-items:flex-start">
      <input type="radio" name="mode" ${S.reorgMode === id ? "checked" : ""} tabindex="-1" aria-hidden="true" style="margin-top:0.25rem">
      <div class="stack g4"><span style="font-size:1.1875rem;font-weight:600">${title}</span><span class="muted">${text}</span></div></button>`;
    setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen")}
      <main class="wrap narrow">
        <div class="stack g10"><h1 class="title">Ablage neu ordnen</h1>
        <p class="lead">${li && li.ok ? `In „${esc(li.display)}“ liegen ${plural(li.count, "Dokument", "Dokumente")}${li.too_many ? "" : ` – das Einlesen dauert etwa ${durationText(li.minutes)}`}.` : ""} Ich lese alle Dokumente, schlage dir eine übersichtliche Ordnung vor – und du entscheidest. Fotos lasse ich dabei in Ruhe.</p></div>
        ${r.phase === "error" ? `<div class="notice warn">${I.warn()}<div><b>Beim letzten Versuch ist etwas schiefgegangen.</b>${esc(r.error || "")}
          ${r.detail ? `<div class="tiny" style="margin-top:0.5rem;opacity:0.8">Technischer Hinweis: ${esc(r.detail)}</div>` : ""}</div></div>` : ""}
        ${li && li.too_many ? `<div class="notice warn">${I.warn()}<div class="stack g10"><span><b>Das sind sehr viele Dokumente.</b>
          Alle zu lesen und einzuordnen dauert etwa ${durationText(li.minutes)}. Tipp: Wähle als Ablage nur den Ordner, in dem deine Papiere liegen – zum Beispiel „iCloud Drive › Dokumente“.</span>
          <button type="button" class="btn small" style="align-self:flex-start" data-act="changeLib">Ablage-Ordner ändern</button></div></div>` : ""}
        ${li && li.cloud_only ? `<div class="notice warn">${I.cloud()}<div class="stack g10"><span>${plural(li.cloud_only, "Datei liegt", "Dateien liegen")} nur in der Cloud. Damit ich sie lesen kann, lade ich sie vorher herunter (etwa ${li.cloud_mb} MB).</span>
          <button type="button" class="btn small" style="align-self:flex-start" data-act="keepLocal">Jetzt herunterladen</button><span class="small" id="keeplocal-progress"></span></div></div>` : ""}
        <div class="stack g12" role="radiogroup" aria-label="Art der Neuordnung">
          ${opt("neu", "Komplett neue Struktur", "Ich entwerfe aus deinen Dokumenten eine neue, übersichtliche Ordnerstruktur.")}
          ${opt("verbessern", "Bestehende Ordner verbessern", "Deine Ordner bleiben die Grundlage. Ich schlage Zusammenlegungen, neue Ordner und falsch abgelegte Dateien vor.")}
        </div>
        <div class="notice ok">${I.shield()}<div><b>Erst wird alles gesichert</b>Bevor ich etwas verändere, mache ich eine vollständige Sicherung deiner Ablage. Jeder Schritt lässt sich rückgängig machen.</div></div>
        <div class="actions" style="border:none;padding:0"><span class="muted small" style="align-self:center">Das Einlesen dauert je nach Menge eine Weile – du kannst nebenbei weiterarbeiten.</span>
          <button type="button" class="btn primary tall shadow" data-act="start" ${li && li.count ? "" : "disabled"}>Neuordnung starten ${I.right()}</button></div>
        ${li && li.ok && !li.count ? `<p class="muted">In deiner Ablage liegen noch keine Dokumente – hier gibt es nichts aufzuräumen.</p>` : ""}
      </main></div>`);
    S.actions = {
      back: () => go("home"),
      mode: (el) => { S.reorgMode = el.dataset.id; drawReorgIntro(r); },
      changeLib: async () => {
        const f = await browseFolder(S.state.settings.library_dir, "Welcher Ordner soll neu geordnet werden?", false);
        if (!f) return;
        const res = await tryCall("save_settings", { library_dir: f.path });
        if (res) { await refreshState(); toast(`Ablage ist jetzt „${f.display}“.`); drawReorgIntro(S.state.reorg || {}); }
      },
      keepLocal: async (el) => { el.disabled = true; await tryCall("keep_local", S.state.settings.library_dir); },
      start: async (el) => {
        el.disabled = true;
        const st = await tryCall("reorg_start", S.reorgMode);
        if (st) { S.state.reorg = st; S.struct = null; render(); } else el.disabled = false;
      },
    };
  }).catch((e) => toast(e.message));
}

function drawReorgPaused(r) {
  const label = { backup: "Sicherung anlegen", reading: "Dokumente lesen", structure: "Ordnerstruktur entwerfen" }[r.paused_phase] || "";
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen")}
    <main class="wrap narrow">
      <div class="stack g10"><h1 class="title">Die Neuordnung ist pausiert</h1>
      <p class="lead">Alles, was schon erledigt ist, bleibt gespeichert – auch nach einem Neustart oder Update. Es geht genau dort weiter, wo sie stand.</p></div>
      <section class="card big stack g16">
        <span style="font-size:1.125rem;font-weight:600">Gerade dran: ${esc(label)}${r.total ? ` · ${r.done.toLocaleString("de-DE")} von ${r.total.toLocaleString("de-DE")}` : ""}</span>
        <div class="progress"><div style="width:${r.total ? Math.round((r.done / r.total) * 100) : 0}%"></div></div>
      </section>
      <div class="row g12 wrapflex"><button type="button" class="btn primary tall shadow" data-act="resume">Weitermachen ${I.right()}</button>
        <button type="button" class="btn link" data-act="cancel">Neuordnung abbrechen</button></div>
    </main></div>`);
  S.actions = {
    back: () => go("home"),
    resume: async () => { const st = await tryCall("reorg_resume"); if (st) { S.state.reorg = st; render(); } },
    cancel: async () => {
      const ok = await confirmDialog("Neuordnung abbrechen?", "Es wurde noch nichts verschoben. Die Sicherung bleibt erhalten.", "Abbrechen", true);
      if (ok) { await tryCall("reorg_cancel"); await refreshState(); go("home"); }
    },
  };
}

function drawReorgProgress(r) {
  const phases = [["backup", "Sicherung anlegen"], ["reading", "Dokumente lesen"], ["structure", "Ordnerstruktur entwerfen"]];
  const idx = phases.findIndex((p) => p[0] === r.phase);
  const pct = r.total ? Math.round((r.done / r.total) * 100) : 0;
  const list = phases.map(([id, label], i) => {
    const cls = i < idx ? "done" : i === idx ? "cur" : "";
    const icon = i < idx ? I.check(18) : i === idx ? '<div class="spinner small" style="width:1.1rem;height:1.1rem"></div>' : "";
    let extra = "";
    if (i === idx && r.total) extra = ` <span class="muted" style="font-weight:500">· ${r.done} von ${r.total}</span>`;
    return `<li class="${cls}"><span class="pi">${icon}</span>${label}${extra}</li>`;
  }).join("");
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen")}
    <main class="wrap narrow">
      <div class="stack g10"><h1 class="title">Ich lese deine Ablage</h1>
      <p class="lead">Du kannst das Fenster offen lassen und etwas anderes machen. Ich melde mich, wenn ich einen Vorschlag habe.</p></div>
      <section class="card big stack g24">
        <ul class="phase-list">${list}</ul>
        <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div style="width:${pct}%"></div></div>
        ${r.detail && (r.phase === "reading" || r.phase === "backup") ? `<span class="small muted" style="overflow-wrap:anywhere">${esc(r.detail)}</span>` : ""}
        ${r.phase === "backup" ? `<span class="small muted">Dateien, die nur in der iCloud liegen, lade ich dabei herunter – das kann etwas dauern.</span>` : ""}
      </section>
      <div class="row g12 wrapflex"><button type="button" class="btn" data-act="pause">Pause – später weitermachen</button>
        <button type="button" class="btn link" data-act="cancel">Abbrechen</button></div>
    </main></div>`);
  S.actions = {
    back: () => go("home"),
    pause: async (el) => { el.disabled = true; el.textContent = "Wird pausiert …"; await tryCall("reorg_pause"); },
    cancel: async () => {
      const ok = await confirmDialog("Neuordnung abbrechen?", "Es wurde noch nichts verändert. Die Sicherung bleibt erhalten.", "Abbrechen", true);
      if (ok) { await tryCall("reorg_cancel"); await refreshState(); go("home"); }
    },
  };
}

function structToTree(folders) {
  const tops = [];
  const byName = {};
  folders.forEach((f) => {
    const parts = f.path.split("/");
    const top = parts[0];
    const sub = parts.slice(1).join("/");
    if (!byName[top]) { byName[top] = { name: top, scheme: "", example: "", subs: [] }; tops.push(byName[top]); }
    if (sub) byName[top].subs.push({ name: sub, scheme: f.scheme, example: f.example });
    else { byName[top].scheme = f.scheme; byName[top].example = f.example; }
  });
  return tops;
}

function treeToStruct(tops) {
  const out = [];
  tops.forEach((t) => {
    const top = t.name.trim();
    if (!top) return;
    out.push({ path: top, scheme: t.scheme || "JJJJ-MM Dokumentart", example: t.example || "" });
    t.subs.forEach((s) => { if (s.name.trim()) out.push({ path: top + "/" + s.name.trim(), scheme: s.scheme || "JJJJ-MM Dokumentart", example: s.example || "" }); });
  });
  return out;
}

let draftTimer = null;
function saveDraft() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => { if (S.struct) tryCall("reorg_save_structure", treeToStruct(S.struct.tops)); }, 600);
}

function drawStructure() {
  if (!S.struct) {
    setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen")}<div class="waiting"><div class="spinner"></div></div></div>`);
    S.actions = { back: () => go("home") };
    call("reorg_structure").then((d) => { S.struct = { tops: structToTree(d.folders), showEx: true, count: d.doc_count, backup: d.backup, skipped: d.skipped || [], skippedCount: d.skipped_count || 0 }; if (S.route === "reorg") render(); })
      .catch((e) => toast(e.message));
    return;
  }
  const st = S.struct;
  const exName = (x) => x.example ? `z. B. ${x.example}${/\.[a-z0-9]{2,4}$/i.test(x.example) ? "" : ".pdf"}` : "";
  const cards = st.tops.map((t, ti) => `<section class="fcard">
      <div class="row g10"><span style="color:var(--violet)">${I.folder()}</span>
        <input class="fname" value="${esc(t.name)}" aria-label="Ordnername" data-input="topName" data-t="${ti}">
        <button type="button" class="xbtn" data-act="delTop" data-t="${ti}" aria-label="Ordner entfernen" title="Ordner entfernen">${I.x(18)}</button></div>
      ${st.showEx && t.example && !t.subs.length ? `<span class="ex" style="padding-left:2.625rem">${esc(exName(t))}</span>` : ""}
      <ul class="subs">${t.subs.map((s, si) => `<li><div class="row g4"><input class="fname subname" value="${esc(s.name)}" aria-label="Unterordner (weitere Ebene mit /)" data-input="subName" data-t="${ti}" data-s="${si}">
        <button type="button" class="xbtn" data-act="delSub" data-t="${ti}" data-s="${si}" aria-label="Unterordner entfernen" title="Unterordner entfernen">${I.x(16)}</button></div>
        ${st.showEx && s.example ? `<span class="ex">${esc(exName(s))}</span>` : ""}</li>`).join("")}
        <li><button type="button" class="btn link small" style="align-self:flex-start;padding:0" data-act="addSub" data-t="${ti}">${I.plus(16)} Unterordner</button></li></ul>
    </section>`).join("");
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen · Schritt 3 von 4")}
    <main class="wrap wide" style="gap:1.375rem">
      <div class="row between wrapflex g20" style="align-items:flex-end">
        <div class="stack g8" style="flex:1 1 32rem"><h1 class="title">So würde ich deine ${st.count} Dokumente ordnen</h1>
        <p class="lead">Klicke auf einen Ordnernamen, um ihn zu ändern. Noch wird nichts verschoben.</p></div>
        <div class="notice ok" style="padding:0.75rem 1rem;align-items:center">${I.shield()}<span style="font-weight:600">Sicherung erstellt – alles lässt sich wiederherstellen</span></div>
      </div>
      ${st.skippedCount ? `<div class="notice warn">${I.cloud()}<div><b>${plural(st.skippedCount, "Datei konnte", "Dateien konnten")} nicht gesichert oder gelesen werden.</b>
        Diese bleiben genau, wo sie sind – ich fasse sie nicht an.${st.skipped.length ? `<div class="tiny" style="margin-top:0.375rem">z. B. ${st.skipped.slice(0, 3).map((x) => esc(x.rel.split("/").pop()) + " (" + esc(x.reason) + ")").join(", ")}</div>` : ""}</div></div>` : ""}
      <button type="button" class="switch" aria-pressed="${st.showEx}" data-act="toggleEx"><span class="track"><span class="knob"></span></span>Beispiel-Dateinamen anzeigen</button>
      <div class="foldergrid">${cards}</div>
      <div class="row between wrapflex g12" style="margin-top:auto;padding-top:0.5rem">
        <div class="row g12 wrapflex"><button type="button" class="btn" data-act="addTop">${I.plus()} Ordner hinzufügen</button>
        <button type="button" class="btn link" data-act="cancel">Neuordnung abbrechen</button></div>
        <button type="button" class="btn primary tall" data-act="apply">Struktur übernehmen ${I.right()}</button>
      </div>
    </main></div>`);
  S.actions = {
    back: () => go("home"),
    toggleEx: () => { st.showEx = !st.showEx; drawStructure(); },
    topName: (el) => { st.tops[+el.dataset.t].name = el.value; saveDraft(); },
    subName: (el) => { st.tops[+el.dataset.t].subs[+el.dataset.s].name = el.value; saveDraft(); },
    delTop: (el) => { st.tops.splice(+el.dataset.t, 1); saveDraft(); drawStructure(); },
    delSub: (el) => { st.tops[+el.dataset.t].subs.splice(+el.dataset.s, 1); saveDraft(); drawStructure(); },
    addSub: (el) => {
      st.tops[+el.dataset.t].subs.push({ name: "Neuer Unterordner", scheme: "JJJJ-MM Dokumentart", example: "" });
      saveDraft();
      drawStructure();
      const ins = document.querySelectorAll(`[data-input=subName][data-t="${el.dataset.t}"]`);
      if (ins.length) { ins[ins.length - 1].focus(); ins[ins.length - 1].select(); }
    },
    addTop: () => {
      st.tops.push({ name: "Neuer Ordner", scheme: "JJJJ-MM Dokumentart", example: "", subs: [] });
      saveDraft();
      drawStructure();
      const ins = document.querySelectorAll("[data-input=topName]");
      ins[ins.length - 1].focus(); ins[ins.length - 1].select();
    },
    cancel: async () => {
      const ok = await confirmDialog("Neuordnung abbrechen?", "Es wurde noch nichts verschoben. Die Sicherung bleibt erhalten.", "Abbrechen", true);
      if (ok) { await tryCall("reorg_cancel"); S.struct = null; await refreshState(); go("home"); }
    },
    apply: async (el) => {
      const folders = treeToStruct(st.tops);
      if (!folders.length) { toast("Bitte mindestens einen Ordner anlegen."); return; }
      el.disabled = true;
      const r = await tryCall("reorg_apply", folders);
      if (r) { S.state.reorg = r; S.struct = null; render(); } else el.disabled = false;
    },
  };
}

function drawReorgHub(r) {
  const ov = (S.state.queue.by_origin && S.state.queue.by_origin.reorg) || { total: 0, working: 0, batch: 0, ready: 0 };
  const total = (S.state.reorg && S.state.reorg.doc_count) || ov.total;
  const placed = Math.max(0, total - ov.total);
  const allDone = ov.total === 0;
  const pct = total ? Math.round((placed / total) * 100) : 100;
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen · Schritt 4 von 4")}
    <main class="wrap narrow">
      <div class="stack g10"><h1 class="title">${allDone ? "Alle Dokumente haben ihren Platz" : "Jetzt ordnen wir die Dokumente zu"}</h1>
      <p class="lead">${allDone ? "Zum Schluss räume ich leere Ordner auf." : "Ich schlage für jedes Dokument einen Ordner und einen Namen vor. Du bestätigst – wie bei neuen Scans."}</p></div>
      <section class="card big stack g20">
        <div class="row between wrapflex g12"><span style="font-size:1.125rem;font-weight:600">${placed} von ${total} erledigt</span>
        ${ov.working ? `<span class="row g8 muted"><div class="spinner small"></div> ich lese noch ${ov.working}</span>` : ""}</div>
        <div class="progress"><div style="width:${pct}%"></div></div>
      </section>
      ${allDone ? `<div><button type="button" class="btn primary big shadow" style="max-width:28rem" data-act="finish">${I.check(26, 2.6)} Abschließen und aufräumen</button></div>`
        : `<div class="tiles">
          <button type="button" class="tile" data-act="batch" ${ov.batch ? "" : "disabled"} style="${ov.batch ? "" : "opacity:0.55;cursor:default"}"><div class="icon-box">${I.check(28, 2)}</div>
            <span class="tile-title">Sichere Vorschläge abhaken</span><span class="tile-text">${ov.batch ? `${plural(ov.batch, "Dokument", "Dokumente")} – schnell in einer Liste.` : "Gerade keine."}</span></button>
          <button type="button" class="tile" data-act="single" ${ov.ready - ov.batch > 0 ? "" : "disabled"} style="${ov.ready - ov.batch > 0 ? "" : "opacity:0.55;cursor:default"}"><div class="icon-box">${I.doc(28)}</div>
            <span class="tile-title">Einzeln prüfen</span><span class="tile-text">${ov.ready - ov.batch > 0 ? `${plural(ov.ready - ov.batch, "Dokument", "Dokumente")}, bei denen ich unsicher bin.` : "Gerade keine."}</span></button>
        </div>`}
      <div><button type="button" class="btn link" data-act="cancel">Neuordnung abbrechen</button></div>
    </main></div>`);
  S.actions = {
    back: () => go("home"),
    batch: () => go("batch", { origin: "reorg" }),
    single: () => go("single", { origin: "reorg" }),
    finish: async (el) => {
      el.disabled = true;
      const res = await tryCall("reorg_finish");
      if (res) { S.state.reorg = res; S.reorgJustDone = true; render(); } else el.disabled = false;
    },
    cancel: async () => {
      const ok = await confirmDialog("Neuordnung abbrechen?", "Bereits einsortierte Dokumente bleiben an ihrem neuen Platz – im Verlauf kannst du sie alle zusammen zurücksetzen. Alle anderen bleiben unverändert.", "Abbrechen", true);
      if (ok) { await tryCall("reorg_cancel"); await refreshState(); go("home"); }
    },
  };
}

function drawReorgDone(r) {
  const removed = (r.removed_dirs || []).length;
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Ablage neu ordnen")}
    <div class="waiting"><div class="big-icon">${I.check(40, 2.4)}</div><h1 class="title">Deine Ablage ist jetzt aufgeräumt!</h1>
    <p class="lead">${removed ? `${plural(removed, "leerer Ordner wurde", "leere Ordner wurden")} entfernt. ` : ""}Die Sicherung bleibt erhalten. Im Verlauf kannst du alles rückgängig machen.</p>
    <div class="row g12 wrapflex" style="justify-content:center"><button type="button" class="btn tall" data-act="history">Zum Verlauf</button>
    <button type="button" class="btn primary tall shadow" data-act="back">Zur Startseite</button></div></div></div>`);
  S.actions = { back: () => { S.reorgJustDone = false; go("home"); }, history: () => { S.reorgJustDone = false; go("history"); } };
}

/* ===================== Start ===================== */

async function init() {
  try {
    await refreshState();
  } catch (e) {
    setHTML(`<div class="waiting"><h1 class="title">Ordnungsliebe konnte nicht starten</h1><p class="lead">${esc(e.message)}</p></div>`);
    return;
  }
  if (!hasBridge()) startDevPolling();
  if (!S.state.settings.setup_done) go("setup");
  else if (S.state.queue.total === 0 && S.state.reorg && ["backup", "reading", "structure", "structure_review", "review", "paused"].includes(S.state.reorg.phase)) go("reorg");
  else go("home");
}

if (hasBridge()) init();
else {
  let started = false;
  window.addEventListener("pywebviewready", () => { if (!started) { started = true; init(); } });
  setTimeout(() => { if (!started && !hasBridge()) { started = true; init(); } }, 600);
}

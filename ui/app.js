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
  if (ev.key === "Escape" && $modal.innerHTML) { closeModal(null); return; }
  const t = ev.target;
  if (ev.key === "Enter" && t && t.dataset && t.dataset.enter) {
    const b = (t.closest("#modal-root") || document).querySelector(`[data-act="${t.dataset.enter}"]`);
    if (b) { ev.preventDefault(); b.click(); }
    return;
  }
  if ($modal.innerHTML || ev.ctrlKey || ev.altKey || ev.metaKey || ev.repeat) return;
  if (t && (t.closest("input, textarea, select, [contenteditable]") || (t.closest("button, a") && (ev.key === "Enter" || ev.key === " ")))) return;
  const map = SHORTCUTS[S.route];
  const name = map && (map[ev.key] || map[ev.key.toLowerCase()]);
  if (!name) return;
  const btn = document.querySelector(`[data-act="${name}"]:not([disabled])`);
  if (!btn) return;
  ev.preventDefault();
  btn.click();
});

// Tastaturkürzel: Taste → Knopf (data-act), der dann ganz normal angeklickt wird.
const SHORTCUTS = {
  single: { Enter: "confirm", Delete: "reject", " ": "skip", h: "hintToggle" },
  batch: { Enter: "go" },
};

function go(route, params) {
  S.route = route;
  S.params = params || {};
  window.scrollTo(0, 0);
  render();
}

function render() {
  const fn = SCREENS[S.route] || SCREENS.home;
  if (!S.soft) S.lastHTML = null;
  S.actions = {};
  fn();
}

// Neu zeichnen: Bei Meldungen aus dem Hintergrund (S.soft) wird der vorhandene Bildschirm nur
// angepasst statt ersetzt – kein Flackern, Eingaben, Fokus und Bildlauf bleiben erhalten.
function setHTML(html) {
  const same = S.soft && S.lastRoute === S.route && $app.firstElementChild;
  S.lastRoute = S.route;
  if (!same) { $app.innerHTML = html; S.lastHTML = html; return; }
  if (html === S.lastHTML) return;
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  morphChildren($app, tpl.content);
  S.lastHTML = html;
}

function morphChildren(from, to) {
  const a = [...from.childNodes];
  const b = [...to.childNodes];
  for (let i = 0; i < b.length; i++) {
    const n = b[i], o = a[i];
    if (!o) { from.appendChild(n); continue; }
    if (o.nodeType !== n.nodeType || o.nodeName !== n.nodeName || (o.nodeType === 1 && (o.id || "") !== (n.id || ""))) {
      from.replaceChild(n, o); continue;
    }
    if (o.nodeType !== 1) { if (o.nodeValue !== n.nodeValue) o.nodeValue = n.nodeValue; continue; }
    morphElement(o, n);
  }
  for (let i = a.length - 1; i >= b.length; i--) from.removeChild(a[i]);
}

function morphElement(o, n) {
  const tag = o.nodeName;
  const valueChanged = o.getAttribute("value") !== n.getAttribute("value");
  for (const at of [...o.attributes]) if (!n.hasAttribute(at.name)) o.removeAttribute(at.name);
  for (const at of [...n.attributes]) if (o.getAttribute(at.name) !== at.value) o.setAttribute(at.name, at.value);
  if (tag === "INPUT") {
    if (o.type === "checkbox" || o.type === "radio") o.checked = n.hasAttribute("checked");
    else if (valueChanged && o !== document.activeElement) o.value = n.getAttribute("value") || "";
    return;
  }
  if (tag === "TEXTAREA") {
    if (o.defaultValue !== n.defaultValue && o !== document.activeElement) o.value = n.defaultValue;
    return;
  }
  morphChildren(o, n);
}

// Für Meldungen aus dem Hintergrund: gleicher Bildschirm wird sanft aktualisiert.
function softRender() {
  S.soft = true;
  try { render(); } finally { S.soft = false; }
}

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
  cal: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>`,
  user: (s = 24) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1.2-3.8 4-5.5 7.5-5.5s6.3 1.7 7.5 5.5"/></svg>`,
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

/* Update-Dialog */
function updateDialogBody() {
  const u = (S.state && S.state.update) || {};
  let action;
  if (u.state === "downloading") action = `<div class="stack g8"><div class="progress"><div style="width:${u.percent || 0}%"></div></div><span class="small muted">Wird geladen … ${Math.round(u.percent || 0)} %</span></div>`;
  else if (u.state === "ready") action = `<button type="button" class="btn primary tall" data-act="install">${I.check()} Jetzt installieren und neu starten</button>`;
  else if (u.state === "installing") action = `<div class="row g12"><div class="spinner small"></div><span>Ordnungsliebe schließt sich kurz und startet gleich neu …</span></div>`;
  else action = `<button type="button" class="btn primary tall" data-act="download">Neue Version laden (${Math.round((u.size || 0) / 1e6)} MB)</button>`;
  return `<h2>Neue Version ${esc(u.version || "")}</h2>
    ${u.notes && u.notes.length ? `<div class="stack g4"><span class="label">Was ist neu?</span><ul style="margin:0;padding-left:1.25rem;color:var(--text-2)">${u.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>` : ""}
    <p class="small muted">Laufende Arbeit wird vorher gesichert – eine Neuordnung macht danach genau dort weiter. ${u.can_install ? "" : "(Im Testbetrieb lässt sich nicht installieren.)"}</p>
    ${u.error && u.state === "error" ? `<div class="notice warn">${I.warn()}<div>${esc(u.error)}</div></div>` : ""}
    <div class="row between wrapflex g12"><button type="button" class="btn" data-act="close">Später</button>${action}</div>`;
}

function updateDialogRefresh() {
  const box = $modal.querySelector(".upd");
  if (box) box.innerHTML = updateDialogBody();
}

function updateDialog() {
  openModal(`<div class="upd stack g20">${updateDialogBody()}</div>`, {
    close: () => closeModal(null),
    download: async () => { const r = await tryCall("update_download"); if (r) { S.state.update = r; updateDialogRefresh(); } },
    install: async () => { S.state.update.state = "installing"; updateDialogRefresh(); await tryCall("update_install"); },
  });
}

/* ===================== Ereignisse vom Programm ===================== */

const HANDLERS = {
  inspect(st) {
    const was = S.inspect && S.inspect.phase;
    S.inspect = st;
    if (S.route !== "collections") return;
    if (st.phase === "done" && was && was !== "done") render();  // neue Steuer-Mappen anzeigen
    else redrawInspect();
  },
  refine(st) {
    if (!S.refine) return;
    const prev = S.refine.status && S.refine.status.phase;
    S.refine.status = st;
    if (st.phase === "review" && prev !== "review") S.refine.prop = null;
    if (S.route === "refine") { if (prev === st.phase) softRender(); else render(); }
  },
  search(st) {
    if (S.route === "search" && S.search) { S.search.status = { ...(S.search.status || {}), ...st, indexed: st.done }; const el = document.getElementById("search-status"); if (el) el.textContent = searchStatusText(S.search.status); }
  },
  deadlines() { if (S.route === "home") loadDeadlines(); },
  queue(payload) {
    if (!S.state) return;
    S.state.queue = payload;
    if (S.route === "home") softRender();
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
    if (S.route === "home") softRender();
  },
  reorg(p) {
    if (!S.state) return;
    S.state.reorg = p;
    if (S.route === "reorg" || S.route === "home") softRender();
  },
  reorg_item_done() { /* über queue abgedeckt */ },
  update(p) {
    if (!S.state) return;
    S.state.update = p;
    updateDialogRefresh();
    if (S.route === "home") softRender();
  },
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

  const up = st.update || {};
  const updateBanner = up.available
    ? `<div class="notice ok">${I.check(24, 2.2)}<div class="grow"><b>Es gibt eine neue Version (${esc(up.version)}).</b>
       Mit einem Klick ist sie installiert – deine Arbeit bleibt erhalten.</div>
       <button type="button" class="btn small" data-act="update">Ansehen</button></div>` : "";
  setHTML(`<div class="screen">
    <header class="home-head"><div class="brand"><div class="logo">${I.logo()}</div><span class="brand-name">Ordnungsliebe</span></div>
    <div class="pill">${pill}</div></header>
    <main class="wrap">
      <div class="stack g10"><h1 class="title xl">Hallo! Was möchtest du heute tun?</h1><p class="lead">${esc(sub)}</p></div>
      ${updateBanner}
      ${reorgBanner}
      ${hero}
      <div id="due-box">${dueBoxHTML()}</div>
      <form class="searchbar" role="search" onsubmit="return false">
        <span class="searchbar-icon">${I.search(24)}</span>
        <label class="sr-only" for="home-q">Dokument suchen</label>
        <input id="home-q" class="text" type="search" data-enter="homeSearch" placeholder="Dokument suchen – z. B. „Kfz-Versicherung 2025“ oder „Erika Zahnarzt“" autocomplete="off">
        <button type="button" class="btn violet" data-act="homeSearch">Suchen</button>
      </form>
      <div class="tiles four">
        <button type="button" class="tile" data-act="collections"><div class="icon-box">${I.folder()}</div>
          <span class="tile-title">Mappen</span><span class="tile-text">Dokumente für die Steuer oder einen Antrag zusammenstellen.</span></button>
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
    update: () => updateDialog(),
    history: () => go("history"),
    settings: () => go("settings"),
    collections: () => go("collections"),
    homeSearch: () => go("search", { q: (document.getElementById("home-q").value || "").trim() }),
    ...dueActions(),
  };
  if (!S.soft) loadDeadlines();
};

/* ---------- Suche ---------- */
function markSnippet(t) {
  return esc(t).replace(/\u0002/g, "<mark>").replace(/\u0003/g, "</mark>");
}

function searchStatusText(st) {
  if (!st) return "";
  if (st.running && st.pending > 0) return `Ich lese gerade noch ${plural(st.pending, "Dokument", "Dokumente")} für die Suche – die Ergebnisse werden laufend vollständiger.`;
  return st.indexed ? `Ich durchsuche ${plural(st.indexed, "Dokument", "Dokumente")} in deiner Ablage.` : "";
}

SCREENS.search = () => {
  const q0 = S.params.q || "";
  S.search = { q: q0, hits: null, sel: null, preview: null, status: null, seq: 0 };
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Suchen")}
    <main class="wrap wide" style="gap:1.25rem">
      <form class="searchbar" role="search" onsubmit="return false">
        <span class="searchbar-icon">${I.search(24)}</span>
        <label class="sr-only" for="q">Suchbegriff</label>
        <input id="q" class="text" type="search" data-input="q" value="${esc(q0)}" placeholder="Wonach suchst du? Wörter aus dem Dokument, Absender, Ordner …" autocomplete="off">
      </form>
      <p class="tiny muted" id="search-status"></p>
      <div class="search-grid"><div id="hits" class="stack g10"></div><aside id="hit-preview" class="hit-preview" aria-label="Vorschau"></aside></div>
    </main></div>`);
  const f = document.getElementById("q");
  f.focus(); f.setSelectionRange(f.value.length, f.value.length);
  let timer = null;
  S.actions = {
    back: () => go("home"),
    q: (el) => { clearTimeout(timer); timer = setTimeout(() => runSearch(el.value), 280); },
    hit: (el) => selectHit(+el.dataset.i),
    open: (el) => tryCall("open_file", el.dataset.path),
    reveal: (el) => tryCall("show_in_folder", el.dataset.path),
    toCollection: (el) => addToCollectionDialog(el.dataset.path),
    prevPage: () => { const p = S.search.preview; if (p) loadHitPreview(Math.max(0, p.page - 1)); },
    nextPage: () => { const p = S.search.preview; if (p) loadHitPreview(p.page + 1); },
    zoom: () => {},
  };
  if (q0) runSearch(q0); else tryCall("search_status").then((st) => { const el = document.getElementById("search-status"); if (el && st) el.textContent = searchStatusText(st); });
};

async function runSearch(q) {
  const sr = S.search;
  if (!sr) return;
  sr.q = q;
  const seq = ++sr.seq;
  if (!q.trim()) { sr.hits = null; drawHits(); return; }
  const r = await tryCall("search", q);
  if (!r || S.route !== "search" || seq !== sr.seq) return;
  sr.hits = r.hits; sr.status = r.status; sr.sel = null; sr.preview = null;
  drawHits();
  if (r.hits.length && window.matchMedia("(min-width: 62rem)").matches) selectHit(0);
}

function drawHits() {
  const sr = S.search;
  const box = document.getElementById("hits");
  if (!box) return;
  const st = document.getElementById("search-status");
  if (st) st.textContent = searchStatusText(sr.status);
  if (sr.hits === null) { box.innerHTML = ""; document.getElementById("hit-preview").innerHTML = ""; return; }
  if (!sr.hits.length) {
    box.innerHTML = `<div class="card stack g8"><b style="font-size:1.1875rem">Nichts gefunden</b>
      <span class="muted">Versuch es mit weniger oder anderen Wörtern – zum Beispiel nur dem Absender oder der Art des Dokuments.</span></div>`;
    document.getElementById("hit-preview").innerHTML = "";
    return;
  }
  box.innerHTML = `<span class="small muted">${sr.hits.length >= 60 ? "Die ersten 60 Treffer" : plural(sr.hits.length, "Treffer", "Treffer")}</span>
    <ul class="hits">${sr.hits.map((h, i) => `<li><button type="button" class="hit ${sr.sel === i ? "on" : ""}" data-act="hit" data-i="${i}" aria-pressed="${sr.sel === i}">
      <span class="hit-name">${esc(h.name)}</span>
      <span class="small muted row g6">${I.folder(16)} ${esc(h.folder || "Ablage")}</span>
      ${h.snippet ? `<span class="small hit-snip">${markSnippet(h.snippet)}</span>` : h.summary ? `<span class="small hit-snip">${esc(h.summary)}</span>` : ""}
    </button></li>`).join("")}</ul>`;
}

function hitActions(h) {
  return `<div class="row g10 wrapflex">
    <button type="button" class="btn primary" data-act="open" data-path="${esc(h.path)}">Öffnen</button>
    <button type="button" class="btn" data-act="reveal" data-path="${esc(h.path)}">Im Ordner zeigen</button>
    <button type="button" class="btn violet" data-act="toCollection" data-path="${esc(h.path)}">${I.plus(18)} Zur Mappe</button></div>`;
}

function selectHit(i) {
  const sr = S.search;
  sr.sel = i;
  drawHits();
  const h = sr.hits[i];
  const pane = document.getElementById("hit-preview");
  pane.innerHTML = `<div class="stack g12"><div class="stack g4"><b style="font-size:1.1875rem;overflow-wrap:anywhere">${esc(h.name)}</b>
    <span class="small muted">${esc(h.folder || "Ablage")}</span></div>${hitActions(h)}<div id="hit-paper">${previewHTML(null)}</div></div>`;
  if (!window.matchMedia("(min-width: 62rem)").matches) pane.scrollIntoView({ behavior: "smooth", block: "start" });
  loadHitPreview(0);
}

async function loadHitPreview(page) {
  const sr = S.search;
  const h = sr.hits && sr.hits[sr.sel];
  if (!h) return;
  const pv = await tryCall("preview_path", h.path, page);
  if (!pv || S.route !== "search" || sr.hits[sr.sel] !== h) return;
  sr.preview = pv;
  const box = document.getElementById("hit-paper");
  if (box) box.innerHTML = previewHTML(pv, false) + pagerHTML(pv).replace(/<button type="button" class="btn small" data-act="zoom">Vergrößern<\/button>/, "");
}

/* ---------- Mappen ---------- */
async function addToCollectionDialog(path) {
  const list = (await tryCall("collections_list")) || [];
  const own = list.filter((c) => !c.auto);
  const tax = list.filter((c) => c.auto);
  openModal(`<h2>In welche Mappe?</h2>
    <p class="small muted">Das Dokument bleibt in seinem Ordner. In der Mappe steht nur ein Verweis darauf.</p>
    <div class="stack g8">${[...tax, ...own].map((c) => `<button type="button" class="choice" data-act="pick" data-id="${esc(c.id)}">
      <div class="icon-box s">${I.folder(22)}</div><div class="stack g4 grow"><span style="font-size:1.125rem;font-weight:600">${esc(c.name)}</span>
      <span class="tiny muted">${plural(c.count, "Dokument", "Dokumente")}${c.auto ? " · stellt sich von selbst zusammen" : ""}</span></div></button>`).join("")}</div>
    <div class="stack g8"><label class="tiny muted" for="new-col">Oder eine neue Mappe anlegen</label>
    <div class="row g8"><input class="text" id="new-col" data-enter="create" placeholder="z. B. Antrag Elterngeld" maxlength="60">
      <button type="button" class="btn violet" data-act="create">Anlegen</button></div></div>
    <div class="btns"><button type="button" class="btn" data-act="cancel">Abbrechen</button></div>`, {
    cancel: () => closeModal(null),
    pick: async (el) => {
      const r = await tryCall("collection_add", el.dataset.id, path);
      if (r !== undefined) { closeModal(null); toast(r === false ? "Das Dokument ist schon in dieser Mappe." : "Zur Mappe hinzugefügt."); }
    },
    create: async () => {
      const name = (document.getElementById("new-col").value || "").trim();
      if (!name) { toast("Bitte gib der Mappe einen Namen."); return; }
      const c = await tryCall("collection_create", name, path);
      if (c) { closeModal(null); toast(`Mappe „${c.name}“ angelegt.`); }
    },
  });
}

SCREENS.collections = () => {
  call("inspect_status").then((st) => { S.inspect = st; redrawInspect(); }).catch(() => {});
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Mappen")}
    <main class="wrap narrow"><div class="waiting"><div class="spinner"></div></div></main></div>`);
  S.actions = { back: () => go("home") };
  call("collections_list").then((list) => { if (S.route === "collections") drawCollections(list); }).catch((e) => toast(e.message));
};

function drawCollections(list) {
  const card = (c) => `<li><button type="button" class="choice" data-act="openCol" data-id="${esc(c.id)}">
    <div class="icon-box">${I.folder(26)}</div>
    <div class="stack g4 grow"><span style="font-size:1.25rem;font-weight:700">${esc(c.name)}</span>
    <span class="small muted">${plural(c.count, "Dokument", "Dokumente")}${c.auto ? " · stellt sich von selbst zusammen" : ""}</span></div>${I.right()}</button></li>`;
  const tax = list.filter((c) => c.auto);
  const own = list.filter((c) => !c.auto);
  setHTML(`<div class="screen">${topbar("Zur Startseite", "back", "Mappen")}
    <main class="wrap narrow">
      <div class="stack g10"><h1 class="title">Mappen</h1>
      <p class="lead">Eine Mappe sammelt Dokumente für einen Zweck – zum Beispiel die Steuererklärung. Die Dokumente bleiben dabei in ihren Ordnern; die Mappe merkt sich nur, wo sie liegen.</p></div>
      <div id="inspect-card">${inspectCardHTML()}</div>
      <section class="stack g10"><h2 class="h2">Für die Steuer</h2>
        ${tax.length ? `<ul class="plainlist">${tax.map(card).join("")}</ul>` : `<div class="card"><span class="muted">Sobald ich beim Einsortieren Dokumente erkenne, die für die Steuer wichtig sind (Lohnsteuerbescheinigung, Spendenquittung, Handwerkerrechnung …), sammle ich sie hier nach Jahren.</span></div>`}
      </section>
      <section class="stack g10"><h2 class="h2">Eigene Mappen</h2>
        ${own.length ? `<ul class="plainlist">${own.map(card).join("")}</ul>` : `<div class="card"><span class="muted">Noch keine. Lege eine an und füge über die Suche Dokumente hinzu.</span></div>`}
        <div class="row g8" style="max-width:36rem"><input class="text" id="new-col" data-enter="create" placeholder="Neue Mappe, z. B. Antrag Elterngeld" maxlength="60" aria-label="Name der neuen Mappe">
          <button type="button" class="btn violet" data-act="create">${I.plus(18)} Anlegen</button></div>
      </section>
    </main></div>`);
  S.actions = {
    back: () => go("home"),
    ...inspectActions(),
    openCol: (el) => go("collection", { id: el.dataset.id }),
    create: async () => {
      const name = (document.getElementById("new-col").value || "").trim();
      if (!name) { toast("Bitte gib der Mappe einen Namen."); return; }
      const c = await tryCall("collection_create", name, "");
      if (c) go("collection", { id: c.id });
    },
  };
}

SCREENS.collection = () => {
  setHTML(`<div class="screen">${topbar("Zu den Mappen", "back", "Mappe")}
    <main class="wrap narrow"><div class="waiting"><div class="spinner"></div></div></main></div>`);
  S.actions = { back: () => go("collections") };
  call("collection_view", S.params.id).then((c) => { if (S.route === "collection") drawCollection(c); }).catch((e) => { toast(e.message); go("collections"); });
};

function drawCollection(c) {
  const missing = c.items.filter((i) => !i.exists).length;
  const rows = c.items.map((i) => `<li class="${i.exists ? "" : "off"}">
    <div class="mini" aria-hidden="true"><span></span><span></span><span></span><span style="width:75%"></span></div>
    <div class="stack g4 grow" style="flex-basis:16rem;min-width:0">
      <button type="button" class="textbtn" style="align-self:flex-start;text-align:left;font-size:1.125rem;font-weight:600;color:var(--text);overflow-wrap:anywhere" data-act="open" data-path="${esc(i.path)}" ${i.exists ? "" : "disabled"}>${esc(i.name)}</button>
      <span class="small muted">${i.exists ? `${I.folder(16)} ${esc(i.folder || "Ablage")}` : "Nicht mehr gefunden – vielleicht gelöscht oder umbenannt."}</span></div>
    <div class="row g8">${i.exists ? `<button type="button" class="btn small" data-act="reveal" data-path="${esc(i.path)}">Im Ordner zeigen</button>` : ""}
      <button type="button" class="iconbtn" data-act="remove" data-path="${esc(i.orig || i.path)}" data-cur="${esc(i.path)}" aria-label="Aus der Mappe nehmen" title="Aus der Mappe nehmen">${I.x()}</button></div>
  </li>`).join("");
  setHTML(`<div class="screen">${topbar("Zu den Mappen", "back", c.auto ? "Stellt sich von selbst zusammen" : "Eigene Mappe")}
    <main class="wrap narrow">
      <div class="row between wrapflex g12"><h1 class="title">${esc(c.name)}</h1>
        ${c.auto ? "" : `<div class="row g8"><button type="button" class="btn small" data-act="rename">Umbenennen</button>
          <button type="button" class="btn small danger" data-act="del">Mappe löschen</button></div>`}</div>
      <p class="lead">${c.items.length ? plural(c.items.length, "Dokument", "Dokumente") + ". " : ""}Die Dokumente bleiben in ihren Ordnern. „Aus der Mappe nehmen“ löscht nichts.</p>
      ${c.items.length ? `<ul class="biglist col-list">${rows}</ul>` : `<div class="card stack g12"><span class="muted">Diese Mappe ist noch leer. Suche ein Dokument und tippe auf „Zur Mappe“.</span>
        <button type="button" class="btn violet" style="align-self:flex-start" data-act="search">${I.search(20)} Dokument suchen</button></div>`}
      ${c.items.length ? `<div class="footbar"><span class="muted" style="flex:1 1 17rem">Alles in einer Datei – zum Ausdrucken, Mailen oder Hochladen. ${missing ? `(${missing} nicht gefundene Dokumente lasse ich aus.)` : ""}</span>
        <div class="row g10 wrapflex"><button type="button" class="btn tall" data-act="exportZip">Als ZIP-Ordner</button>
        <button type="button" class="btn primary tall" data-act="exportPdf">${I.doc(22)} Als ein PDF speichern</button></div></div>` : ""}
    </main></div>`);
  const reload = async () => { const c2 = await tryCall("collection_view", c.id); if (c2 && S.route === "collection") drawCollection(c2); };
  const doExport = async (el, fmt) => {
    const old = el.innerHTML;
    el.disabled = true; el.innerHTML = `<div class="spinner small"></div> Wird erstellt …`;
    const r = await tryCall("collection_export", c.id, fmt);
    el.disabled = false; el.innerHTML = old;
    if (!r) return;
    openModal(`<div class="big-icon" style="margin:0 auto">${I.check(36, 2.4)}</div><h2 style="text-align:center">Fertig!</h2>
      <p style="text-align:center">„${esc(r.name)}“ liegt jetzt in <b>${esc(r.folder)}</b>.</p>
      <div class="btns"><button type="button" class="btn" data-act="close">Schließen</button>
      <button type="button" class="btn" data-act="reveal">Im Ordner zeigen</button>
      <button type="button" class="btn primary" data-act="open">Öffnen</button></div>`, {
      close: () => closeModal(null),
      reveal: () => { tryCall("show_in_folder", r.path); closeModal(null); },
      open: () => { tryCall("open_file", r.path); closeModal(null); },
    });
  };
  S.actions = {
    back: () => go("collections"),
    open: (el) => tryCall("open_file", el.dataset.path),
    reveal: (el) => tryCall("show_in_folder", el.dataset.path),
    search: () => go("search", {}),
    remove: async (el) => { if (await tryCall("collection_remove", c.id, c.auto ? el.dataset.cur : el.dataset.path)) { toast("Aus der Mappe genommen. Das Dokument liegt weiter in seinem Ordner."); reload(); } },
    exportPdf: (el) => doExport(el, "pdf"),
    exportZip: (el) => doExport(el, "zip"),
    rename: async () => {
      openModal(`<h2>Mappe umbenennen</h2><input class="text" id="col-name" data-enter="ok" value="${esc(c.name)}" maxlength="60" aria-label="Name">
        <div class="btns"><button type="button" class="btn" data-act="cancel">Abbrechen</button><button type="button" class="btn primary" data-act="ok">Speichern</button></div>`, {
        cancel: () => closeModal(null),
        ok: async () => { const v = document.getElementById("col-name").value.trim(); if (v && await tryCall("collection_rename", c.id, v)) { closeModal(null); reload(); } },
      });
      const f = document.getElementById("col-name"); if (f) { f.focus(); f.select(); }
    },
    del: async () => {
      const ok = await confirmDialog("Mappe löschen?", "Nur die Mappe verschwindet. Alle Dokumente bleiben in ihren Ordnern.", "Mappe löschen", true);
      if (ok && await tryCall("collection_delete", c.id)) { toast("Mappe gelöscht."); go("collections"); }
    },
  };
}

/* ---------- Bestand prüfen (Steuer, Fristen) ---------- */
function inspectCardHTML() {
  const st = S.inspect;
  if (!st) return "";
  const pct = st.total ? Math.round((st.done / st.total) * 100) : 0;
  const found = (st.found_tax || st.found_deadlines)
    ? `Bisher gefunden: ${plural(st.found_tax, "Steuer-Dokument", "Steuer-Dokumente")}, ${plural(st.found_deadlines, "Frist", "Fristen")}.` : "";
  const cloud = st.cloud_only ? `<span class="tiny muted">${plural(st.cloud_only, "Datei liegt", "Dateien liegen")} nur in der Cloud – die lasse ich aus.</span>` : "";
  const head = `<div class="row g12"><div class="icon-box">${I.search(24)}</div><div class="stack g4 grow"><b style="font-size:1.1875rem">Bestehende Ablage durchsehen</b>`;
  if (st.phase === "counting" || (st.active && st.phase === "running")) {
    return `<section class="card stack g12">${head}<span class="small muted">${st.phase === "counting" ? "Ich zähle deine Dokumente …" : `${st.done} von ${st.total} angesehen${st.left ? ` · noch etwa ${durationText(st.minutes)}` : ""}`}</span></div></div>
      <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div style="width:${pct}%"></div></div>
      <span class="small">${found || "Ich arbeite nur, wenn gerade nichts anderes zu tun ist. Verschoben wird nichts."}</span>${cloud}
      <button type="button" class="btn small" style="align-self:flex-start" data-act="inspectPause">Pause</button></section>`;
  }
  if (st.phase === "paused") {
    return `<section class="card stack g12">${head}<span class="small muted">Pausiert bei ${st.done} von ${st.total}. ${found}</span></div></div>
      <button type="button" class="btn violet small" style="align-self:flex-start" data-act="inspectStart">Weitermachen</button></section>`;
  }
  if (st.phase === "done") {
    return `<section class="card stack g12">${head}<span class="small muted">Fertig – ${plural(st.total, "Dokument", "Dokumente")} angesehen. ${(st.found_tax || st.found_deadlines) ? `Neu gefunden: ${plural(st.found_tax, "Steuer-Dokument", "Steuer-Dokumente")}, ${plural(st.found_deadlines, "offene Frist", "offene Fristen")}.` : "Dabei ist nichts Neues aufgetaucht."}</span></div></div>
      ${cloud}<button type="button" class="btn small" style="align-self:flex-start" data-act="inspectStart">Neue Dokumente durchsehen</button></section>`;
  }
  const err = st.phase === "error" ? `<div class="notice warn">${I.warn()}<div>${esc(st.error)}</div></div>` : "";
  return `<section class="card stack g12">${head}<span class="small muted">Ich lese deine schon abgelegten Dokumente und suche Steuer-Dokumente und offene Fristen heraus. Ich verschiebe und ändere dabei nichts. Das läuft nebenbei und kann bei vielen Dokumenten einige Stunden dauern – du kannst jederzeit pausieren.</span></div></div>
    ${err}<button type="button" class="btn violet" style="align-self:flex-start" data-act="inspectStart">${st.phase === "error" ? "Nochmal versuchen" : "Jetzt durchsehen"}</button></section>`;
}

function redrawInspect() {
  const box = document.getElementById("inspect-card");
  if (!box) return;
  const html = inspectCardHTML();
  if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
}

function inspectActions() {
  return {
    inspectStart: async (el) => { el.disabled = true; const st = await tryCall("inspect_start"); if (st) { S.inspect = st; redrawInspect(); } else el.disabled = false; },
    inspectPause: async (el) => { el.disabled = true; const st = await tryCall("inspect_pause"); if (st) { S.inspect = st; redrawInspect(); } },
  };
}

/* ---------- Feinschliff: volle Ordner unterteilen ---------- */
SCREENS.refine = () => {
  if (!S.refine || !S.soft) S.refine = { off: new Set(), names: {}, open: new Set(), ...(S.refine || {}) };
  const st = S.refine.status;
  if (!st) {
    setHTML(`<div class="screen">${topbar("Zurück", "back", "Feinschliff")}<main class="wrap narrow"><div class="waiting"><div class="spinner"></div></div></main></div>`);
    S.actions = { back: () => go(S.params.from || "home") };
    call("refine_candidates").then((r) => { S.refine.status = r.status; S.refine.cands = r.folders; S.refine.reorgActive = r.reorg_active; if (S.route === "refine") render(); }).catch((e) => toast(e.message));
    return;
  }
  if (st.phase === "review" && !S.refine.prop) {
    call("refine_proposal").then((p) => { S.refine.prop = p; if (S.route === "refine") render(); }).catch((e) => toast(e.message));
  }
  drawRefine();
};

function drawRefine() {
  const R = S.refine;
  const st = R.status;
  const wrap = (title, body) => setHTML(`<div class="screen">${topbar("Zurück", "back", "Feinschliff")}
    <main class="wrap narrow"><div class="stack g10"><h1 class="title">${title}</h1></div>${body}</main></div>`);
  const actions = {
    back: () => { S.refine = null; go(S.params.from || "home"); },
    pick: async (el) => { el.disabled = true; const r = await tryCall("refine_start", el.dataset.folder); if (r) { R.status = r; R.prop = null; R.off = new Set(); R.names = {}; R.open = new Set(); render(); } else el.disabled = false; },
    cancel: async () => { const r = await tryCall("refine_cancel"); if (r) { R.status = r; R.prop = null; R.status = null; render(); } },
    undo: async (el) => {
      const ok = await confirmDialog("Feinschliff rückgängig machen?", "Alle Dokumente kommen zurück in den ursprünglichen Ordner. Leere neue Unterordner werden entfernt.", "Rückgängig machen");
      if (!ok) return;
      el.disabled = true;
      const r = await tryCall("undo_reorg", st.group);
      if (r) { toast(r.failed ? `${r.ok} zurückgelegt, ${r.failed} nicht (inzwischen verändert).` : "Alles wieder wie vorher."); R.status = null; await tryCall("refine_cancel"); render(); }
    },
    again: async () => { await tryCall("refine_cancel"); S.refine = null; render(); },
  };
  S.actions = actions;
  const pct = st.total ? Math.round((st.done / st.total) * 100) : 0;
  if (["reading", "thinking", "moving"].includes(st.phase)) {
    const label = { reading: `Ich lese die Dokumente in „${esc(st.display)}“`, thinking: "Ich überlege mir passende Unterordner", moving: "Ich verschiebe die Dokumente" }[st.phase];
    wrap(label, `<section class="card big stack g16"><div class="row g12"><div class="spinner small"></div><span class="muted">${st.done} von ${st.total}</span></div>
      <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div style="width:${pct}%"></div></div>
      ${st.phase === "moving" ? "" : `<span class="small muted">Verschoben wird erst, wenn du den Vorschlag bestätigt hast.</span>`}</section>
      ${st.phase === "moving" ? "" : `<button type="button" class="btn link" style="align-self:flex-start" data-act="cancel">Abbrechen</button>`}`);
    return;
  }
  if (st.phase === "done") {
    wrap("Fertig!", `<section class="card stack g12"><span class="lead" style="margin:0">${plural(st.moved, "Dokument", "Dokumente")} in Unterordner von „${esc(st.display)}“ verschoben${st.failed ? ` · ${st.failed} konnte ich nicht verschieben (inzwischen verändert oder nicht mehr da)` : ""}.</span>
      <span class="muted">Neue Dokumente dieser Art lege ich ab jetzt gleich in die passenden Unterordner. Im Verlauf kannst du alles rückgängig machen.</span></section>
      <div class="row g12 wrapflex"><button type="button" class="btn primary" data-act="again">Weiteren Ordner unterteilen</button>
      ${st.group ? `<button type="button" class="btn" data-act="undo">Rückgängig machen</button>` : ""}</div>`);
    return;
  }
  if (st.phase === "review") {
    const P = R.prop;
    if (!P) { wrap("Mein Vorschlag", `<div class="waiting"><div class="spinner"></div></div>`); return; }
    const docRow = (d) => `<li><label><input type="checkbox" data-change="toggleDoc" data-i="${d.i}" ${R.off.has(d.i) ? "" : "checked"}>
      <span style="overflow-wrap:anywhere">${esc(d.name)}</span></label></li>`;
    const subs = P.subfolders.map((sub, si) => {
      const n = sub.docs.filter((d) => !R.off.has(d.i)).length;
      const isOpen = R.open.has(si);
      return `<section class="card stack g10">
        <div class="row g10 wrapflex">${I.folder(22)}<span class="muted">${esc(P.display)} ›</span>
          <input class="text" style="flex:1 1 12rem;max-width:22rem" data-input="rename" data-name="${esc(sub.name)}" value="${esc(R.names[sub.name] ?? sub.name)}" aria-label="Name des Unterordners" maxlength="50"></div>
        <span class="small muted">${esc(sub.description)}</span>
        <button type="button" class="btn link small" style="align-self:flex-start" data-act="openSub" data-si="${si}" aria-expanded="${isOpen}">${n === sub.docs.length ? plural(n, "Dokument", "Dokumente") : `${n} von ${sub.docs.length} Dokumenten`} ${I.chev()}</button>
        ${isOpen ? `<ul class="refine-docs">${sub.docs.map(docRow).join("")}</ul>` : ""}</section>`;
    }).join("");
    const total = P.subfolders.reduce((a, sub) => a + sub.docs.filter((d) => !R.off.has(d.i)).length, 0);
    wrap(`Vorschlag für „${esc(P.display)}“`, `<p class="lead">So würde ich den Ordner unterteilen. Du kannst die Namen ändern und einzelne Dokumente abwählen – die bleiben dann, wo sie sind. Ein leerer Name heißt: diesen Unterordner nicht anlegen.</p>
      <div class="stack g12">${subs}</div>
      ${P.stay.length ? `<div class="card stack g8"><b>Bleibt direkt in „${esc(P.display)}“</b><span class="small muted">${P.stay.map((d) => esc(d.name)).slice(0, 12).join(" · ")}${P.stay.length > 12 ? ` · und ${P.stay.length - 12} weitere` : ""}</span></div>` : ""}
      ${P.cloud_only ? `<p class="tiny muted">${plural(P.cloud_only, "Datei liegt", "Dateien liegen")} nur in der Cloud und bleibt, wo sie ist.</p>` : ""}
      <div class="footbar"><button type="button" class="btn link" data-act="cancel">Verwerfen</button>
        <button type="button" class="btn primary tall" data-act="apply" ${total ? "" : "disabled"}>${I.check()} ${plural(total, "Dokument", "Dokumente")} verschieben</button></div>`);
    Object.assign(S.actions, {
      toggleDoc: (el) => { const i = +el.dataset.i; if (el.checked) R.off.delete(i); else R.off.add(i); drawRefine(); },
      openSub: (el) => { const si = +el.dataset.si; if (R.open.has(si)) R.open.delete(si); else R.open.add(si); drawRefine(); },
      rename: (el) => { R.names[el.dataset.name] = el.value; },
      apply: async (el) => {
        el.disabled = true;
        const subsArg = P.subfolders.map((sub) => ({ name: sub.name, new_name: (R.names[sub.name] ?? sub.name).trim() }));
        const moves = {};
        R.off.forEach((i) => { moves[i] = ""; });
        const r = await tryCall("refine_apply", subsArg, moves);
        if (r) { R.status = r; R.prop = null; render(); } else el.disabled = false;
      },
    });
    return;
  }
  // Auswahl eines Ordners
  const err = st.phase === "error" ? `<div class="notice warn">${I.warn()}<div>${esc(st.error)}</div></div>` : "";
  const list = (R.cands || []).map((c) => `<li><div class="choice" style="cursor:default"><div class="icon-box s">${I.folder(22)}</div>
    <div class="stack g4 grow"><span style="font-size:1.125rem;font-weight:600;overflow-wrap:anywhere">${esc(c.display)}</span><span class="small muted">${plural(c.count, "Dokument", "Dokumente")} direkt darin</span></div>
    <button type="button" class="btn violet small" data-act="pick" data-folder="${esc(c.folder)}" ${R.reorgActive ? "disabled" : ""}>Unterteilen</button></div></li>`).join("");
  wrap("Volle Ordner unterteilen", `<p class="lead">Wenn sich in einem Ordner viele Dokumente sammeln, schlage ich passende Unterordner vor. Du prüfst den Vorschlag – erst dann verschiebe ich etwas, und alles lässt sich rückgängig machen.</p>
    ${err}${R.reorgActive ? `<div class="notice info">${I.info ? I.info() : ""}<div>Gerade läuft eine Neuordnung. Schließe sie erst ab.</div></div>` : ""}
    ${list ? `<ul class="plainlist">${list}</ul>` : `<div class="card"><span class="muted">Kein Ordner ist so voll, dass sich eine Unterteilung lohnt (ab 25 Dokumenten). Prima!</span></div>`}`);
}

/* ---------- Fristen („Demnächst fällig“) ---------- */
const MONTHS_SHORT = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const MONTHS_LONG = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

function dateLong(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d}. ${MONTHS_LONG[m - 1]} ${y}`;
}

function daysText(n) {
  if (n === 0) return "heute";
  if (n === 1) return "morgen";
  if (n === -1) return "seit gestern überfällig";
  if (n < 0) return `seit ${-n} Tagen überfällig`;
  if (n < 14) return `in ${n} Tagen`;
  if (n < 60) return `in ${Math.round(n / 7)} Wochen`;
  return `in ${Math.round(n / 30)} Monaten`;
}

function loadDeadlines() {
  call("deadlines").then((list) => {
    S.deadlines = list;
    const box = document.getElementById("due-box");
    const html = dueBoxHTML();
    if (box && S.route === "home" && S.dueHTML !== html) box.innerHTML = html;
    S.dueHTML = html;
  }).catch(() => {});
}

function dueBoxHTML() {
  const list = S.deadlines || [];
  if (!list.length) return "";
  const all = !!S.dueAll;
  const shown = all ? list : list.slice(0, 4);
  const rows = shown.map((d) => {
    const [, m, day] = d.date.split("-").map(Number);
    const cls = d.days < 0 ? "over" : d.days <= 7 ? "soon" : "";
    return `<li class="due-row">
      <div class="due-date ${cls}" aria-hidden="true"><b>${day}</b><span>${MONTHS_SHORT[m - 1]}</span></div>
      <div class="stack g4 grow" style="flex-basis:14rem;min-width:0">
        <span class="due-what">${esc(d.what)}</span>
        <span class="small muted"><span class="${cls ? "due-" + cls : ""}">${esc(daysText(d.days))}</span> · ${esc(dateLong(d.date))}${d.person ? " · " + esc(d.person) : ""}</span>
        <button type="button" class="textbtn small" style="align-self:flex-start;overflow-wrap:anywhere;text-align:left" data-act="dueOpen" data-path="${esc(d.path)}">${I.doc(16)} ${esc(d.name)}</button>
      </div>
      <div class="row g8 wrapflex due-btns">
        <button type="button" class="btn small" data-act="dueCal" data-id="${esc(d.id)}">${I.cal(18)} In den Kalender</button>
        <button type="button" class="btn small violet" data-act="dueDone" data-id="${esc(d.id)}">${I.check(18, 2.4)} Erledigt</button>
      </div></li>`;
  }).join("");
  return `<section class="card stack g12 due" aria-label="Demnächst fällig">
    <div class="row between wrapflex g12"><h2 style="font-size:1.3125rem" class="row g10">${I.cal()} Demnächst fällig</h2>
      ${list.length > 1 ? `<button type="button" class="textbtn" data-act="dueCalAll">Alle in den Kalender</button>` : ""}</div>
    <ul class="duelist">${rows}</ul>
    ${list.length > 4 ? `<button type="button" class="textbtn" style="align-self:flex-start" data-act="dueMore">${all ? "Weniger anzeigen" : `Alle ${list.length} anzeigen`}</button>` : ""}
  </section>`;
}

function dueActions() {
  const redraw = () => { const box = document.getElementById("due-box"); if (box) box.innerHTML = dueBoxHTML(); };
  const calNote = "Die Kalenderdatei ist geöffnet – dein Kalenderprogramm fragt, ob du den Termin übernehmen möchtest.";
  return {
    dueOpen: (el) => tryCall("open_file", el.dataset.path),
    dueMore: () => { S.dueAll = !S.dueAll; redraw(); },
    dueCal: async (el) => { if (await tryCall("deadline_ics", [el.dataset.id])) toast(calNote); },
    dueCalAll: async () => { if (await tryCall("deadline_ics", (S.deadlines || []).map((d) => d.id))) toast(calNote); },
    dueDone: async (el) => {
      const id = el.dataset.id;
      if (await tryCall("deadline_done", id, true)) {
        S.deadlines = (S.deadlines || []).filter((d) => d.id !== id);
        redraw();
        toast("Als erledigt abgehakt.", { label: "Rückgängig", fn: async () => { await tryCall("deadline_done", id, false); loadDeadlines(); } });
      }
    },
  };
}

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

function batchGroups(items) {
  const map = new Map();
  for (const it of items) {
    const key = it.suggestion.folder;
    if (!map.has(key)) map.set(key, { key, label: it.suggestion.folder_display, isNew: !!it.suggestion.is_new_folder, items: [] });
    map.get(key).items.push(it);
  }
  return [...map.values()].sort((a, b) => b.items.length - a.items.length || a.label.localeCompare(b.label, "de"));
}

function drawBatch() {
  const { items, off, origin } = S.batch;
  if (!S.batch.open) S.batch.open = new Set(items.length <= 24 ? items.map((i) => i.suggestion.folder) : []);
  const open = S.batch.open;
  const [backLabel, backFn] = backTo(origin);
  const ov = (S.state.queue.by_origin && S.state.queue.by_origin[origin]) || {};
  const checked = items.length - off.size;
  const rest = Math.max(0, (ov.total || items.length) - checked);
  const groups = batchGroups(items);
  const html = groups.map((g, gi) => {
    const on = g.items.filter((i) => !off.has(i.id)).length;
    const isOpen = open.has(g.key);
    const rows = isOpen ? g.items.map((it) => {
      const s = it.suggestion;
      const isOff = off.has(it.id);
      return `<li class="${isOff ? "off" : ""}"><label>
        <input type="checkbox" ${isOff ? "" : "checked"} data-change="toggle" data-id="${esc(it.id)}">
        <div class="mini" aria-hidden="true"><span></span><span></span><span></span><span style="width:75%"></span></div>
        <div class="stack g4 grow" style="flex-basis:16rem"><span style="font-size:1.1875rem;font-weight:600;overflow-wrap:anywhere">${esc(s.filename)}</span>
        <span class="small muted">${esc(s.summary || it.name)}</span></div></label></li>`;
    }).join("") : "";
    return `<section class="bgroup ${on ? "" : "off"}">
      <div class="bgroup-head">
        <label class="bgroup-check"><input type="checkbox" data-change="toggleGroup" data-g="${gi}" ${on ? "checked" : ""} ${on && on < g.items.length ? 'data-mixed="1"' : ""}
          aria-label="Alle ${g.items.length} für ${esc(g.label)}">
          <span class="foldertag">${I.folder(18)} ${esc(g.label)}</span>${g.isNew ? '<span class="tag new">Neuer Ordner</span>' : ""}</label>
        <button type="button" class="btn link small" data-act="openGroup" data-g="${gi}" aria-expanded="${isOpen}">
          ${on === g.items.length ? plural(g.items.length, "Dokument", "Dokumente") : `${on} von ${g.items.length}`} ${I.chev()}</button>
      </div>
      ${isOpen ? `<ul class="biglist">${rows}</ul>` : ""}
    </section>`;
  }).join("");
  setHTML(`<div class="screen">${topbar(backLabel, "back", "Schritt 1 von 2 · Sichere Vorschläge")}
    <main class="wrap narrow">
      <div class="stack g10"><h1 class="title">${items.length === 1 ? "Bei diesem Dokument bin ich mir sicher" : `Bei diesen ${items.length} Dokumenten bin ich mir sicher`}</h1>
      <p class="lead">Sortiert nach Ordner. Ein Haken beim Ordner gilt für alle Dokumente darin. Passt etwas nicht, nimm den Haken weg – dann zeige ich dir das Dokument gleich einzeln.</p></div>
      <div class="stack g12">${html}</div>
      <div class="footbar"><span class="muted" style="flex:1 1 17rem">${rest ? `Danach: ${plural(rest, "Dokument, das", "Dokumente, die")} ich dir einzeln zeige.` : "Danach bist du fertig."}</span>
        <button type="button" class="btn primary tall" data-act="go" ${checked ? "" : "disabled"}>${I.check()} ${checked === 1 ? "1 Dokument einsortieren" : `${checked} Dokumente einsortieren`}</button>
        ${checked === 0 ? `<button type="button" class="btn tall" data-act="goSingle">Einzeln anschauen</button>` : ""}</div>
    </main></div>`);
  document.querySelectorAll("[data-mixed]").forEach((el) => { el.indeterminate = true; });
  S.actions = {
    back: backFn,
    toggle: (el) => { const id = el.dataset.id; if (el.checked) off.delete(id); else off.add(id); drawBatch(); },
    toggleGroup: (el) => {
      const g = groups[+el.dataset.g];
      const allOn = g.items.every((i) => !off.has(i.id));
      for (const i of g.items) { if (allOn) off.add(i.id); else off.delete(i.id); }
      drawBatch();
    },
    openGroup: (el) => { const k = groups[+el.dataset.g].key; if (open.has(k)) open.delete(k); else open.add(k); drawBatch(); },
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
        ${personRow(s)}
      </div>
      ${deadlineNotes(s)}
      ${it.hint ? `<div class="small muted">Dein Hinweis: „${esc(it.hint)}“</div>` : ""}
      ${hintBox(c)}
      <div class="stack g12 mt-auto">
        <button type="button" class="btn primary big shadow" data-act="confirm">${I.check(26, 2.6)} Passt so – einsortieren</button>
        <div class="row g12 wrapflex">
          <button type="button" class="btn tall" style="flex:2 1 15rem" data-act="reject">${I.x()} Passt nicht – neuer Vorschlag</button>
          <button type="button" class="btn link tall" style="flex:1 1 8rem" data-act="skip">Später</button>
        </div>
        <p class="tiny muted keys">Tastatur: <kbd>Enter</kbd> passt so · <kbd>Entf</kbd> passt nicht · <kbd>Leertaste</kbd> später · <kbd>H</kbd> Hinweis</p>
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
      const res = await tryCall("confirm", it.id, s.folder, s.filename, { deadlines: s.deadlines || [], person: s.person || "" });
      if (res) {
        const extra = res.removed_pages ? ` ${plural(res.removed_pages, "leere Seite", "leere Seiten")} entfernt.` : "";
        toast((res.rechecked ? `Abgelegt in ${res.folder_display}. Ich passe ${plural(res.rechecked, "ähnlichen Vorschlag", "ähnliche Vorschläge")} an.` : `Abgelegt in ${res.folder_display}.`) + extra);
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
    person: async (el) => {
      const s = it.suggestion;
      if (c.editName) S.actions.saveName();
      const r = await tryCall("set_person", it.id, el.dataset.name, s.folder, s.filename);
      if (r) { Object.assign(s, r); drawSingle(); }
    },
    dlRemove: (el) => {
      const s = it.suggestion;
      s.deadlines = (s.deadlines || []).filter((_, i) => i !== +el.dataset.i);
      drawSingle();
    },
    notDoc: async () => {
      if (await tryCall("not_document", it.id)) {
        toast("Bleibt, wo es ist – ich schlage es nicht mehr vor. Im Verlauf kannst du das zurücknehmen.");
        loadNextSingle();
      }
    },
  });
}

function personRow(s) {
  const persons = (S.state.settings.persons || []);
  if (!persons.length) return "";
  const cur = s.person || "";
  const chip = (name, label) => `<button type="button" class="btn chip ${cur === name ? "on" : ""}" aria-pressed="${cur === name}" data-act="person" data-name="${esc(name)}">${esc(label)}</button>`;
  return `<hr class="hr"><div class="stack g10"><span class="label">Für wen?</span>
    <div class="row g8 wrapflex">${persons.map((p) => chip(p, p)).join("")}${chip("", "Alle / Haushalt")}</div></div>`;
}

function deadlineNotes(s) {
  const list = s.deadlines || [];
  if (!list.length) return "";
  return `<div class="notice info due-note">${I.cal()}<div class="stack g8 grow">
    <b>${list.length === 1 ? "Ich habe eine Frist gefunden" : `Ich habe ${list.length} Fristen gefunden`}</b>
    ${list.map((d, i) => `<div class="row g10 wrapflex"><span class="grow" style="flex-basis:12rem">${esc(dateLong(d.date))} – ${esc(d.what)}</span>
      <button type="button" class="textbtn small" data-act="dlRemove" data-i="${i}">Stimmt nicht</button></div>`).join("")}
    <span class="tiny muted">Ich erinnere dich auf der Startseite. In deinen Kalender kommt nur etwas, wenn du es dort möchtest.</span></div></div>`;
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
      <input class="text" id="hint" data-input="hintText" data-enter="hintSend" value="${esc(c.hintText || "")}" placeholder="z. B. „Rechnungen von Amazon gehören zu Einkäufe“" maxlength="500">
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
  const reorgs = h.reorgs.map((g) => `<div class="stack g10"><h2 class="h2">${esc(g.label)} · ${g.kind === "feinschliff" ? `„${esc(g.folder)}“ unterteilt` : "Ablage neu geordnet"}${g.cancelled ? " (abgebrochen)" : ""}</h2>
    <div class="card row g20 wrapflex"><div class="icon-box">${I.layers(26)}</div>
      <div class="stack g4 grow" style="flex-basis:20rem"><span style="font-size:1.1875rem;font-weight:600">${plural(g.count, "Dokument", "Dokumente")} neu einsortiert</span>
      <span class="tiny muted">${g.undone ? "Diese Neuordnung wurde rückgängig gemacht."
        : g.undo_failed ? `${plural(g.undo_failed, "Dokument wurde", "Dokumente wurden")} inzwischen verändert oder verschoben und blieben, wo sie sind. Du kannst es noch einmal versuchen.`
        : "Die alte Ordnung lässt sich jederzeit komplett wiederherstellen."}</span></div>
      ${g.undone ? "" : `<button type="button" class="btn small danger" data-act="undoReorg" data-id="${esc(g.id)}">${g.kind === "feinschliff" ? "Unterteilung rückgängig machen" : "Gesamte Neuordnung rückgängig machen"}</button>`}
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
          <hr class="hr">
          <button type="button" class="switch" aria-pressed="${s.scan_enhance !== false}" data-act="scanEnhance"><span class="track"><span class="knob"></span></span>Scans aufbereiten</button>
          <span class="tiny muted">Leere Seiten entfernen, schiefe Seiten gerade richten und die Datei verkleinern. Das Original hebe ich 30 Tage lang auf – „Rückgängig“ holt es zurück.</span>
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
      <section class="card stack g16"><h2 style="font-size:1.3125rem">Personen im Haushalt</h2>
          <span class="tiny muted">Wenn ich weiß, wer bei euch wohnt, merke ich mir bei jedem Dokument, für wen es ist.</span>
          <div class="row g8 wrapflex">${(s.persons || []).map((p, i) => `<span class="tag person">${I.user(16)} ${esc(p)}
            <button type="button" class="iconbtn tiny-x" data-act="personDel" data-i="${i}" aria-label="${esc(p)} entfernen">${I.x(16)}</button></span>`).join("")}
            ${(s.persons || []).length ? "" : '<span class="small muted">Noch niemand eingetragen.</span>'}</div>
          <div class="row g8" style="max-width:36rem"><input class="text" id="person-new" data-enter="personAdd" placeholder="Vorname, z. B. Erika" maxlength="40" aria-label="Name hinzufügen">
            <button type="button" class="btn small violet" data-act="personAdd">${I.plus(18)} Hinzufügen</button></div>
          ${(s.persons || []).length ? `<div class="stack g10" style="max-width:44rem"><span class="tiny muted">Wie soll man das in der Ablage sehen?</span>
          ${seg("person_mode", [["dateiname", "Name im Dateinamen"], ["unterordner", "Eigener Unterordner"], ["merken", "Nur merken"]])}
          <span class="tiny muted">${esc({ dateiname: "Beispiel: Finanzen › Bank › „2026-11 Kontoauszug – Erika.pdf“", unterordner: "Beispiel: Finanzen › Bank › Erika › „2026-11 Kontoauszug.pdf“", merken: "Datei- und Ordnernamen bleiben unverändert; ich merke es mir nur für die Suche." }[s.person_mode] || "")}</span></div>` : ""}
        </section>
      <section class="card stack g16"><h2 style="font-size:1.3125rem">Programm</h2>
        <div class="row between wrapflex g12"><span>Ordnungsliebe ${esc(S.state.version)}${(S.state.update || {}).available ? ` · <b>neue Version ${esc(S.state.update.version)} verfügbar</b>` : ""}</span>
          <button type="button" class="btn small violet" data-act="checkUpdate">${(S.state.update || {}).available ? "Ansehen" : "Nach Updates suchen"}</button></div>
        <button type="button" class="switch" aria-pressed="${s.auto_update !== false}" data-act="autoUpdate"><span class="track"><span class="knob"></span></span>Beim Start automatisch nach neuen Versionen suchen</button>
        <span class="tiny muted">Dafür fragt Ordnungsliebe nur die Versionsnummer bei GitHub ab. Deine Dokumente verlassen nie den Computer.</span>
      </section>
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
    personAdd: async () => {
      const f = document.getElementById("person-new");
      const v = (f.value || "").trim();
      if (!v) { toast("Bitte einen Namen eingeben."); f.focus(); return; }
      if (await tryCall("save_settings", { persons: [...(s.persons || []), v] })) { await refreshState(); render(); }
    },
    personDel: async (el) => {
      const list = (s.persons || []).filter((_, i) => i !== +el.dataset.i);
      if (await tryCall("save_settings", { persons: list })) { await refreshState(); render(); }
    },
    scanEnhance: async () => { if (await tryCall("save_settings", { scan_enhance: s.scan_enhance === false })) { await refreshState(); render(); } },
    autoUpdate: async () => { if (await tryCall("save_settings", { auto_update: s.auto_update === false })) { await refreshState(); render(); } },
    checkUpdate: async (el) => {
      if ((S.state.update || {}).available) { updateDialog(); return; }
      el.disabled = true; el.textContent = "Suche …";
      const r = await tryCall("update_check");
      if (r) { S.state.update = r; if (r.available) updateDialog(); else toast(r.error || "Du hast schon die neueste Version."); }
      render();
    },
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
  call("reorg_status").then((r) => { S.state.reorg = r; if (S.route === "reorg") softRender(); }).catch(() => {});
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
        <button type="button" class="choice" data-act="refine"><div class="icon-box">${I.folder(24)}</div>
          <div class="stack g4 grow"><span style="font-size:1.1875rem;font-weight:600">Nur volle Ordner unterteilen</span>
          <span class="muted">Feinschliff: Ich schlage für Ordner mit vielen Dokumenten passende Unterordner vor – ohne die ganze Ablage neu zu ordnen.</span></div>${I.right()}</button>
      </main></div>`);
    S.actions = {
      back: () => go("home"),
      mode: (el) => { S.reorgMode = el.dataset.id; drawReorgIntro(r); },
      refine: () => { S.refine = null; go("refine", { from: "reorg" }); },
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

// Bot Bridge - service worker.
// This process fetches only http://127.0.0.1:<port> (the local bridge). It does not
// talk to the developer. The assistant that reads bridge results may process them off-device.
const EXT_VERSION = chrome.runtime.getManifest().version;
const DEFAULTS = { port: 8765, token: "", enabled: true, consent: false, consentVersion: 0, dialogPolicy: "" };
// Developer build attaches the debugger. The store build sets this to false and does not request the permission.
const DEV_DEBUGGER = false;
// Bump when the consent notice changes so earlier agreement is not reused.
// Developer build is 4 (debugger). store/build_store.py rewrites the store package to 3.
const REQUIRED_CONSENT_VERSION = 3;

let cfg = { ...DEFAULTS };
let running = false;
let connected = false;
let lastError = "";
let lastCommand = "";
let lastCommandAt = 0;
let loopGen = 0;
let pollCtrl = null;
let didRelease = false;

// ------------------------------------------------------------------ badge
function setBadge(state) {
  const map = {
    on: { text: "ON", color: "#4F46E5" },
    err: { text: "!", color: "#DC2626" },
    off: { text: "", color: "#777" },
  };
  const b = map[state] || map.off;
  chrome.action.setBadgeText({ text: b.text }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ color: b.color }).catch(() => {});
  if (chrome.action.setBadgeTextColor) chrome.action.setBadgeTextColor({ color: "#FFFFFF" }).catch(() => {});
}
function setConnected(v, err) {
  connected = v;
  if (err !== undefined) lastError = err;
  setBadge(!cfg.enabled ? "off" : v ? "on" : "err");
}

// ------------------------------------------------------------------ config
async function loadCfg() {
  cfg = { ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) };
  return cfg;
}
chrome.storage.onChanged.addListener(async () => {
  await loadCfg();
  loopGen++;           // restart the loop with new settings
  running = false;
  if (pollCtrl) { try { pollCtrl.abort(); } catch (e) {} pollCtrl = null; }
  connected = false;
  setBadge(cfg.enabled ? "err" : "off");
  start();
});

// ------------------------------------------------------------------ long-poll loop
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const base = () => `http://127.0.0.1:${cfg.port}`;
const headers = () => ({ "X-Token": cfg.token, "X-Extension-Version": EXT_VERSION, "Content-Type": "application/json" });

// The developer build has no consent key. The store build adds consent + consentVersion.
function consentOk() {
  if (!Object.prototype.hasOwnProperty.call(DEFAULTS, "consent")) return true;
  return !!cfg.consent && cfg.consentVersion === REQUIRED_CONSENT_VERSION;
}

function disconnectBridge() {
  if (!cfg.token) return;
  fetch(base() + "/disconnect", { method: "POST", headers: headers(), body: "{}" }).catch(() => {});
}

function normalizeNavigationUrl(url) {
  let parsed;
  try { parsed = new URL(String(url)); }
  catch (e) { throw new Error("invalid url"); }
  const scheme = parsed.protocol;
  if (scheme === "http:" || scheme === "https:" || scheme === "file:") return parsed.href;
  if (scheme === "about:" && parsed.href === "about:blank") return parsed.href;
  throw new Error("url scheme not allowed (" + scheme + "). Use http, https, or file.");
}

async function start() {
  if (running) return;
  running = true;
  await loadCfg();
  if (!cfg.enabled || !consentOk()) {
    running = false;
    if (!cfg.enabled) { setConnected(false, ""); setBadge("off"); }
    else setConnected(false, "waiting for consent · Zustimmung fehlt");
    // Once per stop. Alarms call start() every 30s and must not repeat this POST.
    // A fresh worker (didRelease false) still releases a bridge left in its grace window.
    if (!didRelease) { didRelease = true; disconnectBridge(); }
    return;
  }
  didRelease = false;
  if (!cfg.token) { running = false; setConnected(false, "no token set"); return; }
  const gen = ++loopGen;
  let backoff = 1000;
  while (gen === loopGen && cfg.enabled && consentOk()) {
    try {
      if (!connected) {
        // quick handshake so the popup/badge show the real state immediately
        const s = await fetch(base() + "/status", { headers: headers(), cache: "no-store" });
        if (gen !== loopGen) break;
        if (s.status === 401) { setConnected(false, "wrong token"); await sleep(5000); continue; }
        if (!s.ok) { setConnected(false, "bridge HTTP " + s.status); await sleep(backoff); continue; }
        setConnected(true, "");
      }
      const ctrl = new AbortController();
      pollCtrl = ctrl;
      const t = setTimeout(() => ctrl.abort(), 35000);
      const r = await fetch(base() + "/next", { headers: headers(), signal: ctrl.signal, cache: "no-store" });
      clearTimeout(t);
      if (r.status === 401) { setConnected(false, "wrong token"); await sleep(5000); continue; }
      if (r.status === 204) { setConnected(true, ""); backoff = 1000; continue; }
      if (!r.ok) { setConnected(false, "bridge HTTP " + r.status); await sleep(backoff); continue; }
      setConnected(true, "");
      backoff = 1000;
      const item = await r.json();
      if (!cfg.enabled || !consentOk()) { reply(item, { ok: false, error: "extension is switched off" }); continue; }
      handle(item);   // do not await: keep polling, allow parallel commands
    } catch (e) {
      if (gen !== loopGen) break;
      setConnected(false, "bridge not reachable");
      await sleep(backoff);
      backoff = Math.min(backoff * 2, 10000);
    }
  }
  if (gen === loopGen) running = false;
}

async function handle(item) {
  const cmd = item.command || {};
  lastCommand = cmd.cmd;
  lastCommandAt = Date.now();
  let payload;
  try {
    const result = await runCommand(cmd);
    payload = { id: item.id, ok: true, result };
  } catch (e) {
    payload = { id: item.id, ok: false, error: String((e && e.message) || e) };
  }
  await reply(item, payload);
}

async function reply(item, payload) {
  payload.id = item.id;
  for (let i = 0; i < 3; i++) {
    try {
      await fetch(base() + "/result", { method: "POST", headers: headers(), body: JSON.stringify(payload) });
      return;
    } catch (e) { await sleep(500); }
  }
}

// keep-alive: alarms wake the worker and restart the loop if it died;
// an extension API call every 20s resets the MV3 idle timer while enabled.
chrome.alarms.create("gbb-keepalive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "gbb-keepalive") start(); });
setInterval(() => { if (cfg.enabled) chrome.runtime.getPlatformInfo().catch(() => {}); }, 20000);
chrome.runtime.onStartup.addListener(start);
chrome.runtime.onInstalled.addListener((d) => {
  // first install: open the setup page so the user sees the disclosure and can consent
  if (d && d.reason === "install") chrome.tabs.create({ url: chrome.runtime.getURL("popup.html") });
  start();
});
chrome.runtime.onMessage.addListener((msg, _s, reply) => {
  if (msg && msg.type === "getStatus") {
    reply({ enabled: cfg.enabled, connected, port: cfg.port, lastError, lastCommand, lastCommandAt, version: EXT_VERSION });
  }
  return false;
});
start();

// ------------------------------------------------------------------ tab helpers
async function getTab(tabId) {
  if (tabId !== undefined && tabId !== null) return chrome.tabs.get(Number(tabId));
  let [t] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!t) [t] = await chrome.tabs.query({ active: true });
  if (!t) throw new Error("no active tab");
  return t;
}

function waitForLoad(tabId, timeoutMs = 20000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = async () => {
      if (done) return; done = true;
      chrome.tabs.onUpdated.removeListener(listener);
      clearTimeout(timer);
      try { resolve(await chrome.tabs.get(tabId)); } catch (e) { resolve(null); }
    };
    const listener = (id, info) => { if (id === tabId && info.status === "complete") finish(); };
    const timer = setTimeout(finish, timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then((t) => { if (t.status === "complete" && t.url && t.url !== "about:blank") setTimeout(() => chrome.tabs.get(tabId).then((t2) => { if (t2.status === "complete") finish(); }), 300); }).catch(finish);
  });
}

const tabInfo = (t) => t && ({ tab_id: t.id, window_id: t.windowId, url: t.url, title: t.title, active: t.active, status: t.status });

async function inPage(tabId, func, args = [], world = "ISOLATED") {
  let res;
  try {
    res = await chrome.scripting.executeScript({ target: { tabId }, func, args, world });
  } catch (e) {
    throw new Error("cannot script this page (" + ((e && e.message) || e) + "). chrome://, the Web Store and some built-in pages are off-limits.");
  }
  const r = res && res[0];
  if (!r) throw new Error("no result from page");
  if (r.result && r.result.__error) throw new Error(r.result.__error);
  return r.result;
}

// ------------------------------------------------------------------ in-page functions (must be self-contained)
function pageGetPage(maxChars, maxElements) {
  // Copied into pageClick and pageType: executeScript serializes each function alone.
  const passwordField = (el) => {
    if (!el || !el.tagName) return false;
    const t = el.tagName.toLowerCase();
    if (t !== "input" && t !== "textarea") return false;
    const type = String(el.getAttribute("type") || el.type || "").toLowerCase();
    if (type === "password") return true;
    const ac = String(el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
    return ac.indexOf("current-password") !== -1 || ac.indexOf("new-password") !== -1;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none" && parseFloat(s.opacity || "1") > 0.05;
  };
  const sel = 'a[href], button, input:not([type=hidden]), textarea, select, summary, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [role=menuitem], [role=option], [role=switch], [role=combobox], [role=textbox], [role=searchbox], [contenteditable=""], [contenteditable=true], [onclick], [tabindex]:not([tabindex="-1"])';
  document.querySelectorAll("[data-gbb-idx]").forEach((e) => e.removeAttribute("data-gbb-idx"));
  const els = [];
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el)) continue;
    if (i >= maxElements) break;
    el.setAttribute("data-gbb-idx", String(i));
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute("role") || ({ a: "link", button: "button", select: "combobox", textarea: "textbox", summary: "button" })[tag] ||
      (tag === "input" ? ({ checkbox: "checkbox", radio: "radio", submit: "button", button: "button", reset: "button", image: "button" })[el.type] || "textbox" : (el.isContentEditable ? "textbox" : "generic"));
    let label = el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("alt") || "";
    if (!label && el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = l.innerText.trim(); }
    if (!label && el.closest("label")) label = el.closest("label").innerText.trim();
    const secret = passwordField(el);
    const text = secret
      ? ((String(el.value || "") || String(el.innerText || "").trim()) ? "•••" : "")
      : (el.innerText || el.value || "").replace(/\s+/g, " ").trim().slice(0, 100);
    const r = el.getBoundingClientRect();
    const item = { index: i, tag, role, label: label.slice(0, 100), text };
    if (tag === "input" || tag === "textarea" || tag === "select") { item.type = el.type; item.name = el.name || undefined; item.value = secret ? (String(el.value || "") ? "•••" : "") : String(el.value || "").slice(0, 100); }
    if (el.type === "checkbox" || el.type === "radio") item.checked = el.checked;
    if (tag === "a") item.href = el.href;
    if (el.disabled) item.disabled = true;
    item.in_viewport = r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
    els.push(item);
    i++;
  }
  // File inputs are often hidden behind a button. List them even when not visible.
  // This does not read file bytes. Shadow roots are included.
  const fileRoots = [document];
  const seenFiles = new Set();
  while (fileRoots.length && i < maxElements) {
    const root = fileRoots.pop();
    const nodes = root.querySelectorAll ? root.querySelectorAll("*") : [];
    for (const el of nodes) {
      if (el.shadowRoot) fileRoots.push(el.shadowRoot);
      if (!el.tagName || el.tagName.toLowerCase() !== "input" || (el.getAttribute("type") || "").toLowerCase() !== "file") continue;
      if (seenFiles.has(el) || el.hasAttribute("data-gbb-idx")) continue;
      seenFiles.add(el);
      if (i >= maxElements) break;
      el.setAttribute("data-gbb-idx", String(i));
      els.push({
        index: i, tag: "input", role: "file", type: "file",
        name: el.name || undefined, multiple: !!el.multiple,
        accept: el.accept || undefined, hidden: true,
        label: String(el.getAttribute("aria-label") || "").slice(0, 100),
      });
      i++;
    }
  }
  const text = (document.body ? document.body.innerText : "").replace(/\n{3,}/g, "\n\n");
  return {
    url: location.href, title: document.title,
    text: text.slice(0, maxChars), text_truncated: text.length > maxChars, text_length: text.length,
    elements: els,
    scroll: { x: scrollX, y: scrollY, max_y: document.documentElement.scrollHeight - innerHeight, viewport_h: innerHeight },
  };
}

function pageFind(index, selector) {
  let el = null;
  if (selector) el = document.querySelector(selector);
  else if (index !== null && index !== undefined) el = document.querySelector('[data-gbb-idx="' + index + '"]');
  return el;
}

function pageClick(index, selector) {
  const passwordField = (el) => {
    if (!el || !el.tagName) return false;
    const t = el.tagName.toLowerCase();
    if (t !== "input" && t !== "textarea") return false;
    const type = String(el.getAttribute("type") || el.type || "").toLowerCase();
    if (type === "password") return true;
    const ac = String(el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
    return ac.indexOf("current-password") !== -1 || ac.indexOf("new-password") !== -1;
  };
  let el = selector ? document.querySelector(selector) : document.querySelector('[data-gbb-idx="' + index + '"]');
  if (!el) return { __error: selector ? "no element matches selector " + selector : "no element with index " + index + " (call get_page again; indexes change after navigation)" };
  el.scrollIntoView({ block: "center", inline: "center" });
  const r = el.getBoundingClientRect();
  const opts = { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0 };
  try {
    el.dispatchEvent(new PointerEvent("pointerdown", opts));
    el.dispatchEvent(new MouseEvent("mousedown", opts));
    if (el.focus) el.focus();
    el.dispatchEvent(new PointerEvent("pointerup", opts));
    el.dispatchEvent(new MouseEvent("mouseup", opts));
  } catch (e) {}
  el.click();
  const shown = passwordField(el)
    ? ((String(el.value || "") || String(el.innerText || "").trim()) ? "•••" : "")
    : (el.innerText || el.value || "").replace(/\s+/g, " ").trim().slice(0, 100);
  return { clicked: true, tag: el.tagName.toLowerCase(), text: shown };
}

function pageType(index, selector, text, clear, submit) {
  const passwordField = (el) => {
    if (!el || !el.tagName) return false;
    const t = el.tagName.toLowerCase();
    if (t !== "input" && t !== "textarea") return false;
    const type = String(el.getAttribute("type") || el.type || "").toLowerCase();
    if (type === "password") return true;
    const ac = String(el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
    return ac.indexOf("current-password") !== -1 || ac.indexOf("new-password") !== -1;
  };
  let el = selector ? document.querySelector(selector) : (index !== null && index !== undefined ? document.querySelector('[data-gbb-idx="' + index + '"]') : document.activeElement);
  if (!el) return { __error: "target element not found" };
  el.scrollIntoView({ block: "center" });
  el.focus();
  const tag = el.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea") {
    const proto = tag === "input" ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;  // React/Vue friendly
    setter.call(el, (clear ? "" : el.value) + text);
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (tag === "select") {
    const opt = [...el.options].find((o) => o.value === text || o.text.trim() === text);
    if (!opt) return { __error: "no option '" + text + "' in select" };
    el.value = opt.value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (el.isContentEditable) {
    if (clear) { document.execCommand("selectAll", false, null); document.execCommand("delete", false, null); }
    document.execCommand("insertText", false, text);
  } else {
    return { __error: "element is not typeable (" + tag + ")" };
  }
  let submitted = false;
  if (submit) {
    const ko = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true };
    const notCancelled = el.dispatchEvent(new KeyboardEvent("keydown", ko));
    el.dispatchEvent(new KeyboardEvent("keypress", ko));
    el.dispatchEvent(new KeyboardEvent("keyup", ko));
    if (notCancelled && el.form) { if (el.form.requestSubmit) el.form.requestSubmit(); else el.form.submit(); submitted = true; }
  }
  const shown = passwordField(el) ? "•••" : (el.value !== undefined ? String(el.value).slice(0, 200) : el.innerText.slice(0, 200));
  return { typed: true, value: shown, submitted };
}

function pagePressKey(key, index, selector, modifiers) {
  let el = selector ? document.querySelector(selector) : (index !== null && index !== undefined ? document.querySelector('[data-gbb-idx="' + index + '"]') : (document.activeElement || document.body));
  if (!el) return { __error: "target element not found" };
  if (el.focus && el !== document.body) el.focus();
  const mods = Array.isArray(modifiers) ? modifiers.map((m) => String(m).toLowerCase()) : [];
  const codes = { Enter: 13, Tab: 9, Escape: 27, Backspace: 8, ArrowUp: 38, ArrowDown: 40, ArrowLeft: 37, ArrowRight: 39, " ": 32, Delete: 46, Home: 36, End: 35, PageUp: 33, PageDown: 34 };
  const kc = codes[key] || (key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0);
  const ko = {
    key, code: key.length === 1 ? "Key" + key.toUpperCase() : key, keyCode: kc, which: kc,
    bubbles: true, cancelable: true,
    ctrlKey: mods.indexOf("control") !== -1 || mods.indexOf("ctrl") !== -1,
    shiftKey: mods.indexOf("shift") !== -1,
    altKey: mods.indexOf("alt") !== -1,
    metaKey: mods.indexOf("meta") !== -1 || mods.indexOf("cmd") !== -1 || mods.indexOf("command") !== -1,
  };
  const notCancelled = el.dispatchEvent(new KeyboardEvent("keydown", ko));
  if (key.length === 1 || key === "Enter") el.dispatchEvent(new KeyboardEvent("keypress", ko));
  el.dispatchEvent(new KeyboardEvent("keyup", ko));
  let action = null;
  if (notCancelled) {   // emulate the most useful default actions
    if (key === "Enter" && el.form && el.tagName === "INPUT") { el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); action = "form submitted"; }
    else if (key === "Enter" && (el.tagName === "A" || el.tagName === "BUTTON")) { el.click(); action = "clicked"; }
    else if (key === "PageDown") { scrollBy(0, innerHeight * 0.9); action = "scrolled"; }
    else if (key === "PageUp") { scrollBy(0, -innerHeight * 0.9); action = "scrolled"; }
    else if (key === "End" && el === document.body) { scrollTo(0, document.body.scrollHeight); action = "scrolled"; }
    else if (key === "Home" && el === document.body) { scrollTo(0, 0); action = "scrolled"; }
  }
  return { pressed: key, modifiers: mods, target: el.tagName.toLowerCase(), default_action: action };
}

function pageUpload(op, selector, index, mode, spec, submit) {
  // Isolated world. It does not call the bridge. The service worker reads the
  // staged file and sends chunks here, so a public page never makes a loopback request.
  // Arguments stay small: names and sizes, not file bytes, the token, or a path.
  const queryDeep = (sel, root) => {
    const start = root || document;
    const stack = [start];
    while (stack.length) {
      const node = stack.pop();
      if (!node || !node.querySelector) continue;
      const hit = node.querySelector(sel);
      if (hit) return hit;
      const all = node.querySelectorAll("*");
      for (let i = 0; i < all.length; i++) if (all[i].shadowRoot) stack.push(all[i].shadowRoot);
    }
    return null;
  };
  const findEl = (sel, idx, which) => {
    if (sel) return queryDeep(sel, document);
    if (idx !== null && idx !== undefined) return document.querySelector('[data-gbb-idx="' + idx + '"]');
    if (which === "drop") return null;
    return queryDeep("input[type=file]", document);
  };
  if (op === "install") {
    if (!globalThis.__gbbUploadListen) {
      globalThis.__gbbUploadListen = true;
      globalThis.__gbbParts = {};
      chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
        if (!msg || (msg.type !== "gbb-chunk" && msg.type !== "gbb-end" && msg.type !== "gbb-error")) return;
        const key = String(msg.transferId || "") + ":" + String(msg.fileId || "");
        if (msg.type === "gbb-chunk" && msg.b64) {
          const bin = atob(msg.b64);
          const arr = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
          const list = globalThis.__gbbParts[key] || [];
          list.push(arr);
          globalThis.__gbbParts[key] = list;
        } else if (msg.type === "gbb-error") {
          globalThis.__gbbParts[key] = { error: String(msg.error || "upload transfer failed").slice(0, 180) };
        }
        try { sendResponse({ ok: true }); } catch (e) {}
        return true;
      });
    }
    return { installed: true };
  }
  const el = findEl(selector, index, mode);
  if (op === "find") return el ? { found: true } : { __miss: true };
  if (!el) return { __miss: true };
  const files = (spec && spec.files) || [];
  const transferId = spec && spec.transferId;
  const built = [];
  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    const key = String(transferId) + ":" + String(f.id);
    const parts = globalThis.__gbbParts && globalThis.__gbbParts[key];
    if (!parts || parts.error) return { __error: (parts && parts.error) || "upload did not start: the extension did not deliver the file" };
    let got = 0;
    for (let p = 0; p < parts.length; p++) got += parts[p].byteLength;
    if (typeof f.size === "number" && got !== f.size) return { __error: "upload size mismatch" };
    built.push(new File([new Blob(parts, { type: f.mime || "application/octet-stream" })], f.name, { type: f.mime || "application/octet-stream" }));
    delete globalThis.__gbbParts[key];
  }
  const dt = new DataTransfer();
  for (let i = 0; i < built.length; i++) dt.items.add(built[i]);
  if (mode === "drop") {
    for (const type of ["dragenter", "dragover", "drop"]) {
      el.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
    }
    return { dropped: true, count: built.length, names: built.map((f) => f.name), delivery: "stream" };
  }
  const input = el.tagName && el.tagName.toLowerCase() === "input" && String(el.getAttribute("type") || el.type || "").toLowerCase() === "file"
    ? el : queryDeep("input[type=file]", el);
  if (!input) return { __error: "target is not a file input (use mode drop for a drop target)" };
  if (built.length > 1 && !input.multiple) return { __error: "this file input does not accept multiple files" };
  input.files = dt.files;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  const names = [];
  const sizes = [];
  for (let i = 0; i < input.files.length; i++) { names.push(input.files[i].name); sizes.push(input.files[i].size); }
  let submitted = false;
  if (submit && input.form) {
    if (input.form.requestSubmit) input.form.requestSubmit();
    else input.form.submit();
    submitted = true;
  }
  return {
    set: true, count: input.files.length, names, sizes,
    multiple: !!input.multiple, accept: input.accept || "", submitted, delivery: "stream",
  };
}

function pageScroll(direction, amount, to, index, selector) {
  if (selector || (index !== null && index !== undefined)) {
    const el = selector ? document.querySelector(selector) : document.querySelector('[data-gbb-idx="' + index + '"]');
    if (!el) return { __error: "target element not found" };
    el.scrollIntoView({ block: "center" });
  } else if (to === "top") scrollTo(0, 0);
  else if (to === "bottom") scrollTo(0, document.documentElement.scrollHeight);
  else {
    const a = amount || Math.round(innerHeight * 0.8);
    const m = { down: [0, a], up: [0, -a], right: [a, 0], left: [-a, 0] }[direction || "down"] || [0, a];
    scrollBy(m[0], m[1]);
  }
  return { x: scrollX, y: scrollY, max_y: document.documentElement.scrollHeight - innerHeight };
}

function pageWaitFor(selector, text, timeoutMs, visibleOnly) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const check = () => {
      if (selector) {
        const el = document.querySelector(selector);
        if (el && (!visibleOnly || (el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0))) return resolve({ found: true, waited_ms: Date.now() - t0 });
      } else if (text) {
        if (document.body && document.body.innerText.includes(text)) return resolve({ found: true, waited_ms: Date.now() - t0 });
      }
      if (Date.now() - t0 > timeoutMs) return resolve({ __error: "timeout: " + (selector || text) + " not found after " + timeoutMs + "ms" });
      setTimeout(check, 150);
    };
    check();
  });
}


// ------------------------------------------------------------------ debugger (developer build)
let dialogArm = null;
const dbgBusy = new Map();

function armDialog(c) {
  if (!c) return;
  const raw = c.dialog !== undefined ? c.dialog : c.dialog_policy;
  if (raw === "accept" || raw === "dismiss") dialogArm = { policy: raw, promptText: c.prompt_text || c.promptText || "" };
  else if (raw && typeof raw === "object") dialogArm = { policy: raw.accept === false ? "dismiss" : "accept", promptText: raw.prompt_text || raw.promptText || "" };
}

function takeDialogDecision(params) {
  const oneShot = dialogArm;
  dialogArm = null;
  const type = (params && params.type) || "alert";
  const policy = (oneShot && oneShot.policy) || cfg.dialogPolicy || "";
  const promptText = (oneShot && oneShot.promptText) || (params && params.defaultPrompt) || "";
  if (policy === "accept") return { accept: true, promptText };
  if (policy === "dismiss") return { accept: false, promptText: "" };
  if (type === "alert") return { accept: true, promptText: "" };
  return { accept: false, promptText: "" };
}

function dbgSend(tabId, method, params, sessionId) {
  const target = sessionId ? { tabId, sessionId } : { tabId };
  return chrome.debugger.sendCommand(target, method, params || {});
}

function modifierBits(mods) {
  const list = (mods || []).map((m) => String(m).toLowerCase());
  let n = 0;
  if (list.indexOf("alt") !== -1) n |= 1;
  if (list.indexOf("control") !== -1 || list.indexOf("ctrl") !== -1) n |= 2;
  if (list.indexOf("meta") !== -1 || list.indexOf("cmd") !== -1 || list.indexOf("command") !== -1) n |= 4;
  if (list.indexOf("shift") !== -1) n |= 8;
  return n;
}

const KEY_CODES = {
  Enter: [13, "Enter"], Tab: [9, "Tab"], Escape: [27, "Escape"], Backspace: [8, "Backspace"],
  ArrowUp: [38, "ArrowUp"], ArrowDown: [40, "ArrowDown"], ArrowLeft: [37, "ArrowLeft"], ArrowRight: [39, "ArrowRight"],
  Delete: [46, "Delete"], Home: [36, "Home"], End: [35, "End"], PageUp: [33, "PageUp"], PageDown: [34, "PageDown"],
  " ": [32, "Space"],
};

async function withDebugger(tabId, fn) {
  while (dbgBusy.get(tabId)) await sleep(30);
  dbgBusy.set(tabId, true);
  let attachedHere = false;
  const state = { tabId, sessions: new Map(), contexts: [], choosers: [], dialogs: [], downloads: [], intercept: false };
  const onEvent = (source, method, params) => {
    if (method === "Browser.downloadWillBegin" || method === "Browser.downloadProgress") state.downloads.push({ method, params, source });
    if (!source || source.tabId !== tabId) return;
    if (method === "Target.attachedToTarget" && params && params.sessionId) {
      state.sessions.set(params.sessionId, (params.targetInfo) || {});
      dbgSend(tabId, "Page.enable", {}, params.sessionId).catch(() => {});
      if (state.intercept) dbgSend(tabId, "Page.setInterceptFileChooserDialog", { enabled: true }, params.sessionId).catch(() => {});
    }
    if (method === "Runtime.executionContextCreated" && params && params.context) state.contexts.push(params.context);
    if (method === "Page.fileChooserOpened") state.choosers.push({ source, params });
    if (method === "Page.javascriptDialogOpening") {
      const decision = takeDialogDecision(params);
      state.dialogs.push({ type: params && params.type, message: String((params && params.message) || "").slice(0, 200), accept: decision.accept });
      dbgSend(tabId, "Page.handleJavaScriptDialog", decision, source.sessionId).catch(() => {});
    }
  };
  chrome.debugger.onEvent.addListener(onEvent);
  try {
    try {
      await chrome.debugger.attach({ tabId }, "1.3");
      attachedHere = true;
    } catch (e) {
      const msg = String((e && e.message) || e);
      if (!/already attached/i.test(msg)) throw new Error("debugger attach failed: " + msg.slice(0, 180));
    }
    await dbgSend(tabId, "Page.enable");
    await dbgSend(tabId, "Runtime.enable").catch(() => {});
    await dbgSend(tabId, "Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true }).catch(() => {});
    await sleep(400);
    return await fn(state);
  } finally {
    chrome.debugger.onEvent.removeListener(onEvent);
    if (state.browserTarget) { try { await chrome.debugger.detach({ targetId: state.browserTarget }); } catch (e) {} }
    if (attachedHere) { try { await chrome.debugger.detach({ tabId }); } catch (e) {} }
    dbgBusy.delete(tabId);
  }
}

const DEEP_FN = "function gbbDeep(sel){const stack=[document];while(stack.length){const node=stack.pop();if(!node||!node.querySelector)continue;let hit=null;try{hit=node.querySelector(sel);}catch(e){hit=null;}if(hit)return hit;const all=node.querySelectorAll('*');for(let i=0;i<all.length;i++){if(all[i].shadowRoot)stack.push(all[i].shadowRoot);if(all[i].tagName==='IFRAME'){try{if(all[i].contentDocument)stack.push(all[i].contentDocument);}catch(e){}}}}return null;}";

function whichExpr(selector, index, preferFile) {
  if (selector) return "gbbDeep(" + JSON.stringify(selector) + ")";
  if (index !== null && index !== undefined) return "document.querySelector('[data-gbb-idx=\"" + Number(index) + "\"]')";
  if (preferFile) return "gbbDeep('input[type=file]')";
  return "null";
}

async function findNode(tabId, sessionId, selector, index, preferFile) {
  const expression = "(function(){" + DEEP_FN + "return " + whichExpr(selector, index, preferFile) + ";})()";
  const res = await dbgSend(tabId, "Runtime.evaluate", { expression }, sessionId);
  const objectId = res && res.result && res.result.objectId;
  if (!objectId || (res.result && res.result.subtype === "null")) return null;
  const metaRes = await dbgSend(tabId, "Runtime.callFunctionOn", {
    objectId,
    functionDeclaration: "function(){if(this.scrollIntoView)this.scrollIntoView({block:'center',inline:'center'});const r=this.getBoundingClientRect();return {tag:this.tagName,multiple:!!this.multiple,type:String((this.getAttribute&&this.getAttribute('type'))||this.type||''),x:r.left+r.width/2,y:r.top+r.height/2,text:String(this.innerText||this.value||'').replace(/\\s+/g,' ').trim().slice(0,100)};}",
    returnByValue: true,
  }, sessionId);
  const meta = (metaRes && metaRes.result && metaRes.result.value) || {};
  const desc = await dbgSend(tabId, "DOM.describeNode", { objectId }, sessionId);
  return Object.assign({}, meta, { backendNodeId: desc && desc.node && desc.node.backendNodeId, sessionId: sessionId || null, objectId });
}

async function findInFrames(state, selector, index, preferFile) {
  const main = await findNode(state.tabId, null, selector, index, preferFile);
  if (main) return main;
  for (const sid of state.sessions.keys()) {
    const hit = await findNode(state.tabId, sid, selector, index, preferFile);
    if (hit) return hit;
  }
  return null;
}

async function frameOffset(state, sessionId) {
  if (!sessionId) return { x: 0, y: 0 };
  const info = state.sessions.get(sessionId) || {};
  const url = info.url || "";
  if (!url) return { x: 0, y: 0 };
  const res = await dbgSend(state.tabId, "Runtime.evaluate", {
    expression: "(function(){const list=[].slice.call(document.querySelectorAll('iframe'));const hit=list.find(function(f){return f.src===" + JSON.stringify(url) + ";});if(!hit)return null;const r=hit.getBoundingClientRect();return {x:r.left,y:r.top};})()",
    returnByValue: true,
  });
  return (res && res.result && res.result.value) || { x: 0, y: 0 };
}

async function dispatchClick(tabId, x, y) {
  const common = { x, y, button: "left", clickCount: 1 };
  await dbgSend(tabId, "Input.dispatchMouseEvent", Object.assign({ type: "mouseMoved" }, common));
  await dbgSend(tabId, "Input.dispatchMouseEvent", Object.assign({ type: "mousePressed" }, common));
  await dbgSend(tabId, "Input.dispatchMouseEvent", Object.assign({ type: "mouseReleased" }, common));
}

const MOD_KEYS = { alt: ["Alt", 18], control: ["Control", 17], ctrl: ["Control", 17], meta: ["Meta", 91], cmd: ["Meta", 91], command: ["Meta", 91], shift: ["Shift", 16] };

async function dispatchKey(tabId, key, mods) {
  const named = KEY_CODES[key];
  const vk = named ? named[0] : (key && key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0);
  const code = named ? named[1] : (key && key.length === 1 ? "Key" + key.toUpperCase() : key);
  const list = mods || [];
  for (let i = 0; i < list.length; i++) {
    const spec = MOD_KEYS[String(list[i]).toLowerCase()];
    if (spec) await dbgSend(tabId, "Input.dispatchKeyEvent", { type: "keyDown", key: spec[0], code: spec[0], windowsVirtualKeyCode: spec[1], nativeVirtualKeyCode: spec[1], modifiers: modifierBits(list.slice(0, i + 1)) });
  }
  const modifiers = modifierBits(list);
  const text = modifiers ? (key === "Enter" ? "\r" : "") : (key === "Enter" ? "\r" : (key && key.length === 1 ? key : ""));
  await dbgSend(tabId, "Input.dispatchKeyEvent", { type: "keyDown", key, code, text, unmodifiedText: text, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers });
  await dbgSend(tabId, "Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers });
  for (let i = list.length - 1; i >= 0; i--) {
    const spec = MOD_KEYS[String(list[i]).toLowerCase()];
    if (spec) await dbgSend(tabId, "Input.dispatchKeyEvent", { type: "keyUp", key: spec[0], code: spec[0], windowsVirtualKeyCode: spec[1], nativeVirtualKeyCode: spec[1], modifiers: modifierBits(list.slice(0, i)) });
  }
}

async function dispatchText(tabId, text) {
  for (const ch of String(text)) await dispatchKey(tabId, ch, []);
}

async function dragFiles(tabId, x, y, paths) {
  const data = { items: [], files: paths, dragOperationsMask: 1 };
  for (const type of ["dragEnter", "dragOver", "drop"]) {
    await dbgSend(tabId, "Input.dispatchDragEvent", { type, x, y, data });
  }
}

async function waitChooser(state, before, ms) {
  const start = Date.now();
  while (Date.now() - start < ms) {
    if (state.choosers.length > before) return state.choosers[state.choosers.length - 1];
    await sleep(50);
  }
  return null;
}

async function enableIntercept(state) {
  state.intercept = true;
  await dbgSend(state.tabId, "Page.setInterceptFileChooserDialog", { enabled: true });
  for (const sid of state.sessions.keys()) {
    dbgSend(state.tabId, "Page.setInterceptFileChooserDialog", { enabled: true }, sid).catch(() => {});
  }
}

async function submitFiles(state, sessionId) {
  const res = await dbgSend(state.tabId, "Runtime.evaluate", {
    expression: "(function(){function walk(root){if(!root||!root.querySelectorAll)return false;const inputs=root.querySelectorAll('input[type=file]');for(let i=0;i<inputs.length;i++){const input=inputs[i];if(input.files&&input.files.length&&input.form){if(input.form.requestSubmit)input.form.requestSubmit();else input.form.submit();return true;}}const all=root.querySelectorAll('*');for(let i=0;i<all.length;i++){if(all[i].shadowRoot&&walk(all[i].shadowRoot))return true;if(all[i].tagName==='IFRAME'){try{if(all[i].contentDocument&&walk(all[i].contentDocument))return true;}catch(e){}}}return false;}return walk(document);})()",
    returnByValue: true,
  }, sessionId);
  return !!(res && res.result && res.result.value);
}

async function listedFiles(state, sessionId) {
  const res = await dbgSend(state.tabId, "Runtime.evaluate", {
    expression: "(function(){function walk(root){if(!root||!root.querySelectorAll)return null;const inputs=root.querySelectorAll('input[type=file]');for(let i=0;i<inputs.length;i++){const input=inputs[i];if(input.files&&input.files.length){const names=[];const sizes=[];for(let j=0;j<input.files.length;j++){names.push(input.files[j].name);sizes.push(input.files[j].size);}return {count:input.files.length,names:names,sizes:sizes,multiple:!!input.multiple,accept:input.accept||''};}}const all=root.querySelectorAll('*');for(let i=0;i<all.length;i++){if(all[i].shadowRoot){const hit=walk(all[i].shadowRoot);if(hit)return hit;}if(all[i].tagName==='IFRAME'){try{if(all[i].contentDocument){const hit=walk(all[i].contentDocument);if(hit)return hit;}}catch(e){}}}return null;}return walk(document);})()",
    returnByValue: true,
  }, sessionId);
  return (res && res.result && res.result.value) || null;
}

async function setDownloads(state, dir) {
  const behavior = { behavior: "allow", downloadPath: dir, eventsEnabled: true };
  const errors = [];
  try {
    const attached = await dbgSend(state.tabId, "Target.attachToBrowserTarget");
    if (attached && attached.sessionId) {
      state.browserSession = attached.sessionId;
      await dbgSend(state.tabId, "Browser.setDownloadBehavior", behavior, attached.sessionId);
      return;
    }
  } catch (e) { errors.push(String((e && e.message) || e).slice(0, 140)); }
  try {
    await dbgSend(state.tabId, "Browser.setDownloadBehavior", behavior);
    return;
  } catch (e) { errors.push(String((e && e.message) || e).slice(0, 120)); }
  let pageError = "";
  try {
    await dbgSend(state.tabId, "Page.setDownloadBehavior", { behavior: "allow", downloadPath: dir });
    return;
  } catch (e) { pageError = String((e && e.message) || e); }
  throw new Error("download folder was not set: " + pageError.slice(0, 300));
}

function waitBrowserDownload(timeoutMs, note) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      try { chrome.downloads.onChanged.removeListener(onChange); } catch (e) {}
      reject(new Error("download did not finish"));
    }, timeoutMs);
    const onChange = (delta) => {
      if (!delta || !delta.state || delta.state.current !== "complete") return;
      chrome.downloads.search({ id: delta.id }, (items) => {
        clearTimeout(timer);
        try { chrome.downloads.onChanged.removeListener(onChange); } catch (e) {}
        const item = items && items[0];
        const path = item && item.filename;
        const filename = path ? path.split(/[/\\]/).pop() : "download";
        resolve({ path, filename, state: "complete", folder_control: false, note });
      });
    };
    chrome.downloads.onChanged.addListener(onChange);
  });
}

async function waitDownload(state, dir, timeoutMs) {
  const start = Date.now();
  let began = null;
  while (Date.now() - start < timeoutMs) {
    for (let i = 0; i < state.downloads.length; i++) {
      const ev = state.downloads[i];
      if (ev.method === "Browser.downloadWillBegin") began = ev.params;
      if (ev.method === "Browser.downloadProgress" && ev.params && ev.params.state === "completed") {
        const name = (began && began.suggestedFilename) || "download";
        const sep = dir.indexOf("\\") !== -1 && dir.indexOf("/") === -1 ? "\\" : "/";
        return { path: dir.replace(/[\\/]+$/, "") + sep + name, filename: name, state: "completed", bytes: ev.params.receivedBytes || ev.params.totalBytes || null };
      }
    }
    await sleep(100);
  }
  throw new Error("download did not finish");
}

async function frameSnaps(state) {
  const frames = [];
  const seen = {};
  const take = (value) => {
    if (!value || !value.url || seen[value.url]) return;
    seen[value.url] = true;
    frames.push(value);
  };
  for (const [sid, info] of state.sessions) {
    if (info && info.type && info.type !== "iframe") continue;
    try {
      const res = await dbgSend(state.tabId, "Runtime.evaluate", {
        expression: "({url:location.href,title:document.title,text:(document.body&&document.body.innerText||'').slice(0,2000)})",
        returnByValue: true,
      }, sid);
      take(res && res.result && res.result.value);
    } catch (e) {}
  }
  for (let i = 0; i < state.contexts.length; i++) {
    const ctx = state.contexts[i];
    if (!ctx || !ctx.auxData || !ctx.auxData.isDefault) continue;
    try {
      const res = await dbgSend(state.tabId, "Runtime.evaluate", {
        expression: "({url:location.href,title:document.title,text:(document.body&&document.body.innerText||'').slice(0,2000)})",
        contextId: ctx.id,
        returnByValue: true,
      });
      take(res && res.result && res.result.value);
    } catch (e) {}
  }
  return frames;
}

function pathsOf(files) {
  const paths = [];
  for (const f of files) {
    if (!f || typeof f.real_path !== "string" || !f.real_path) throw new Error("staged file is missing its path");
    paths.push(f.real_path);
  }
  return paths;
}

async function doUploadCdp(c, tab) {
  const files = Array.isArray(c.files) ? c.files : [];
  const paths = pathsOf(files);
  const mode = c.mode === "drop" ? "drop" : "input";
  const viaClick = c.via === "click" || c.cmd === "click_upload";
  return await withDebugger(tab.id, async (state) => {
    armDialog(c);
    if (mode === "drop") {
      const node = await findInFrames(state, c.selector, c.index ?? null, false);
      if (!node) throw new Error("drop target not found");
      const off = await frameOffset(state, node.sessionId);
      await dragFiles(tab.id, node.x + off.x, node.y + off.y, paths);
      return { dropped: true, count: paths.length, names: files.map((f) => f.name), delivery: "cdp", trusted: true };
    }
    if (viaClick) {
      if (!c.selector && (c.index === undefined || c.index === null)) throw new Error("selector or index required for the upload button");
      await enableIntercept(state);
      const node = await findInFrames(state, c.selector, c.index ?? null, false);
      if (!node) throw new Error("upload button not found");
      const off = await frameOffset(state, node.sessionId);
      const before = state.choosers.length;
      await dispatchClick(tab.id, node.x + off.x, node.y + off.y);
      const chooser = await waitChooser(state, before, 5000);
      if (!chooser) throw new Error("file chooser did not open. The click did not open a file input, so no file was set and the system dialog was not used.");
      await dbgSend(tab.id, "DOM.setFileInputFiles", { backendNodeId: chooser.params.backendNodeId, files: paths }, chooser.source && chooser.source.sessionId);
      const info = (await listedFiles(state, chooser.source && chooser.source.sessionId)) || {};
      const submitted = c.submit ? await submitFiles(state, chooser.source && chooser.source.sessionId) : false;
      return { set: true, via: "click", count: info.count || paths.length, names: info.names || files.map((f) => f.name), sizes: info.sizes || [], submitted, delivery: "cdp", trusted: true, dialogs: state.dialogs.slice() };
    }
    const node = await findInFrames(state, c.selector, c.index ?? null, true);
    if (!node) throw new Error("file input not found");
    const isFile = String(node.type || "").toLowerCase() === "file" || String(node.tag || "").toUpperCase() === "INPUT";
    if (!isFile || String(node.type || "").toLowerCase() !== "file") throw new Error("target is not a file input (use mode drop for a drop target)");
    if (paths.length > 1 && !node.multiple) throw new Error("this file input does not accept multiple files");
    if (!node.backendNodeId) throw new Error("file input not found");
    await dbgSend(tab.id, "DOM.setFileInputFiles", { backendNodeId: node.backendNodeId, files: paths }, node.sessionId);
    const info = (await listedFiles(state, node.sessionId)) || {};
    const submitted = c.submit ? await submitFiles(state, node.sessionId) : false;
    return { set: true, count: info.count || paths.length, names: info.names || files.map((f) => f.name), sizes: info.sizes || [], multiple: !!node.multiple, accept: info.accept || "", submitted, delivery: "cdp", trusted: true, dialogs: state.dialogs.slice() };
  });
}

async function fetchStaged(file) {
  const url = base() + "/blob/" + encodeURIComponent(file.id);
  const hdrs = { "X-Token": cfg.token };
  const once = async (extra) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 15000);
    try {
      return await fetch(url, Object.assign({ headers: hdrs, cache: "no-store", signal: ctrl.signal }, extra));
    } finally {
      clearTimeout(timer);
    }
  };
  try {
    let resp;
    try {
      resp = await once({ targetAddressSpace: "loopback" });
    } catch (e) {
      const msg = String((e && e.message) || e);
      if (/abort|timed out|Timeout/i.test(msg)) throw e;
      resp = await once({});
    }
    if (!resp.ok) throw new Error("upload did not start (" + resp.status + ")");
    return resp;
  } catch (e) {
    const msg = String((e && e.message) || e);
    if (/abort|timed out|Timeout/i.test(msg)) throw new Error("upload did not start: no response from the bridge within 15s");
    throw new Error("upload did not start: " + msg.slice(0, 160));
  }
}

async function streamOneFile(tabId, frameId, transferId, file) {
  const resp = await fetchStaged(file);
  if (!resp.body || !resp.body.getReader) throw new Error("upload did not start: the bridge response has no body");
  const reader = resp.body.getReader();
  const toB64 = (u8) => {
    let s = "";
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, Math.min(u8.length, i + 0x8000)));
    return btoa(s);
  };
  while (true) {
    const step = await reader.read();
    if (step.done) break;
    let value = step.value;
    let offset = 0;
    while (offset < value.length) {
      const slice = value.subarray(offset, Math.min(value.length, offset + 262144));
      await chrome.tabs.sendMessage(tabId, { type: "gbb-chunk", transferId, fileId: file.id, b64: toB64(slice) }, { frameId });
      offset += slice.length;
    }
  }
  await chrome.tabs.sendMessage(tabId, { type: "gbb-end", transferId, fileId: file.id }, { frameId });
}

async function doUploadStream(c, tab) {
  const files = Array.isArray(c.files) ? c.files : [];
  const mode = c.mode === "drop" ? "drop" : "input";
  const sel = c.selector ?? null;
  const idx = c.index ?? null;
  const target = (c.frame_id !== undefined && c.frame_id !== null)
    ? { tabId: tab.id, frameIds: [Number(c.frame_id)] }
    : (idx !== null ? { tabId: tab.id } : { tabId: tab.id, allFrames: true });
  let frames;
  try {
    frames = await chrome.scripting.executeScript({ target, func: pageUpload, args: ["find", sel, idx, mode], world: "ISOLATED" });
  } catch (e) {
    throw new Error("cannot script this page (" + ((e && e.message) || e) + "). chrome://, the Web Store and some built-in pages are off-limits.");
  }
  const hits = (frames || []).filter((f) => f && f.result && f.result.found);
  if (!hits.length) throw new Error(mode === "drop" ? "drop target not found" : "file input not found");
  if (hits.length > 1) throw new Error("file target matched " + hits.length + " frames (" + hits.map((f) => f.frameId).join(", ") + "). Pass frame_id.");
  const frameId = hits[0].frameId;
  await chrome.scripting.executeScript({
    target: { tabId: tab.id, frameIds: [frameId] }, func: pageUpload, world: "ISOLATED",
    args: ["install", sel, idx, mode],
  });
  const transferId = Math.random().toString(36).slice(2) + Date.now().toString(36);
  try {
    for (const file of files) await streamOneFile(tab.id, frameId, transferId, file);
  } catch (e) {
    const detail = String((e && e.message) || e || "");
    try { await chrome.tabs.sendMessage(tab.id, { type: "gbb-error", transferId, fileId: "", error: detail.slice(0, 160) }, { frameId }); } catch (err) {}
    throw new Error(detail.indexOf("upload did not start") === 0 ? detail : "upload did not start: " + detail.slice(0, 160));
  }
  const spec = { transferId, files: files.map((f) => ({ id: f.id, name: f.name, mime: f.mime, size: f.size })) };
  let applied;
  try {
    const run = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: [frameId] }, func: pageUpload, world: "ISOLATED",
      args: ["apply", sel, idx, mode, spec, !!c.submit],
    });
    applied = run && run[0] && run[0].result;
  } catch (e) {
    const detail = String((e && e.message) || e || "");
    throw new Error("upload transfer failed" + (detail ? ": " + detail.slice(0, 180) : ""));
  }
  if (!applied || applied.__error) throw new Error((applied && applied.__error) || "upload transfer failed");
  if (applied.__miss) throw new Error(mode === "drop" ? "drop target not found" : "file input not found");
  return { applied, frameId };
}

async function afterNavigation(tabId, c, submitted) {
  if (!submitted && !c.submit) return chrome.tabs.get(tabId);
  await sleep(300);
  const after = await chrome.tabs.get(tabId);
  if (after.status === "loading") return waitForLoad(tabId, c.load_timeout_ms || 120000);
  return after;
}

// ------------------------------------------------------------------ command dispatcher
async function runCommand(c) {
  const name = c.cmd;
  const idx = c.index ?? null;
  const sel = c.selector ?? null;
  switch (name) {
    case "ping": return { pong: true, version: EXT_VERSION };

    case "list_tabs": {
      const tabs = await chrome.tabs.query({});
      return { tabs: tabs.map(tabInfo) };
    }
    case "open_url": {
      if (!c.url) throw new Error("url required");
      const dest = normalizeNavigationUrl(c.url);
      const t = await chrome.tabs.create({ url: dest, active: c.active !== false });
      if (c.wait === false) return tabInfo(t);
      return tabInfo(await waitForLoad(t.id, c.load_timeout_ms || 20000));
    }
    case "navigate": {
      if (!c.url) throw new Error("url required");
      const dest = normalizeNavigationUrl(c.url);
      const t = await getTab(c.tab_id);
      await chrome.tabs.update(t.id, { url: dest });
      if (c.wait === false) return tabInfo(await chrome.tabs.get(t.id));
      await sleep(150);
      return tabInfo(await waitForLoad(t.id, c.load_timeout_ms || 20000));
    }
    case "activate_tab": {
      const t = await chrome.tabs.update(Number(c.tab_id), { active: true });
      await chrome.windows.update(t.windowId, { focused: true }).catch(() => {});
      return tabInfo(t);
    }
    case "close_tab": {
      const t = await getTab(c.tab_id);
      await chrome.tabs.remove(t.id);
      return { closed: t.id };
    }
    case "back": case "forward": case "reload": {
      const t = await getTab(c.tab_id);
      const before = t.url;
      try {
        if (name === "back") await chrome.tabs.goBack(t.id);
        else if (name === "forward") await chrome.tabs.goForward(t.id);
        else await chrome.tabs.reload(t.id);
      } catch (e) {
        // Chrome's back/forward UI skips entries the page reached without a real user gesture
        // ("history manipulation intervention"); history.back()/forward() inside the page does not.
        if (name === "reload") throw e;
        await inPage(t.id, (d) => { d === "back" ? history.back() : history.forward(); return true; }, [name], "MAIN");
        await sleep(300);
        const now = await chrome.tabs.get(t.id);
        if (now.url === before && now.status === "complete") throw new Error("no " + (name === "back" ? "previous" : "next") + " page in history");
      }
      await sleep(200);
      return tabInfo(await waitForLoad(t.id, c.load_timeout_ms || 20000));
    }
    case "screenshot": {
      const t = await getTab(c.tab_id);
      const fmt = c.format === "jpeg" ? "jpeg" : "png";
      if (DEV_DEBUGGER && c.trusted !== false) {
        try {
          const shot = await withDebugger(t.id, async () => {
            const params = { format: fmt };
            if (fmt === "jpeg") params.quality = c.quality || 80;
            return dbgSend(t.id, "Page.captureScreenshot", params);
          });
          if (shot && shot.data) return { tab_id: t.id, url: t.url, format: fmt, data_base64: shot.data, via: "cdp" };
        } catch (e) {}
      }
      if (!t.active) { await chrome.tabs.update(t.id, { active: true }); await sleep(300); }
      const url = await chrome.tabs.captureVisibleTab(t.windowId, fmt === "jpeg" ? { format: "jpeg", quality: c.quality || 80 } : { format: "png" });
      return { tab_id: t.id, url: t.url, format: fmt, data_base64: url.split(",")[1] };
    }
    case "get_page": {
      const t = await getTab(c.tab_id);
      const r = await inPage(t.id, pageGetPage, [c.max_chars || 15000, c.max_elements || 300]);
      r.tab_id = t.id;
      if (DEV_DEBUGGER && c.frames !== false) {
        try {
          const snap = await withDebugger(t.id, async (state) => ({
            frames: await frameSnaps(state),
            contexts: state.contexts.length,
            sessions: state.sessions.size,
          }));
          r.frames = snap.frames || [];
          r.frame_debug = { contexts: snap.contexts, sessions: snap.sessions };
        } catch (e) { r.frames = []; r.frame_debug = { error: String((e && e.message) || e).slice(0, 160) }; }
      }
      return r;
    }
    case "click": {
      if (idx === null && !sel) throw new Error("index or selector required");
      const t = await getTab(c.tab_id);
      if (DEV_DEBUGGER && c.trusted !== false) {
        try {
          const trusted = await withDebugger(t.id, async (state) => {
            armDialog(c);
            let folderControl = false;
            let downloadNote = "";
            let browserDownload = null;
            if (c.download_dir) {
              try {
                await setDownloads(state, c.download_dir);
                folderControl = true;
              } catch (e) {
                if (!chrome.downloads) throw e;
                downloadNote = String((e && e.message) || e).slice(0, 180);
                browserDownload = waitBrowserDownload(c.load_timeout_ms || 20000, downloadNote);
              }
            }
            const node = await findInFrames(state, sel, idx, false);
            if (!node) throw new Error(sel ? "no element matches selector " + sel : "no element with index " + idx);
            const off = await frameOffset(state, node.sessionId);
            await dispatchClick(t.id, node.x + off.x, node.y + off.y);
            let download = null;
            if (browserDownload) download = await browserDownload;
            else if (c.download_dir && folderControl) download = await waitDownload(state, c.download_dir, c.load_timeout_ms || 20000);
            return { clicked: true, trusted: true, tag: String(node.tag || "").toLowerCase(), text: node.text || "", dialogs: state.dialogs.slice(), download };
          });
          await sleep(c.settle_ms ?? 300);
          const after = await chrome.tabs.get(t.id);
          if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
          const fin = await chrome.tabs.get(t.id);
          return Object.assign({}, trusted, { tab_id: t.id, url: fin.url, title: fin.title });
        } catch (e) {
          if (String((e && e.message) || e).indexOf("debugger attach failed") !== 0) throw e;
        }
      }
      const r = await inPage(t.id, pageClick, [idx, sel]);
      await sleep(c.settle_ms ?? 300);
      const after = await chrome.tabs.get(t.id);
      if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
      const fin = await chrome.tabs.get(t.id);
      return Object.assign({}, r, { trusted: false, tab_id: t.id, url: fin.url, title: fin.title });
    }
    case "type": {
      if (typeof c.text !== "string") throw new Error("text required");
      const t = await getTab(c.tab_id);
      if (DEV_DEBUGGER && c.trusted !== false) {
        try {
          const trusted = await withDebugger(t.id, async (state) => {
            armDialog(c);
            const node = await findInFrames(state, sel, idx, false);
            if (!node) throw new Error("target element not found");
            if (String(node.tag || "").toUpperCase() === "SELECT") return null;
            const off = await frameOffset(state, node.sessionId);
            await dispatchClick(t.id, node.x + off.x, node.y + off.y);
            await sleep(40);
            if (c.clear !== false) {
              const os = await chrome.runtime.getPlatformInfo();
              await dispatchKey(t.id, "a", [(os && os.os === "mac") ? "Meta" : "Control"]);
              await dispatchKey(t.id, "Backspace", []);
            }
            await dbgSend(t.id, "Input.insertText", { text: c.text });
            let submitted = false;
            if (c.submit) { await dispatchKey(t.id, "Enter", []); submitted = true; }
            return { typed: true, trusted: true, submitted, value: c.text.slice(0, 200) };
          });
          if (trusted) {
            const fin = await afterNavigation(t.id, c, trusted.submitted);
            return Object.assign({}, trusted, { tab_id: t.id, url: fin && fin.url });
          }
        } catch (e) {
          if (String((e && e.message) || e).indexOf("debugger attach failed") !== 0) throw e;
        }
      }
      const r = await inPage(t.id, pageType, [idx, sel, c.text, c.clear !== false, !!c.submit]);
      if (c.submit) {
        await sleep(300);
        const after = await chrome.tabs.get(t.id);
        if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
      }
      const fin = await chrome.tabs.get(t.id);
      return Object.assign({}, r, { trusted: false, tab_id: t.id, url: fin.url });
    }
    case "press_key": {
      if (!c.key) throw new Error("key required (e.g. Enter, Tab, Escape, ArrowDown, a)");
      const t = await getTab(c.tab_id);
      if (DEV_DEBUGGER && c.trusted !== false) {
        try {
          const trusted = await withDebugger(t.id, async (state) => {
            armDialog(c);
            if (sel || idx !== null) {
              const node = await findInFrames(state, sel, idx, false);
              if (!node) throw new Error("target element not found");
              const off = await frameOffset(state, node.sessionId);
              await dispatchClick(t.id, node.x + off.x, node.y + off.y);
            }
            await dispatchKey(t.id, c.key, c.modifiers || []);
            return { pressed: c.key, modifiers: c.modifiers || [], trusted: true, dialogs: state.dialogs.slice() };
          });
          await sleep(200);
          const after = await chrome.tabs.get(t.id);
          if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
          return Object.assign({}, trusted, { tab_id: t.id });
        } catch (e) {
          if (String((e && e.message) || e).indexOf("debugger attach failed") !== 0) throw e;
        }
      }
      const r = await inPage(t.id, pagePressKey, [c.key, idx, sel, c.modifiers || []]);
      await sleep(200);
      const after = await chrome.tabs.get(t.id);
      if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
      return Object.assign({}, r, { trusted: false, tab_id: t.id });
    }
    case "scroll": {
      const t = await getTab(c.tab_id);
      return await inPage(t.id, pageScroll, [c.direction || "down", c.amount || 0, c.to || null, idx, sel]);
    }
    case "wait_for": {
      if (!sel && !c.text) throw new Error("selector or text required");
      const t = await getTab(c.tab_id);
      return await inPage(t.id, pageWaitFor, [sel, c.text || null, c.timeout_ms || 10000, c.visible !== false]);
    }
    case "dialog": {
      const policy = c.policy || (c.accept === false ? "dismiss" : "accept");
      if (c.persist) {
        await chrome.storage.local.set({ dialogPolicy: policy });
        cfg.dialogPolicy = policy;
      }
      if (c.now) {
        const t = await getTab(c.tab_id);
        return await withDebugger(t.id, async (state) => {
          await dbgSend(t.id, "Page.handleJavaScriptDialog", { accept: policy !== "dismiss", promptText: c.prompt_text || "" });
          return { handled: true, policy, dialogs: state.dialogs.slice() };
        });
      }
      dialogArm = { policy, promptText: c.prompt_text || "" };
      return { armed: true, policy };
    }
    case "click_upload":
    case "upload": {
      const files = Array.isArray(c.files) ? c.files : [];
      if (!files.length) throw new Error("no files staged");
      for (const f of files) {
        if (!f || typeof f.id !== "string" || typeof f.name !== "string") throw new Error("staged file is incomplete");
      }
      const t = await getTab(c.tab_id);
      if (DEV_DEBUGGER) {
        try {
          const applied = await doUploadCdp(c, t);
          const fin = await afterNavigation(t.id, c, applied.submitted || applied.dropped);
          return Object.assign({}, applied, { tab_id: t.id, url: fin && fin.url });
        } catch (e) {
          const msg = String((e && e.message) || e);
          if (msg.indexOf("debugger attach failed") === 0) {
            throw new Error(msg + " This build does not fall back to a page fetch of 127.0.0.1, because a public site blocks that.");
          }
          throw e;
        }
      }
      const streamed = await doUploadStream(c, t);
      const fin = await afterNavigation(t.id, c, streamed.applied && streamed.applied.submitted);
      return Object.assign({}, streamed.applied, { frame_id: streamed.frameId, tab_id: t.id, url: fin && fin.url });
    }
    default:
      throw new Error("unknown cmd '" + name + "'. Known: ping, list_tabs, open_url, navigate, activate_tab, close_tab, screenshot, get_page, click, type, press_key, scroll, wait_for, click_upload, dialog, upload, back, forward, reload");
  }
}

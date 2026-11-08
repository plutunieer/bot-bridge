// Bot Bridge - service worker.
// This process fetches only http://127.0.0.1:<port> (the local bridge). It does not
// talk to the developer. The assistant that reads bridge results may process them off-device.
const EXT_VERSION = chrome.runtime.getManifest().version;
const DEFAULTS = { port: 8765, token: "", enabled: true, allowEval: true };
// Bump when the consent notice changes so earlier agreement is not reused. Store build only.
const REQUIRED_CONSENT_VERSION = 2;

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
chrome.runtime.onInstalled.addListener(start);
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

function pagePressKey(key, index, selector) {
  let el = selector ? document.querySelector(selector) : (index !== null && index !== undefined ? document.querySelector('[data-gbb-idx="' + index + '"]') : (document.activeElement || document.body));
  if (!el) return { __error: "target element not found" };
  if (el.focus && el !== document.body) el.focus();
  const codes = { Enter: 13, Tab: 9, Escape: 27, Backspace: 8, ArrowUp: 38, ArrowDown: 40, ArrowLeft: 37, ArrowRight: 39, " ": 32, Delete: 46, Home: 36, End: 35, PageUp: 33, PageDown: 34 };
  const kc = codes[key] || (key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0);
  const ko = { key, code: key.length === 1 ? "Key" + key.toUpperCase() : key, keyCode: kc, which: kc, bubbles: true, cancelable: true };
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
  return { pressed: key, target: el.tagName.toLowerCase(), default_action: action };
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

function pageEval(expr) {
  try {
    // indirect eval in the page's main world; subject to the page's Content-Security-Policy
    let v = (0, eval)(expr);
    const finish = (val) => {
      try { return { value: JSON.parse(JSON.stringify(val === undefined ? null : val)) }; }
      catch (e) { return { value: String(val) }; }
    };
    if (v && typeof v.then === "function") return v.then(finish, (e) => ({ __error: String(e) }));
    return finish(v);
  } catch (e) {
    return { __error: String(e && e.message || e) + (String(e).includes("unsafe-eval") ? " (page CSP blocks eval)" : "") };
  }
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
      if (!t.active) { await chrome.tabs.update(t.id, { active: true }); await sleep(300); }
      const fmt = c.format === "jpeg" ? "jpeg" : "png";
      const url = await chrome.tabs.captureVisibleTab(t.windowId, fmt === "jpeg" ? { format: "jpeg", quality: c.quality || 80 } : { format: "png" });
      return { tab_id: t.id, url: t.url, format: fmt, data_base64: url.split(",")[1] };
    }
    case "get_page": {
      const t = await getTab(c.tab_id);
      const r = await inPage(t.id, pageGetPage, [c.max_chars || 15000, c.max_elements || 300]);
      r.tab_id = t.id;
      return r;
    }
    case "click": {
      if (idx === null && !sel) throw new Error("index or selector required");
      const t = await getTab(c.tab_id);
      const r = await inPage(t.id, pageClick, [idx, sel]);
      await sleep(c.settle_ms ?? 300);
      const after = await chrome.tabs.get(t.id);
      if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
      const fin = await chrome.tabs.get(t.id);
      return { ...r, tab_id: t.id, url: fin.url, title: fin.title };
    }
    case "type": {
      if (typeof c.text !== "string") throw new Error("text required");
      const t = await getTab(c.tab_id);
      const r = await inPage(t.id, pageType, [idx, sel, c.text, c.clear !== false, !!c.submit]);
      if (c.submit) {
        await sleep(300);
        const after = await chrome.tabs.get(t.id);
        if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
      }
      const fin = await chrome.tabs.get(t.id);
      return { ...r, tab_id: t.id, url: fin.url };
    }
    case "press_key": {
      if (!c.key) throw new Error("key required (e.g. Enter, Tab, Escape, ArrowDown, a)");
      const t = await getTab(c.tab_id);
      const r = await inPage(t.id, pagePressKey, [c.key, idx, sel]);
      await sleep(200);
      const after = await chrome.tabs.get(t.id);
      if (after.status === "loading") await waitForLoad(t.id, c.load_timeout_ms || 15000);
      return { ...r, tab_id: t.id };
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
    case "eval": {
      await loadCfg();
      if (!cfg.allowEval) throw new Error("eval is disabled in the extension settings");
      if (typeof c.expression !== "string") throw new Error("expression required");
      const t = await getTab(c.tab_id);
      return await inPage(t.id, pageEval, [c.expression], "MAIN");
    }
    default:
      throw new Error("unknown cmd '" + name + "'. Known: ping, list_tabs, open_url, navigate, activate_tab, close_tab, screenshot, get_page, click, type, press_key, scroll, wait_for, back, forward, reload, eval");
  }
}

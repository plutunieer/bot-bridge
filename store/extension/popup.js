const $ = (id) => document.getElementById(id);

async function load() {
  const s = await chrome.storage.local.get({ port: 8765, token: "", enabled: true, consent: false, consentVersion: 0 });
  showConsent(consentCurrent(s));
  $("port").value = s.port;
  $("token").value = s.token;
  $("enabled").checked = s.enabled;
  refresh();
}

async function save() {
  await chrome.storage.local.set({
    port: parseInt($("port").value, 10) || 8765,
    token: $("token").value.trim(),
    enabled: $("enabled").checked,
  });
  setTimeout(refresh, 600);
}

async function refresh() {
  let st;
  try { st = await chrome.runtime.sendMessage({ type: "getStatus" }); } catch (e) { st = null; }
  const el = $("status");
  if (!st) { el.className = "status err"; el.textContent = "Service worker not reachable"; return; }
  if (!st.enabled) { el.className = "status"; el.textContent = "Off · Aus"; }
  else if (st.connected) { el.className = "status ok"; el.textContent = "Connected · Verbunden (127.0.0.1:" + st.port + ")"; }
  else { el.className = "status err"; el.textContent = "Not connected · Nicht verbunden" + (st.lastError ? " – " + st.lastError : ""); }
  $("last").textContent = st.lastCommand ? ("Last command: " + st.lastCommand + " · " + new Date(st.lastCommandAt).toLocaleTimeString()) : "";
}

$("save").addEventListener("click", save);
$("enabled").addEventListener("change", save);
const CONSENT_VERSION = 2;
function consentCurrent(s) { return !!s.consent && s.consentVersion === CONSENT_VERSION; }
function showConsent(ok) {
  $("consentBox").style.display = ok ? "none" : "block";
  $("consentedLine").style.display = ok ? "block" : "none";
  $("consent").checked = !!ok;
}
$("consent").addEventListener("change", async () => {
  const agreed = $("consent").checked;
  await chrome.storage.local.set({ consent: agreed, consentVersion: agreed ? CONSENT_VERSION : 0 });
  showConsent(agreed);
  setTimeout(refresh, 600);
});
$("revoke").addEventListener("click", async (e) => {
  e.preventDefault();
  await chrome.storage.local.set({ consent: false, consentVersion: 0 });
  showConsent(false);
  setTimeout(refresh, 600);
});
load();
setInterval(refresh, 1500);

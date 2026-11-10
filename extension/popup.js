const $ = (id) => document.getElementById(id);

async function load() {
  const s = await chrome.storage.local.get({ port: 8765, token: "", enabled: true, allowEval: true });
  $("port").value = s.port;
  $("token").value = s.token;
  $("enabled").checked = s.enabled;
  $("allowEval").checked = s.allowEval;
  refresh();
}

async function save() {
  await chrome.storage.local.set({
    port: parseInt($("port").value, 10) || 8765,
    token: $("token").value.trim(),
    enabled: $("enabled").checked,
    allowEval: $("allowEval").checked,
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
$("allowEval").addEventListener("change", save);
/*DEVCONSENT-START*/
const CONSENT_VERSION = 4;
function consentCurrent(s) { return !!s.consent && s.consentVersion === CONSENT_VERSION; }
function showConsent(ok) {
  const box = document.getElementById("consentBox");
  const line = document.getElementById("consentedLine");
  if (!box || !line) return;
  box.style.display = ok ? "none" : "block";
  line.style.display = ok ? "block" : "none";
  const boxInput = document.getElementById("consent");
  if (boxInput) boxInput.checked = !!ok;
}
const consentInput = document.getElementById("consent");
if (consentInput) consentInput.addEventListener("change", async () => {
  const agreed = consentInput.checked;
  await chrome.storage.local.set({ consent: agreed, consentVersion: agreed ? CONSENT_VERSION : 0 });
  showConsent(agreed);
  setTimeout(refresh, 600);
});
const revoke = document.getElementById("revoke");
if (revoke) revoke.addEventListener("click", async (e) => {
  e.preventDefault();
  await chrome.storage.local.set({ consent: false, consentVersion: 0 });
  showConsent(false);
  setTimeout(refresh, 600);
});
chrome.storage.local.get({ consent: false, consentVersion: 0 }).then((s) => showConsent(consentCurrent(s)));
/*DEVCONSENT-END*/
load();
setInterval(refresh, 1500);

"""Build the Chrome Web Store version of the extension.

Source: ../extension (local dev build, has the optional `eval` command).
Output: store/extension/ and dist/extension-store.zip

Store build differences (Chrome Web Store / MV3 remote-code policy):
  * `eval` command, pageEval() and the allowEval toggle are removed. Every page
    action runs code that ships inside the extension package; the bridge only
    sends data (command name, URL, selector, text), never code.
  * `activeTab` permission dropped (redundant with the host permission).
  * version 1.0.5, store-oriented description, popup help line, en/de locales, consent screen.
"""
import json, os, re, shutil, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "extension")
OUT = os.path.join(HERE, "extension")
DIST = os.path.join(ROOT, "dist")
VERSION = "1.0.5"

def rep(s, old, new, count=1):
    if old not in s:
        sys.exit("build_store: pattern not found:\n" + old[:200])
    return s.replace(old, new, count)

shutil.rmtree(OUT, ignore_errors=True)
shutil.copytree(SRC, OUT)

# ---- manifest
m = json.load(open(os.path.join(OUT, "manifest.json")))
m["version"] = VERSION
m["permissions"] = ["tabs", "scripting", "storage", "alarms"]
m["name"] = "Bot Bridge"
m["description"] = "Lets your AI assistant (e.g. Grok Bot) control this Chrome through a bridge on your computer. Extension traffic is 127.0.0.1 only."
assert len(m["description"]) <= 132, len(m["description"])
DESC = {"en": m["description"],
        "de": "Lässt deinen KI-Assistenten (z. B. Grok Bot) dein Chrome über eine Bridge auf deinem Computer steuern. Erweiterung nur zu 127.0.0.1."}
for lang, d in DESC.items():
    assert len(d) <= 132, (lang, len(d))
    os.makedirs(os.path.join(OUT, "_locales", lang), exist_ok=True)
    json.dump({"extName": {"message": m["name"]}, "extDescription": {"message": d}},
              open(os.path.join(OUT, "_locales", lang, "messages.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
m["default_locale"] = "en"
m["name"] = "__MSG_extName__"
m["description"] = "__MSG_extDescription__"
json.dump(m, open(os.path.join(OUT, "manifest.json"), "w"), indent=2)

# ---- background.js
p = os.path.join(OUT, "background.js"); s = open(p).read()
s = rep(s, 'const DEFAULTS = { port: 8765, token: "", enabled: true, allowEval: true };',
           'const DEFAULTS = { port: 8765, token: "", enabled: true };')
s = re.sub(r"\nfunction pageEval\(expr\) \{.*?\n\}\n", "\n", s, flags=re.S)
s = re.sub(r'\n    case "eval": \{.*?\n    \}\n', "\n", s, flags=re.S)
s = rep(s, "back, forward, reload, eval\");", "back, forward, reload\");")
open(p, "w").write(s)

# ---- popup
p = os.path.join(OUT, "popup.html"); s = open(p).read()
s = re.sub(r"<!--EVAL-->.*?<!--/EVAL-->\n", "", s, flags=re.S)
s = rep(s, "<!--STORE-NOTE-->", '      <p>Requires the free bridge app on this computer · Benötigt die Bridge-App: <a href="https://github.com/plutunieer/bot-bridge#readme" target="_blank" rel="noopener">github.com/plutunieer/bot-bridge</a></p>\n      <p><a href="https://plutunieer.github.io/bot-bridge/privacy-policy.html" target="_blank" rel="noopener">Privacy policy · Datenschutz</a></p>')
open(p, "w").write(s)
p = os.path.join(OUT, "popup.js"); s = open(p).read()
s = rep(s, 'enabled: true, allowEval: true });', 'enabled: true });')
s = rep(s, '  $("allowEval").checked = s.allowEval;\n', '')
s = rep(s, '    allowEval: $("allowEval").checked,\n', '')
s = rep(s, '$("allowEval").addEventListener("change", save);\n', '')
open(p, "w").write(s)

# ---- prominent disclosure + affirmative consent (CWS User Data Policy)
p = os.path.join(OUT, "background.js"); s = open(p).read()
s = rep(s, 'const DEFAULTS = { port: 8765, token: "", enabled: true };',
           'const DEFAULTS = { port: 8765, token: "", enabled: true, consent: false, consentVersion: 0 };')
s = rep(s, 'chrome.runtime.onInstalled.addListener(start);',
           'chrome.runtime.onInstalled.addListener((d) => {\n'
           '  // first install: open the setup page so the user sees the disclosure and can consent\n'
           '  if (d && d.reason === "install") chrome.tabs.create({ url: chrome.runtime.getURL("popup.html") });\n'
           '  start();\n});')
open(p, "w").write(s)

CONSENT_HTML = """    <div id="consentBox" class="consent">
      <b class="t">Read before connecting · Bitte vor dem Verbinden lesen</b>
      <ul>
        <li>Your assistant, via the bridge on <b>this computer</b>, can open tabs, read page text and form values, click, type, take screenshots, and place <b>local files you name</b> into file inputs.</li>
        <li>The extension sends that data only to <b>127.0.0.1</b>, not to the developer. Your assistant, and any site you upload to, may process it <b>off this device</b>. This is not an offline guarantee.</li>
        <li>Password fields are masked only in page reads. Screenshots, other fields, and text you ask the assistant to type are not. Pages can contain sensitive personal data.</li>
        <li>Dein Assistent kann das über die Bridge auf diesem Computer. Die Erweiterung sendet es nur an <b>127.0.0.1</b>, nicht an den Entwickler. Der Assistent kann es <b>ausserhalb des Geräts</b> verarbeiten. Passwortfelder werden nur beim Auslesen maskiert.</li>
      </ul>
      <label><input id="consent" type="checkbox"> I understand and agree · Ich stimme zu</label>
    </div>
    <div id="consentedLine" class="consented" style="display:none">Consent given · Zugestimmt. Your assistant may process data off-device. <a href="#" id="revoke">Revoke · Widerrufen</a></div>"""
CONSENT_JS = """const CONSENT_VERSION = 3;
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
load();"""
p = os.path.join(OUT, "popup.html"); s = open(p).read()
s = rep(s, "<!--CONSENT-->", CONSENT_HTML)
open(p, "w").write(s)
p = os.path.join(OUT, "popup.js"); s = open(p).read()
s = rep(s, 'enabled: true });\n  $("port").value', 'enabled: true, consent: false, consentVersion: 0 });\n  showConsent(consentCurrent(s));\n  $("port").value')
s = rep(s, "load();", CONSENT_JS)
open(p, "w").write(s)

# ---- compliance scan: no dynamic code execution anywhere in the package
bad = re.compile(r"\beval\s*\(|\(0,\s*eval\)|new\s+Function\s*\(|\bFunction\s*\(|setTimeout\s*\(\s*['\"`]|setInterval\s*\(\s*['\"`]|importScripts|import\s*\(|allowEval|https?://(?!127\.0\.0\.1|github\.com/plutunieer/bot-bridge|plutunieer\.github\.io/bot-bridge/)")
problems = []
for d, _, files in os.walk(OUT):
    for f in files:
        if f.endswith((".js", ".html", ".json")):
            for i, line in enumerate(open(os.path.join(d, f), encoding="utf-8"), 1):
                if bad.search(line):
                    problems.append(f"{f}:{i}: {line.strip()[:120]}")
if problems:
    sys.exit("compliance scan failed:\n" + "\n".join(problems))
print("compliance scan: OK (no eval/new Function/string timers/imports; only URLs: 127.0.0.1 + project link)")

# ---- zip (manifest at root)
os.makedirs(DIST, exist_ok=True)
zp = os.path.join(DIST, "extension-store.zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for d, dirs, files in os.walk(OUT):
        dirs.sort()
        for f in sorted(files):
            if f.startswith("."): continue
            fp = os.path.join(d, f)
            info = zipfile.ZipInfo(os.path.relpath(fp, OUT).replace(os.sep, "/"), (2026, 11, 8, 0, 0, 0))
            info.external_attr = 0o644 << 16; info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, open(fp, "rb").read())
print("wrote", zp, os.path.getsize(zp), "bytes, version", VERSION)

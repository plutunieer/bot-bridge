"""Capture real Chromium screenshots of the store build for the Web Store listing.
Runs a headed Chromium on a private Xvfb display (1280x800), drives it through the
real bridge + extension, and grabs the X screen. Also captures the popup at 2x."""
import hashlib, json, os, subprocess, sys, tempfile, time, urllib.request
from PIL import ImageGrab
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXT = os.path.join(ROOT, "store", "extension")
RAW = os.path.join(HERE, "raw"); os.makedirs(RAW, exist_ok=True)
DISP = ":99"
HOME = tempfile.mkdtemp(prefix="bbshots-")
env = dict(os.environ, HOME=HOME)

def ext_id(path):
    h = hashlib.sha256(path.encode()).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in h)

xvfb = subprocess.Popen(["Xvfb", DISP, "-screen", "0", "1280x800x24", "-nolisten", "tcp"], stderr=subprocess.DEVNULL)
site = subprocess.Popen([sys.executable, "-m", "http.server", "8812", "--bind", "127.0.0.1", "-d", os.path.join(HERE, "demo-site")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
bridge = subprocess.Popen([sys.executable, os.path.join(ROOT, "bridge", "bridge.py"), "serve"], env=env, stdout=subprocess.DEVNULL)
time.sleep(1.2)
token = json.load(open(os.path.join(HOME, ".bot-bridge", "config.json")))["token"]

def call(path, body=None):
    req = urllib.request.Request("http://127.0.0.1:8765" + path, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET", headers={"X-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())

log = []
def bot(body):
    r = call("/command", body); log.append({"request": body, "response": r}); return r

def grab(name):
    time.sleep(0.8)
    im = ImageGrab.grab(xdisplay=DISP).convert("RGB")
    im.save(os.path.join(RAW, name)); print("saved", name, im.size)

def popup_shot(ctx, eid, name, height):
    """Popup rendered at 2x for crisp compositing. Height grows to fit the notice."""
    pg = ctx.new_page()
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": 340, "height": height, "deviceScaleFactor": 2, "mobile": False})
    pg.goto(f"chrome-extension://{eid}/popup.html"); time.sleep(1.5)
    full = pg.evaluate("""() => {
      document.body.style.maxHeight = 'none';
      document.body.style.overflow = 'visible';
      return Math.ceil(document.documentElement.scrollHeight);
    }""")
    use = max(height, int(full) + 8)
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": 340, "height": use, "deviceScaleFactor": 2, "mobile": False})
    time.sleep(0.4)
    pg.locator("body").screenshot(path=os.path.join(RAW, name)); print("saved", name, "css_height", use)
    pg.close()

try:
    prof = tempfile.mkdtemp(prefix="bbprof-")
    eid = ext_id(EXT)
    os.makedirs(os.path.join(prof, "Default"), exist_ok=True)
    json.dump({"extensions": {"pinned_extensions": [eid]}, "browser": {"has_seen_welcome_page": True}},
              open(os.path.join(prof, "Default", "Preferences"), "w"))
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(prof, channel="chromium", headless=False, no_viewport=True,
            env={**os.environ, "DISPLAY": DISP}, ignore_default_args=["--enable-automation"],
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}",
                  "--disable-features=DisableLoadExtensionCommandLineSwitch",
                  "--no-sandbox", "--disable-dev-shm-usage",
                  "--window-position=0,0", "--window-size=1280,800",
                  "--no-first-run", "--hide-crash-restore-bubble", "--test-type", "--lang=en-US"])
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
        assert sw.url.split("/")[2] == eid, (sw.url, eid)
        time.sleep(1.5)
        popup_shot(ctx, eid, "popup_consent@2x.png", 760)          # notice version 2, full disclosure
        page = ctx.pages[0]
        page.goto(f"chrome-extension://{eid}/popup.html"); time.sleep(0.5)
        page.check("#consent")
        page.fill("#port", "8765"); page.fill("#token", token); page.click("#save")
        for pg in list(ctx.pages):
            if pg != page: pg.close()
        for _ in range(30):
            if call("/status")["extension_connected"]: break
            time.sleep(0.5)
        time.sleep(1)
        # --- the assistant drives the browser through the bridge
        bot({"cmd": "navigate", "url": "http://127.0.0.1:8812/index.html"})
        g = bot({"cmd": "get_page", "max_chars": 400})
        q = next(e["index"] for e in g["result"]["elements"] if e["role"] == "textbox")
        btn = next(e["index"] for e in g["result"]["elements"] if e["text"] == "Search")
        bot({"cmd": "type", "index": q, "text": "Altstadt"})
        bot({"cmd": "click", "index": btn})
        bot({"cmd": "get_page", "max_chars": 600})
        popup_shot(ctx, eid, "popup_connected@2x.png", 560)
        page.bring_to_front(); time.sleep(0.5)
        grab("browser_page.png")
        sw.evaluate("chrome.action.openPopup()"); time.sleep(1.5)
        grab("browser_page_popup.png")
        json.dump(log, open(os.path.join(RAW, "bot_log.json"), "w"), indent=1, ensure_ascii=False)
        ctx.close()
finally:
    bridge.terminate(); site.terminate(); xvfb.terminate()

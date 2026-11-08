"""End-to-end test: bridge + extension loaded in Playwright Chromium + local test site."""
import base64, hashlib, json, os, subprocess, sys, time, tempfile, urllib.request
from upload_fixture import UploadFixture
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.environ.get("GBB_EXT") or os.path.join(ROOT, "extension")
NO_EVAL = bool(os.environ.get("GBB_NO_EVAL"))   # store build has no eval command
HOME = tempfile.mkdtemp(prefix="gbbhome-")
PORT = 8765
env = dict(os.environ, HOME=HOME, USERPROFILE=HOME)

site = subprocess.Popen([sys.executable, "-m", "http.server", "8811", "--bind", "127.0.0.1", "-d", os.path.join(ROOT, "test", "site")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
uploads = UploadFixture()
bridge = subprocess.Popen([sys.executable, os.path.join(ROOT, "bridge", "bridge.py"), "serve", "--port", str(PORT)], env=env, stdout=subprocess.PIPE, text=True)
time.sleep(1.0)
token = json.load(open(os.path.join(HOME, ".bot-bridge", "config.json")))["token"]

def http(method, path, body=None, tok=token, headers=None, timeout=120):
    h = {"Content-Type": "application/json"}
    if tok is not None: h["X-Token"] = tok
    h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")

def cli(cmd):
    out = subprocess.run([sys.executable, os.path.join(ROOT, "bridge", "bridge.py"), "send", json.dumps(cmd)], env=env, capture_output=True, text=True)
    return json.loads(out.stdout)

results = []
def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("  -> " + info if info else ""))

try:
    # auth checks before the extension even exists
    check("no token -> 401", http("GET", "/status", tok=None)[0] == 401)
    check("wrong token -> 401", http("GET", "/status", tok="nope")[0] == 401)
    check("web origin -> 403", http("GET", "/status", headers={"Origin": "https://evil.example"})[0] == 403)
    check("status: not connected yet", http("GET", "/status")[1]["extension_connected"] is False)

    with sync_playwright() as p:
        channel = os.environ.get("GBB_CHANNEL") or "chromium"
        headless = os.environ.get("GBB_HEADED") != "1"
        ctx = p.chromium.launch_persistent_context(tempfile.mkdtemp(prefix="gbbprofile-"), channel=channel, headless=headless,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}",
                  "--disable-features=DisableLoadExtensionCommandLineSwitch",
                  "--no-sandbox", "--disable-dev-shm-usage"])
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
        ext_id = sw.url.split("/")[2]
        print("extension id:", ext_id, "version:", sw.evaluate("chrome.runtime.getManifest().version"), "permissions:", sw.evaluate("chrome.runtime.getManifest().permissions"))
        # configure through the real popup UI
        pop = ctx.new_page()
        pop.goto(f"chrome-extension://{ext_id}/popup.html")
        if pop.query_selector("#consent"):   # store build: consent required before connecting
            pop.fill("#port", str(PORT)); pop.fill("#token", token); pop.click("#save")
            time.sleep(2)
            st0 = http("GET", "/status")[1]
            check("store build: no connection before consent", st0["extension_connected"] is False, json.dumps(st0))
            code, denied = http("POST", "/command", {"cmd": "upload", "path": os.path.join(HOME, "no-such-file"), "selector": "#file"})
            check("store build: upload refused before consent", code == 503, json.dumps(denied)[:160])
            pop.check("#consent")
        pop.fill("#port", str(PORT)); pop.fill("#token", token); pop.click("#save")
        for _ in range(40):
            st = http("GET", "/status")[1]
            if st["extension_connected"]: break
            time.sleep(0.5)
        check("extension connects to bridge", st["extension_connected"], json.dumps(st))
        time.sleep(1)
        check("popup shows Connected", "Connected" in pop.inner_text("#status"), pop.inner_text("#status"))
        badge = sw.evaluate("chrome.action.getBadgeText({})")
        check("badge shows ON", badge == "ON", badge)

        r = http("POST", "/command", {"cmd": "open_url", "url": "http://127.0.0.1:8811/index.html"})[1]
        check("open_url", r["ok"] and r["result"]["title"] == "GBB Test Page", json.dumps(r)[:200])
        tab = r["result"]["tab_id"]

        r = http("POST", "/command", {"cmd": "get_page"})[1]
        els = r["result"]["elements"]
        check("get_page text", "Bot Bridge Test" in r["result"]["text"], f"{len(els)} elements")
        pw = next((e for e in els if e.get("name") == "pw"), None)
        pw_blob = json.dumps(pw or {})
        check("password field masked", bool(pw) and pw.get("value") == "•••" and pw.get("text") == "•••" and "fixture-password-value" not in pw_blob)
        check("page text does not include the password field", "fixture-password-value" not in r["result"]["text"])

        # File upload: the fixture server must receive the same bytes, not just a filename.
        up_dir = os.path.join(HOME, "uploads")
        os.makedirs(up_dir)
        def write_file(name, data):
            path = os.path.join(up_dir, name)
            with open(path, "wb") as f:
                f.write(data)
            return path, hashlib.sha256(data).hexdigest()
        small_path, small_sha = write_file("note.txt", b"hello upload fixture")
        other_path, other_sha = write_file("second.txt", b"second file bytes")
        video = b"\x00\x00\x00\x18ftypmp42" + (b"BBUPLOAD-MARKER-9f3c" * (5 * 1024 * 1024 // 20))
        video = video[:5 * 1024 * 1024]
        video_path, video_sha = write_file("clip.mp4", video)
        def received():
            with urllib.request.urlopen(uploads.url("/received"), timeout=10) as resp:
                return json.load(resp)["files"]
        def reset_received():
            urllib.request.urlopen(uploads.url("/reset"), timeout=10).read()
        def shas():
            return {item["sha256"] for item in received()}
        def open_upload():
            http("POST", "/command", {"cmd": "open_url", "url": uploads.url("/")})
        open_upload()
        reset_received()
        r = http("POST", "/command", {"cmd": "upload", "selector": "#file", "path": small_path, "submit": True, "timeout": 60})
        blob = json.dumps(r[1])
        check("single file upload sets the input and submits", r[0] == 200 and r[1].get("ok") and r[1]["result"].get("set") and r[1]["result"].get("submitted"), blob[:240])
        check("single file result has no raw bytes", "data_base64" not in blob and "hello upload fixture" not in blob)
        check("single file bytes arrived", small_sha in shas() and r[1]["result"]["files"][0]["sha256"] == small_sha)
        reset_received()
        open_upload()
        r = http("POST", "/command", {"cmd": "upload", "selector": "#hid", "path": small_path, "submit": True, "timeout": 60})
        check("hidden file input upload", r[0] == 200 and r[1].get("ok") and small_sha in shas(), json.dumps(r[1])[:200])
        reset_received()
        open_upload()
        r = http("POST", "/command", {"cmd": "upload", "selector": "#multi", "paths": [small_path, other_path], "submit": True, "timeout": 60})
        got = shas()
        check("multiple file upload", r[0] == 200 and r[1].get("ok") and r[1]["result"].get("count") == 2 and small_sha in got and other_sha in got, json.dumps({k: r[1].get(k) for k in ("ok",)}) )
        reset_received()
        open_upload()
        r = http("POST", "/command", {"cmd": "upload", "selector": "#inside", "path": other_path, "submit": True, "timeout": 60})
        check("shadow DOM file input", r[0] == 200 and r[1].get("ok") and other_sha in shas(), json.dumps(r[1])[:200])
        reset_received()
        open_upload()
        r = http("POST", "/command", {"cmd": "upload", "selector": "#framefile", "path": small_path, "submit": True, "timeout": 60})
        check("iframe file input", r[0] == 200 and r[1].get("ok") and small_sha in shas(), json.dumps(r[1])[:220])
        reset_received()
        open_upload()
        r = http("POST", "/command", {"cmd": "upload", "selector": "#file", "paths": [small_path, other_path], "timeout": 30})
        check("non-multiple input rejects two files", r[0] == 200 and not r[1].get("ok") and "multiple" in r[1].get("error", ""), json.dumps(r[1])[:200])
        check("rejected multiple did not upload", shas() == set())
        r = http("POST", "/command", {"cmd": "upload", "selector": "#missing", "path": small_path, "timeout": 30})
        check("missing file input is an error", r[0] == 200 and not r[1].get("ok") and "not found" in r[1].get("error", ""), json.dumps(r[1])[:200])
        r = http("POST", "/command", {"cmd": "upload", "path": os.path.join(up_dir, "absent.bin"), "selector": "#file"})
        check("missing path is 400 and has no file bytes", r[0] == 400 and "hello upload fixture" not in json.dumps(r[1]))
        reset_received()
        open_upload()
        r = http("POST", "/command", {"cmd": "press_key", "selector": "#keys", "key": "a", "modifiers": ["Control"]})
        page = http("POST", "/command", {"cmd": "get_page"})[1]
        check("ctrl+a shortcut reaches the page", r[0] == 200 and r[1].get("ok") and "ctrl-a" in page.get("result", {}).get("text", ""), json.dumps(r[1])[:160])
        reset_received()
        r = http("POST", "/command", {"cmd": "upload", "mode": "drop", "selector": "#drop", "path": small_path, "timeout": 30})
        time.sleep(0.5)
        check("drop target delivered the same bytes", r[0] == 200 and r[1].get("ok") and r[1]["result"].get("dropped") and small_sha in shas(), json.dumps(r[1])[:220])
        reset_received()
        open_upload()
        r = http("POST", "/command", {"cmd": "upload", "selector": "#file", "path": video_path, "submit": True, "timeout": 90})
        vblob = json.dumps(r[1])
        check("5MB mp4-like upload", r[0] == 200 and r[1].get("ok") and r[1]["result"]["files"][0]["size"] == len(video) and video_sha in shas(), "size %d" % len(video))
        check("video bytes were not echoed", "BBUPLOAD-MARKER-9f3c" not in vblob and "data_base64" not in vblob)
        http("POST", "/command", {"cmd": "activate_tab", "tab_id": tab})
        http("POST", "/command", {"cmd": "navigate", "url": "http://127.0.0.1:8811/index.html", "tab_id": tab})
        els = http("POST", "/command", {"cmd": "get_page", "tab_id": tab})[1]["result"]["elements"]
        inc = next(e["index"] for e in els if e["text"] == "Increment")
        q = next(e["index"] for e in els if e.get("name") == "q")
        check("get_page labels input", next(e for e in els if e["index"] == q)["label"] in ("Type here", "Search term"))

        r = http("POST", "/command", {"cmd": "click", "index": inc})[1]
        r = http("POST", "/command", {"cmd": "click", "selector": "#inc"})[1]
        txt = http("POST", "/command", {"cmd": "get_page"})[1]["result"]["text"]
        check("click by index + selector", "Clicks: 2" in txt)

        r = http("POST", "/command", {"cmd": "wait_for", "selector": "#appeared", "timeout_ms": 5000})[1]
        check("wait_for", r["ok"] and r["result"]["found"], json.dumps(r))

        r = http("POST", "/command", {"cmd": "scroll", "to": "bottom"})[1]
        check("scroll", r["ok"] and r["result"]["y"] > 1000, json.dumps(r))

        shot = os.path.join(HOME, "shot.png")
        r = http("POST", "/command", {"cmd": "screenshot", "save_path": shot})[1]
        ok = r["ok"] and os.path.exists(shot) and open(shot, "rb").read(8) == b"\x89PNG\r\n\x1a\n"
        check("screenshot saved via bridge (PNG)", ok, json.dumps(r)[:200])
        r = http("POST", "/command", {"cmd": "screenshot"})[1]
        check("screenshot base64 PNG", r["ok"] and base64.b64decode(r["result"]["data_base64"])[:4] == b"\x89PNG", f"{len(r['result']['data_base64'])} b64 chars" if r["ok"] else json.dumps(r))
        if r["ok"]:
            open(os.path.join(ROOT, "test", "last_screenshot.png"), "wb").write(base64.b64decode(r["result"]["data_base64"]))

        r = http("POST", "/command", {"cmd": "type", "index": q, "text": "hello bridge", "submit": True})[1]
        check("type + submit", r["ok"] and "result.html?q=hello+bridge" in r["result"]["url"], json.dumps(r))
        r = cli({"cmd": "get_page"})
        check("CLI send get_page after submit", "You searched for: hello bridge" in r["result"]["text"], r["result"]["text"][:80])

        out = subprocess.run([os.path.join(ROOT, "client", "gbb"), "get_page", "max_chars=200"], env=env, capture_output=True, text=True).stdout
        check("client/gbb shorthand", json.loads(out)["result"]["title"] == "GBB Result", out.strip()[:120])
        out = subprocess.run([os.path.join(ROOT, "client", "gbb-curl.sh"), '{"cmd":"list_tabs"}'], env=env, capture_output=True, text=True).stdout
        check("client/gbb-curl.sh", json.loads(out)["ok"], out[:120])
        r = http("POST", "/command", {"cmd": "back"})[1]
        check("back", r["ok"] and r["result"]["url"].endswith("index.html"), json.dumps(r))
        r = http("POST", "/command", {"cmd": "type", "selector": "#q", "text": "via enter"})[1]
        r = http("POST", "/command", {"cmd": "press_key", "key": "Enter", "selector": "#q"})[1]
        time.sleep(0.5)
        r = http("POST", "/command", {"cmd": "get_page"})[1]
        check("press_key Enter (form submitted)", r["ok"] and "You searched for: via enter" in r["result"]["text"], json.dumps(r)[:200])
        if not NO_EVAL:
            r = http("POST", "/command", {"cmd": "eval", "expression": "document.getElementById('out') && document.getElementById('out').textContent"})[1]
            check("eval", r["ok"] and r["result"]["value"] == "You searched for: via enter", json.dumps(r))
        else:
            r = http("POST", "/command", {"cmd": "eval", "expression": "1+1"})[1]
            check("store build: eval command absent", not r["ok"] and "unknown cmd" in r["error"], json.dumps(r))
            check("store build: no eval toggle in popup", pop.evaluate("document.getElementById('allowEval') === null"))
        r = http("POST", "/command", {"cmd": "forward"})[1]; r = http("POST", "/command", {"cmd": "reload"})[1]
        check("forward/reload", r["ok"], json.dumps(r)[:150])

        r = http("POST", "/command", {"cmd": "navigate", "url": "http://127.0.0.1:8811/index.html"})[1]
        check("navigate", r["ok"] and r["result"]["title"] == "GBB Test Page")
        r = http("POST", "/command", {"cmd": "open_url", "url": "http://127.0.0.1:8811/result.html?q=tab2"})[1]
        t2 = r["result"]["tab_id"]
        r = http("POST", "/command", {"cmd": "list_tabs"})[1]
        check("list_tabs", r["ok"] and len(r["result"]["tabs"]) >= 2, str(len(r["result"]["tabs"])))
        r = http("POST", "/command", {"cmd": "activate_tab", "tab_id": tab})[1]
        check("activate_tab", r["ok"] and r["result"]["active"])
        r = http("POST", "/command", {"cmd": "close_tab", "tab_id": t2})[1]
        check("close_tab", r["ok"])
        r = http("POST", "/command", {"cmd": "nonsense"})[1]
        check("unknown cmd -> error", not r["ok"] and "unknown cmd" in r["error"])

        if os.environ.get("GBB_IDLE_TEST"):
            pop.close()   # no extension page open -> service worker must survive on its own
            print("   idling 75s to test MV3 service-worker keep-alive…"); time.sleep(75)
            r = http("POST", "/command", {"cmd": "ping"})[1]
            check("still connected after 75s idle", r.get("ok"), json.dumps(r))
            r = http("POST", "/command", {"cmd": "open_url", "url": "https://example.com"})[1]
            g = http("POST", "/command", {"cmd": "get_page"})[1]; check("real website (example.com) get_page", r.get("ok") and "Example Domain" in json.dumps(g), json.dumps(g)[:400])
            pop = ctx.new_page(); pop.goto(f"chrome-extension://{ext_id}/popup.html")
        if not NO_EVAL:
          # eval toggle off via popup
          pop.evaluate("document.getElementById('allowEval').click()"); time.sleep(1.5)
          for _ in range(20):
              if http("GET", "/status")[1]["extension_connected"]: break
              time.sleep(0.5)
          r = http("POST", "/command", {"cmd": "eval", "expression": "1+1"})[1]
          check("eval blocked when toggled off", not r["ok"] and "disabled" in r.get("error", ""), json.dumps(r))
        # turning extension off -> bridge sees disconnect
        pop.evaluate("document.getElementById('enabled').click()"); time.sleep(1)
        # (connected flag has a grace window; a command should then time out instead of running)
        st = http("GET", "/status")[1]
        check("bridge sees extension switched off", st["extension_connected"] is False, json.dumps(st))
        code, r = http("POST", "/command", {"cmd": "list_tabs"})
        check("command refused while off (503)", code == 503, json.dumps(r))
        badge = sw.evaluate("chrome.action.getBadgeText({})")
        check("badge cleared when off", badge == "", repr(badge))
        ctx.close()
finally:
    bridge.terminate(); site.terminate(); uploads.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)

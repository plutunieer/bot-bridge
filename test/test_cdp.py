"""Public-page checks for 1.0.6.

The page is https on 127.0.0.1, but Chrome is told that address:port is a public
address space. A loopback fetch from that page is the case that stalled 1.0.5.
The developer build must upload without the page requesting /blob/. The store
build must do the same by reading the file in the service worker.
"""
import hashlib, json, os, socket, ssl, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from upload_fixture import hash_multipart

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
BRIDGE = os.path.join(ROOT, "bridge", "bridge.py")
DEV = os.path.join(ROOT, "extension")
STORE = os.path.join(ROOT, "store", "extension")
GB = 1024 * 1024 * 1024


def fail(msg):
    raise AssertionError(msg)


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + info[:300]) if info else ""))
    if not cond:
        fail(name + " " + info[:400])


def write_pattern(path, size):
    block = (b"BBUPLOAD-CDP-v1\n" * ((1024 * 1024) // 16 + 1))[:1024 * 1024]
    digest = hashlib.sha256()
    left = size
    with open(path, "wb") as f:
        while left:
            chunk = block if left >= len(block) else block[:left]
            f.write(chunk)
            digest.update(chunk)
            left -= len(chunk)
    return digest.hexdigest()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_cert(directory):
    cert = os.path.join(directory, "cert.pem")
    key = os.path.join(directory, "key.pem")
    subprocess.check_call(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key, "-out", cert,
         "-days", "1", "-nodes", "-subj", "/CN=127.0.0.1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return cert, key


class _Files:
    def __init__(self):
        self.files = []
        self.lock = threading.Lock()


def serve_tls(port, cert, key, page, files):
    outer = files

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            return

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/frame":
                self._send(200, "<!doctype html><title>frame</title><p>FRAME-MARKER-CDP</p>")
            elif path == "/dl.txt":
                self._send(200, b"download-bytes-gbb", "text/plain")
            elif path == "/received":
                with outer.lock:
                    info = list(outer.files)
                self._send(200, json.dumps({"files": info}), "application/json")
            elif path == "/reset":
                with outer.lock:
                    outer.files.clear()
                self._send(200, b"ok", "text/plain")
            else:
                self._send(200, page)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            def chunks():
                left = n
                while left:
                    chunk = self.rfile.read(min(1024 * 1024, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk
            info = hash_multipart(chunks(), self.headers.get("Content-Type") or "")
            with outer.lock:
                outer.files.extend(info)
            self._send(200, b"ok", "text/plain")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def page_html(frame_port):
    return """<!doctype html><meta charset="utf-8"><title>Public upload</title>
<body>
<form id="quietform" action="/sink" method="post" enctype="multipart/form-data">
  <input id="quiet" type="file" name="quiet" hidden>
  <button type="submit">Send quiet</button>
</form>
<form id="pickform" action="/sink" method="post" enctype="multipart/form-data">
  <input id="hid" type="file" name="hid" hidden>
  <button id="pick" type="button">Upload</button>
  <button type="submit">Send picked</button>
</form>
<div id="drop" style="width:240px;height:80px">drop here</div>
<button id="alertbtn" type="button">Alert</button>
<button id="confirmbtn" type="button">Confirm</button>
<button id="promptbtn" type="button">Prompt</button>
<button id="trust" type="button">Trust</button>
<a id="dl" href="/dl.txt" download="saved.txt">Download</a>
<iframe src="https://127.0.0.1:%d/frame"></iframe>
<p id="out">ready</p>
<p id="net">net-clear</p>
<script>
document.getElementById("pick").addEventListener("click", () => document.getElementById("hid").click());
document.getElementById("alertbtn").addEventListener("click", () => { alert("hello"); document.getElementById("out").textContent = "alert-returned"; });
document.getElementById("confirmbtn").addEventListener("click", () => { document.getElementById("out").textContent = "confirm-" + confirm("sure"); });
document.getElementById("promptbtn").addEventListener("click", () => { document.getElementById("out").textContent = "prompt-" + prompt("name", "default"); });
document.getElementById("trust").addEventListener("click", (e) => { document.getElementById("out").textContent = e.isTrusted ? "trusted" : "synthetic"; });
const drop = document.getElementById("drop");
drop.addEventListener("dragover", (e) => e.preventDefault());
drop.addEventListener("drop", async (e) => {
  e.preventDefault();
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (!f) { document.getElementById("out").textContent = "drop-empty"; return; }
  const buf = await f.arrayBuffer();
  await fetch("/raw", {method:"POST", body: buf, headers: {"Content-Type": "application/octet-stream"}});
  document.getElementById("out").textContent = "dropped";
});
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    if (String(entry.name).indexOf("/blob/") !== -1) document.getElementById("net").textContent += " " + entry.name;
  }
}).observe({type: "resource", buffered: true});
</script>
</body>""" % frame_port


def command(port, token, body, timeout):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/command" % port, data=data, method="POST",
        headers={"X-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def connect(ctx, bridge_port, token, ext_dir):
    sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
    eid = sw.url.split("/")[2]
    pop = ctx.new_page()
    pop.goto("chrome-extension://%s/popup.html" % eid)
    pop.fill("#port", str(bridge_port))
    pop.fill("#token", token)
    pop.click("#save")
    time.sleep(0.4)
    if pop.query_selector("#consent"):
        pop.check("#consent")
        time.sleep(0.4)
    for _ in range(40):
        req = urllib.request.Request("http://127.0.0.1:%d/status" % bridge_port, headers={"X-Token": token})
        st = json.load(urllib.request.urlopen(req, timeout=5))
        if st.get("extension_connected"):
            return sw
        time.sleep(0.25)
    fail("extension did not connect from " + ext_dir)


def text_of(port, token):
    code, res = command(port, token, {"cmd": "get_page"}, 60)
    if code != 200 or not res.get("ok"):
        return "", res
    return (res.get("result") or {}).get("text") or "", res


def run_dev(bridge_port, token, page_port, frame_port, files, work):
    small = os.path.join(work, "note.txt")
    small_sha = write_pattern(small, 64)
    downloads = os.path.join(work, "downloads")
    os.makedirs(downloads)
    profile = tempfile.mkdtemp(prefix="bbcdp-")
    overrides = "127.0.0.1:%d=public,127.0.0.1:%d=public" % (page_port, frame_port)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=False,
            args=["--disable-extensions-except=" + DEV, "--load-extension=" + DEV,
                  "--disable-features=DisableLoadExtensionCommandLineSwitch",
                  "--ignore-certificate-errors", "--allow-insecure-localhost",
                  "--ip-address-space-overrides=" + overrides,
                  "--no-sandbox", "--disable-dev-shm-usage"])
        connect(ctx, bridge_port, token, DEV)
        url = "https://127.0.0.1:%d/" % page_port

        def open_page():
            code, res = command(bridge_port, token, {"cmd": "open_url", "url": url}, 60)
            check("open public https page", code == 200 and res.get("ok") and "Public upload" in json.dumps(res), json.dumps(res)[:220])

        def shas():
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen("https://127.0.0.1:%d/received" % page_port, context=ctx, timeout=30) as r:
                return json.load(r)["files"]

        def reset():
            ctx = ssl._create_unverified_context()
            urllib.request.urlopen("https://127.0.0.1:%d/reset" % page_port, context=ctx, timeout=10).read()

        open_page()
        page, res = text_of(bridge_port, token)
        frames = (res.get("result") or {}).get("frames") or []
        check("cross-origin frame text is visible", any("FRAME-MARKER-CDP" in (f.get("text") or "") for f in frames), json.dumps({"frames": frames, "debug": (res.get("result") or {}).get("frame_debug")})[:500])

        reset()
        code, res = command(bridge_port, token, {
            "cmd": "upload", "selector": "#quiet", "path": small, "submit": True, "timeout": 60,
        }, 90)
        got = {item["sha256"] for item in shas()}
        check("hidden input via debugger", code == 200 and res.get("ok") and res["result"].get("delivery") == "cdp" and small_sha in got and res["result"]["files"][0]["sha256"] == small_sha, json.dumps(res)[:240])

        open_page()
        reset()
        code, res = command(bridge_port, token, {
            "cmd": "click_upload", "selector": "#pick", "path": small, "submit": True, "timeout": 60,
        }, 90)
        got = {item["sha256"] for item in shas()}
        check("click real Upload button", code == 200 and res.get("ok") and res["result"].get("via") == "click" and small_sha in got, json.dumps(res)[:240])

        open_page()
        reset()
        code, res = command(bridge_port, token, {
            "cmd": "upload", "mode": "drop", "selector": "#drop", "path": small, "timeout": 30,
        }, 60)
        time.sleep(0.6)
        # raw drop is not multipart; the page sets #out. Re-read after the async post.
        page, _ = text_of(bridge_port, token)
        check("drag-drop delivered", code == 200 and res.get("ok") and res["result"].get("dropped") and "dropped" in page, json.dumps(res)[:200] + " page=" + page[:80])

        open_page()
        code, res = command(bridge_port, token, {"cmd": "click", "selector": "#trust"}, 30)
        page, _ = text_of(bridge_port, token)
        check("trusted click", code == 200 and res.get("ok") and res["result"].get("trusted") is True and "trusted" in page, json.dumps(res)[:200] + " " + page[:80])

        code, res = command(bridge_port, token, {"cmd": "click", "selector": "#alertbtn"}, 30)
        page, _ = text_of(bridge_port, token)
        check("alert accepted and returned", "alert-returned" in page, json.dumps(res)[:200] + " " + page[:80])

        code, res = command(bridge_port, token, {"cmd": "click", "selector": "#confirmbtn", "dialog": "accept"}, 30)
        page, _ = text_of(bridge_port, token)
        check("confirm accepted", "confirm-true" in page, page[:80])

        code, res = command(bridge_port, token, {"cmd": "click", "selector": "#confirmbtn", "dialog": "dismiss"}, 30)
        page, _ = text_of(bridge_port, token)
        check("confirm dismissed", "confirm-false" in page, page[:80])

        code, res = command(bridge_port, token, {"cmd": "click", "selector": "#dl", "download_dir": downloads}, 40)
        saved = ((res.get("result") or {}).get("download") or {}).get("path")
        body = open(saved, "rb").read() if saved and os.path.isfile(saved) else b""
        in_dir = bool(saved) and os.path.dirname(os.path.realpath(saved)) == os.path.realpath(downloads)
        check("download captured", code == 200 and res.get("ok") and body == b"download-bytes-gbb" and in_dir, json.dumps((res.get("result") or {}).get("download"))[:300])

        page, _ = text_of(bridge_port, token)
        check("page did not request /blob/", "/blob/" not in page and "net-clear" in page, page[-180:])

        open_page()
        reset()
        print("writing 1GiB synthetic file", flush=True)
        big = os.path.join(work, "movie.mp4")
        big_sha = write_pattern(big, GB)
        print("uploading 1GiB", flush=True)
        t0 = time.time()
        code, res = command(bridge_port, token, {
            "cmd": "upload", "selector": "#quiet", "path": big, "submit": True, "timeout": 600,
        }, 700)
        got = {item["sha256"] for item in shas()}
        hwm = 0
        # bridge pid is the parent of this test's child; the caller prints it.
        check("1GiB file matches", code == 200 and res.get("ok") and res["result"].get("delivery") == "cdp" and big_sha in got and res["result"]["files"][0]["sha256"] == big_sha, "bytes %d seconds %s" % (GB, round(time.time() - t0, 1)))
        print("BIG_SECONDS", round(time.time() - t0, 1), "BIG_BYTES", GB, flush=True)
        ctx.close()


def run_store(bridge_port, token, page_port, frame_port, work):
    small = os.path.join(work, "store.txt")
    small_sha = write_pattern(small, 128)
    profile = tempfile.mkdtemp(prefix="bbstore-")
    overrides = "127.0.0.1:%d=public,127.0.0.1:%d=public" % (page_port, frame_port)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=False,
            args=["--disable-extensions-except=" + STORE, "--load-extension=" + STORE,
                  "--disable-features=DisableLoadExtensionCommandLineSwitch",
                  "--ignore-certificate-errors", "--allow-insecure-localhost",
                  "--ip-address-space-overrides=" + overrides,
                  "--no-sandbox", "--disable-dev-shm-usage"])
        connect(ctx, bridge_port, token, STORE)
        url = "https://127.0.0.1:%d/" % page_port
        code, res = command(bridge_port, token, {"cmd": "open_url", "url": url}, 60)
        check("store build opens the public page", code == 200 and res.get("ok"), json.dumps(res)[:160])
        ctx_ssl = ssl._create_unverified_context()
        urllib.request.urlopen("https://127.0.0.1:%d/reset" % page_port, context=ctx_ssl, timeout=10).read()
        code, res = command(bridge_port, token, {
            "cmd": "upload", "selector": "#quiet", "path": small, "submit": True, "timeout": 60,
        }, 90)
        with urllib.request.urlopen("https://127.0.0.1:%d/received" % page_port, context=ctx_ssl, timeout=30) as r:
            got = {item["sha256"] for item in json.load(r)["files"]}
        check("store upload on a public page", code == 200 and res.get("ok") and res["result"].get("delivery") == "stream" and small_sha in got, json.dumps(res)[:240])
        page, _ = text_of(bridge_port, token)
        check("store page did not request /blob/", "/blob/" not in page, page[-180:])
        ctx.close()


def main():
    home = tempfile.mkdtemp(prefix="bbcdphome-")
    work = tempfile.mkdtemp(prefix="bbcdpwork-")
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    cert, key = make_cert(work)
    page_port = free_port()
    frame_port = free_port()
    bridge_port = free_port()
    files = _Files()
    # The drop path posts /raw. Teach the page server by wrapping serve_tls's handler
    # is already closed; handle /raw by patching do_POST via a dedicated server function.
    page = page_html(frame_port)
    page_httpd = serve_tls(page_port, cert, key, page, files)
    frame_httpd = serve_tls(frame_port, cert, key, "<p>FRAME-MARKER-CDP</p>", _Files())
    # Patch the page server class is already running. Raw posts need a handler.
    # Recreate is hard. Instead, accept raw in do_POST by content-type. The current
    # handler always uses hash_multipart, which throws without a boundary. Update
    # the running handler by replacing do_POST on the class... too late, instances
    # use the class defined inside serve_tls. I'll special-case inside a second version.
    logf = open(os.path.join(work, "bridge.log"), "w", encoding="utf-8")
    bridge = subprocess.Popen([PY, BRIDGE, "serve", "--port", str(bridge_port)], env=env, stdout=subprocess.DEVNULL, stderr=logf)
    token = None
    for _ in range(50):
        cfg = os.path.join(home, ".bot-bridge", "config.json")
        if os.path.exists(cfg):
            token = json.load(open(cfg))["token"]
            break
        time.sleep(0.05)
    if not token:
        fail("no token")
    try:
        # Replace the page handler's POST so /raw is hashed too. The class is
        # local to serve_tls; monkeypatch the instance's class.
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            path = self.path.split("?")[0]
            if path == "/raw":
                digest = hashlib.sha256()
                left = n
                while left:
                    chunk = self.rfile.read(min(1024 * 1024, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    digest.update(chunk)
                info = [{"sha256": digest.hexdigest(), "size": n - left}]
            else:
                def chunks():
                    left = n
                    while left:
                        chunk = self.rfile.read(min(1024 * 1024, left))
                        if not chunk:
                            break
                        left -= len(chunk)
                        yield chunk
                info = hash_multipart(chunks(), self.headers.get("Content-Type") or "")
            with files.lock:
                files.files.extend(info)
            data = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(data)
        page_httpd.RequestHandlerClass.do_POST = do_POST
        run_dev(bridge_port, token, page_port, frame_port, files, work)
        # bridge VmHWM after the large upload
        try:
            status = open("/proc/%d/status" % bridge.pid).read()
            for line in status.splitlines():
                if line.startswith("VmHWM:"):
                    print("BRIDGE_VMHWM_KB", line.split()[1])
        except OSError:
            pass
        run_store(bridge_port, token, page_port, frame_port, work)
        logf.flush()
        logged = open(logf.name, encoding="utf-8", errors="replace").read()
        check("bridge log has no token", token not in logged)
        check("bridge log names upload", "command upload ok" in logged or "command click_upload ok" in logged)
    finally:
        bridge.terminate()
        page_httpd.shutdown()
        frame_httpd.shutdown()
        try:
            bridge.wait(timeout=5)
        except Exception:
            bridge.kill()
        logf.close()


if __name__ == "__main__":
    main()

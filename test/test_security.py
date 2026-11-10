"""Security regressions for the bridge and the packaged store extension.

The fixture secrets below are fake. Assertions must not print them.
"""
import json, os, socket, stat, subprocess, sys, tempfile, textwrap, threading, time, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "bridge", "bridge.py")
PY = sys.executable
FIXTURE = "fixture-bridge-token-0123456789abcdef"
PASSWORD = "fixture-password-value"
TYPED = "fixture-typed-secret"


def redact(text, *secrets):
    out = text if isinstance(text, str) else text.decode("utf-8", "replace")
    for secret in secrets:
        if secret:
            out = out.replace(secret, "[redacted]")
    return out


def fail(message):
    raise AssertionError(message)


def assert_absent(blob, secret, where):
    text = blob if isinstance(blob, str) else blob.decode("utf-8", "replace")
    if secret and secret in text:
        fail(f"{where} contains the secret ({len(secret)} characters)")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def listeners(port):
    found = []
    port_hex = f"{port:04X}"
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            parts = line.split()
            if len(parts) < 4 or parts[3] != "0A":
                continue
            ip_hex, p_hex = parts[1].split(":")
            if p_hex.upper() == port_hex:
                found.append(ip_hex.upper())
    return found


def http_raw(port, method, path, token=None, host=None, origin=None, content_length=None, body=None, timeout=3):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        host = f"127.0.0.1:{port}" if host is None else host
        raw = body.encode() if isinstance(body, str) else body
        lines = [f"{method} {path} HTTP/1.1", f"Host: {host}"]
        if token is not None:
            lines.append(f"X-Token: {token}")
        if origin is not None:
            lines.append(f"Origin: {origin}")
        if raw is not None:
            lines.append(f"Content-Length: {len(raw)}")
        elif content_length is not None:
            lines.append(f"Content-Length: {content_length}")
        lines += ["Connection: close", "", ""]
        s.sendall("\r\n".join(lines).encode())
        if raw:
            s.sendall(raw)
        s.settimeout(timeout)
        data = b""
        try:
            while True:
                chunk = s.recv(8192)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            fail(f"{method} {path} timed out")
    finally:
        s.close()
    if not data.startswith(b"HTTP/"):
        fail("no HTTP status from " + path)
    status = int(data.split(b" ", 2)[1])
    return status, data


def extract_function(src, name):
    key = "function " + name + "("
    i = src.find(key)
    if i < 0:
        fail("missing function " + name)
    j = src.find("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    fail("unbalanced function " + name)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fail(name)
    return True


def test_serve_does_not_log_token():
    home = tempfile.mkdtemp(prefix="bbsec-")
    port = free_port()
    env = dict(os.environ, HOME=home, USERPROFILE=home, GBB_VERBOSE="1")
    cfg_dir = os.path.join(home, ".bot-bridge")
    os.makedirs(cfg_dir, 0o755)
    cfg_path = os.path.join(cfg_dir, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"token": FIXTURE, "port": port}, f)
    os.chmod(cfg_path, 0o644)
    proc = subprocess.Popen(
        [PY, BRIDGE, "serve", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    out_box, err_box = [], []
    threads = [
        threading.Thread(target=lambda: out_box.append(proc.stdout.read())),
        threading.Thread(target=lambda: err_box.append(proc.stderr.read())),
    ]
    for t in threads:
        t.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                status, _ = http_raw(port, "GET", "/status", token=FIXTURE, timeout=1)
                if status in (200, 401, 403):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            fail("bridge did not accept a connection")

        ext = "chrome-extension://" + ("a" * 32)
        check("loopback host and token -> 200", http_raw(port, "GET", "/status", token=FIXTURE)[0] == 200)
        check("localhost host -> 200", http_raw(port, "GET", "/status", token=FIXTURE, host=f"localhost:{port}")[0] == 200)
        check("missing token -> 401", http_raw(port, "GET", "/status")[0] == 401)
        check("wrong token -> 401", http_raw(port, "GET", "/status", token="not-the-token")[0] == 401)
        check("foreign host -> 403", http_raw(port, "GET", "/status", token=FIXTURE, host="evil.example")[0] == 403)
        check("host suffix -> 403", http_raw(port, "GET", "/status", token=FIXTURE, host="127.0.0.1.evil.example")[0] == 403)
        check("empty host -> 403", http_raw(port, "GET", "/status", token=FIXTURE, host="")[0] == 403)
        web = http_raw(port, "GET", "/status", token=FIXTURE, origin="https://evil.example")
        check("web origin rejected even with token -> 403", web[0] == 403)
        assert_absent(web[1], FIXTURE, "403 body")
        bad_ext = http_raw(port, "GET", "/status", token=FIXTURE, origin="chrome-extension://not-an-id")
        check("malformed extension origin -> 403", bad_ext[0] == 403)
        check("real extension origin -> 200", http_raw(port, "GET", "/status", token=FIXTURE, origin=ext)[0] == 200)
        check("OPTIONS -> 403", http_raw(port, "OPTIONS", "/status", token=FIXTURE)[0] == 403)
        blob_opt = http_raw(port, "OPTIONS", "/blob/abc", token=FIXTURE, origin="http://127.0.0.1:9")
        check(
            "blob preflight allows the page origin",
            blob_opt[0] == 204
            and b"Access-Control-Allow-Origin: http://127.0.0.1:9" in blob_opt[1]
            and b"Access-Control-Allow-Headers: X-Token, Content-Type" in blob_opt[1]
            and b"Access-Control-Allow-Private-Network: true" in blob_opt[1],
        )
        check("blob get without token -> 401", http_raw(port, "GET", "/blob/abc", origin="http://127.0.0.1:9")[0] == 401)
        check(
            "blob get with web origin still needs a real id -> 404",
            http_raw(port, "GET", "/blob/not-a-real-id", token=FIXTURE, origin="http://127.0.0.1:9")[0] == 404,
        )
        check(
            "command route still rejects a web origin",
            http_raw(port, "POST", "/command", token=FIXTURE, origin="http://127.0.0.1:9", content_length="0")[0] == 403,
        )
        unauth = http_raw(port, "GET", "/status")
        assert_absent(unauth[1], FIXTURE, "401 body")
        neg = http_raw(port, "POST", "/command", token=FIXTURE, content_length="-1")
        check("negative content-length -> 400", neg[0] == 400)
        code, _ = http_raw(port, "POST", "/command", token=FIXTURE, content_length="0")
        # body {} has no cmd; handler returns 400. Connection is up, so 503 is also possible
        # only when the extension is connected. It is not.
        check("unconnected command -> 400 or 503", code in (400, 503))
        bound = listeners(port)
        check("listens on 127.0.0.1", "0100007F" in bound)
        check("does not listen on 0.0.0.0", "00000000" not in bound)
        mode = stat.S_IMODE(os.stat(cfg_path).st_mode)
        dir_mode = stat.S_IMODE(os.stat(cfg_dir).st_mode)
        check("config file mode 600", mode == 0o600)
        check("config directory mode 700", dir_mode == 0o700)
        ping = http_raw(port, "POST", "/command", token=FIXTURE, body='{"cmd":"ping"}')
        check("disconnected command is 503", ping[0] == 503)
        # Close during the response so a vanished client does not traceback.
        drop = socket.create_connection(("127.0.0.1", port), timeout=3)
        drop.sendall(("GET /status HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Token: %s\r\nConnection: close\r\n\r\n" % (port, FIXTURE)).encode())
        drop.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for t in threads:
            t.join(timeout=5)
    stdout = out_box[0] if out_box else ""
    stderr = err_box[0] if err_box else ""
    assert_absent(stdout, FIXTURE, "serve stdout")
    assert_absent(stderr, FIXTURE, "serve stderr")
    check("startup says the token is not printed", "not printed on startup" in stdout)
    check("startup does not use the old Token label", "Token:" not in stdout)
    check("verbose request log has no secret", FIXTURE not in stderr)
    check("command log names the command and not the token", "command ping error" in stderr and FIXTURE not in stderr)
    check("closed client does not traceback", "Traceback" not in stderr)

    shown = subprocess.run([PY, BRIDGE, "token"], env=env, capture_output=True, text=True)
    check("token command returns the token", shown.stdout.strip() == FIXTURE)
    assert_absent(shown.stderr, FIXTURE, "token stderr")

    rotated = subprocess.run([PY, BRIDGE, "new-token"], env=env, capture_output=True, text=True)
    new_token = rotated.stdout.strip()
    check("new-token returns a different token", bool(new_token) and new_token != FIXTURE)
    check("new-token warns about logs", "service log" in rotated.stderr)
    port2 = free_port()
    proc2 = subprocess.Popen(
        [PY, BRIDGE, "serve", "--port", str(port2)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if http_raw(port2, "GET", "/status", token=new_token, timeout=1)[0] == 200:
                    break
            except OSError:
                time.sleep(0.05)
        else:
            fail("rotated bridge did not accept a connection")
    finally:
        proc2.terminate()
        try:
            out2, err2 = proc2.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc2.kill()
            out2, err2 = proc2.communicate(timeout=5)
    assert_absent(out2, new_token, "serve stdout after rotation")
    assert_absent(err2, new_token, "serve stderr after rotation")
    assert_absent(out2, FIXTURE, "serve stdout old token")
    check("rotated serve still withholds the token", "not printed on startup" in out2)


def test_legacy_config_dir():
    home = tempfile.mkdtemp(prefix="bblegacy-")
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    legacy = os.path.join(home, ".grok-chrome-bridge")
    os.makedirs(legacy)
    with open(os.path.join(legacy, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"token": FIXTURE, "port": 8765}, f)
    shown = subprocess.run([PY, BRIDGE, "token"], env=env, capture_output=True, text=True)
    check("legacy config token still readable", shown.stdout.strip() == FIXTURE)
    assert_absent(shown.stderr, FIXTURE, "legacy token stderr")


def test_curl_argv_has_no_token():
    home = tempfile.mkdtemp(prefix="bbcurl-")
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    cfg = os.path.join(home, ".bot-bridge")
    os.makedirs(cfg)
    with open(os.path.join(cfg, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"token": FIXTURE, "port": 9}, f)
    bindir = tempfile.mkdtemp(prefix="bbbin-")
    captured = os.path.join(bindir, "argv.txt")
    fake = os.path.join(bindir, "curl")
    with open(fake, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURE\"\nexit 0\n")
    os.chmod(fake, 0o755)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    env["CAPTURE"] = captured
    script = os.path.join(ROOT, "client", "gbb-curl.sh")
    os.chmod(script, 0o755)
    subprocess.run([script, "status"], env=env, capture_output=True, text=True, check=True)
    argv = open(captured, encoding="utf-8").read()
    assert_absent(argv, FIXTURE, "curl argv")
    check("curl receives a config file", "--config" in argv)
    # The header file is removed after curl returns. The fake curl can see it
    # only while running; assert the script itself does not expand the token into -H.
    source = open(script, encoding="utf-8").read()
    check("curl script does not pass X-Token on the command line", 'X-Token: $TOKEN' not in source and "X-Token: ${TOKEN}" not in source)


def test_navigation_and_consent_logic():
    src = open(os.path.join(ROOT, "extension", "background.js"), encoding="utf-8").read()
    store = open(os.path.join(ROOT, "store", "extension", "background.js"), encoding="utf-8").read()
    nav = extract_function(src, "normalizeNavigationUrl")
    consent = extract_function(src, "consentOk")
    part_nav = nav + """
const cases = [
  ['https://example.com/a', true],
  ['http://127.0.0.1/x', true],
  ['file:///tmp/a', true],
  ['about:blank', true],
  ['javascript:alert(1)', false],
  ['data:text/html,hi', false],
  ['chrome://settings', false],
  ['about:srcdoc', false],
];
for (const [url, ok] of cases) {
  let threw = false;
  try { normalizeNavigationUrl(url); } catch (e) { threw = true; }
  if (threw === ok) process.exit(1);
}
console.log('nav-ok');
"""
    scenarios = """
const REQUIRED_CONSENT_VERSION = 3;
function check(defaults, state, expect) {
  const DEFAULTS = defaults;
  const cfg = state;
  %s
  if (consentOk() !== expect) process.exit(1);
}
check({ consent: false, consentVersion: 0 }, { consent: true, consentVersion: 0 }, false);
check({ consent: false, consentVersion: 0 }, { consent: true, consentVersion: 3 }, true);
check({ consent: false, consentVersion: 0 }, { consent: false, consentVersion: 3 }, false);
check({ port: 8765, enabled: true, allowEval: true }, { enabled: true }, true);
console.log('consent-ok');
""" % consent
    r1 = subprocess.run(["node", "-e", part_nav], capture_output=True, text=True)
    check("navigation scheme allowlist", r1.returncode == 0 and "nav-ok" in r1.stdout)
    r2 = subprocess.run(["node", "-e", scenarios], capture_output=True, text=True)
    if r2.returncode != 0:
        sys.stderr.write(r2.stderr)
    check("consent version gate", r2.returncode == 0 and "consent-ok" in r2.stdout)
    check("store build requires consent version", "consentVersion === REQUIRED_CONSENT_VERSION" in store)
    check("store defaults withhold consent", "consent: false, consentVersion: 0" in store)
    popup = open(os.path.join(ROOT, "store", "extension", "popup.js"), encoding="utf-8").read()
    check("popup saves the same consent version", "const CONSENT_VERSION = 3;" in popup and "REQUIRED_CONSENT_VERSION = 3" in store)
    dev = open(os.path.join(ROOT, "extension", "background.js"), encoding="utf-8").read()
    dev_popup = open(os.path.join(ROOT, "extension", "popup.js"), encoding="utf-8").read()
    dev_manifest = json.load(open(os.path.join(ROOT, "extension", "manifest.json"), encoding="utf-8"))
    check("developer build requests debugger", "debugger" in dev_manifest.get("permissions", []))
    check("developer consent is version 4", "REQUIRED_CONSENT_VERSION = 4" in dev and "const CONSENT_VERSION = 4;" in dev_popup)
    page_upload = extract_function(store, "pageUpload")
    check("page upload does not fetch loopback", "127.0.0.1" not in page_upload and "fetch(" not in page_upload)


def test_password_masking_in_packaged_handlers():
    store_js = open(os.path.join(ROOT, "store", "extension", "background.js"), encoding="utf-8").read()
    funcs = "\n".join(extract_function(store_js, name) for name in ("pageGetPage", "pageClick", "pageType"))
    html = """<!doctype html><meta charset="utf-8"><title>mask</title>
<body>
<input id="pw" type="password" name="pw" value="@@PASSWORD@@">
<input id="ac" name="ac" type="text" autocomplete="current-password" value="fixture-autocomplete-secret">
<input id="otp" type="text" name="otp" autocomplete="one-time-code" value="fixture-otp-123456">
<input id="plain" type="text" name="q" value="hello">
<p id="visible">visible-page-marker</p>
<script>
@@FUNCS@@
const page = pageGetPage(5000, 50);
const pw = page.elements.find((e) => e.name === "pw");
const ac = page.elements.find((e) => e.name === "ac");
const otp = page.elements.find((e) => e.name === "otp");
const plain = page.elements.find((e) => e.name === "q");
const clickPw = pageClick(pw.index, null);
const typed = pageType(pw.index, null, "@@TYPED@@", true, false);
const out = {
  pw, ac, otp, plain,
  click: clickPw,
  typed,
  pageTextHasMarker: page.text.includes("visible-page-marker"),
  pageTextHasPassword: page.text.includes("@@PASSWORD@@"),
};
document.body.replaceChildren();
const pre = document.createElement("pre");
pre.id = "out";
pre.textContent = JSON.stringify(out);
document.body.appendChild(pre);
</script>
</body>"""
    html = html.replace("@@FUNCS@@", funcs).replace("@@PASSWORD@@", PASSWORD).replace("@@TYPED@@", TYPED)
    work = tempfile.mkdtemp(prefix="bbmask-")
    path = os.path.join(work, "mask.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    # Chrome prints the DOM and then may not exit in this environment. Kill it after the dump.
    proc = subprocess.Popen(
        ["google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
         "--user-data-dir=" + os.path.join(work, "profile"), "--dump-dom", "file://" + path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except ProcessLookupError:
            pass
        stdout, _ = proc.communicate()
    if 'id="out"' not in (stdout or ""):
        fail("chrome masking run produced no result")
    start = stdout.find('id="out"')
    snippet = stdout[start:stdout.find("</pre>", start)]
    # textContent is escaped in dump-dom. Parse the JSON from the element text.
    raw = snippet.split(">", 1)[1]
    raw = raw.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    data = json.loads(raw)
    blob = json.dumps(data)
    assert_absent(blob, PASSWORD, "masked page result")
    assert_absent(blob, "fixture-autocomplete-secret", "autocomplete password result")
    assert_absent(blob, TYPED, "type result")
    check("password value masked", data["pw"]["value"] == "•••" and data["pw"]["text"] == "•••")
    check("autocomplete password masked", data["ac"]["value"] == "•••" and data["ac"]["text"] == "•••")
    check("password click masked", data["click"]["text"] == "•••")
    check("password type result masked", data["typed"]["value"] == "•••" and data["typed"]["typed"] is True)
    check("otp field is not universally masked", data["otp"]["value"] == "fixture-otp-123456")
    check("ordinary field still returned", data["plain"]["value"] == "hello")
    check("visible page text is not redacted", data["pageTextHasMarker"] is True and data["pageTextHasPassword"] is False)


def test_packaged_store_has_no_remote_code():
    zp = os.path.join(ROOT, "dist", "extension-store.zip")
    check("store zip exists", os.path.isfile(zp))
    bad = ("eval(", "(0, eval)", "new Function", "allowEval", "pageEval", "importScripts")
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        check("manifest at zip root", "manifest.json" in names)
        manifest = json.loads(z.read("manifest.json"))
        check("package version 1.0.6", manifest.get("version") == "1.0.6")
        check("store build has no debugger permission", "debugger" not in manifest.get("permissions", []))
        check("store build has no downloads permission", "downloads" not in manifest.get("permissions", []))
        check("no activeTab in store manifest", "activeTab" not in manifest.get("permissions", []))
        joined = []
        for info in z.infolist():
            if info.filename.endswith((".js", ".html", ".json")):
                text = z.read(info).decode("utf-8")
                joined.append(text)
                for needle in bad:
                    if needle in text:
                        fail("packaged file contains " + needle)
        blob = "\n".join(joined)
    check("packaged handlers and consent are present", "function pageGetPage" in blob and "function pageUpload" in blob and "REQUIRED_CONSENT_VERSION = 3" in blob)
    check("packaged popup states off-device processing", "off this device" in blob and "ausserhalb des Geräts" in blob)
    check("old absolute no-server sentence is gone", "Nothing is sent to the developer or any server" not in blob)
    dev = open(os.path.join(ROOT, "extension", "background.js"), encoding="utf-8").read()
    check("developer build still has optional eval", "function pageEval" in dev and 'case "eval"' in dev)
    bridge = open(BRIDGE, encoding="utf-8").read()
    check("bridge source has no startup token print", 'print("Token:' not in bridge and "Token: %s" not in bridge)
    root_policy = open(os.path.join(ROOT, "privacy-policy.html"), encoding="utf-8").read()
    store_policy = open(os.path.join(ROOT, "store", "privacy-policy.html"), encoding="utf-8").read()
    check("privacy policy copies match", root_policy == store_policy)
    check("policy names Limited Use", "Limited Use" in root_policy and "127.0.0.1" in root_policy)
    check("policy does not say nowhere else", "nowhere else" not in root_policy and "nirgendwohin sonst" not in root_policy)


def main():
    test_serve_does_not_log_token()
    test_legacy_config_dir()
    test_curl_argv_has_no_token()
    test_navigation_and_consent_logic()
    test_password_masking_in_packaged_handlers()
    test_packaged_store_has_no_remote_code()
    print("all security checks passed")


if __name__ == "__main__":
    main()

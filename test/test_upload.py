"""Path, auth, and size checks for upload. Browser byte checks live in e2e_test.py.

Fixture secrets and file markers are fake. Assertions must not print file bytes.
"""
import hashlib, json, os, socket, stat, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "bridge", "bridge.py")
PY = sys.executable
MARKER = "BBUPLOAD-MARKER-9f3c"


def fail(message):
    raise AssertionError(message)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fail(name)


def load_bridge(home):
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    import importlib.util
    spec = importlib.util.spec_from_file_location("bb_bridge_upload_" + str(os.getpid()), BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http(port, token, body, timeout=3):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Token"] = token
    req = urllib.request.Request("http://127.0.0.1:%d/command" % port, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw or b"{}"), raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw or b"{}"), raw


def test_stage_rules():
    home = tempfile.mkdtemp(prefix="bbup-")
    mod = load_bridge(home)
    folder = tempfile.mkdtemp(prefix="bbfiles-")
    small = os.path.join(folder, "note.txt")
    payload = (MARKER + "-small").encode()
    with open(small, "wb") as f:
        f.write(payload)
    staged = mod.stage_upload_files({"path": small})
    check("opens a named file without embedding bytes", staged[0]["size"] == len(payload) and staged[0]["name"] == "note.txt" and "data_base64" not in staged[0] and staged[0].get("id"))
    mod.release_staged(staged)
    try:
        mod.stage_upload_files({"path": folder})
        fail("directory was accepted")
    except ValueError as e:
        check("directory refused", "not a regular file" in str(e) and MARKER not in str(e))
    try:
        mod.stage_upload_files({"path": os.path.join(folder, "missing.bin")})
        fail("missing file was accepted")
    except ValueError as e:
        check("missing file refused", "cannot open" in str(e))
    try:
        mod.stage_upload_files({})
        fail("upload without a path was accepted")
    except ValueError as e:
        check("path required", "path or paths required" in str(e))
    bigger = os.path.join(folder, "over-limit.bin")
    with open(bigger, "wb") as f:
        f.write(b"x" * 50)
    t0 = time.time()
    try:
        mod.stage_upload_files({"path": bigger}, limit=20)
        fail("configured limit was ignored")
    except ValueError as e:
        check("configured limit refused without a default ceiling", "max_upload_bytes" in str(e) and (time.time() - t0) < 2)
    unlimited = mod.stage_upload_files({"path": bigger})
    check("default stage has no size ceiling", unlimited[0]["size"] == 50)
    mod.release_staged(unlimited)
    link = os.path.join(folder, "link.txt")
    os.symlink(small, link)
    linked = mod.stage_upload_files({"path": link})
    check("symlink resolves and is reported", linked[0]["real_path"] == os.path.realpath(small) and linked[0]["requested_path"] == link)
    mod.release_staged(linked)
    many = {"paths": [small] * (mod.MAX_UPLOAD_FILES + 1)}
    try:
        mod.stage_upload_files(many)
        fail("too many files accepted")
    except ValueError as e:
        check("file count cap is not a size cap", "too many files" in str(e))
    # Caller-supplied bytes are not a path and are ignored.
    try:
        mod.stage_upload_files({"data_base64": "AAAA", "files": [{"data_base64": "AAAA"}]})
        fail("bytes without a path were accepted")
    except ValueError as e:
        check("embedded bytes are not a read API", "path or paths required" in str(e))


def test_refused_command_does_not_read():
    home = tempfile.mkdtemp(prefix="bbuphttp-")
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    port = 0
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen([PY, BRIDGE, "serve", "--port", str(port)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        token = None
        for _ in range(50):
            cfg = os.path.join(home, ".bot-bridge", "config.json")
            if os.path.exists(cfg):
                token = json.load(open(cfg))["token"]
                break
            time.sleep(0.05)
        if not token:
            fail("bridge did not write a config")
        folder = tempfile.mkdtemp(prefix="bbupfiles-")
        marked = os.path.join(folder, "marked.bin")
        with open(marked, "wb") as f:
            f.write(MARKER.encode() + b"\n" + os.urandom(32))
        fifo = os.path.join(folder, "block.fifo")
        os.mkfifo(fifo)
        t0 = time.time()
        code, body, raw = http(port, token, {"cmd": "upload", "path": fifo})
        check("disconnected upload does not open the path", code == 503 and (time.time() - t0) < 2)
        code, body, raw = http(port, token, {"cmd": "upload", "path": marked})
        check("disconnected upload of a real file is 503", code == 503)
        check("503 body has no file marker", MARKER not in raw.decode("utf-8", "replace"))
        t0 = time.time()
        code, body, raw = http(port, None, {"cmd": "upload", "path": marked})
        check("upload without token is 401", code == 401 and (time.time() - t0) < 2)
        check("401 body has no file marker", MARKER not in raw.decode("utf-8", "replace"))
        mode = stat.S_IMODE(os.stat(os.path.join(home, ".bot-bridge", "config.json")).st_mode)
        check("config stays mode 600", mode == 0o600)
    finally:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=5)
        if MARKER in (out or "") or MARKER in (err or ""):
            fail("serve log contained file bytes")
        check("serve log has no file marker", True)


def _serve(home):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    proc = subprocess.Popen([PY, BRIDGE, "serve", "--port", str(port)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    token = None
    for _ in range(50):
        cfg = os.path.join(home, ".bot-bridge", "config.json")
        if os.path.exists(cfg):
            token = json.load(open(cfg))["token"]
            break
        time.sleep(0.05)
    if not token:
        proc.kill()
        fail("bridge did not write a config")
    return proc, port, token


def _poll_once(port, token, timeout=30):
    req = urllib.request.Request("http://127.0.0.1:%d/next" % port, headers={"X-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.status != 200 or not raw:
                return None
            return json.loads(raw)
    except Exception:
        return None


def _post_result(port, token, item_id, ok, error=None):
    body = {"id": item_id, "ok": ok, "result": {"set": True} if ok else None, "error": error}
    data = json.dumps(body).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/result" % port, data=data, method="POST", headers={"X-Token": token, "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def test_stream_limit_and_cancel():
    home = tempfile.mkdtemp(prefix="bbstream-")
    proc, port, token = _serve(home)
    folder = tempfile.mkdtemp(prefix="bbstreamfiles-")
    payload = (MARKER + "-stream").encode()
    path = os.path.join(folder, "stream.bin")
    with open(path, "wb") as f:
        f.write(payload)
    try:
        cfg_path = os.path.join(home, ".bot-bridge", "config.json")
        cfg = json.load(open(cfg_path))
        cfg["max_upload_bytes"] = 4
        json.dump(cfg, open(cfg_path, "w"))
        # Keep the extension "connected" without reading a file on the 503 path.
        holder = {}
        def stay():
            holder["item"] = _poll_once(port, token, timeout=20)
        threading.Thread(target=stay, daemon=True).start()
        time.sleep(0.3)
        code, body, raw = http(port, token, {"cmd": "upload", "path": path, "selector": "#file"}, timeout=10)
        check("connected command honors max_upload_bytes", code == 400 and "max_upload_bytes" in body.get("error", ""))
        check("limit error has no file marker", MARKER not in raw.decode("utf-8", "replace"))
        cfg["max_upload_bytes"] = 0
        json.dump(cfg, open(cfg_path, "w"))
        box = {}
        def do_upload():
            box["res"] = http(port, token, {"cmd": "upload", "path": path, "selector": "#file"}, timeout=20)
        threading.Thread(target=do_upload, daemon=True).start()
        item = None
        for _ in range(40):
            item = holder.get("item") or _poll_once(port, token, timeout=5)
            if item and item.get("command", {}).get("cmd") == "upload":
                break
            time.sleep(0.1)
        if not item:
            fail("extension poll did not receive the upload")
        fid = item["command"]["files"][0]["id"]
        req = urllib.request.Request("http://127.0.0.1:%d/blob/%s" % (port, fid), headers={"X-Token": token})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
        check("streamed bytes match the file", data == payload)
        _post_result(port, token, item["id"], True)
        for _ in range(40):
            if "res" in box:
                break
            time.sleep(0.05)
        res = box["res"]
        check("result sha256 matches and has no bytes", res[0] == 200 and res[1]["result"]["files"][0]["sha256"] == hashlib.sha256(payload).hexdigest() and MARKER not in res[2].decode("utf-8", "replace"))
        again = urllib.request.Request("http://127.0.0.1:%d/blob/%s" % (port, fid), headers={"X-Token": token})
        try:
            urllib.request.urlopen(again, timeout=5).read()
            fail("blob could be downloaded twice")
        except urllib.error.HTTPError as e:
            check("finished blob is not readable again", e.code == 404)

        # Interrupted transfer: read a prefix, drop the socket, then the session is gone.
        big = os.path.join(folder, "partial.bin")
        with open(big, "wb") as f:
            f.write(b"A" * (2 * 1024 * 1024))
        box2 = {}
        def do_partial():
            box2["res"] = http(port, token, {"cmd": "upload", "path": big, "selector": "#file", "timeout": 30}, timeout=40)
        threading.Thread(target=do_partial, daemon=True).start()
        item2 = None
        for _ in range(50):
            item2 = _poll_once(port, token, timeout=5)
            if item2 and item2.get("command", {}).get("cmd") == "upload":
                break
        fid2 = item2["command"]["files"][0]["id"]
        raw_sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        raw_sock.sendall(("GET /blob/%s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Token: %s\r\nConnection: close\r\n\r\n" % (fid2, port, token)).encode())
        raw_sock.recv(65536)
        raw_sock.close()
        time.sleep(0.3)
        _post_result(port, token, item2["id"], False, "interrupted")
        for _ in range(40):
            if "res" in box2:
                break
            time.sleep(0.05)
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/blob/%s" % (port, fid2), headers={"X-Token": token}), timeout=5).read()
            fail("interrupted blob was still readable")
        except urllib.error.HTTPError as e:
            check("interrupted blob is cleaned up", e.code == 404)
        fds = os.listdir("/proc/%d/fd" % proc.pid)
        check("bridge did not keep a descriptor per cancelled upload", len(fds) < 40)
    finally:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=5)
        if MARKER in (out or "") or MARKER in (err or ""):
            fail("stream test log contained file bytes")


def test_client_waits_longer_than_the_bridge():
    home = tempfile.mkdtemp(prefix="bbwait-")
    mod = load_bridge(home)
    check("upload client outlives the bridge", mod._client_timeout({"cmd": "upload"}) == mod._command_timeout({"cmd": "upload"}) + 60)
    check("click_upload uses the upload wait", mod._command_timeout({"cmd": "click_upload", "timeout": 10}) == 10)
    check("click_upload client keeps a margin", mod._client_timeout({"cmd": "click_upload", "timeout": 10}) == 70)
    check("ordinary command stays short", mod._command_timeout({"cmd": "ping"}) == mod.DEFAULT_TIMEOUT)
    check("broken pipe is a quiet client error", mod._client_gone(BrokenPipeError()) and mod._client_gone(ConnectionResetError()))
    check("other errors are not treated as a hung-up client", not mod._client_gone(ValueError("no")))


def main():
    test_stage_rules()
    test_refused_command_does_not_read()
    test_stream_limit_and_cancel()
    test_client_waits_longer_than_the_bridge()
    print("upload constraint checks passed")


if __name__ == "__main__":
    main()

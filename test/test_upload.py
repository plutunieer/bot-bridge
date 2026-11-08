"""Path, auth, and size checks for upload. Browser byte checks live in e2e_test.py.

Fixture secrets and file markers are fake. Assertions must not print file bytes.
"""
import hashlib, json, os, socket, stat, subprocess, sys, tempfile, time, urllib.error, urllib.request

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
    check("reads a named regular file", staged[0]["sha256"] == hashlib.sha256(payload).hexdigest())
    check("reports size and base name", staged[0]["size"] == len(payload) and staged[0]["name"] == "note.txt")
    check("does not keep the marker only in the hash", MARKER not in staged[0]["sha256"])
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
    big = os.path.join(folder, "too-big.bin")
    with open(big, "wb") as f:
        f.seek(mod.MAX_UPLOAD_BYTES)
        f.write(b"x")
    t0 = time.time()
    try:
        mod.stage_upload_files({"path": big})
        fail("oversized file was accepted")
    except ValueError as e:
        check("oversized file refused without reading it all", "too large" in str(e) and (time.time() - t0) < 2)
    link = os.path.join(folder, "link.txt")
    os.symlink(small, link)
    linked = mod.stage_upload_files({"path": link})
    check("symlink resolves and is reported", linked[0]["real_path"] == os.path.realpath(small) and linked[0]["requested_path"] == link)
    check("symlink bytes match the target", linked[0]["sha256"] == hashlib.sha256(payload).hexdigest())
    many = [{"paths": [small] * (mod.MAX_UPLOAD_FILES + 1)}]
    try:
        mod.stage_upload_files(many[0])
        fail("too many files accepted")
    except ValueError as e:
        check("file count cap", "too many files" in str(e))
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


def main():
    test_stage_rules()
    test_refused_command_does_not_read()
    print("upload constraint checks passed")


if __name__ == "__main__":
    main()

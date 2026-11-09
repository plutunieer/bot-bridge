"""Large-file upload. Generates synthetic bytes; does not use personal media.

Reports the size actually transferred and the peak RSS of the bridge and Chrome.
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from playwright.sync_api import sync_playwright
from upload_fixture import UploadFixture

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "bridge", "bridge.py")
EXT = os.path.join(ROOT, "store", "extension")
PY = sys.executable
# Just under 2 GiB so a signed 32-bit boundary is not the thing under test.
# A 3 GiB follow-up runs only when the 2 GiB transfer stayed off the RAM cliff.
# GBB_LARGE_BYTES overrides the first file (used to probe past 2 GiB).
BIG = int(os.environ.get("GBB_LARGE_BYTES") or (2 * 1024 * 1024 * 1024 - 1024 * 1024))
BIGGER = 3 * 1024 * 1024 * 1024
MULTI = 512 * 1024 * 1024
SKIP_MULTI = os.environ.get("GBB_SKIP_MULTI") == "1"
NO_FOLLOWUP = os.environ.get("GBB_NO_FOLLOWUP") == "1"


def fail(msg):
    raise AssertionError(msg)


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fail(name)


def mem_kb(pid):
    rss = hwm = 0
    try:
        text = open("/proc/%d/status" % pid).read()
    except OSError:
        return 0, 0
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            rss = int(line.split()[1])
        elif line.startswith("VmHWM:"):
            hwm = int(line.split()[1])
    return rss, hwm


def tree_stats(root):
    total = 0
    largest = 0
    if not root or not os.path.isdir(root):
        return 0, 0
    for dirpath, _, files in os.walk(root):
        for name in files:
            try:
                n = os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
            total += n
            if n > largest:
                largest = n
    return total, largest


def write_pattern(path, size):
    block = (b"BBUPLOAD-LARGE-v1\n" * ((1024 * 1024) // 18 + 1))[:1024 * 1024]
    digest = hashlib.sha256()
    left = size
    with open(path, "wb") as f:
        while left:
            chunk = block if left >= len(block) else block[:left]
            f.write(chunk)
            digest.update(chunk)
            left -= len(chunk)
    return digest.hexdigest()


def live_pids(bridge_pid, profile):
    found = [bridge_pid]
    needle = profile.encode() if profile else b""
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            cmd = open("/proc/%s/cmdline" % name, "rb").read()
        except OSError:
            continue
        low = cmd.lower()
        if b"chrome" not in low and b"chromium" not in low:
            continue
        if needle and needle not in cmd:
            continue
        found.append(int(name))
    return found


def peak_sampler(bridge_pid, stop, out):
    tick = 0
    while not stop.is_set():
        pids = live_pids(bridge_pid, out.get("profile") or "")
        bridge_rss, bridge_hwm = mem_kb(bridge_pid)
        chrome_rss = 0
        chrome_hwm = 0
        for pid in pids:
            if pid == bridge_pid:
                continue
            rss, hwm = mem_kb(pid)
            chrome_rss += rss
            chrome_hwm += hwm
        if bridge_hwm > out.get("bridge_hwm_kb", 0):
            out["bridge_hwm_kb"] = bridge_hwm
        if bridge_rss > out.get("bridge_rss_kb", 0):
            out["bridge_rss_kb"] = bridge_rss
        if chrome_rss > out.get("chrome_rss_kb", 0):
            out["chrome_rss_kb"] = chrome_rss
        if chrome_hwm > out.get("chrome_hwm_kb", 0):
            out["chrome_hwm_kb"] = chrome_hwm
        tick += 1
        if tick % 4 == 0:
            total, largest = tree_stats(out.get("profile") or "")
            if total > out.get("profile_bytes", 0):
                out["profile_bytes"] = total
            if largest > out.get("profile_largest", 0):
                out["profile_largest"] = largest
        stop.wait(0.5)


def upload(port, token, body, timeout):
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


def report_failure(code, res):
    err = res.get("error") if isinstance(res, dict) else res
    print("DETAIL", code, err)


def snapshot(peaks, label):
    print(
        label,
        "bridge_hwm_kb", peaks.get("bridge_hwm_kb"),
        "bridge_rss_kb", peaks.get("bridge_rss_kb"),
        "chrome_rss_kb", peaks.get("chrome_rss_kb"),
        "chrome_hwm_sum_kb", peaks.get("chrome_hwm_kb"),
        "profile_bytes", peaks.get("profile_bytes"),
        "profile_largest", peaks.get("profile_largest"),
    )


def main():
    home = tempfile.mkdtemp(prefix="bblarge-")
    work = tempfile.mkdtemp(prefix="bblargefiles-")
    profile = tempfile.mkdtemp(prefix="bblargeprof-")
    log_path = os.path.join(home, "bridge-stderr.txt")
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    print("writing synthetic files...", flush=True)
    big_path = os.path.join(work, "movie.mp4")
    big_sha = write_pattern(big_path, BIG)
    a_sha = b_sha = None
    a_path = b_path = None
    if not SKIP_MULTI:
        a_path = os.path.join(work, "a.mp4")
        b_path = os.path.join(work, "b.mp4")
        a_sha = write_pattern(a_path, MULTI)
        b_sha = write_pattern(b_path, MULTI)
    print("wrote", BIG, "multi", (not SKIP_MULTI), flush=True)
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); sock_port = s.getsockname()[1]; s.close()
    logf = open(log_path, "w", encoding="utf-8")
    bridge = subprocess.Popen(
        [PY, BRIDGE, "serve", "--port", str(sock_port)],
        env=env, stdout=subprocess.DEVNULL, stderr=logf,
    )
    uploads = UploadFixture()
    token = None
    for _ in range(50):
        cfg = os.path.join(home, ".bot-bridge", "config.json")
        if os.path.exists(cfg):
            token = json.load(open(cfg))["token"]
            break
        time.sleep(0.05)
    if not token:
        fail("no token")
    stop = threading.Event()
    peaks = {"profile": profile}
    sampler = threading.Thread(target=peak_sampler, args=(bridge.pid, stop, peaks), daemon=True)
    sampler.start()
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                profile, channel="chromium", headless=False,
                args=["--disable-extensions-except=" + EXT, "--load-extension=" + EXT,
                      "--disable-features=DisableLoadExtensionCommandLineSwitch",
                      "--no-sandbox", "--disable-dev-shm-usage"])
            sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
            eid = sw.url.split("/")[2]
            pop = ctx.new_page()
            pop.goto("chrome-extension://%s/popup.html" % eid)
            if pop.query_selector("#consent"):
                pop.fill("#port", str(sock_port))
                pop.fill("#token", token)
                pop.check("#consent")
                pop.click("#save")
            else:
                pop.fill("#port", str(sock_port))
                pop.fill("#token", token)
                pop.click("#save")
            for _ in range(40):
                req = urllib.request.Request("http://127.0.0.1:%d/status" % sock_port, headers={"X-Token": token})
                st = json.load(urllib.request.urlopen(req, timeout=5))
                if st.get("extension_connected"):
                    break
                time.sleep(0.25)
            else:
                fail("extension did not connect")

            def command(body, timeout=1800):
                return upload(sock_port, token, body, timeout)

            def received():
                return json.load(urllib.request.urlopen(uploads.url("/received"), timeout=30))["files"]

            def reset():
                urllib.request.urlopen(uploads.url("/reset"), timeout=10).read()

            def one_upload(path, selector, timeout):
                reset()
                code, _ = command({"cmd": "open_url", "url": uploads.url("/")}, timeout=60)
                if code != 200:
                    return code, {"error": "open_url failed"}, set()
                code, res = command({
                    "cmd": "upload", "selector": selector, "path": path,
                    "submit": True, "timeout": timeout, "load_timeout_ms": timeout * 1000,
                }, timeout=timeout + 60)
                try:
                    got = {item["sha256"] for item in received()}
                except Exception as e:
                    got = set()
                    print("fixture read failed", type(e).__name__)
                return code, res, got

            if not SKIP_MULTI:
                t0 = time.time()
                reset()
                code, res = command({"cmd": "open_url", "url": uploads.url("/")}, timeout=60)
                code, res = command({
                    "cmd": "upload", "selector": "#multi", "paths": [a_path, b_path],
                    "submit": True, "timeout": 1800, "load_timeout_ms": 1800000,
                }, timeout=1860)
                try:
                    got = {item["sha256"] for item in received()}
                except Exception as e:
                    got = set()
                    print("fixture read failed", type(e).__name__)
                meta_shas = {item.get("sha256") for item in ((res.get("result") or {}).get("files") or [])}
                ok = code == 200 and res.get("ok") and a_sha in got and b_sha in got and a_sha in meta_shas and b_sha in meta_shas
                if not ok:
                    report_failure(code, res)
                check("two 512MB files byte-match", ok)
                print("multiple seconds", round(time.time() - t0, 1), flush=True)
                snapshot(peaks, "AFTER_MULTI")

            t0 = time.time()
            code, res, got = one_upload(big_path, "#file", 3600)
            bridge_sha = (res.get("result") or {}).get("files", [{}])[0].get("sha256")
            ok = code == 200 and res.get("ok") and big_sha in got and bridge_sha == big_sha
            if not ok:
                report_failure(code, res)
            check("sha matches fixture and bridge (%d bytes)" % BIG, ok)
            print("big seconds", round(time.time() - t0, 1), "bytes", BIG, flush=True)
            snapshot(peaks, "AFTER_BIG")

            chrome_rss = peaks.get("chrome_rss_kb") or 0
            if NO_FOLLOWUP:
                print("no extra size follow-up", flush=True)
            elif chrome_rss < 1.2 * 1024 * 1024:
                print("writing 3GiB follow-up", flush=True)
                bigger_path = os.path.join(work, "longer.mp4")
                bigger_sha = write_pattern(bigger_path, BIGGER)
                t0 = time.time()
                code, res, got = one_upload(bigger_path, "#file", 3600)
                bridge_sha = (res.get("result") or {}).get("files", [{}])[0].get("sha256")
                ok = code == 200 and res.get("ok") and bigger_sha in got and bridge_sha == bigger_sha
                if not ok:
                    report_failure(code, res)
                    print("3GiB follow-up did not match; 2GiB-class result above still stands")
                else:
                    print("PASS 3GiB file sha matches fixture and bridge", flush=True)
                    print("bigger seconds", round(time.time() - t0, 1), "bytes", BIGGER, flush=True)
            else:
                print("skipped 3GiB follow-up because chrome rss peak was", chrome_rss, "kB")
            snapshot(peaks, "FINAL")
            print("BIG_BYTES", BIG, "MULTI_BYTES", MULTI, "BIGGER_BYTES", BIGGER)
            ctx.close()
    finally:
        stop.set()
        bridge.terminate()
        uploads.close()
        try:
            bridge.wait(timeout=5)
        except Exception:
            bridge.kill()
        logf.close()
        try:
            text = open(log_path, encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        if token and token in text:
            print("FAIL token appeared in bridge stderr")
        else:
            print("PASS bridge stderr has no token")
        progressed = [line for line in text.splitlines() if line.startswith("upload ")]
        if progressed:
            print("PROGRESS_LAST", progressed[-1])
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()

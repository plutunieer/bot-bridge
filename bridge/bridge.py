#!/usr/bin/env python3
"""Bot Bridge - local relay between an AI assistant and the Bot Bridge Chrome extension.

Pure Python 3 standard library. Runs on Windows, macOS and Linux.
Binds to 127.0.0.1 only. Every request must carry the shared token
(header "X-Token"), which is generated on first run and stored in
~/.bot-bridge/config.json (an existing ~/.grok-chrome-bridge/ from
version 1.0 is still used if present).

Usage:
  python3 bridge.py serve [--port 8765]      start the bridge (foreground; does not print the token)
  python3 bridge.py token                     print the token to this terminal (creates config if missing)
  python3 bridge.py status                    show whether the extension is connected
  python3 bridge.py send '{"cmd":"get_page"}' send one command, print the JSON result
  python3 bridge.py send click index=3        same, shorthand key=value form
  python3 bridge.py new-token                 rotate the token and print the new one to this terminal

`serve` must stay safe to run under launchd, systemd, or nohup, where stdout is
kept. The token is shown only by `token` and `new-token`. Do not redirect those
two commands into a service log.
"""
import argparse
import base64
import json
import os
import queue
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

VERSION = "1.0.3"
DEFAULT_PORT = 8765
_HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(_HOME, ".bot-bridge")
_LEGACY_DIR = os.path.join(_HOME, ".grok-chrome-bridge")   # 1.0.x installs
if not os.path.isdir(CONFIG_DIR) and os.path.isfile(os.path.join(_LEGACY_DIR, "config.json")):
    CONFIG_DIR = _LEGACY_DIR
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
POLL_WAIT = 25          # seconds a /next long-poll is held open
CONNECTED_GRACE = 40    # extension counts as connected if it polled within this window
DEFAULT_TIMEOUT = 30    # seconds /command waits for a result
MAX_BODY = 64 * 1024 * 1024


# ---------------------------------------------------------------- config
def _tighten_perms():
    """Keep the token file and its directory private even when serve does not rewrite them."""
    try:
        if os.path.isdir(CONFIG_DIR):
            os.chmod(CONFIG_DIR, 0o700)
    except Exception:
        pass
    try:
        if os.path.isfile(CONFIG_FILE):
            os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass


def load_config(create=True):
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    changed = False
    token = cfg.get("token")
    if not isinstance(token, str) or not token:
        cfg["token"] = secrets.token_urlsafe(24)
        changed = True
    if not cfg.get("port"):
        cfg["port"] = DEFAULT_PORT
        changed = True
    if changed and create:
        save_config(cfg)
    elif create:
        _tighten_perms()
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    _tighten_perms()


# ---------------------------------------------------------------- state
class State:
    def __init__(self, token):
        self.token = token
        self.pending = queue.Queue()        # commands waiting for the extension
        self.waiters = {}                   # id -> {"event", "result", "cmd"}
        self.lock = threading.Lock()
        self.last_poll = 0.0
        self.poll_seq = 0
        self.ext_info = {}


STATE = None


def _save_screenshot_if_requested(cmd, result):
    """If the bot asked for save_path, write the PNG to disk on this machine."""
    path = cmd.get("save_path")
    if not path or not isinstance(result, dict) or not result.get("ok"):
        return result
    data = (result.get("result") or {}).get("data_base64")
    if not data:
        return result
    try:
        path = os.path.abspath(os.path.expanduser(path))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        result["result"]["saved_path"] = path
        if not cmd.get("include_data"):
            result["result"]["data_base64"] = None
            result["result"]["note"] = "image saved to saved_path; pass include_data:true to also get base64"
    except Exception as e:  # noqa
        result["result"]["save_error"] = str(e)
    return result


def _host_name(value):
    """Hostname from a Host header. Ports and brackets are not part of the name."""
    value = (value or "").strip().lower()
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return ""
        return value[1:end]
    return value.split(":", 1)[0].strip()


def _allowed_extension_origin(origin):
    """Chrome extension ids are 32 characters from a-p. Reject prefix tricks."""
    prefix = "chrome-extension://"
    if not origin.startswith(prefix):
        return False
    ext_id = origin[len(prefix):]
    return len(ext_id) == 32 and all(c in "abcdefghijklmnop" for c in ext_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "BotBridge/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Request line only. Never log headers or bodies: they carry the token and page data.
        if os.environ.get("GBB_VERBOSE"):
            sys.stderr.write("[bridge] " + (fmt % args) + "\n")

    # --- helpers
    def _send(self, code, obj=None):
        body = b"" if obj is None else json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authorized(self):
        # DNS-rebinding protection: only accept a loopback Host, exact name, not a suffix.
        if _host_name(self.headers.get("Host")) not in ("127.0.0.1", "localhost", "::1"):
            self._send(403, {"ok": False, "error": "bad host"})
            return False
        # Browsers always send Origin. Web origins are refused even if they know the token.
        # CLI clients omit Origin. Extension origins are chrome-extension://<32-char id>.
        origin = self.headers.get("Origin") or ""
        if origin and not _allowed_extension_origin(origin):
            self._send(403, {"ok": False, "error": "origin not allowed"})
            return False
        expected = STATE.token if isinstance(STATE.token, str) else ""
        tok = self.headers.get("X-Token") or ""
        if not expected or not isinstance(tok, str) or not secrets.compare_digest(tok, expected):
            self._send(401, {"ok": False, "error": "missing or wrong X-Token"})
            return False
        return True

    def _body(self):
        raw_len = self.headers.get("Content-Length") or "0"
        try:
            n = int(raw_len)
        except ValueError:
            raise ValueError("bad content length")
        if n < 0 or n > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _connected(self):
        return (time.time() - STATE.last_poll) < CONNECTED_GRACE

    # --- routes
    def do_OPTIONS(self):
        self._send(403, {"ok": False, "error": "CORS not supported"})

    def do_GET(self):
        if not self._authorized():
            return
        path = self.path.split("?")[0]
        if path == "/status":
            self._send(200, {
                "ok": True,
                "bridge_version": VERSION,
                "extension_connected": self._connected(),
                "seconds_since_last_poll": round(time.time() - STATE.last_poll, 1) if STATE.last_poll else None,
                "extension": STATE.ext_info,
                "queued_commands": STATE.pending.qsize(),
            })
        elif path == "/next":
            STATE.last_poll = time.time()
            ua = self.headers.get("X-Extension-Version")
            if ua:
                STATE.ext_info = {"version": ua}
            with STATE.lock:
                STATE.poll_seq += 1
                my_seq = STATE.poll_seq
            deadline = time.time() + POLL_WAIT
            while True:
                remaining = deadline - time.time()
                # a newer poll (or /disconnect) supersedes this one, so a dead
                # connection never swallows a command
                if remaining <= 0 or my_seq != STATE.poll_seq:
                    self._send(204)
                    return
                try:
                    item = STATE.pending.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    continue
                if my_seq != STATE.poll_seq:
                    STATE.pending.put(item)
                    self._send(204)
                    return
                with STATE.lock:
                    alive = item["id"] in STATE.waiters
                if not alive:   # caller already timed out, drop it
                    continue
                STATE.last_poll = time.time()
                try:
                    self._send(200, item)
                except Exception:
                    STATE.pending.put(item)  # extension went away, requeue
                return
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self._authorized():
            return
        path = self.path.split("?")[0]
        try:
            body = self._body()
        except Exception as e:
            self._send(400, {"ok": False, "error": "invalid JSON: %s" % e})
            return
        if path == "/disconnect":   # extension was switched off
            with STATE.lock:
                STATE.last_poll = 0.0
                STATE.poll_seq += 1
            self._send(200, {"ok": True})
        elif path == "/result":
            STATE.last_poll = time.time()
            cid = body.get("id")
            with STATE.lock:
                w = STATE.waiters.get(cid)
            if w:
                w["result"] = body
                w["event"].set()
            self._send(200, {"ok": True})
        elif path == "/command":
            if not isinstance(body, dict) or not body.get("cmd"):
                self._send(400, {"ok": False, "error": 'body must be JSON like {"cmd":"list_tabs"}'})
                return
            if not self._connected():
                self._send(503, {"ok": False, "error": "extension not connected (is Chrome open and the extension enabled with the right port/token?)"})
                return
            timeout = float(body.get("timeout") or DEFAULT_TIMEOUT)
            timeout = max(1.0, min(timeout, 300.0))
            cid = uuid.uuid4().hex
            ev = threading.Event()
            with STATE.lock:
                STATE.waiters[cid] = {"event": ev, "result": None}
            STATE.pending.put({"id": cid, "command": body})
            got = ev.wait(timeout)
            with STATE.lock:
                w = STATE.waiters.pop(cid, None)
            if not got or not w or w["result"] is None:
                self._send(504, {"ok": False, "error": "timeout after %.0fs waiting for the extension" % timeout})
                return
            res = w["result"]
            out = {"ok": bool(res.get("ok")), "cmd": body.get("cmd")}
            if res.get("ok"):
                out["result"] = res.get("result")
            else:
                out["error"] = res.get("error") or "unknown error"
            out = _save_screenshot_if_requested(body, out)
            self._send(200, out)
        else:
            self._send(404, {"ok": False, "error": "not found"})


# ---------------------------------------------------------------- CLI
def serve(port):
    global STATE
    cfg = load_config()
    if port:
        cfg["port"] = port
        save_config(cfg)
    STATE = State(cfg["token"])
    # Loopback only. Do not bind 0.0.0.0 or a LAN address.
    srv = ThreadingHTTPServer(("127.0.0.1", int(cfg["port"])), Handler)
    srv.daemon_threads = True
    script = os.path.abspath(__file__)
    py = sys.executable or "python3"
    # Do not print the token. launchd/systemd/nohup keep this stdout.
    print("Bot Bridge %s" % VERSION)
    print("Listening on http://127.0.0.1:%s (localhost only)" % cfg["port"])
    print("Port: %s" % cfg["port"])
    print("Config: %s" % CONFIG_FILE)
    print("The token is not printed on startup.")
    print("Show it in a terminal you control, and do not redirect that command to a log:")
    print("  %s %s token" % (py, script))
    print("Paste the port and that token into the extension popup. Ctrl+C to stop.")
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def _call(method, path, body=None, timeout=330):
    cfg = load_config()
    url = "http://127.0.0.1:%s%s" % (cfg["port"], path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urlrequest.Request(url, data=data, method=method,
                             headers={"X-Token": cfg["token"], "Content-Type": "application/json"})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except HTTPError as e:
        raw = e.read()
    except URLError as e:
        return {"ok": False, "error": "bridge not reachable on port %s (%s). Start it with: python3 bridge.py serve" % (cfg["port"], e.reason)}
    try:
        return json.loads(raw.decode("utf-8")) if raw else {"ok": True}
    except Exception:
        return {"ok": False, "error": raw.decode("utf-8", "replace")}


def main(argv=None):
    p = argparse.ArgumentParser(description="Bot Bridge – local bridge for the Bot Bridge Chrome extension")
    sub = p.add_subparsers(dest="mode")
    s = sub.add_parser("serve", help="run the bridge (does not print the token)")
    s.add_argument("--port", type=int, default=None)
    sub.add_parser("token", help="print the token to this terminal")
    sub.add_parser("new-token", help="generate a new token and print it to this terminal")
    sub.add_parser("status", help="extension connection status")
    sd = sub.add_parser("send", help="send one JSON command")
    sd.add_argument("json", help='e.g. \'{"cmd":"list_tabs"}\', - for stdin, or shorthand: click index=3')
    sd.add_argument("kv", nargs="*", help="shorthand key=value pairs (values parsed as JSON when possible)")
    a = p.parse_args(argv)

    if a.mode in (None, "serve"):
        serve(getattr(a, "port", None))
    elif a.mode == "token":
        cfg = load_config()
        print(cfg["token"])
    elif a.mode == "new-token":
        cfg = load_config()
        cfg["token"] = secrets.token_urlsafe(24)
        save_config(cfg)
        print(cfg["token"])
        print("Restart the bridge and paste the new token into the extension.", file=sys.stderr)
        print("This command prints the token. Do not redirect it into a service log.", file=sys.stderr)
    elif a.mode == "status":
        print(json.dumps(_call("GET", "/status", timeout=10), indent=2))
    elif a.mode == "send":
        raw = sys.stdin.read() if a.json == "-" else a.json
        if raw.strip().startswith("{"):
            try:
                body = json.loads(raw)
            except Exception as e:
                print(json.dumps({"ok": False, "error": "invalid JSON argument: %s" % e}))
                return 2
        else:   # shorthand:  send type index=2 text="hello world" submit=true
            body = {"cmd": raw.strip()}
            for pair in a.kv:
                k, _, v = pair.partition("=")
                try:
                    body[k] = json.loads(v)
                except Exception:
                    body[k] = v
        res = _call("POST", "/command", body)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

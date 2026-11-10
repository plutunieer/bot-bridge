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
import errno
import hashlib
import json
import mimetypes
import os
import queue
import secrets
import shutil
import socket
import stat
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

VERSION = "1.0.6"
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
# How many named files one command may open. This is a file-descriptor guard,
# not a size cap. Size is unlimited unless config max_upload_bytes is set.
MAX_UPLOAD_FILES = 100
UPLOAD_CHUNK = 1024 * 1024
UPLOAD_STALL_SECONDS = 120
UPLOAD_DEFAULT_WAIT = 6 * 3600


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


class UploadSession:
    """One named file, held as an open descriptor until it is streamed once."""

    def __init__(self, sid, fd, size, name, mime, requested, real):
        self.id = sid
        self.fd = fd
        self.size = size
        self.name = name
        self.mime = mime
        self.requested_path = requested
        self.real_path = real
        self.bytes_sent = 0
        self.sha256 = None
        self.done = False
        self.cancelled = False
        self.error = None
        self.started = False
        self.last_progress = 0.0
        self.finished = threading.Event()
        self._closed = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self.fd)
        except OSError:
            pass


class UploadSessions:
    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def add(self, sess):
        with self._lock:
            self._items[sess.id] = sess

    def get(self, sid):
        with self._lock:
            return self._items.get(sid)

    def drop(self, sid):
        with self._lock:
            sess = self._items.pop(sid, None)
        if sess:
            sess.cancelled = True
            sess.finished.set()
            sess.close()
        return sess

    def ids(self):
        with self._lock:
            return list(self._items.keys())


UPLOADS = UploadSessions()


def configured_upload_limit():
    """Positive max_upload_bytes from config, or None when unlimited (the default)."""
    cfg = load_config(create=False)
    if "max_upload_bytes" not in cfg or cfg.get("max_upload_bytes") in (None, "", False):
        return None
    raw = cfg.get("max_upload_bytes")
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        raise ValueError("max_upload_bytes in the bridge config must be an integer (0 means unlimited)")
    if limit <= 0:
        return None
    return limit


def stage_upload_files(body, limit=None):
    """Open regular files explicitly named by an upload command.

    Caller-supplied file bytes are ignored. There is no directory listing,
    glob, or general read endpoint. The file is not read here; the extension
    streams it later. Symlinks are resolved and both paths are reported.
    """
    if not isinstance(body, dict):
        raise ValueError("upload body must be an object")
    paths = []
    if isinstance(body.get("paths"), list):
        paths.extend(body["paths"])
    if "path" in body and body.get("path") is not None:
        paths.append(body.get("path"))
    if not paths:
        raise ValueError("path or paths required")
    if len(paths) > MAX_UPLOAD_FILES:
        raise ValueError("too many files (limit %d)" % MAX_UPLOAD_FILES)
    opened = []
    try:
        for raw in paths:
            if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
                raise ValueError("invalid path")
            requested = raw
            real = os.path.realpath(os.path.expanduser(raw))
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                fd = os.open(real, flags)
            except OSError as e:
                raise ValueError("cannot open file: %s" % e.strerror)
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    os.close(fd)
                    raise ValueError("not a regular file")
                if limit is not None and st.st_size > limit:
                    os.close(fd)
                    raise ValueError(
                        "file exceeds configured max_upload_bytes (%d bytes, limit %d). "
                        "The default is unlimited; set max_upload_bytes to 0 to clear a limit."
                        % (st.st_size, limit)
                    )
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
            mime = mimetypes.guess_type(os.path.basename(real))[0] or "application/octet-stream"
            sess = UploadSession(
                secrets.token_urlsafe(18), fd, st.st_size,
                os.path.basename(real) or "file", mime, requested, real,
            )
            UPLOADS.add(sess)
            opened.append(sess)
    except Exception:
        for sess in opened:
            UPLOADS.drop(sess.id)
        raise
    return [{
        "id": s.id,
        "name": s.name,
        "mime": s.mime,
        "size": s.size,
        "requested_path": s.requested_path,
        "real_path": s.real_path,
    } for s in opened]


def release_staged(files):
    for item in files or []:
        if isinstance(item, dict) and item.get("id"):
            UPLOADS.drop(item["id"])


def _hash_session(sess):
    """Hash a staged file from its open descriptor. Constant memory. No path in errors."""
    try:
        os.lseek(sess.fd, 0, os.SEEK_SET)
    except OSError:
        return False
    digest = hashlib.sha256()
    remaining = sess.size
    while remaining:
        chunk = os.read(sess.fd, min(UPLOAD_CHUNK, remaining))
        if not chunk:
            break
        digest.update(chunk)
        remaining -= len(chunk)
    if remaining:
        return False
    sess.sha256 = digest.hexdigest()
    sess.bytes_sent = sess.size
    sess.done = True
    return True


def _safe_cmd(cmd):
    if not isinstance(cmd, str) or not cmd or len(cmd) > 40:
        return "?"
    for ch in cmd:
        if ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-":
            return "?"
    return cmd


def _log_outcome(cmd, ok, error=None):
    """One stderr line: time, command name, ok or a short error. Never the token or file bytes."""
    status = "ok"
    if not ok:
        status = "error " + (error or "failed")
        status = " ".join(status.split())
        token = STATE.token if STATE is not None and isinstance(getattr(STATE, "token", None), str) else ""
        if token and token in status:
            status = status.replace(token, "[redacted]")
        status = status[:240]
    line = "%s command %s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), _safe_cmd(cmd), status)
    try:
        sys.stderr.write(line)
        sys.stderr.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass


_PIPE_ERRNOS = {errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED}


def _client_gone(exc):
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, socket.timeout)):
        return True
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in _PIPE_ERRNOS


def _place_download(body, out):
    """If Chrome refused a custom download folder, copy the finished file into the requested one.

    The extension reports the path Chrome actually wrote. The chosen folder is the
    caller's, and only the file's base name is used.
    """
    if not isinstance(body, dict) or not isinstance(out, dict):
        return out
    result = out.get("result")
    download = result.get("download") if isinstance(result, dict) else None
    dest_dir = body.get("download_dir")
    if not isinstance(download, dict) or download.get("folder_control") is not False:
        return out
    src = download.get("path")
    if not isinstance(src, str) or not isinstance(dest_dir, str) or not src or not dest_dir:
        return out
    try:
        dest_dir = os.path.realpath(os.path.expanduser(dest_dir))
        src_real = os.path.realpath(src)
    except OSError:
        return out
    if not os.path.isdir(dest_dir) or not os.path.isfile(src_real):
        return out
    name = os.path.basename(src_real)
    if not name or name in (".", ".."):
        return out
    dest = os.path.join(dest_dir, name)
    if os.path.dirname(os.path.realpath(dest)) != dest_dir:
        return out
    if src_real == os.path.realpath(dest):
        download["path"] = dest
        return out
    try:
        shutil.copyfile(src_real, dest)
    except OSError:
        return out
    download["browser_path"] = src_real
    download["path"] = dest
    download["copied"] = True
    return out


def _upload_public_meta(files):
    meta = []
    for item in files:
        sess = UPLOADS.get(item["id"]) if isinstance(item, dict) else None
        row = {
            "name": item.get("name"),
            "mime": item.get("mime"),
            "size": item.get("size"),
            "requested_path": item.get("requested_path"),
            "real_path": item.get("real_path"),
            "bytes_sent": sess.bytes_sent if sess else 0,
        }
        if sess and sess.sha256:
            row["sha256"] = sess.sha256
        meta.append(row)
    return meta


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
        # Request line only, and only when asked. Never log headers or bodies:
        # they carry the token and page data. Command outcomes are logged separately.
        if os.environ.get("GBB_VERBOSE"):
            try:
                sys.stderr.write("[bridge] " + (fmt % args) + "\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def handle_error(self, request, client_address):
        # A client that gave up (upload timeout, closed tab) must not dump a traceback.
        err = sys.exc_info()[1]
        if _client_gone(err):
            return
        try:
            super().handle_error(request, client_address)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    # --- helpers
    def _send(self, code, obj=None):
        body = b"" if obj is None else json.dumps(obj).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(body)
        except Exception as exc:
            if _client_gone(exc):
                self.close_connection = True
                return
            raise

    def _authorized(self, allow_web_origin=False):
        # DNS-rebinding protection: only accept a loopback Host, exact name, not a suffix.
        if _host_name(self.headers.get("Host")) not in ("127.0.0.1", "localhost", "::1"):
            self._send(403, {"ok": False, "error": "bad host"})
            return False
        # Browsers always send Origin. Command routes refuse web origins even with the token.
        # CLI clients omit Origin. Extension origins are chrome-extension://<32-char id>.
        # /blob/ is fetched by the extension's isolated world, which sends the page's Origin,
        # so that route allows it and still requires the token plus an unguessable id.
        origin = self.headers.get("Origin") or ""
        if origin and not _allowed_extension_origin(origin) and not allow_web_origin:
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
    def _cors_blob(self, origin):
        """Let the extension's isolated world read a staged file.

        The page itself still needs the bridge token and the unguessable blob id.
        Command routes stay without these headers.
        """
        if not origin or any(c in origin for c in "\r\n"):
            origin = "null"
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        path = self.path.split("?")[0]
        if path.startswith("/blob/"):
            self.send_response(204)
            self._cors_blob(self.headers.get("Origin"))
            self.send_header("Access-Control-Allow-Methods", "GET")
            self.send_header("Access-Control-Allow-Headers", "X-Token, Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(403, {"ok": False, "error": "CORS not supported"})

    def _stream_blob(self, sess):
        try:
            self.send_response(200)
            self.send_header("Content-Type", sess.mime)
            self.send_header("Content-Length", str(sess.size))
            self.send_header("Cache-Control", "no-store")
            self._cors_blob(self.headers.get("Origin"))
            self.end_headers()
            digest = hashlib.sha256()
            remaining = sess.size
            sess.started = True
            sess.last_progress = time.time()
            while remaining:
                if sess.cancelled:
                    sess.error = sess.error or "cancelled"
                    return
                chunk = os.read(sess.fd, min(UPLOAD_CHUNK, remaining))
                if not chunk:
                    sess.error = "file ended early"
                    return
                if len(chunk) > remaining:
                    chunk = chunk[:remaining]
                digest.update(chunk)
                self.wfile.write(chunk)
                remaining -= len(chunk)
                sess.bytes_sent += len(chunk)
                sess.last_progress = time.time()
            if remaining == 0 and not sess.cancelled:
                sess.sha256 = digest.hexdigest()
                sess.done = True
        except Exception as e:
            if not sess.error:
                sess.error = "transfer interrupted"
            _ = e
        finally:
            sess.finished.set()
            sess.close()

    def do_GET(self):
        path = self.path.split("?")[0]
        blob = path.startswith("/blob/")
        if not self._authorized(allow_web_origin=blob):
            return
        if path.startswith("/blob/"):
            sid = path[len("/blob/"):]
            if not sid or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in sid):
                self._send(404, {"ok": False, "error": "unknown upload"})
                return
            sess = UPLOADS.get(sid)
            if not sess or sess.done or sess.cancelled:
                self._send(404, {"ok": False, "error": "unknown upload"})
                return
            self._stream_blob(sess)
            if not sess.done:
                UPLOADS.drop(sid)
            return
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
                _log_outcome(body.get("cmd"), False, "extension not connected")
                self._send(503, {"ok": False, "error": "extension not connected (is Chrome open and the extension enabled with the right port/token?)"})
                return
            staged = None
            if body.get("cmd") in ("upload", "click_upload"):
                # Never accept bytes from the caller. Open only named regular files,
                # and only after the extension is connected, so a refused command
                # does not touch the disk. Bytes are streamed later on GET /blob/<id>.
                body.pop("files", None)
                body.pop("data_base64", None)
                try:
                    staged = stage_upload_files(body, configured_upload_limit())
                except ValueError as e:
                    _log_outcome(body.get("cmd"), False, str(e))
                    self._send(400, {"ok": False, "error": str(e)})
                    return
                body = dict(body)
                body["files"] = staged
            timeout = _command_timeout(body)
            cid = uuid.uuid4().hex
            ev = threading.Event()
            with STATE.lock:
                STATE.waiters[cid] = {"event": ev, "result": None}
            STATE.pending.put({"id": cid, "command": body})
            deadline = time.time() + timeout
            last_note = 0.0
            got = False
            stalled = False
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                if staged:
                    for item in staged:
                        sess = UPLOADS.get(item["id"])
                        if sess and sess.started and not sess.done and not sess.cancelled:
                            if time.time() - sess.last_progress > UPLOAD_STALL_SECONDS:
                                sess.error = "stalled"
                                stalled = True
                    if stalled:
                        break
                    now = time.time()
                    if now - last_note >= 1.0:
                        sent = 0
                        total = 0
                        for item in staged:
                            sess = UPLOADS.get(item["id"])
                            total += int(item.get("size") or 0)
                            if sess:
                                sent += sess.bytes_sent
                        if sent:
                            print("upload %d/%d bytes" % (sent, total), file=sys.stderr)
                        last_note = now
                if ev.wait(min(0.5, remaining)):
                    got = True
                    break
            with STATE.lock:
                w = STATE.waiters.pop(cid, None)
            if not got or not w or w["result"] is None:
                release_staged(staged)
                reason = "stalled" if stalled else "timeout"
                # Sessions were dropped above; the error string must not include paths or bytes.
                err = "upload %s" % reason if body.get("cmd") in ("upload", "click_upload") else "timeout after %.0fs waiting for the extension" % timeout
                _log_outcome(body.get("cmd"), False, err)
                self._send(504, {"ok": False, "error": err})
                return
            res = w["result"]
            out = {"ok": bool(res.get("ok")), "cmd": body.get("cmd")}
            if res.get("ok"):
                out["result"] = res.get("result") if isinstance(res.get("result"), dict) else {"value": res.get("result")}
                if staged is not None:
                    delivery = out["result"].get("delivery")
                    if delivery == "cdp":
                        # Chrome read the paths itself. Hash here so the result still has a sha256.
                        failed = [item for item in staged if not (UPLOADS.get(item["id"]) and _hash_session(UPLOADS.get(item["id"])))]
                        if failed:
                            release_staged(staged)
                            _log_outcome(body.get("cmd"), False, "upload hash failed")
                            self._send(502, {"ok": False, "error": "upload hash failed"})
                            return
                    else:
                        incomplete = [item for item in staged if not (UPLOADS.get(item["id"]) and UPLOADS.get(item["id"]).done)]
                        if incomplete:
                            release_staged(staged)
                            _log_outcome(body.get("cmd"), False, "upload transfer did not finish")
                            self._send(502, {"ok": False, "error": "upload transfer did not finish"})
                            return
                    out["result"]["files"] = _upload_public_meta(staged)
                    out["result"].pop("data_base64", None)
            else:
                out["error"] = res.get("error") or "unknown error"
            release_staged(staged)
            out = _save_screenshot_if_requested(body, out)
            out = _place_download(body, out)
            _log_outcome(body.get("cmd"), out.get("ok"), None if out.get("ok") else out.get("error"))
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


def _command_timeout(body):
    """How long /command waits. The CLI uses this plus a margin, so it cannot hang up first."""
    if not isinstance(body, dict):
        return float(DEFAULT_TIMEOUT)
    long_upload = body.get("cmd") in ("upload", "click_upload")
    cap = float(UPLOAD_DEFAULT_WAIT if long_upload else 300)
    default = float(UPLOAD_DEFAULT_WAIT if long_upload else DEFAULT_TIMEOUT)
    if body.get("download_dir") and not long_upload:
        default = max(default, 120.0)
        cap = max(cap, 300.0)
    if body.get("timeout") is None:
        return default
    try:
        asked = float(body.get("timeout"))
    except (TypeError, ValueError):
        return default
    return max(1.0, min(asked, cap))


def _client_timeout(body):
    """Stay connected until the bridge has finished, including a long upload."""
    return _command_timeout(body) + 60


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
        try:
            raw = e.read()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout, OSError):
            return {"ok": False, "error": "the bridge closed the connection before the result was read"}
    except (TimeoutError, socket.timeout):
        return {"ok": False, "error": "timed out waiting for the bridge. An upload waits for the command timeout; the extension did not answer in that time."}
    except URLError as e:
        reason = getattr(e, "reason", e)
        if _client_gone(reason) or isinstance(reason, (TimeoutError, socket.timeout)):
            return {"ok": False, "error": "timed out waiting for the bridge. An upload waits for the command timeout; the extension did not answer in that time."}
        return {"ok": False, "error": "bridge not reachable on port %s (%s). Start it with: python3 bridge.py serve" % (cfg["port"], reason)}
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
        res = _call("POST", "/command", body, timeout=_client_timeout(body))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res.get("ok") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

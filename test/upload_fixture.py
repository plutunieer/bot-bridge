"""Loopback page that accepts real multipart uploads. Test fixture only."""
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Upload fixture</title>
<body>
<form id="classic" action="/sink" method="post" enctype="multipart/form-data">
  <input id="file" type="file" name="file">
  <button type="submit">Send</button>
</form>
<form id="hidform" action="/sink" method="post" enctype="multipart/form-data">
  <input id="hid" type="file" name="hid" style="display:none">
  <button type="submit">Send hidden</button>
</form>
<form id="multiform" action="/sink" method="post" enctype="multipart/form-data">
  <input id="multi" type="file" name="docs" multiple>
  <button type="submit">Send multi</button>
</form>
<div id="host"></div>
<iframe src="/frame" id="ifr"></iframe>
<div id="drop" style="width:240px;height:80px">drop here</div>
<div id="keys" tabindex="0">keys</div>
<script>
const host = document.getElementById("host");
const root = host.attachShadow({mode:"open"});
root.innerHTML = '<form action="/sink" method="post" enctype="multipart/form-data"><input id="inside" type="file" name="shadow"><button type="submit">Go</button></form>';
const drop = document.getElementById("drop");
drop.addEventListener("dragover", (e) => e.preventDefault());
drop.addEventListener("drop", async (e) => {
  e.preventDefault();
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (!f) return;
  const buf = await f.arrayBuffer();
  await fetch("/raw", {method:"POST", body: buf});
});
document.getElementById("keys").addEventListener("keydown", (e) => {
  if (e.ctrlKey && (e.key === "a" || e.key === "A")) e.currentTarget.textContent = "ctrl-a";
});
</script>
</body>
"""

FRAME = """<!doctype html><meta charset="utf-8"><title>frame</title><body>
<form action="/sink" method="post" enctype="multipart/form-data">
  <input id="framefile" type="file" name="frame">
  <button type="submit">Send</button>
</form>
</body>"""


def _boundary(content_type):
    match = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not match:
        raise ValueError("missing multipart boundary")
    return match.group(1).encode()


def hash_multipart(chunks, content_type):
    """Hash file parts from a multipart body without keeping the bytes.

    chunks is an iterator of bytes. Returns [{sha256, size}, ...].
    """
    boundary = _boundary(content_type)
    marker = b"\r\n--" + boundary
    pending = b""
    in_file = False
    digest = None
    size = 0
    found = []

    def feed(data):
        nonlocal pending, in_file, digest, size
        pending += data
        while True:
            if not in_file:
                split = pending.find(b"\r\n\r\n")
                if split < 0:
                    if len(pending) > 65536:
                        pending = pending[-65536:]
                    return
                header = pending[:split]
                pending = pending[split + 4:]
                if b"filename=" in header:
                    in_file = True
                    digest = hashlib.sha256()
                    size = 0
            else:
                at = pending.find(marker)
                if at < 0:
                    keep = len(marker) - 1
                    if len(pending) > keep:
                        take = pending[:-keep]
                        digest.update(take)
                        size += len(take)
                        pending = pending[-keep:]
                    return
                digest.update(pending[:at])
                size += at
                found.append({"sha256": digest.hexdigest(), "size": size})
                in_file = False
                digest = None
                pending = pending[at + 2:]  # drop the CRLF, leave --boundary...

    for chunk in chunks:
        feed(chunk)
    feed(b"")
    return found


class UploadFixture:
    def __init__(self):
        self.files = []  # {sha256, size} only; bodies are not retained
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
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
                if path == "/received":
                    with outer.lock:
                        info = list(outer.files)
                    self._send(200, json.dumps({"files": info}), "application/json")
                elif path == "/reset":
                    with outer.lock:
                        outer.files.clear()
                    self._send(200, b"ok", "text/plain")
                elif path == "/frame":
                    self._send(200, FRAME)
                else:
                    self._send(200, PAGE)

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
                with outer.lock:
                    outer.files.extend(info)
                self._send(200, b"ok", "text/plain")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path="/"):
        return "http://127.0.0.1:%d%s" % (self.port, path)

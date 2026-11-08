"""Loopback page that accepts real multipart uploads. Test fixture only."""
import email
import hashlib
import json
import threading
from email import policy
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


def parse_multipart(body, content_type):
    header = ("MIME-Version: 1.0\r\nContent-Type: %s\r\n\r\n" % content_type).encode()
    msg = email.message_from_bytes(header + body, policy=policy.default)
    found = []
    if not msg.is_multipart():
        return found
    for part in msg.iter_parts():
        disp = part.get("Content-Disposition", "")
        if "filename=" not in disp:
            continue
        payload = part.get_payload(decode=True)
        if payload is not None:
            found.append(payload)
    return found


class UploadFixture:
    def __init__(self):
        self.files = []
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
                        info = [{"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for b in outer.files]
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
                raw = self.rfile.read(n)
                path = self.path.split("?")[0]
                if path == "/raw":
                    blobs = [raw]
                else:
                    blobs = parse_multipart(raw, self.headers.get("Content-Type") or "")
                with outer.lock:
                    outer.files.extend(blobs)
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

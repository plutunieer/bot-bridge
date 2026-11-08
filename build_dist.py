"""Build dist/extension.zip (Web Store-ready, manifest at root) dist/bot-bridge.zip (whole project) and dist/bridge-app.zip."""
import os, zipfile
ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist"); os.makedirs(DIST, exist_ok=True)
SKIP = ("__pycache__", ".DS_Store", "last_screenshot.png", "raw", "drafts", ".git")
def add_tree(z, src, arc_prefix):
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if x not in SKIP and not x.startswith(".") and x not in ("dist", "publish"))
        for f in sorted(files):
            if f in SKIP or f.endswith(".zip"): continue
            p = os.path.join(d, f)
            info = zipfile.ZipInfo(os.path.join(arc_prefix, os.path.relpath(p, src)).replace(os.sep, "/"), (2026, 11, 8, 0, 0, 0))
            info.external_attr = (0o755 if os.access(p, os.X_OK) else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, open(p, "rb").read())
with zipfile.ZipFile(os.path.join(DIST, "extension.zip"), "w") as z:
    add_tree(z, os.path.join(ROOT, "extension"), "")
with zipfile.ZipFile(os.path.join(DIST, "bot-bridge.zip"), "w") as z:
    add_tree(z, ROOT, "bot-bridge")
# bridge-only download for Web Store users (attach to a GitHub release)
with zipfile.ZipFile(os.path.join(DIST, "bridge-app.zip"), "w") as z:
    for sub in ("bridge", "client"):
        add_tree(z, os.path.join(ROOT, sub), "bot-bridge/" + sub)
    for f in ("README.md", "BOT-SKILL.md"):
        info = zipfile.ZipInfo("bot-bridge/docs/" + f, (2026, 11, 8, 0, 0, 0)); info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, open(os.path.join(ROOT, "docs", f), "rb").read())
print("built", sorted(os.listdir(DIST)))

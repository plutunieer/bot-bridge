import json, os, re
H = os.path.dirname(os.path.abspath(__file__))
m = json.load(open(os.path.join(H, "extension", "manifest.json")))
for lang in ("en", "de"):
    msg = json.load(open(os.path.join(H, "extension", "_locales", lang, "messages.json"), encoding="utf-8"))
    m.setdefault("_loc", {})[lang] = msg
items = {
  "name (manifest)": (m["_loc"]["en"]["extName"]["message"], 45), "short_name": (m["short_name"], 12),
  "description EN (_locales)": (m["_loc"]["en"]["extDescription"]["message"], 132), "description DE (_locales)": (m["_loc"]["de"]["extDescription"]["message"], 132),
}
t = open(os.path.join(H, "LISTING.md"), encoding="utf-8").read()
for lab, rx in [("short EN", r"\*\*Short description.*?\n`(.*?)`"), ("short DE", r"\*\*Kurzbeschreibung.*?\n`(.*?)`")]:
    items[lab] = (re.search(rx, t, re.S).group(1), 132)
for blk, lab in zip(re.findall(r"```\n(.*?)```", t, re.S)[:3], ["detailed EN", "detailed DE", "single purpose"]):
    items[lab] = (blk, 16000 if "detailed" in lab else 1000)
ok = True
for k, (v, mx) in items.items():
    flag = "OK " if len(v) <= mx else "TOO LONG"; ok &= len(v) <= mx
    print(f"{flag} {k}: {len(v)}/{mx}")
raise SystemExit(0 if ok else 1)

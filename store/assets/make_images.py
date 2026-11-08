"""Build the Chrome Web Store images (Bot Bridge brand) from the real captures in raw/.
Run capture.py first. Output: store/images/."""
import base64, html, json, os
from PIL import Image
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.dirname(HERE); ROOT = os.path.dirname(STORE)
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(STORE, "images"); os.makedirs(OUT, exist_ok=True)
BRAND = os.path.join(ROOT, "brand")
uri = lambda p: "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
ICON_SVG = open(os.path.join(BRAND, "icon.svg")).read().split("-->", 1)[1].replace("</svg>", "")
ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="{s}" height="{s}">' + ICON_SVG + "</svg>"
MARK = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="{s}" height="{s}" style="{st}">'
        '<path d="M40 88 C40 56 56 40 88 40" fill="none" stroke="{c}" stroke-width="12" stroke-linecap="round"/>'
        '<circle cx="40" cy="88" r="16" fill="{c}"/><circle cx="88" cy="40" r="16" fill="{c}"/></svg>')

BASE_CSS = """
*{box-sizing:border-box} body{margin:0;width:1280px;height:800px;overflow:hidden;font-family:Inter,sans-serif;color:#0F172A;
 background:radial-gradient(900px 500px at 100% 0%,#EEF2FF 0%,rgba(238,242,255,0) 70%),#F8FAFC;-webkit-font-smoothing:antialiased}
.lock{position:absolute;left:64px;top:44px;display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px;letter-spacing:-.01em}
h1{position:absolute;left:64px;top:92px;margin:0;font-size:40px;line-height:1.1;font-weight:800;letter-spacing:-.025em}
.sub{position:absolute;left:64px;top:146px;font-size:19px;color:#64748B}
.frame{position:absolute;border-radius:14px;overflow:hidden;box-shadow:0 1px 2px rgba(15,23,42,.06),0 24px 60px -12px rgba(15,23,42,.25);border:1px solid #E2E8F0;background:#fff}
.frame img{display:block;width:100%;height:100%}
.accent{color:#4F46E5}
"""
def lock(): return f'<div class="lock">{ICON.format(s=30)}<span>Bot Bridge</span></div>'
def page(body, w=1280, h=800, css=""):
    return f"<html><head><style>{BASE_CSS}{css}</style></head><body style='width:{w}px;height:{h}px'>{body}</body></html>"

# ---------------------------------------------------------------- 1: real browser + real popup
s1 = page(f"""{lock()}
<h1>Your AI assistant, in <span class="accent">your own Chrome</span></h1>
<div class="sub">Open tabs, read pages, click and type – through a small bridge app on your computer.</div>
<div class="frame" style="left:184px;top:212px;width:912px;height:570px"><img src="{uri(os.path.join(RAW,'browser_page_popup.png'))}"></div>""")

# ---------------------------------------------------------------- 2: commands
log = json.load(open(os.path.join(RAW, "bot_log.json")))
def short(r):
    res = r["response"].get("result", {}); c = r["request"]["cmd"]
    if c == "navigate": return '{"ok": true, "title": "%s"}' % res["title"]
    if c == "get_page":
        if "found" in res["text"]:
            t = " ".join(res["text"].split()); i = t.index("4 cafés"); return '{"ok": true, "text": "%s…"}' % t[i:i+44]
        e = res["elements"]; return '{"ok": true, "elements": [\n  {"index": 0, "role": "%s", "label": "%s"},\n  {"index": 1, "role": "%s", "text": "%s"}]}' % (e[0]["role"], e[0]["label"], e[1]["role"], e[1]["text"])
    if c == "type": return '{"ok": true, "typed": true, "value": "%s"}' % res["value"]
    if c == "click": return '{"ok": true, "clicked": "%s", "text": "%s"}' % (res["tag"], res["text"])
lines = []
for r in log:
    rq = r["request"]; c = rq["cmd"]
    args = " ".join(f"{k}={v}" for k, v in rq.items() if k not in ("cmd", "max_chars"))
    args = args.replace("http://127.0.0.1:8812/index.html", "http://127.0.0.1:8812/")
    lines.append(f'<div class="p"><span class="d">$</span> gbb {html.escape(c)} <span class="a">{html.escape(args)}</span></div><div class="o">{html.escape(short(r))}</div>')
chips = "".join(f'<span class="chip">{c}</span>' for c in ["open_url", "get_page", "click", "type", "press_key", "scroll", "wait_for", "screenshot", "tabs"])
s2 = page(f"""{lock()}
<h1>Simple commands. <span class="accent">Real browser actions.</span></h1>
<div class="sub">Your assistant sends a command – Bot Bridge carries it out in the tab and returns the result.</div>
<div class="frame" style="left:64px;top:222px;width:720px;height:450px"><img src="{uri(os.path.join(RAW,'browser_page.png'))}"></div>
<div class="term"><div class="bar"><i></i><i></i><i></i><span>assistant → bridge · 127.0.0.1</span></div>{''.join(lines)}</div>
<div class="chips">{chips}</div>""", css="""
.term{position:absolute;left:808px;top:222px;width:408px;height:450px;border-radius:14px;background:#0F172A;padding:0 20px 18px;
 font:12.5px/1.5 'DejaVu Sans Mono',monospace;color:#CBD5E1;box-shadow:0 24px 60px -12px rgba(15,23,42,.35);overflow:hidden}
.bar{display:flex;align-items:center;gap:6px;height:38px;margin:0 -20px 6px;padding:0 14px;border-bottom:1px solid #1E293B;font:12px Inter;color:#64748B}
.bar i{width:10px;height:10px;border-radius:50%;background:#334155}.bar span{margin-left:8px}
.p{margin-top:10px;color:#F8FAFC;white-space:pre-wrap}.p .d{color:#818CF8}.p .a{color:#A5B4FC}
.o{color:#94A3B8;white-space:pre-wrap;word-break:break-word}
.chips{position:absolute;left:64px;top:708px;display:flex;gap:10px;flex-wrap:wrap;width:1152px}
.chip{font:500 14px 'DejaVu Sans Mono',monospace;color:#4338CA;background:#EEF2FF;border:1px solid #C7D2FE;border-radius:999px;padding:7px 14px}
""")

# ---------------------------------------------------------------- 3: how it works
ic_chat = '<svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="#4F46E5" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M8 12a6 6 0 0 1 6-6h20a6 6 0 0 1 6 6v14a6 6 0 0 1-6 6H20l-8 8v-8h0a4 4 0 0 1-4-4z"/><path d="M17 19h14M17 25h8"/></svg>'
ic_term = '<svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="#4F46E5" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="8" width="38" height="32" rx="6"/><path d="M13 19l6 5-6 5M23 30h11"/></svg>'
ic_web = '<svg viewBox="0 0 48 48" width="48" height="48" fill="none" stroke="#4F46E5" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="8" width="38" height="32" rx="6"/><path d="M5 17h38"/><circle cx="11" cy="12.5" r=".5"/><circle cx="16" cy="12.5" r=".5"/><path d="M18 33c0-6 3-9 9-9" /><circle cx="18" cy="33" r="2.5" fill="#4F46E5"/><circle cx="27" cy="24" r="2.5" fill="#4F46E5"/></svg>'
cards = [(ic_chat, "Your AI assistant", "e.g. Grok Bot – runs commands on your computer, with your approval."),
         (ic_term, "Bridge app", "bridge.py · Python, no extra packages. Listens on 127.0.0.1 only, secret token."),
         (ic_web, "Bot Bridge extension", "Opens tabs, reads pages, clicks and types in your Chrome.")]
conn = '<svg width="76" height="40" viewBox="0 0 76 40"><path d="M10 20 H66" stroke="#A5B4FC" stroke-width="3" stroke-dasharray="2 7" stroke-linecap="round"/><circle cx="8" cy="20" r="6" fill="#4F46E5"/><circle cx="68" cy="20" r="6" fill="#4F46E5"/></svg>'
row = conn.join(f'<div class="card"><div class="ic">{i}</div><b>{t}</b><p>{d}</p></div>' for i, t, d in cards)
check = '<svg width="18" height="18" viewBox="0 0 18 18"><circle cx="9" cy="9" r="9" fill="#4F46E5"/><path d="M5 9.2l2.6 2.6L13 6.6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
feats = "".join(f'<span class="feat">{check}{f}</span>' for f in ["Localhost only", "Secret token", "On/off switch", "Consent first", "No tracking"])
s3 = page(f"""{lock()}
<h1>How it works</h1>
<div class="sub">Everything stays on your computer. The extension sends nothing to any server.</div>
<div class="row">{row}</div><div class="feats">{feats}</div>""", css="""
.row{position:absolute;left:64px;right:64px;top:300px;display:flex;align-items:center;justify-content:space-between}
.card{width:330px;height:260px;background:#fff;border:1px solid #E2E8F0;border-radius:18px;padding:30px;box-shadow:0 1px 2px rgba(15,23,42,.05),0 18px 40px -16px rgba(15,23,42,.18)}
.card .ic{width:72px;height:72px;border-radius:16px;background:#EEF2FF;display:flex;align-items:center;justify-content:center;margin-bottom:22px}
.card b{display:block;font-size:22px;letter-spacing:-.01em}.card p{margin:8px 0 0;font-size:16px;line-height:1.45;color:#64748B}
.feats{position:absolute;left:64px;right:64px;top:640px;display:flex;justify-content:center;gap:14px}
.feat{display:flex;align-items:center;gap:9px;font-size:16px;font-weight:600;background:#fff;border:1px solid #E2E8F0;border-radius:999px;padding:10px 18px}
""")

# ---------------------------------------------------------------- 4: consent / control
pts = [("Nothing connects until you agree", "A clear notice explains what the extension can do."),
       ("Only your own computer", "Data goes to the bridge on 127.0.0.1 – never to a server."),
       ("Off in one click", "The switch stops all access instantly. Revoke consent any time.")]
plist = "".join(f'<div class="pt">{check.replace("18", "26")}<div><b>{a}</b><span>{b}</span></div></div>' for a, b in pts)
s4 = page(f"""{lock()}
<h1 style="top:200px">You stay<br><span class="accent">in control.</span></h1>
<div class="pts">{plist}</div>
<div class="frame" style="left:806px;top:64px;width:340px;height:640px;border-radius:16px"><img src="{uri(os.path.join(RAW,'popup_consent@2x.png'))}" style="height:auto"></div>""", css="""
h1{font-size:52px}
.pts{position:absolute;left:64px;top:360px;width:600px}
.pt{display:flex;gap:16px;align-items:flex-start;margin-bottom:26px}.pt svg{flex:none;margin-top:2px}
.pt b{display:block;font-size:21px;letter-spacing:-.01em}.pt span{display:block;font-size:17px;color:#64748B;margin-top:3px}
""")

# ---------------------------------------------------------------- promo tile 440x280
promo = f"""<html><head><style>*{{box-sizing:border-box}}body{{margin:0;width:440px;height:280px;overflow:hidden;font-family:Inter,sans-serif;color:#fff;
 background:radial-gradient(420px 300px at 85% 30%,#6366F1 0%,rgba(99,102,241,0) 70%),linear-gradient(135deg,#4F46E5,#3730A3);position:relative;-webkit-font-smoothing:antialiased}}
.tile{{position:absolute;left:36px;top:40px;width:64px;height:64px;border-radius:16px;background:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 10px 24px -8px rgba(15,23,42,.45)}}
.name{{position:absolute;left:36px;top:124px;font-size:40px;font-weight:800;letter-spacing:-.03em}}
.tag{{position:absolute;left:36px;top:180px;width:260px;font-size:15.5px;line-height:1.4;color:#E0E7FF}}
</style></head><body>
{MARK.format(s=300, c="rgba(255,255,255,.13)", st="position:absolute;right:-110px;top:-40px")}
<div class="tile">{MARK.format(s=56, c="#4F46E5", st="")}</div>
<div class="name">Bot Bridge</div>
<div class="tag">Let your AI assistant use your own Chrome – privately, via localhost.</div>
</body></html>"""

with sync_playwright() as p:
    b = p.chromium.launch()
    for name, doc, w, h in [("screenshot-1-assistant-in-chrome-1280x800.png", s1, 1280, 800),
                            ("screenshot-2-commands-1280x800.png", s2, 1280, 800),
                            ("screenshot-3-how-it-works-1280x800.png", s3, 1280, 800),
                            ("screenshot-4-consent-1280x800.png", s4, 1280, 800),
                            ("promo-small-440x280.png", promo, 440, 280)]:
        pg = b.new_page(viewport={"width": w, "height": h})
        pg.set_content(doc); pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(OUT, name))
    b.close()

for f in os.listdir(OUT):   # Web Store: 24-bit PNG (no alpha) for screenshots/tiles
    if f != "store-icon-128.png":
        Image.open(os.path.join(OUT, f)).convert("RGB").save(os.path.join(OUT, f))
for f in sorted(os.listdir(OUT)):
    im = Image.open(os.path.join(OUT, f)); print(f, im.size, im.mode)

"""Render brand SVGs to crisp PNGs with Chromium (transparent background)."""
import os, sys
from playwright.sync_api import sync_playwright
H = os.path.dirname(os.path.abspath(__file__))
def render(svg, out, size):
    src = open(svg if os.path.isabs(svg) else os.path.join(H, svg)).read()
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        pg.set_content(f'<html><body style="margin:0;background:transparent">{src.replace("<svg ", f"<svg style=\"display:block;width:{size}px;height:{size}px\" ", 1)}</body></html>')
        pg.screenshot(path=out, omit_background=True); b.close()
if __name__ == "__main__":
    for svg, out, size in [a.split(":") for a in sys.argv[1:]]:
        render(svg, out, int(size)); print(out)

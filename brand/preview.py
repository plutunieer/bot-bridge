import sys, os
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(__file__)); from render import render
files = sys.argv[1:]
row = 150; W = 520
sheet = Image.new("RGB", (W, row * len(files)), (255, 255, 255)); d = ImageDraw.Draw(sheet)
for n, f in enumerate(files):
    y = n * row + 10; x = 10
    for s in (128, 48, 32, 16):
        render(f, f"/tmp/p{s}.png", s); im = Image.open(f"/tmp/p{s}.png"); sheet.paste(im, (x, y), im); x += s + 14
    z = Image.open("/tmp/p16.png").resize((112, 112), Image.NEAREST); sheet.paste(z, (x + 10, y), z)
    # dark-toolbar test at 16
    dk = Image.new("RGB", (40, 40), (32, 33, 36)); im = Image.open("/tmp/p16.png"); dk.paste(im, (12, 12), im); sheet.paste(dk, (x + 130, y))
    d.text((x + 130, y + 50), os.path.basename(f), fill=(0, 0, 0))
sheet.save("/tmp/sheet.png")

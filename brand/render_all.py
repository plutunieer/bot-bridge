import os
from render import render
H = os.path.dirname(os.path.abspath(__file__)); R = os.path.dirname(H)
jobs = [("icon-16.svg", "extension/icons/icon16.png", 16), ("icon.svg", "extension/icons/icon32.png", 32),
        ("icon.svg", "extension/icons/icon48.png", 48), ("icon.svg", "extension/icons/icon128.png", 128),
        ("store-icon.svg", "store/images/store-icon-128.png", 128)]
for svg, out, s in jobs:
    os.makedirs(os.path.dirname(os.path.join(R, out)), exist_ok=True)
    render(os.path.join(H, svg), os.path.join(R, out), s); print(out)

<p align="center">
  <img src="icon.png" width="96" height="96" alt="Bot Bridge logo">
</p>

<h1 align="center">Bot Bridge</h1>

<p align="center">
  Let your own AI assistant use <b>your own Chrome</b> – open tabs, read pages, click, type and take screenshots.<br>
  Privately, through a small bridge app on your computer (127.0.0.1 only).
</p>

<p align="center">
  <a href="https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip"><b>⬇ Download the bridge</b></a> ·
  <a href="https://github.com/plutunieer/bot-bridge/releases/latest">All downloads</a> ·
  Chrome Web Store: <i>coming soon</i> ·
  <a href="https://plutunieer.github.io/bot-bridge/privacy-policy.html">Privacy policy</a> ·
  <a href="#deutsch">Deutsch</a>
</p>

---

## How it works

```
AI assistant ──(command on your computer)──► bridge.py (127.0.0.1:8765) ◄──── Bot Bridge extension ──► your Chrome tabs
```

1. **Your AI assistant** (for example Grok Bot, which can run commands on your computer with your approval) sends a simple command such as `get_page` or `click index=3`.
2. **The bridge app** (`bridge.py`, Python 3, no extra packages, Windows/macOS/Linux) listens only on `127.0.0.1` and requires a secret token.
3. **The Bot Bridge extension** picks up the command and carries it out in your browser, then returns the result.

Commands: `list_tabs`, `open_url`, `navigate`, `activate_tab`, `close_tab`, `back` / `forward` / `reload`, `get_page` (text + numbered list of buttons, links and fields), `click`, `type`, `press_key`, `scroll`, `wait_for`, `screenshot`.

## Install

**1. Bridge app**

1. Install [Python 3](https://www.python.org/downloads/) if you don't have it (`python3 --version`, on Windows `py --version`).
2. Download **[bridge-app.zip](https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip)** and unzip it, e.g. into your home folder → folder `bot-bridge`.
3. Start it:
   ```
   python3 bot-bridge/bridge/bridge.py serve        # Windows: py -3 bot-bridge\bridge\bridge.py serve
   ```
   It prints the **port** (8765) and a **token**. Show the token again any time with `python3 bot-bridge/bridge/bridge.py token`.

**2. Chrome extension**

- **Chrome Web Store:** *coming soon* – one-click install.
- **Until then:** download **[extension-store.zip](https://github.com/plutunieer/bot-bridge/releases/latest/download/extension-store.zip)**, unzip it, open `chrome://extensions`, switch on **Developer mode**, click **Load unpacked** and select the unzipped folder.

**3. Connect**

Click the Bot Bridge icon (pin it via the puzzle icon) → read the notice and tick **I understand and agree** → paste port and token → **Save**. The popup shows **Connected** and the icon gets an **ON** badge.

Test: `python3 bot-bridge/bridge/bridge.py send list_tabs` lists your open tabs.

**4. Tell your assistant**

*"Use Bot Bridge to control my Chrome – instructions are in `bot-bridge/docs/BOT-SKILL.md`."*
The file is included in `bridge-app.zip` and explains setup, status checks and every command with examples.

## Privacy & security

- The extension talks **only** to the bridge on `127.0.0.1` (your computer). It sends nothing to the developer or any server – no analytics, no tracking, no ads.
- Every request needs a secret token that is generated on your computer. The bridge rejects requests from websites.
- Nothing connects until you agree to the notice in the popup. An on/off switch stops all access instantly.
- All actions run code that ships inside the extension – no remote code.
- Anyone who has your token *and* can run commands on your computer can control your browser, including logged-in sites. Only give it to your own assistant.

Full privacy policy: <https://plutunieer.github.io/bot-bridge/privacy-policy.html>

## Limitations

- Chrome doesn't allow scripting `chrome://` pages, the Chrome Web Store or the PDF viewer (screenshots still work).
- Clicks and keys are simulated in the page. Captchas, file pickers, native browser dialogs and sites with strict bot detection need to be done by hand.
- Content inside iframes from other domains isn't included in `get_page`.

## Downloads (each release)

| File | What it is |
|---|---|
| `bridge-app.zip` | The bridge app + command-line helpers + docs (`README.md`, `BOT-SKILL.md`) |
| `extension-store.zip` | The Chrome extension (same package as submitted to the Chrome Web Store) |
| `bot-bridge.zip` | Full source: bridge, extension (store + developer build), tests, store material, brand |

## Support

Questions, bugs and ideas: [open an issue](https://github.com/plutunieer/bot-bridge/issues).

Bot Bridge is an independent project and is not affiliated with or endorsed by the makers of Grok or Grok Bot. Licensed under the [MIT License](LICENSE).

---

<a name="deutsch"></a>
## Deutsch

**Bot Bridge** lässt deinen eigenen KI-Assistenten (z. B. Grok Bot) **dein eigenes Chrome** bedienen: Tabs öffnen, Seiten lesen, klicken, tippen, Screenshots machen – privat, über eine kleine Bridge-App auf deinem Computer (nur 127.0.0.1).

**Installation**

1. [Python 3](https://www.python.org/downloads/) installieren (falls nötig).
2. **[bridge-app.zip](https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip)** herunterladen und entpacken (Ordner `bot-bridge`).
3. Bridge starten: `python3 bot-bridge/bridge/bridge.py serve` (Windows: `py -3 bot-bridge\bridge\bridge.py serve`). Port und Token werden angezeigt.
4. Erweiterung: **Chrome Web Store – bald verfügbar.** Bis dahin [extension-store.zip](https://github.com/plutunieer/bot-bridge/releases/latest/download/extension-store.zip) entpacken → `chrome://extensions` → **Entwicklermodus** → **Entpackte Erweiterung laden**.
5. Bot-Bridge-Symbol öffnen → Hinweis lesen und **zustimmen** → Port und Token einfügen → **Speichern**. Das Popup zeigt **Verbunden**, das Symbol ein **ON**.
6. Deinem Assistenten sagen: *„Nutze Bot Bridge, Anleitung in `bot-bridge/docs/BOT-SKILL.md`.“*

**Datenschutz:** Die Erweiterung spricht nur mit der Bridge auf 127.0.0.1 und sendet nichts an den Entwickler oder an Server. Jede Anfrage braucht einen geheimen Token; nichts verbindet sich ohne deine Zustimmung; Ein/Aus-Schalter im Popup. Datenschutzerklärung: <https://plutunieer.github.io/bot-bridge/privacy-policy.html>

**Support:** [Issue eröffnen](https://github.com/plutunieer/bot-bridge/issues). Unabhängiges Projekt, nicht verbunden mit den Herstellern von Grok oder Grok Bot. MIT-Lizenz.

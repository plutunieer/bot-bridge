<p align="center"><img src="../brand/icon.svg" width="88" alt="Bot Bridge"></p>

# Bot Bridge

**Deutsch** · [English](#english)

Mit Bot Bridge kann dein eigener KI-Assistent (zum Beispiel Grok Bot) **deinen eigenen Chrome** bedienen: Tabs öffnen, Seiten lesen, klicken, tippen, scrollen, Screenshots machen.
Bot Bridge ist ein unabhängiges Projekt und nicht mit den Herstellern von Grok oder Grok Bot verbunden. Projekt & Support: https://github.com/plutunieer/bot-bridge (Issues).

```
KI-Assistent ──(Shell-Befehl auf deinem PC)──► bridge.py (127.0.0.1:8765) ◄──(Long-Poll)── Bot-Bridge-Erweiterung ──► deine Tabs
```

* `bridge/bridge.py` – kleiner lokaler Server, nur Python 3 (keine Pakete nötig), läuft auf Windows, macOS, Linux. Hört **nur auf 127.0.0.1**.
* `extension/` – die Chrome-Erweiterung (Manifest V3), Entwickler-Version.
* `client/` – `gbb` (macOS/Linux), `gbb.cmd` (Windows), `gbb-curl.sh` (nur curl).
* `docs/BOT-SKILL.md` – Anleitung, die jeder KI-Assistent befolgen kann.

## Installation (ca. 3 Minuten)

> **Chrome Web Store:** Sobald Bot Bridge im Store ist, installierst du die Erweiterung dort mit einem Klick (Schritt 4 entfällt) und lädst nur die Bridge ([`bridge-app.zip`](https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip)). Die Store-Version hat kein `eval` und fragt beim ersten Start nach deiner Zustimmung.

1. **Python 3** muss installiert sein (`python3 --version`, unter Windows `py --version`). Download: https://www.python.org/downloads/
2. [`bridge-app.zip`](https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip) (nur Bridge) oder den kompletten Quellcode von https://github.com/plutunieer/bot-bridge/releases/latest herunterladen und als Ordner `bot-bridge` entpacken, z. B. im Benutzerordner.
3. **Bridge starten** (Terminal / Eingabeaufforderung):
   ```
   python3 bot-bridge/bridge/bridge.py serve        # Windows: py -3 bot-bridge\bridge\bridge.py serve
   ```
   Es erscheinen **Port** (8765) und der Hinweis, dass der Token **nicht** ausgegeben wird. Den Token holst du in einem Terminal, das du kontrollierst: `bridge.py token`. Leite `token` und `new-token` nicht in ein Log um.
4. **Erweiterung laden:** `chrome://extensions` öffnen → **Entwicklermodus** einschalten → **Entpackte Erweiterung laden** → den entpackten Ordner von [`extension-store.zip`](https://github.com/plutunieer/bot-bridge/releases/latest/download/extension-store.zip) wählen (oder `bot-bridge/extension` aus dem kompletten Quellcode).
5. Puzzle-Symbol → **Bot Bridge** anheften → öffnen → Port und Token einfügen → **Save · Speichern**.
6. Das Popup zeigt **Connected · Verbunden**, das Symbol ein **ON**-Badge.
7. Deinem Assistenten sagen: *„Nutze Bot Bridge, Anleitung in `bot-bridge/docs/BOT-SKILL.md`.“*

Test: `python3 bridge/bridge.py send list_tabs` listet deine offenen Tabs.

## Sicherheit

* Die Bridge lauscht **nur auf 127.0.0.1** – andere Geräte im Netz kommen nicht dran.
* Jede Anfrage braucht den **geheimen Token** (gespeichert in `~/.bot-bridge/config.json`, nur für dich lesbar; eine bestehende `~/.grok-chrome-bridge/` aus Version 1.0 wird weiter benutzt). Neuer Token: `bridge.py new-token`.
* Anfragen von Webseiten (fremder `Origin`) und fremde `Host`-Header (DNS-Rebinding) werden abgelehnt.
* Die Erweiterung sendet **direkt nur** an `http://127.0.0.1:<port>`. Sie sendet nichts an den Entwickler. Kein Tracking, keine Analytics. Der Assistent, den du verbindest, kann Resultate ausserhalb des Geräts verarbeiten. Das ist keine Offline-Garantie.
* Wer den Token hat und Befehle auf deinem PC ausführen kann, kann deinen Browser steuern – inklusive eingeloggter Seiten. Gib den Token nur deinem eigenen Assistenten.
* **Ein/Aus-Schalter** im Popup: Aus = kein Zugriff. Die Bridge beenden (Strg+C) wirkt ebenso.
* Entwickler-Version: `eval` (beliebiges JavaScript) ist an und im Popup abschaltbar. Die Store-Version enthält kein `eval`.
* Die Erweiterung braucht `<all_urls>`, damit sie auf jeder Seite lesen/klicken kann.

## Laufende Kopie aktualisieren

Ein Dienst kann eine **Kopie** von `bridge.py` starten, nicht den Ordner, den du gerade entpackt hast. Ersetze die Datei, die wirklich ausgeführt wird, und starte den Dienst neu. Unter macOS ist ein bekanntes Layout `~/Library/Application Support/BotBridge/bridge.py` per launchd, mit der Konfiguration in `~/.grok-chrome-bridge/config.json` (1.0) oder `~/.bot-bridge/config.json`. Unter Linux ist es das `ExecStart`-Skript der systemd-User-Unit, unter Windows das Skript der geplanten Aufgabe. `serve` ab 1.0.3 schreibt den Token nicht ins Log. Logs älterer Versionen mit einer Zeile `Token:` löschen und `bridge.py new-token` ausführen. Dieses Repository ändert deinen Computer nicht von selbst.

## Grenzen

* `chrome://`-Seiten, der Chrome Web Store, andere Erweiterungen und der PDF-Viewer können nicht per Script bedient werden (Chrome-Sperre). Screenshots gehen trotzdem.
* Klicks/Tastendrücke sind JavaScript-Events (`isTrusted=false`). Fast alle Seiten funktionieren; Seiten mit strenger Bot-Erkennung, Datei-Upload-Dialoge, Captchas und native Browser-Dialoge nicht.
* `eval` kann durch die Content-Security-Policy einer Seite blockiert sein.
* Inhalte in iframes fremder Domains erscheinen nicht in `get_page`.
* Screenshots zeigen nur den sichtbaren Bereich; der Tab wird dafür kurz aktiviert.

---

<a name="english"></a>
# English

Bot Bridge lets your own AI assistant (for example Grok Bot) drive **your own Chrome**: open tabs, read pages, click, type, scroll, take screenshots.
Bot Bridge is an independent project, not affiliated with or endorsed by the makers of Grok or Grok Bot. Project & support: https://github.com/plutunieer/bot-bridge (Issues).

```
AI assistant ──(shell command on your computer)──► bridge.py (127.0.0.1:8765) ◄──(long-poll)── Bot Bridge extension ──► your tabs
```

* `bridge/bridge.py` – tiny local server, Python 3 standard library only, Windows/macOS/Linux. Listens on **127.0.0.1 only**.
* `extension/` – the Chrome extension (Manifest V3), developer build.
* `client/` – `gbb` (macOS/Linux), `gbb.cmd` (Windows), `gbb-curl.sh` (curl only).
* `docs/BOT-SKILL.md` – instructions any AI assistant can follow.

## Install (about 3 minutes)

> **Chrome Web Store:** once Bot Bridge is in the store, install the extension there with one click (skip step 4) and only download the bridge ([`bridge-app.zip`](https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip)). The store build has no `eval` command and asks for your consent on first start.

1. Make sure **Python 3** is installed (`python3 --version`, on Windows `py --version`). https://www.python.org/downloads/
2. Download [`bridge-app.zip`](https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip) (bridge only) or the full source from https://github.com/plutunieer/bot-bridge/releases/latest and unzip it as a folder `bot-bridge`, e.g. in your home folder.
3. **Start the bridge:**
   ```
   python3 bot-bridge/bridge/bridge.py serve        # Windows: py -3 bot-bridge\bridge\bridge.py serve
   ```
   It prints the **port** (8765) and states that the token is **not** printed. Show the token in a terminal you control: `bridge.py token`. Do not redirect `token` or `new-token` into a log.
4. **Load the extension:** `chrome://extensions` → **Developer mode** → **Load unpacked** → pick the unzipped [`extension-store.zip`](https://github.com/plutunieer/bot-bridge/releases/latest/download/extension-store.zip) folder (or `bot-bridge/extension` from the full source).
5. Puzzle icon → pin **Bot Bridge** → open it → paste port and token → **Save**.
6. The popup shows **Connected** and the icon gets an **ON** badge.
7. Tell your assistant: *"Use Bot Bridge, instructions in `bot-bridge/docs/BOT-SKILL.md`."*

Smoke test: `python3 bridge/bridge.py send list_tabs` lists your open tabs.

## Security

* The bridge listens on **127.0.0.1 only**.
* Every request needs the **secret token** (stored in `~/.bot-bridge/config.json`, mode 600; an existing `~/.grok-chrome-bridge/` from version 1.0 keeps working). Rotate with `bridge.py new-token`.
* Requests from web pages (foreign `Origin`) and non-loopback `Host` headers (DNS rebinding) are rejected.
* The extension sends **directly only** to `http://127.0.0.1:<port>`. It does not send data to the developer. No tracking, no analytics. The assistant you connect may process results off the device. This is not an offline guarantee.
* Anyone who has the token and can run commands on your computer can control your browser, including logged-in sites. Only give it to your own assistant.
* **On/off switch** in the popup; stopping the bridge (Ctrl+C) does the same.
* Developer build: `eval` (arbitrary JavaScript) is on and can be switched off. The store build has no `eval`.
* The extension needs `<all_urls>` so it can read/click on any site.

## Updating the copy that is actually running

A service may run a **copied** `bridge.py`, not the folder you just unzipped. Replace the file that is executed, then restart that service. On macOS one layout is `~/Library/Application Support/BotBridge/bridge.py` via launchd, with config in `~/.grok-chrome-bridge/config.json` (1.0) or `~/.bot-bridge/config.json`. On Linux it is the systemd user unit's `ExecStart` script. On Windows it is the script the scheduled task runs. From 1.0.3, `serve` does not write the token to the log. Delete older logs that contain a `Token:` line and run `bridge.py new-token`. This repository does not change your computer by itself.

## Limitations

* `chrome://` pages, the Chrome Web Store, other extensions' pages and the PDF viewer cannot be scripted (Chrome restriction). Screenshots still work.
* Clicks/keys are synthetic DOM events (`isTrusted=false`). Sites with strict bot detection, file pickers, captchas and native dialogs do not work.
* `eval` may be blocked by a page's Content-Security-Policy.
* Cross-origin iframes are not included in `get_page`.
* Screenshots capture only the visible part of the tab and briefly activate it.

## Builds

* `extension/` – local developer build (includes the optional `eval` command).
* `store/extension/` → `dist/extension-store.zip` – Chrome Web Store build 1.0.3, generated by `python3 store/build_store.py` (no eval, no activeTab, consent screen, en/de locales). Submission material: `store/` (`LISTING.md`, `SUBMIT-CHECKLIST.md`, `privacy-policy.html`, `images/`). Store images were recaptured for 1.0.3: the consent screenshot matches notice version 2, and the how-it-works image and promo tile no longer claim that data never leaves the computer.
* Brand: `brand/` (SVG master icon, colours, type) → `python3 brand/render_all.py`.
* `python3 build_dist.py` → `dist/bot-bridge.zip`, `dist/extension.zip`, `dist/bridge-app.zip`.

## Testing

`test/e2e_test.py` starts the bridge, loads the extension in Playwright Chromium and runs the end-to-end checks against `test/site/` (store build: `GBB_EXT=../store/extension GBB_NO_EVAL=1 python3 e2e_test.py`).

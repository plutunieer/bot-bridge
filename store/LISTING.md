# Chrome Web Store listing – Bot Bridge 1.0.4

Links used in this listing:
- Bridge download: https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip
- Homepage: https://github.com/plutunieer/bot-bridge
- Privacy policy: https://plutunieer.github.io/bot-bridge/privacy-policy.html
- Support / contact: https://github.com/plutunieer/bot-bridge/issues

Character counts were checked with `check_lengths.py`.

---

## Name

The product name is **Bot Bridge** (EN and DE). "Grok" is not part of the name or the visuals; the descriptions only mention Grok Bot as an example of a compatible assistant and state that this is an independent project.

---

## English (primary language)

**Name** (max 45): `Bot Bridge`

**Short description / summary** (max 132; this is the manifest `description`):
`Lets your AI assistant (e.g. Grok Bot) control this Chrome through a bridge on your computer. Extension traffic is 127.0.0.1 only.`

**Detailed description:**
```
Let your own AI assistant use YOUR Chrome – your tabs, your logins – instead of a separate cloud browser.

Bot Bridge connects Chrome to a small bridge app running on your own computer. Your AI assistant (for example Grok Bot, which can run commands on your computer with your approval) sends simple commands to that bridge, and the extension carries them out in your browser:

• open, switch, reload and close tabs, go back/forward
• read a page: title, URL, visible text and a numbered list of buttons, links and fields
• click, type into fields, press keys, scroll, wait for elements
• take a screenshot of the visible tab
• place a file you name on this computer into a file input (more than one file when the control allows it). The bridge reads only that named regular file. The page can then upload it. This does not drive the operating system's file dialog.

IMPORTANT – A SEPARATE BRIDGE APP IS REQUIRED
This extension does nothing on its own. It needs the free bridge app (bridge.py, Python 3, no extra packages, Windows/macOS/Linux) running on the same computer:
1. Download the bridge: https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip
2. Start it: python3 bridge.py serve (Windows: py -3 bridge.py serve). It shows the port and does not print the token. In another terminal run python3 bridge.py token.
3. Open this extension, read and accept the notice, paste port and token, Save. The icon shows an "ON" badge when connected. Agree again if an update changes the notice.
4. Tell your assistant to use the bridge (instructions for assistants are included in the download: docs/BOT-SKILL.md).

PRIVACY & SECURITY
• The extension communicates directly only with the bridge on your computer (127.0.0.1). It does not send data to the extension developer. No analytics, no tracking, no ads.
• On your commands it handles tab URLs and titles, page text, form-field values, screenshots, and files you explicitly name. Those can contain sensitive personal information. The bridge makes results available to the AI assistant you chose; that assistant may process data off your device under its own privacy policy. A file placed into a page can also be uploaded by that website. This is not an end-to-end offline guarantee.
• Password-type fields, and fields marked current-password or new-password, are masked only when the extension reads the page or returns a click/type result. Screenshots, other fields (including one-time codes), page text, and text you tell the assistant to type are not masked.
• Every request needs a secret token that only you have; the bridge refuses requests from websites. Nothing connects until you agree to the notice in the popup. An on/off switch stops all access instantly.
• All actions in this store package are performed by code shipped inside the extension. No remote code is loaded or executed.

LIMITATIONS
Chrome does not allow extensions to script chrome:// pages or the Chrome Web Store. Captchas and native dialogs (the operating system's file-open and save dialogs, print, and permission prompts) still need a person. Naming a file in an upload command fills a file input without opening that dialog.

Independent project – not affiliated with or endorsed by the makers of Grok or Grok Bot.
Source code & support: https://github.com/plutunieer/bot-bridge
Privacy policy: https://plutunieer.github.io/bot-bridge/privacy-policy.html
```

---

## Deutsch (zweite Sprache)

**Name** (max 45): `Bot Bridge`

**Kurzbeschreibung** (max 132):
`Lässt deinen KI-Assistenten (z. B. Grok Bot) dein Chrome über eine Bridge auf deinem Computer steuern. Erweiterung nur zu 127.0.0.1.`

(The package is localised: `_locales/en` and `_locales/de` hold these two short descriptions, so the German store page shows the German summary automatically. Enter the German detailed description in the dashboard under the German language.)

**Ausführliche Beschreibung:**
```
Lass deinen eigenen KI-Assistenten DEIN Chrome benutzen – deine Tabs, deine Logins – statt eines separaten Cloud-Browsers.

Bot Bridge verbindet Chrome mit einer kleinen Bridge-App auf deinem eigenen Computer. Dein KI-Assistent (zum Beispiel Grok Bot, der mit deiner Freigabe Befehle auf deinem Computer ausführen kann) schickt einfache Befehle an diese Bridge, und die Erweiterung führt sie in deinem Browser aus:

• Tabs öffnen, wechseln, neu laden und schliessen, vor/zurück
• Seiten lesen: Titel, URL, sichtbarer Text und eine nummerierte Liste von Buttons, Links und Feldern
• klicken, in Felder tippen, Tasten drücken, scrollen, auf Elemente warten
• Screenshot des sichtbaren Tabs
• eine von dir genannte Datei auf diesem Computer in ein Dateifeld setzen (mehrere Dateien, wenn das Feld das erlaubt). Die Bridge liest nur diese genannte reguläre Datei. Die Seite kann sie danach hochladen. Der Dateidialog des Betriebssystems wird dabei nicht bedient.

WICHTIG – EINE SEPARATE BRIDGE-APP IST NÖTIG
Die Erweiterung macht allein nichts. Sie braucht die kostenlose Bridge-App (bridge.py, Python 3, keine Zusatzpakete, Windows/macOS/Linux) auf demselben Computer:
1. Bridge herunterladen: https://github.com/plutunieer/bot-bridge/releases/latest/download/bridge-app.zip
2. Starten: python3 bridge.py serve (Windows: py -3 bridge.py serve). Sie zeigt den Port und gibt den Token nicht aus. In einem anderen Terminal: python3 bridge.py token.
3. Erweiterung öffnen, Hinweis lesen und zustimmen, Port und Token einfügen, Speichern. Das Symbol zeigt ein „ON“-Badge, wenn verbunden. Bei einem geänderten Hinweis erneut zustimmen.
4. Deinem Assistenten sagen, dass er die Bridge nutzen soll (Anleitung für Assistenten im Download: docs/BOT-SKILL.md).

DATENSCHUTZ & SICHERHEIT
• Die Erweiterung kommuniziert direkt nur mit der Bridge auf deinem Computer (127.0.0.1). Sie sendet keine Daten an den Erweiterungsentwickler. Keine Analyse, kein Tracking, keine Werbung.
• Auf deine Befehle verarbeitet sie Tab-URLs und -Titel, Seitentext, Formularwerte, Screenshots und Dateien, die du ausdrücklich nennst. Diese können sensible personenbezogene Angaben enthalten. Die Bridge stellt die Resultate deinem gewählten KI-Assistenten bereit; dieser kann Daten gemäss seiner eigenen Datenschutzerklärung ausserhalb deines Geräts verarbeiten. Eine Datei in einer Seite kann die Website ebenfalls hochladen. Das ist keine Garantie für eine vollständig lokale Verarbeitung.
• Passwortfelder und Felder mit current-password oder new-password werden nur beim Auslesen der Seite und im Klick-/Tipp-Resultat maskiert. Screenshots, andere Felder (auch Einmalcodes), Seitentext und Text, den du tippen lässt, werden nicht maskiert.
• Jede Anfrage braucht einen geheimen Token, den nur du hast; Anfragen von Webseiten lehnt die Bridge ab. Nichts verbindet sich, bevor du dem Hinweis im Popup zustimmst. Ein Ein/Aus-Schalter stoppt jeden Zugriff sofort.
• Alle Aktionen in diesem Store-Paket laufen mit Code, der in der Erweiterung enthalten ist. Es wird kein Code von aussen geladen oder ausgeführt.

GRENZEN
Chrome erlaubt Erweiterungen keinen Zugriff auf chrome://-Seiten oder den Chrome Web Store. Captchas und native Dialoge (Datei-öffnen und Speichern des Betriebssystems, Drucken, Berechtigungsabfragen) musst du selbst erledigen. Ein Upload-Befehl setzt eine genannte Datei in ein Dateifeld, ohne diesen Dialog zu öffnen.

Unabhängiges Projekt – nicht verbunden mit den Herstellern von Grok oder Grok Bot.
Quellcode & Support: https://github.com/plutunieer/bot-bridge
Datenschutzerklärung: https://plutunieer.github.io/bot-bridge/privacy-policy.html
```

---

## Category

**Productivity → Tools** (alternative: Productivity → Developer Tools). Language: English (add German).

---

## Privacy practices tab (paste as-is)

**Single purpose description** (EN):
```
Lets the user's own AI assistant operate the user's Chrome: open, switch and close tabs, read page text and form fields, click, type, scroll, take screenshots, and place local files the user names into file inputs, using commands from a bridge app the user runs on the same computer. The extension talks only to 127.0.0.1. Results go to the assistant the user chose, which may process them off the device. A named file can also be uploaded by the website.
```

**Permission justifications:**

| Permission | Justification (paste) |
|---|---|
| `tabs` | Needed to list the user's tabs (URL, title), open new tabs, switch, navigate, go back/forward, reload and close tabs when the user's assistant requests it, and to know which window to screenshot. |
| `scripting` | Injects functions bundled in the extension into the page the user's assistant is working on, to read visible text and interactive elements and to click, type, press keys, scroll and wait for elements. No remote code. |
| `storage` | Stores only the extension's own settings in chrome.storage.local: bridge port, the bridge token (a browser-control secret, not a website password), the on/off switch, and consent including the notice version. No page content is stored. |
| `alarms` | Wakes the service worker every 30 seconds so it can reconnect to the local bridge app after Chrome suspends it; without it commands from the user's assistant would stop arriving. |
| Host permission `<all_urls>` | The user chooses which sites the assistant works on, so the extension must read and act on any http or https page. captureVisibleTab also requires this permission. The extension reaches the bridge at http://127.0.0.1 through it. Page data is sent directly only to that local bridge, not to the developer. The bridge gives results to the user's chosen AI assistant, which may process them off the device. This is not an end-to-end offline guarantee. |

**Are you using remote code?** → **No, I am not using remote code.**

The draft dashboard had "Yes" selected with a blank justification. That was unaudited form state, not a finding that the package runs remote code. The uploaded 1.0.2 zip and the corrected 1.0.3 package were scanned: no `eval`, no `new Function`, no string timers, no `importScripts`, no remotely hosted script. Commands are data (command name, URL, CSS selector, text) passed to functions packaged in the extension. `javascript:` and `data:` URLs are rejected. The separate developer build under `extension/` still contains an optional `eval` command and must not be uploaded.

Paste only if the form asks for a justification while "No" is selected, or put it in the reviewer notes:

```
All JavaScript in this package is packaged in the extension. The local bridge sends data only: a command name plus a URL, CSS selector, or text. Those values are arguments to functions shipped in the package. There is no eval, no new Function, and no remotely hosted script. javascript: and data: URLs are rejected. The separate developer build in the repository contains an optional eval command and is not this package.
```

**Data usage**

Local handling must be disclosed. The extension does not filter arbitrary page content, so several categories are incidental rather than a dedicated collector. The developer does not receive the data. That is not a reason to leave a category unchecked. The live checkbox glossary is not fully quoted in the public dashboard docs; the labels below match the form as documented for this item. If a live label is narrower than the note, follow the live label and keep the privacy policy, which already describes the incidental cases.

| Category | Recommend | Factual basis and caveat |
|---|---|---|
| Personally identifiable information | **Yes** | Unfiltered page text, non-password form values, and screenshots can contain names, email addresses, phone numbers, usernames, and account numbers. No redaction. Not a dedicated identity product. |
| Health information | **Yes** | No health API and no health-specific feature. The same unfiltered read/screenshot path returns a health page when the user asks the assistant to read it. This is incidental disclosure, not a claim that Bot Bridge is a health product. |
| Financial and payment information | **Yes** | Card numbers and account details are usually ordinary text fields, so password masking does not remove them. Banking pages and screenshots are returned unfiltered. |
| Authentication information | **Yes** | Password-type fields and autocomplete `current-password` / `new-password` are masked in page reads and in click/type results. That does not cover screenshots, page text, usernames, one-time codes, or the text of a type command. The bridge token is stored in `chrome.storage.local` and sent as `X-Token` to 127.0.0.1. It authorizes browser control. The extension does not read the cookie jar. Do not answer "No" on the ground that passwords are masked. |
| Personal communications | **Yes** | Visible email, chat, and message text is returned by page reads and screenshots. There is no separate mail API. |
| Location | **Yes, with this caveat** | No geolocation permission, no GPS, and no IP geolocation. Addresses, map pages, and location text in URLs are returned unfiltered. If the live checkbox is defined only as device or IP location, the narrower answer is No, and the privacy policy still discloses location text inside page content. The public docs do not quote that glossary. The conservative answer is Yes. |
| Web history | **Yes** | `list_tabs` and later command results include URLs and titles of open tabs. Definite. |
| User activity | **No, provisional** | The extension does not record the user's own clicks, mouse movements, scrolling, or keystrokes as telemetry, and it has no analytics. It performs commanded synthetic actions and returns those results. If the live definition includes any record of actions taken in the browser, revisit this. Do not treat No as a certification against a broader label. |
| Website content | **Yes** | Page text, form values, element lists, and screenshots are returned to the local bridge on request. Definite. |

**Certifications** — supportable for Bot Bridge's own behavior, not for an arbitrary assistant's later use. Do not check a box you cannot stand behind. Checking them does not mean data never leaves the machine.

- **I do not sell or transfer user data to third parties, outside of the approved use cases.** Recommended **yes**. The extension does not sell data. It transfers command results to the user-selected assistant through the local bridge because that is the disclosed single purpose (an allowed transfer when necessary for the purpose, with consent). It is not a claim of no third-party transfer at all, and it does not certify the assistant vendor.
- **I do not use or transfer user data for purposes that are unrelated to my item's single purpose.** Recommended **yes** for the extension: use is requested browser control plus the connection settings. No analytics. The handoff to the assistant is the purpose, not an extra one. It does not certify that the assistant refrains from training or other uses under its own policy.
- **I do not use or transfer user data to determine creditworthiness or for lending purposes.** Recommended **yes**. Handling a banking page is not a lending decision. The extension does not score credit or offer loans.

**Privacy policy URL:** `https://plutunieer.github.io/bot-bridge/privacy-policy.html`

The file in this branch is `privacy-policy.html` at the repository root (same bytes as `store/privacy-policy.html`). GitHub Pages serves the root file only after this branch is merged and Pages rebuilds. Do not submit the store item while the live URL still shows the 26 October 2026 text. This audit does not deploy Pages.

---

## Notes for the reviewer

Username / password: leave empty. **Additional instructions** (499 characters, limit 500). Do not point reviewers at `releases/latest` until that asset is actually 1.0.3. This audit does not publish a release.

```
Use Bot Bridge companion 1.0.4 (Python 3, no packages), not an older release. python3 bridge.py serve does NOT print the token. In another terminal: python3 bridge.py token. Popup: read the notice, tick consent, paste port and token, Save. Badge shows ON. Then: python3 bridge.py send open_url url=https://example.com ; python3 bridge.py send get_page ; python3 bridge.py send click index=0. The extension talks only to http://127.0.0.1. No remote code. The assistant may process results off-device.
```

Longer setup, not for the 500-character field: use `dist/bridge-app.zip` from this branch (or the raw URL of that file on the branch). Unzip, run `python3 bot-bridge/bridge/bridge.py serve`, then `python3 bot-bridge/bridge/bridge.py token` in a terminal you control. The extension package is `dist/extension-store.zip` (manifest at the root, version 1.0.4). Do not upload it over the pending 1.0.3 review. Do not load `extension/` — that developer build still has optional `eval`. Consent is required before the badge shows ON; an earlier consent from 1.0.2 is not reused because the notice version changed. The assistant you connect may send results off the device. Loopback HTTP is intentional; see the privacy policy and Chrome User Data FAQ question 16. Store images in `store/images/` still show the 1.0.3 notice (consent version 2). Version 1.0.4 adds named-file upload to the notice (version 3). Recapture screenshot 4 before any future store submission of 1.0.4. Do not replace the pending 1.0.3 submission from this branch.

# Chrome Web Store – submission checklist (Bot Bridge 1.0.5)

Do not submit this package while 1.0.3 is pending review. This checklist is for a later upload.

Everything referenced here is in `/workspace/grok-chrome-bridge/` (also inside `dist/bot-bridge.zip`).

| What | File |
|---|---|
| Package to upload | `dist/extension-store.zip` (manifest at root, v1.0.3, no eval). Do not upload `extension/`. |
| Listing texts, permission justifications, data disclosures | `store/LISTING.md` |
| Store icon 128×128 | `store/images/store-icon-128.png` |
| Screenshots 1280×800 | `store/images/screenshot-1-assistant-in-chrome-1280x800.png`, `screenshot-2-commands-…`, `screenshot-3-how-it-works-…`, `screenshot-4-consent-…` |
| Small promo tile 440×280 | `store/images/promo-small-440x280.png` |
| Privacy policy (to host) | `store/privacy-policy.html` |
| Bridge download (to host) | `dist/bridge-app.zip` |
| Brand (SVG icon, colours, type) | `brand/icon.svg`, `brand/BRAND.md` |

---

## 0. Before you start – open items only Adele can do

- [x] **Name:** "Bot Bridge" (no "Grok" in name or visuals). Optional: search the Chrome Web Store for "Bot Bridge" to make sure no existing extension uses the same name. If the name ever changes: edit `store/build_store.py`, rebuild, then `python3 store/assets/capture.py && python3 store/assets/make_images.py`.
- [ ] **Bridge download:** do not overwrite or tag a release from the security review. Release v1.0.2 is the previous build and still prints the token on `serve`. After review, the maintainer can publish 1.0.3 and attach `dist/bridge-app.zip`, `dist/extension-store.zip`, and `dist/bot-bridge.zip`. Until then, `releases/latest` is not the corrected companion.
- [ ] **Privacy policy:** Pages serves `privacy-policy.html` from the default branch root. Merging this branch is what updates https://plutunieer.github.io/bot-bridge/privacy-policy.html . Do not submit the store item while that URL still shows 26 October 2026. This review does not deploy Pages.
- [x] All links are filled in (no placeholders left). Contact = GitHub Issues (no email).
- [ ] Google account with **2-Step Verification** on (required for publishing). A dedicated account is a good idea, because the publisher email can be shown publicly.

## 1. Register as a Chrome Web Store developer (one time)

1. Open https://chrome.google.com/webstore/devconsole and sign in with the chosen Google account.
2. Accept the **Developer Agreement** and policies.
3. Pay the **one-time USD 5 registration fee** (card via Google Payments).
4. **Account** tab: set the *Publisher name* (e.g. "plutunieer" or "Adele Iten"), verify the *contact email* (Google requires one for the developer account; it is separate from the support link). Fill in the **trader / non-trader declaration** (EU Digital Services Act). For a free, non-commercial hobby project "non-trader" usually fits; if published as part of a business, choose "trader" (address/phone are then shown publicly).

## 2. Upload the package

1. **+ New item** → choose `dist/extension-store.zip` → Upload.
2. **Package** tab: check that it shows version 1.0.3 and the permissions `tabs, scripting, storage, alarms` + host `<all_urls>`. Do not upload the developer folder `extension/`.

## 3. Store listing tab

| Field | Value |
|---|---|
| Description (English) | "Detailed description" EN block from LISTING.md |
| Category | Productivity → Tools |
| Language | English; then **Add language → German** and paste the DE detailed description (the DE summary comes from `_locales/de` automatically) |
| Store icon | `store/images/store-icon-128.png` |
| Global promo video | leave empty |
| Screenshots | upload the 4 files `screenshot-1…4-…1280x800.png` in that order |
| Small promo tile | `store/images/promo-small-440x280.png` |
| Marquee promo tile | optional, leave empty |
| Official URL | leave empty (only for verified sites in Search Console) |
| Homepage URL | https://github.com/plutunieer/bot-bridge |
| Support URL | https://github.com/plutunieer/bot-bridge/issues |
| Mature content | No |

Name and short summary come from the package (`_locales/en|de/messages.json`) and can't be edited here.

## 4. Privacy tab

| Field | Value |
|---|---|
| Single purpose | "Single purpose description" from LISTING.md |
| Permission justification – tabs / scripting / storage / alarms | the matching row from LISTING.md |
| Host permission justification | the `<all_urls>` row from LISTING.md |
| Remote code | **No, I am not using remote code.** The earlier "Yes" with a blank justification was unaudited form state. See LISTING.md. Do not upload the developer build. |
| Data usage | LISTING.md table. Do not reuse the old "web history + website content only" answers. |
| Certifications | LISTING.md. Recommended yes for Bot Bridge's own behavior, with the stated limits. Not a certification of the assistant. |
| Privacy policy URL | https://plutunieer.github.io/bot-bridge/privacy-policy.html (must be the 1.0.3 text before submit) |

## 5. Distribution tab

- Payments: **Free**
- Visibility: **Public** (or *Unlisted* first, to test the store install with a link)
- Regions: **All regions**

## 6. Test instructions tab (Access → Test instructions)

Username / password: leave empty. **Additional instructions** (499 / 500 characters; copy from LISTING.md). Do not link `releases/latest` until that file is 1.0.3.
```
Use Bot Bridge companion 1.0.3 (Python 3, no packages), not an older release. python3 bridge.py serve does NOT print the token. In another terminal: python3 bridge.py token. Popup: read the notice, tick consent, paste port and token, Save. Badge shows ON. Then: python3 bridge.py send open_url url=https://example.com ; python3 bridge.py send get_page ; python3 bridge.py send click index=0. The extension talks only to http://127.0.0.1. No remote code. The assistant may process results off-device.
```

## 7. Submit

1. **Submit for review**. In the dialog you can untick "publish automatically" (deferred publishing) to publish yourself after approval (within 30 days).
2. Review usually takes from a few days to a few weeks; `<all_urls>` + `scripting` usually triggers an in-depth review. Answer emails from the review team from the publisher account.
3. After approval: replace "coming soon" in the GitHub README (and `docs/BOT-SKILL.md`) with the Web Store link (setup step 1) so assistants send users to the store instead of "Load unpacked".

## 8. Known review risks and how they are handled

| Risk | Status |
|---|---|
| Remote code (MV3) | `eval` command and toggle removed from the store build; `build_store.py` scans for eval/new Function/string timers/remote URLs and fails if any are found. |
| Broad host permission | Justified (the user picks the sites; needed for `captureVisibleTab` and for localhost). `activeTab` removed as redundant. |
| User data disclosure + consent | Prominent notice before connection, re-asked when the notice version changes. The notice says the assistant may process data off-device and states the password-masking limit. Policy and listing match. |
| "Data must be encrypted in transit" | Chrome User Data FAQ question 16: the secure-handling requirement does not apply to transmissions between an extension and a native program on the same computer. Loopback HTTP is intentional. It is not encrypted, and FAQ 16 is not a reason to skip disclosure, the token, or Host/Origin checks. Do not switch to TLS or Native Messaging only to satisfy that sentence. |
| Needs external software | Stated at the top of the description, in the popup and in test instructions. |
| Trademark in name | See step 0. |

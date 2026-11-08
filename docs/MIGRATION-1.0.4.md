# Migration from 1.0.3 to 1.0.4

1.0.4 adds named-file upload. It keeps the 1.0.3 security behavior: loopback only, token checks, Host and Origin checks, no token on `serve` stdout, password masking, and no `eval` in the store package.

This note does not publish a release, deploy the website, or change the pending Chrome Web Store review of 1.0.3. `releases/latest` can still be the older 1.0.2 asset until a maintainer publishes 1.0.4 on purpose.

## What you replace

- **Extension.** Load `dist/extension-store.zip` (version 1.0.4) or the unpacked `store/extension` folder. The developer folder `extension/` is not the store build.
- **Companion.** Replace the `bridge.py` that is actually running. A launchd or systemd unit may be executing a copy, for example `~/Library/Application Support/BotBridge/bridge.py`, not the folder you just unzipped. Restart that process after replacing the file. This repository does not do that on a machine by itself.
- **Consent.** The store notice is now version 3 because the extension can place named local files into pages. Open the popup and agree again. An agreement stored for version 2 does not connect.

## New command

```sh
python3 bridge.py send upload selector='#file' path="$HOME/staging/clip.mp4" submit=true
python3 bridge.py send upload selector='#files' paths='["a.png","b.png"]'
```

`path` is on the computer running the bridge. See `docs/CAPABILITIES.md` for the caps and for what still needs a person.

## Not changed by installing 1.0.4

- Old service logs that already contain a `Token:` line are still on disk until someone deletes them and runs `bridge.py new-token`.
- The public homepage and `releases/latest` links are not updated by this branch.
- Store screenshots in `store/images/` still show the 1.0.3 notice. Recapture screenshot 4 before a future 1.0.4 store submission.

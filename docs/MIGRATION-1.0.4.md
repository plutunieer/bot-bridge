# Migration from 1.0.3 to 1.0.5

1.0.5 adds named-file upload with no default size cap. The bridge streams each file to the extension in 1 MiB chunks. Chrome holds it as a blob that can spill to disk. An optional `max_upload_bytes` in `~/.bot-bridge/config.json` (or the legacy config directory) sets a ceiling; `0` or omitting the key means unlimited. A transfer with no progress for 2 minutes is cancelled. Stderr prints `upload <sent>/<total> bytes` and never the file contents. `GET /blob/<id>` is the only route that accepts a web page Origin, because the extension's isolated world sends one; the token and an unguessable id are still required. Every other route still rejects a web Origin.

It keeps the 1.0.3 security behavior: loopback only, token checks, Host and Origin checks, no token on `serve` stdout, password masking, consent version 3, and no `eval` in the store package.

This note does not publish a release, deploy the website, or change the pending Chrome Web Store review of 1.0.3. `releases/latest` can still be the older 1.0.2 asset until a maintainer publishes 1.0.5 on purpose.

## What you replace

- **Extension.** Load `dist/extension-store.zip` (version 1.0.5) or the unpacked `store/extension` folder. The developer folder `extension/` is not the store build.
- **Companion.** Replace the `bridge.py` that is actually running. A launchd or systemd unit may be executing a copy, for example `~/Library/Application Support/BotBridge/bridge.py`, not the folder you just unzipped. Restart that process after replacing the file. This repository does not do that on a machine by itself.
- **Consent.** The store notice is now version 3 because the extension can place named local files into pages. Open the popup and agree again. An agreement stored for version 2 does not connect.

## New command

```sh
python3 bridge.py send upload selector='#file' path="$HOME/staging/clip.mp4" submit=true
python3 bridge.py send upload selector='#files' paths='["a.png","b.png"]'
```

`path` is on the computer running the bridge. See `docs/CAPABILITIES.md` for the limits that are not a size cap, and for what still needs a person.

## Not changed by installing 1.0.5

- Old service logs that already contain a `Token:` line are still on disk until someone deletes them and runs `bridge.py new-token`.
- The public homepage and `releases/latest` links are not updated by this branch.
- Store screenshots in `store/images/` still show the 1.0.3 notice. Recapture screenshot 4 before a future 1.0.5 store submission.

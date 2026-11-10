# Migration from 1.0.5 to 1.0.6

1.0.5 uploaded a file by fetching `http://127.0.0.1/blob/<id>` from the page's isolated world. On a public site such as `https://x.com`, Chrome's local-network check blocks that fetch or waits on a prompt, so the command sat until `upload timeout` and the client sometimes hung up (`BrokenPipe`). A loopback test page never showed this.

1.0.6 splits the fix:

- **Developer build** (`extension/`, `dist/extension.zip`) requests `debugger`. Uploads use `DOM.setFileInputFiles` with the local path. `click_upload` (or `upload` with `via: "click"`) clicks the site's button and intercepts the file chooser, so the system dialog does not open. Clicks and keys are trusted. `alert` / `confirm` / `prompt` can be answered. `download_dir` saves a download and reports the path. `get_page` includes cross-origin frames it can attach to. Consent is version 4.
- **Store build** does not request `debugger`. The service worker fetches the file and passes it into the page in chunks. The page does not call 127.0.0.1. If that read does not start, the error is `upload did not start` within about 15 seconds. Consent stays version 3.

`serve` logs `timestamp command <name> ok` or `error <reason>` on stderr. The line does not contain the token or file bytes. A client that has already gone away does not produce a traceback. `bridge.py send` waits until the bridge's own command timeout, plus 60 seconds, so an upload does not outlive the client.

This note does not publish a release, deploy the website, or change the pending Chrome Web Store review of 1.0.3. Install steps for the known Mac layout are in `AGENTS.md`.

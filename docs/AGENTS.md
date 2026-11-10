# Commands for an assistant driving Bot Bridge

The assistant runs these on the **user's computer**, in the folder that contains `bridge.py`. Paths in `upload` are paths on that computer. This is not an MCP connector. Do not invent a path that exists only in the assistant's environment.

The token is not printed by `serve`. Read it with `python3 bridge.py token` in a terminal the user controls, or from `~/.bot-bridge/config.json`. Do not write the token into a log.

```sh
python3 bridge.py send ping
python3 bridge.py send open_url url=https://example.com
python3 bridge.py send get_page
python3 bridge.py send click selector='#submit'
python3 bridge.py send type selector='#q' text='hello' submit=true
python3 bridge.py send press_key key=Enter selector='#q'
```

## Files

Developer build (debugger): Chrome reads the path. Any size the disk and the site allow. The page does not call 127.0.0.1.

```sh
python3 bridge.py send upload selector='#file' path="$HOME/staging/clip.mp4" submit=true
python3 bridge.py send click_upload selector='#upload-button' path="$HOME/staging/clip.mp4" submit=true
python3 bridge.py send upload via=click selector='#upload-button' paths='["/absolute/a.mp4","/absolute/b.mp4"]'
python3 bridge.py send upload mode=drop selector='#drop' path="$HOME/staging/clip.mp4"
```

`click_upload` clicks the site's own button, intercepts the file chooser, and sets the named files. The macOS open dialog does not appear. `selector` is the button, not the hidden input.

Store build (no debugger): the service worker reads the file and passes chunks into the page. `upload` with `path` still works. `click_upload` does not. A transfer that never starts fails within about 15 seconds with `upload did not start`, instead of hanging until the command timeout.

There is no default size cap. `max_upload_bytes` in the bridge config is optional; `0` or omitting it means unlimited.

## Dialogs, downloads, trusted input

Developer build only. Clicks and keys are trusted unless `trusted=false`.

```sh
python3 bridge.py send click selector='#alert' 
python3 bridge.py send click selector='#confirm' dialog=accept
python3 bridge.py send click selector='#confirm' dialog=dismiss
python3 bridge.py send click selector='#ask' dialog='{"accept":true,"prompt_text":"ada"}'
python3 bridge.py send dialog policy=accept persist=true
python3 bridge.py send click selector='#download' download_dir="$HOME/Downloads/bot-bridge"
```

`download.path` in the result is the file in that folder, which must already exist. Chrome refuses `Browser.setDownloadBehavior` from an extension, so the bridge copies the completed download into `download_dir` and also reports `download.browser_path`. `alert` is accepted if you set no policy. `confirm` and `prompt` are dismissed unless `dialog` says accept.

`get_page` on the developer build includes `frames` for cross-origin iframes the extension could attach to.

## What still needs a person

The system Save and Print dialogs, permission prompts, and captchas. Do not try to type into an OS file dialog; use `upload` or `click_upload` instead.

## Adele's Mac

The process launchd runs is not this git folder.

1. Replace `~/Library/Application Support/BotBridge/bridge.py` with `bridge/bridge.py` from 1.0.6.
2. Restart the job: `launchctl kickstart -k "gui/$(id -u)/com.botbridge.bridge"`.
3. Replace the unpacked extension at `~/Documents/Startup/grok-chrome-bridge/extension` with the **developer** `extension/` directory (the contents of `dist/extension.zip`). That folder has the `debugger` permission. The store zip does not.
4. In `chrome://extensions`, Reload that unpacked extension. Chrome will ask you to accept the debugger permission.
5. Open the popup, read the notice, tick consent (version 4; a 1.0.5 agreement does not carry over), confirm the port and token, Save. The badge should read ON.

This repository does not perform those steps.

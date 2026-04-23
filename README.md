# Sparvi Live Pointer MVP

Sparvi Live Pointer is a Manifest V3 Chrome Extension plus a Node.js WebSocket backend. An instructor can join a session, start Live Pointer, and show their cursor as a floating non-blocking overlay on student browsers while everyone is on normal http or https websites.

## Folder Tree

```text
project-root/
  extension/
    manifest.json
    service_worker.js
    popup.html
    popup.css
    popup.js
    content.js
    overlay.css
    icons/
      icon16.png
      icon48.png
      icon128.png
  server/
    package.json
    server.js
    README.md
  README.md
```

## Requirements

- Google Chrome or Chromium-based Chrome
- Node.js 18 or newer
- npm

## Run the backend

```bash
cd server
npm install
npm start
```

The backend listens on:

```text
ws://localhost:8787
```

To change the port:

```bash
PORT=9000 npm start
```

On Windows PowerShell:

```powershell
$env:PORT=9000
npm start
```

If you change the port, update `DEFAULT_SERVER_URL` in `extension/service_worker.js`.

## Load the extension

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Select Load unpacked.
4. Choose the `extension` folder.
5. Reload any website tabs that were already open before loading the extension.

## Test with two Chrome profiles

1. Start the backend.
2. Load the unpacked extension in two Chrome profiles, or in Chrome and another Chromium-based profile.
3. Open the same normal website in both profiles, such as `https://example.com`.
4. In one profile, choose `Instructor`, enter a session ID, and connect.
5. In the other profile, choose `Student`, enter the same session ID, and connect.
6. On the instructor browser, select Start Live Pointer.
7. A solid floating Live Pointer rectangle appears on the instructor page.
8. Student avatar circles appear above the rectangle.
9. Choose `All` to show the pointer to every student, or choose one student avatar to show it only to that student.
10. Drag the rectangle from its body, or resize it from the corners and edges.
11. Move or click inside that rectangle. The selected student or students see the Teacher cursor and click pulse mapped by the same x/y ratios on their viewport.

Students can join before the instructor. The room supports one instructor and multiple students.

## Supported and unsupported pages

Supported:

- Most normal `http://` and `https://` websites.
- Single-page apps that change URL without a full reload.

Unsupported by browser design:

- `chrome://` pages
- Chrome Web Store pages
- `chrome-extension://` pages
- Browser settings, new tab, downloads, and other internal surfaces
- Local `file://` pages for this MVP

The extension does not try to bypass browser restrictions. Unsupported pages show a friendly status in the popup, and normal pages where the content script is not ready ask you to reload the tab.

## Permissions

The extension requests only:

- `storage`: saves the last session ID and selected role.
- `tabs`: reads the active tab URL so the popup can show page support and page mismatch state.
- `host_permissions` for `http://*/*` and `https://*/*`: lets the content script run on most regular websites.

The extension does not load remotely hosted code. The backend is a separate WebSocket server.

## Architecture

- `service_worker.js`: owns extension state, WebSocket lifecycle, reconnects, session persistence, and routing between popup, content scripts, and backend.
- `popup.js`: displays session controls, role controls, page support, connection state, and instructor controls.
- `content.js`: injects a fixed overlay, shows the instructor's draggable and resizable pointer area, renders student target avatars, tracks instructor mouse movement and clicks inside that area, receives remote cursor events, and watches SPA URL changes.
- `server/server.js`: manages rooms, one instructor, multiple students, heartbeat, malformed message handling, targeted pointer relay, and page mismatch messages.

## Troubleshooting

- If Connect fails, make sure the backend is running on `ws://localhost:8787`.
- If a normal website says reload needed, reload that tab after loading or updating the extension.
- If the student sees a page mismatch badge, instructor and student URLs differ.
- If a second instructor joins the same room, the server rejects that instructor until the first disconnects.
- If testing across machines, run the server on a reachable host, update `DEFAULT_SERVER_URL`, and adjust the extension CSP `connect-src` in `manifest.json`.

## Packaging later

For Chrome Web Store publishing:

1. Replace development branding and icons as needed.
2. Review host permissions and consider an allowlist mode.
3. Point the extension to a production WebSocket endpoint.
4. Update `connect-src` in `manifest.json`.
5. Zip the `extension` folder contents.

## Next MVP+ improvements

- multi-student classroom improvements
- auto page sync with user consent
- highlight specific DOM elements
- optional voice channel
- optional teacher annotation tools
- optional student help button
- permission minimization strategy for store publishing
- optional allowlist mode for selected domains

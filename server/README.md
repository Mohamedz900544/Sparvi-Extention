# Sparvi Live Pointer Server

This is the local WebSocket backend for the Sparvi Live Pointer Chrome extension MVP.

## Run locally

```bash
cd server
npm install
npm start
```

The default server URL is:

```text
ws://localhost:8787
```

You can choose a different port:

```bash
PORT=9000 npm start
```

On Windows PowerShell:

```powershell
$env:PORT=9000
npm start
```

If you change the port, update `DEFAULT_SERVER_URL` in `extension/service_worker.js`.

## Protocol

Client to server:

- `join`
- `cursor_move`
- `click_pulse`
- `page_update`
- `pointer_state`
- `leave`
- `ping`

Server to client:

- `joined`
- `peer_status`
- `cursor_move`
- `click_pulse`
- `page_mismatch`
- `pointer_state`
- `error`
- `pong`

The server supports one instructor and multiple students per room. Cursor movement and click pulses are relayed only from the room instructor to student clients.

## Notes

- The server keeps rooms in memory.
- Restarting the server clears all rooms.
- Heartbeat pings terminate stale WebSocket connections.
- Malformed messages receive an `error` response and are ignored.

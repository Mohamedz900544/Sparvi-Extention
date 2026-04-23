# Sparvi Desktop Pointer

This folder contains a desktop Python version of Sparvi that works on top of normal desktop applications, not only websites.

## What it does

- Instructor and student both run the desktop app
- Both join the same room ID
- Instructor can start live pointer mode
- Instructor gets a floating draggable and resizable teaching frame
- Only movement and clicks inside the teaching frame are sent
- Student sees the instructor cursor as a floating click-through overlay above the desktop
- Instructor can target all students or one specific student
- Instructor gets a desktop version of the extension tool bar
- Clicks create a pulse animation
- Laser, arrow, circle, underline, pin, step, clear, and highlight-style callouts are supported
- Works across browsers, IDEs, docs, office apps, and other regular desktop windows
- Supports one instructor and multiple students in the same room
- Uses normalized desktop coordinates so different screen sizes still line up reasonably well
- Shows a warning if the instructor and student are currently focused on different desktop windows

## Files

- `client_app.py` - desktop control panel app
- `overlay_window.py` - transparent topmost overlay used to draw the remote cursor
- `network_client.py` - WebSocket client and reconnect logic
- `mouse_capture.py` - global mouse movement and click capture
- `desktop_utils.py` - desktop geometry and active-window helpers
- `server.py` - Python WebSocket backend
- `requirements-client.txt` - client dependencies
- `requirements-server.txt` - server dependencies
- `run_client.bat` - quick launcher for the client
- `run_server.bat` - quick launcher for the server
- `build_exe.bat` - builds a Windows exe with PyInstaller

## Requirements

- Windows laptop or PC
- Python 3.9+
- Internet or LAN connectivity between instructor and student devices

The overlay and active-window detection were built primarily for Windows desktop use.

## Install

Open two terminals inside this folder.

### 1. Install the server dependencies

```powershell
python -m pip install -r requirements-server.txt
```

### 2. Install the client dependencies

```powershell
python -m pip install -r requirements-client.txt
```

## Run

### Start the server

```powershell
python server.py
```

The backend listens on:

```text
ws://localhost:8790
```

### Start the desktop app

```powershell
python client_app.py
```

Or double-click:

- `run_server.bat`
- `run_client.bat`

## Test flow

### On the instructor machine

1. Open the app
2. Enter a room ID
3. Choose `Instructor`
4. Click `Connect`
5. Click `Start Live Pointer`
6. A floating teaching frame appears on the desktop
7. Move the mouse inside the frame
8. Use the target avatars above the frame to send to all students or one student
9. Use the tool bar on the right side of the frame for teaching tools

### On the student machine

1. Open the app
2. Enter the same room ID
3. Choose `Student`
4. Click `Connect`
5. Keep the target app or IDE visible

## Build the Windows exe

```powershell
build_exe.bat
```

When the build finishes, the executable will be created here:

```text
dist\Sparvi Desktop Pointer.exe
```

## Notes

- This desktop version mirrors movement only inside the floating teaching frame, matching the browser extension model more closely
- It is designed for teaching across normal desktop software like VS Code, browser tabs, docs, slides, terminals, and dashboards
- The student overlay is click-through, so it should not block normal work
- The active-window warning is a lightweight desktop equivalent to the browser page mismatch warning
- The desktop `highlight` tool is an approximate spotlight box, not a real DOM element highlighter, because desktop apps do not expose page elements like websites do
- The client app uses a hardcoded server URL from `client_app.py` via the `HARDCODED_SERVER_URL` constant

## Good next upgrades

- optional screen region mode
- voice channel
- signed Windows installer
- better multi-monitor mapping

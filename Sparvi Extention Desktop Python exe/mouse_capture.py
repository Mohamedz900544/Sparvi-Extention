from pynput import mouse


class GlobalMouseCapture:
    def __init__(self, on_move=None, on_click=None):
        self._listener = None
        self._enabled = False
        self._on_move = on_move
        self._on_click = on_click

    def start(self):
        if self._listener is not None:
            return

        self._listener = mouse.Listener(
            on_move=self._handle_move,
            on_click=self._handle_click
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener is None:
            return

        self._listener.stop()
        self._listener = None

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)

    def _handle_move(self, x, y):
        if not self._enabled or not self._on_move:
            return

        self._on_move(x, y)

    def _handle_click(self, x, y, button, pressed):
        if not self._enabled or not self._on_click:
            return

        self._on_click(x, y, button, pressed)

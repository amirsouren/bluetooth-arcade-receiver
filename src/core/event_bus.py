"""Simple thread-safe pub-sub signal dispatcher (spec 02 §1: core/event_bus).

The services layer (D-Bus / GLib thread) must never import Qt.  Instead it
publishes events through :class:`Signal` objects and the Qt controller
(checklist STEP 3) subscribes to them, re-dispatching into queued Qt signals
so the UI thread absorbs updates safely (specs 05 §3 and 08 §3).

Semantics:

- ``connect``/``disconnect``/``emit`` may be called from any thread.
- ``emit`` snapshots the subscriber list under a lock and invokes callbacks
  *outside* the lock, so subscribers may connect/disconnect during dispatch.
- Callbacks execute on the *emitting* thread; a raising subscriber is logged
  and does not break the remaining subscribers.
"""

import logging
from threading import Lock
from typing import Any, Callable, List

logger = logging.getLogger(__name__)

Callback = Callable[..., Any]


class Signal:
    """Minimal named observer-signal (a Qt ``Signal`` analogue, Qt-free)."""

    def __init__(self, name: str = "") -> None:
        self.name = name or "<anonymous>"
        self._callbacks: List[Callback] = []
        self._lock = Lock()

    def connect(self, callback: Callback) -> Callback:
        """Register ``callback``; returns it so it can be used inline."""
        if not callable(callback):
            raise TypeError(f"Signal {self.name!r} expects a callable, got {callback!r}")
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
        return callback

    def disconnect(self, callback: Callback) -> None:
        """Unregister ``callback``; silently ignores unknown callbacks."""
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

    def emit(self, *args: Any, **kwargs: Any) -> None:
        """Invoke all subscribers with ``*args``/``**kwargs`` (never raises)."""
        with self._lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            try:
                callback(*args, **kwargs)
            except Exception:  # noqa: BLE001 - one bad subscriber must not kill the rest
                logger.exception(
                    "Signal %r: subscriber %r raised an exception", self.name, callback
                )

    def clear(self) -> None:
        """Drop all subscribers."""
        with self._lock:
            self._callbacks.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._callbacks)

    def __repr__(self) -> str:
        return f"<Signal {self.name!r} subscribers={len(self)}>"

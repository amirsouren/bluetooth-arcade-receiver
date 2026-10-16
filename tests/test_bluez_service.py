"""Unit tests for the BlueZ D-Bus backend engine (spec 09 STEP 2, spec 07 §1).

Runs fully offline through a duck-typed fake pydbus Bus — no Bluetooth
hardware or running BlueZ daemon required ("mock mode").  The service still
starts its real GLib worker thread, so the thread lifecycle and the
subscription wiring are exercised as well.

Run from the project root:  ``python -m pytest tests/ -q``
"""

import pathlib
import sys
import time

import pytest

# Make the project root importable regardless of the pytest invocation mode.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.core.config import (  # noqa: E402
    IFACE_DEVICE,
    IFACE_MEDIA_PLAYER,
    IFACE_OBJECT_MANAGER,
    IFACE_PROPERTIES,
)
from src.core.models import (  # noqa: E402
    FALLBACK_ALBUM,
    FALLBACK_ARTIST,
    FALLBACK_TITLE,
    TrackMetadata,
)
from src.services.bluez_service import BluezService  # noqa: E402

DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
PLAYER_PATH = f"{DEVICE_PATH}/player0"

DEVICE_PROPS = {"Alias": "Galaxy S23", "Address": "AA:BB:CC:DD:EE:FF", "Connected": True}
TRACK = {
    "Title": "Nightcall",
    "Artist": "Kavinsky",
    "Album": "OutRun",
    "Duration": 259000,
    "TrackNumber": 3,
}
PLAYER_PROPS = {"Status": "playing", "Position": 1200, "Track": TRACK}


# ---------------------------------------------------------------------------
# Fake pydbus bus (duck-typed: only subscribe()/get() are used by the service)
# ---------------------------------------------------------------------------
class FakeSubscription:
    def __init__(self, kwargs, callback):
        self.kwargs = kwargs
        self.callback = callback
        self.unsubscribed = False

    def unsubscribe(self):
        self.unsubscribed = True


class FakePlayer:
    def __init__(self):
        self.calls = []

    def Play(self):
        self.calls.append("Play")

    def Pause(self):
        self.calls.append("Pause")

    def Next(self):
        self.calls.append("Next")

    def Previous(self):
        self.calls.append("Previous")


class FakeManager:
    def __init__(self, objects):
        self._objects = objects

    def GetManagedObjects(self):
        return self._objects


class FakePlayerProxy:
    """Proxy slice: ``bus.get(...)[IFACE_MEDIA_PLAYER]`` -> record-keeping player."""

    def __init__(self, player):
        self._player = player

    def __getitem__(self, iface):
        assert iface == IFACE_MEDIA_PLAYER
        return self._player


class FakeBus:
    def __init__(self, managed_objects=None, fail_get=False):
        self.managed_objects = managed_objects or {}
        self.fail_get = fail_get  # simulate org.bluez absent (Bluetooth off)
        self.subscriptions = []
        self.get_calls = []
        self.player = FakePlayer()

    def subscribe(self, sender=None, iface=None, signal=None, object=None,
                  arg0=None, flags=0, signal_fired=None):
        subscription = FakeSubscription(
            {"sender": sender, "iface": iface, "object": object, "signal": signal},
            signal_fired,
        )
        self.subscriptions.append(subscription)
        return subscription

    def get(self, bus_name, object_path=None):
        self.get_calls.append((bus_name, object_path))
        if self.fail_get:
            raise RuntimeError("org.bluez is not available")
        if object_path == "/":
            return FakeManager(self.managed_objects)
        return FakePlayerProxy(self.player)

    def fire(self, signal_name, params, object_path="/"):
        """Simulate a D-Bus broadcast reaching every live subscription."""
        for subscription in list(self.subscriptions):
            if subscription.unsubscribed or subscription.kwargs["signal"] != signal_name:
                continue
            subscription.callback(
                "org.bluez",
                object_path,
                subscription.kwargs["iface"],
                signal_name,
                params,
            )


def _record(service):
    events = {"connected": [], "disconnected": [], "metadata": [], "status": []}
    service.sig_device_connected.connect(
        lambda name, path: events["connected"].append((name, path))
    )
    service.sig_device_disconnected.connect(lambda: events["disconnected"].append(1))
    service.sig_metadata_changed.connect(lambda meta: events["metadata"].append(meta))
    service.sig_status_changed.connect(lambda status: events["status"].append(status))
    return events


@pytest.fixture
def service_factory():
    """Create started BluezService instances; always stop them afterwards."""
    created = []

    def factory(managed_objects=None, fail_get=False):
        bus = FakeBus(managed_objects=managed_objects, fail_get=fail_get)
        service = BluezService(bus=bus)
        events = _record(service)
        service.start()
        created.append(service)
        return service, bus, events

    yield factory
    for service in created:
        service.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_initial_scan_adopts_existing_player(service_factory):
    managed = {
        DEVICE_PATH: {IFACE_DEVICE: DEVICE_PROPS},
        PLAYER_PATH: {IFACE_MEDIA_PLAYER: PLAYER_PROPS},
    }
    service, bus, events = service_factory(managed_objects=managed)
    assert service.is_running
    assert len(bus.subscriptions) == 3  # Added + Removed + PropertiesChanged
    assert {s.kwargs["iface"] for s in bus.subscriptions} == {
        IFACE_OBJECT_MANAGER,
        IFACE_PROPERTIES,
    }
    assert service.state.connected is True
    assert service.state.device_name == "Galaxy S23"
    assert service.state.status == "playing"
    assert service.player_path == PLAYER_PATH
    assert service.metadata.title == "Nightcall"
    assert events["connected"] == [("Galaxy S23", DEVICE_PATH)]
    assert events["status"] == ["playing"]
    assert events["metadata"][0].artist == "Kavinsky"
    service.stop()
    assert not service.is_running
    assert all(s.unsubscribed for s in bus.subscriptions)


def test_connect_and_disconnect_via_object_manager_signals(service_factory):
    service, bus, events = service_factory(
        managed_objects={DEVICE_PATH: {IFACE_DEVICE: DEVICE_PROPS}}
    )
    assert not service.state.connected  # no player yet -> idle/disconnected

    bus.fire("InterfacesAdded", (PLAYER_PATH, {IFACE_MEDIA_PLAYER: PLAYER_PROPS}))
    assert service.state.connected is True
    assert events["connected"] == [("Galaxy S23", DEVICE_PATH)]

    bus.fire("InterfacesRemoved", (PLAYER_PATH, [IFACE_MEDIA_PLAYER]))
    assert service.state.connected is False
    assert service.state.status == "disconnected"
    assert service.player_path is None
    assert events["disconnected"] == [1]
    assert events["status"][-1] == "disconnected"

    # Device-side removal afterwards must not double-emit (idempotent).
    bus.fire("InterfacesRemoved", (DEVICE_PATH, [IFACE_DEVICE]))
    assert events["disconnected"] == [1]


def test_track_and_status_updates_via_properties_changed(service_factory):
    managed = {
        DEVICE_PATH: {IFACE_DEVICE: DEVICE_PROPS},
        PLAYER_PATH: {IFACE_MEDIA_PLAYER: PLAYER_PROPS},
    }
    service, bus, events = service_factory(managed_objects=managed)

    bus.fire(
        "PropertiesChanged",
        (IFACE_MEDIA_PLAYER,
         {"Track": {"Title": "Resonance", "Artist": "HOME", "Album": "Odyssey",
                    "Duration": 212000}},
         []),
        object_path=PLAYER_PATH,
    )
    assert service.metadata.title == "Resonance"
    assert events["metadata"][-1].artist == "HOME"

    bus.fire("PropertiesChanged", (IFACE_MEDIA_PLAYER, {"Status": "paused"}, []),
             object_path=PLAYER_PATH)
    assert events["status"][-1] == "paused"
    assert service.state.status == "paused"

    # Duplicate status must not re-emit (emit only what actually changed).
    emit_count = len(events["status"])
    bus.fire("PropertiesChanged", (IFACE_MEDIA_PLAYER, {"Status": "paused"}, []),
             object_path=PLAYER_PATH)
    assert len(events["status"]) == emit_count

    bus.fire("PropertiesChanged", (IFACE_MEDIA_PLAYER, {"Position": 5000}, []),
             object_path=PLAYER_PATH)
    assert service.state.position_ms == 5000

    # Non-player interfaces are filtered out (spec 06 §4).
    bus.fire("PropertiesChanged", (IFACE_DEVICE, {"Connected": False}, []),
             object_path=DEVICE_PATH)
    assert len(events["status"]) == emit_count


def test_lazy_adoption_when_interfaces_added_was_missed(service_factory):
    service, bus, _events = service_factory(
        managed_objects={DEVICE_PATH: {IFACE_DEVICE: DEVICE_PROPS}}
    )
    assert not service.state.connected
    bus.fire("PropertiesChanged", (IFACE_MEDIA_PLAYER, PLAYER_PROPS, []),
             object_path=PLAYER_PATH)
    assert service.state.connected is True
    assert service.state.device_name == "Galaxy S23"
    assert service.metadata.title == "Nightcall"


def test_controls_forward_to_active_player(service_factory):
    managed = {
        DEVICE_PATH: {IFACE_DEVICE: DEVICE_PROPS},
        PLAYER_PATH: {IFACE_MEDIA_PLAYER: PLAYER_PROPS},
    }
    service, bus, _events = service_factory(managed_objects=managed)
    assert service.play() is True
    assert service.pause() is True
    assert service.next() is True
    assert service.previous() is True
    assert bus.player.calls == ["Play", "Pause", "Next", "Previous"]


def test_controls_noop_without_active_player(service_factory):
    service, bus, _events = service_factory()  # empty bus, no player ever
    assert service.play() is False
    assert service.pause() is False
    assert bus.player.calls == []


def test_starts_and_recovers_when_bluez_absent(service_factory):
    service, bus, events = service_factory(fail_get=True)  # Bluetooth off
    assert service.is_running
    assert not service.state.connected

    # BlueZ (re)appears later and announces device + player.
    bus.fire("InterfacesAdded", (DEVICE_PATH, {IFACE_DEVICE: DEVICE_PROPS}))
    assert events["connected"] == []
    bus.fire("InterfacesAdded", (PLAYER_PATH, {IFACE_MEDIA_PLAYER: PLAYER_PROPS}))
    assert events["connected"] == [("Galaxy S23", DEVICE_PATH)]
    assert service.state.connected is True


def test_start_surfaces_worker_failure():
    class BrokenBus(FakeBus):
        def subscribe(self, **kwargs):
            raise RuntimeError("no system D-Bus")

    service = BluezService(bus=BrokenBus())
    with pytest.raises(RuntimeError):
        service.start(timeout=5.0)
    assert not service.is_running


def test_metadata_falls_back_to_spec_defaults():
    metadata = TrackMetadata.from_bluez_track(
        {"Title": "", "Artist": None, "Album": "   ", "Duration": "bad"}
    )
    assert metadata.title == FALLBACK_TITLE
    assert metadata.artist == FALLBACK_ARTIST
    assert metadata.album == FALLBACK_ALBUM
    assert metadata.duration_ms == 0
    # Non-dict / missing Track entirely.
    for bogus in (None, "oops", 42):
        assert TrackMetadata.from_bluez_track(bogus).title == FALLBACK_TITLE


def test_stop_is_fast_when_qt_event_loop_exists():
    """Regression (spec 08 §3): once Qt is alive, stop() must still be fast.

    An idle_add()-based quit source gets starved inside Qt processes; the
    quit()+wakeup() pair must tear the GLib worker down promptly.
    """
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([sys.argv[0]])
    assert app is not None
    service = BluezService(bus=FakeBus(managed_objects={}))
    service.start()
    assert service.is_running

    started = time.monotonic()
    service.stop(timeout=3.0)
    elapsed = time.monotonic() - started

    assert not service.is_running
    assert elapsed < 2.5, f"stop() took {elapsed:.1f}s under Qt"



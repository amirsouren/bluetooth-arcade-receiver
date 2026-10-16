# Bluetooth Arcade Receiver

[![CI](https://github.com/amirsouren/bluetooth-arcade-receiver/actions/workflows/ci.yml/badge.svg)](https://github.com/amirsouren/bluetooth-arcade-receiver/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Retro/arcade-styled Bluetooth audio receiver for Ubuntu: turns a Linux PC into
a compact, always-on-top mini "arcade speaker" that an Android phone streams
to over A2DP, with AVRCP playback controls and live track metadata.

Full requirements, architecture and the step-by-step checklist live in
[`specs/`](specs/) — this README only covers setup and current status.

## Install on Ubuntu (22.04 / 24.04)

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/amirsouren/bluetooth-arcade-receiver.git
cd bluetooth-arcade-receiver
./install.sh
```

No git? Grab a release tarball instead:

```bash
wget https://github.com/amirsouren/bluetooth-arcade-receiver/archive/refs/tags/v0.1.0.tar.gz
tar xzf v0.1.0.tar.gz && cd bluetooth-arcade-receiver-0.1.0
./install.sh
```

`install.sh` creates a virtualenv in `./venv`, installs the Python
dependencies (reusing the distro `python3-gi`, so no compiler or
`-dev` headers are needed — it apt-installs `python3-gi` for you if
missing) and registers the **"Bluetooth Arcade Receiver"** entry in the
Ubuntu application menu.

Start it from the app menu, or:

```bash
venv/bin/python -m src.main
```

Then pair your phone with the PC over Bluetooth, start music, and the
arcade widget shows the track metadata with play/pause/next/prev controls.


## Current status (see `specs/09_implementation_checklist.txt`)

- [x] STEP 1: project layout, virtualenv, dependencies, D-Bus verification
- [x] STEP 2: D-Bus backend engine (`src/services/bluez_service.py`)
- [x] STEP 3: Qt controller bridge (`src/ui/controller.py`)
- [x] STEP 4: QML arcade frontend (`src/ui/qml/` + `src/main.py`)
- [ ] STEP 5: end-to-end verification & `.desktop` launcher
  - [x] edge cases: bluetooth off / mid-song disconnect / reconnect
    (`tests/test_integration.py`, offline half of spec 07 §2)
  - [x] `bluetooth-arcade.desktop` installed to `~/.local/share/applications/`
  - [ ] physical phone run of the spec 07 §2 matrix — runbook below

## Directory layout

```
bluetooth-arcade-receiver/
├── assets/{fonts,icons,images}/   # filled in STEP 4 (spec 02 §2)
├── src/
│   ├── main.py                    # entry point (STEP 3+)
│   ├── core/                      # config, models, Qt-free event bus
│   ├── services/                  # BlueZ D-Bus backend (STEP 2) + later audio
│   └── ui/                        # Qt controller + QML (STEP 3/4)
├── tests/                         # mock player + unit tests
├── specs/                         # requirements & architecture docs
├── install.sh                     # one-shot Ubuntu installer (see above)
├── requirements.txt
└── README.md
```

## Quick start (Ubuntu 22.04/24.04)

Prefer `./install.sh` above — the steps below are the manual equivalent:

```bash
cd bluetooth-arcade-receiver   # your clone of this repository

# 1. Virtual environment. --system-site-packages lets the venv reuse the
#    distro's PyGObject (python3-gi) when pkg-config/girepository headers
#    are not installed — see "Dependencies" below.
python3 -m venv --system-site-packages venv

# 2. Install dependencies (specs/09 STEP 1)
venv/bin/pip install -r requirements.txt
venv/bin/pip install pytest        # optional, for the test suite

# 3. Verify system D-Bus access to BlueZ (specs/09 STEP 1)
busctl --system introspect org.bluez / | head
venv/bin/python - <<'PY'
from pydbus import SystemBus
objects = SystemBus().get("org.bluez", "/").GetManagedObjects()
print(f"OK: {len(objects)} BlueZ objects visible")
PY

# 4. Run the backend test suite
venv/bin/python -m pytest tests/ -q

# 5. Launch the arcade mini-player (frameless 390x160 widget)
venv/bin/python -m src.main
#    ...or use the "Bluetooth Arcade Receiver" entry in the Ubuntu app menu.

# 6. Offline UI demo without a phone (fake Galaxy S23, two cycling tracks)
venv/bin/python tests/mock_player.py
```

## Dependencies / PyGObject fallback

`requirements.txt` lists **PySide6**, **pydbus** and **PyGObject** (spec 09).
PyGObject builds from source on PyPI and needs `pkg-config` plus
`libgirepository-1.0-dev`/`libgirepository-2.0-dev`. On machines without
those build tools (or without root), create the venv with
`--system-site-packages` as shown above — the distro package `python3-gi`
then satisfies the import (`import gi` → PyGObject ≥ 3.46). This mirrors the
fallback philosophy of `specs/08_risks_and_fallbacks.txt`.

## Hardware verification matrix (specs/07_testing_plan.txt §2)

Machine readiness (checked on this PC): adapter `hci0` **powered**, not
rfkill-blocked; paired devices found — **Amir's S25 FE** (phone) and
QCY T13 X.  Launch the app (`venv/bin/python -m src.main` or the app-menu
entry), start music on the phone, then walk the matrix:

| ID | Action                 | Expected behavior                    | Status    |
|----|------------------------|--------------------------------------|-----------|
| 01 | Connect BT from phone  | UI: `BT: CONNECTED [AMIR'S S25 FE]`  | [PENDING] |
| 02 | Press Play on phone    | PC speakers play; Title & Artist shown | [PENDING] |
| 03 | Click Pause in UI      | Phone pauses immediately             | [PENDING] |
| 04 | Click Next in UI       | Next song; metadata updates <500 ms  | [PENDING] |
| 05 | Disconnect phone BT    | UI `DISCONNECTED`; controls disabled | [PENDING] |
| 06 | Reconnect phone BT     | Auto-detects player; metadata restored | [PENDING] |

Rows 01-06 already pass **offline** via `tests/test_integration.py`
(25 tests green); only the physical run remains to be ticked.

If audio stays silent after connecting: `wpctl status` — `bluez_input.*`
must appear under the default sink (see risks, spec 08 §2).

## Audio routing sanity check (spec 08 §2)

If the phone connects but silence comes out, verify WirePlumber mapped the
Bluetooth sink as default:

```bash
wpctl status          # look for bluez_input.* under the default sink
wpctl status -n        # full node list
```

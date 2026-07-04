# OtterIR

OtterIR is a Home Assistant custom integration and admin panel for Zigbee2MQTT IR blasters such as the TS1201 and Moes UFO-R11.

It keeps the full IR workflow inside Home Assistant:

- learn IR codes from a Zigbee IR blaster
- save commands in shared or device-specific libraries
- expose saved commands as real Home Assistant button entities
- send saved commands from the UI, automations, or scripts
- import command tables from CSV or TSV files
- import SmartIR JSON files that use Broadlink IR payloads
- browse and selectively import larger `.ir` catalogs

## What This Project Is

OtterIR is a custom integration with a built-in Home Assistant panel.

It is not a Supervisor add-on or a standalone ingress app.

## Requirements

- Home Assistant `2026.4.0` or newer
- Home Assistant MQTT integration enabled
- Zigbee2MQTT with an IR-capable device that exposes:
  - `learn_ir_code`
  - `learned_ir_code`
  - `ir_code_to_send`

## Installation

### HACS

1. Open `HACS -> Integrations`.
2. Open the top-right menu and choose `Custom repositories`.
3. Add the repository URL for `sdotter/OtterIR`.
4. Select category `Integration`.
5. Install `OtterIR` from HACS.
6. Restart Home Assistant.
7. Open `Settings -> Devices & Services -> Add Integration`.
8. Add `OtterIR`.

### Manual

1. Copy `custom_components/zigbee2otterir` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Open `Settings -> Devices & Services -> Add Integration`.
4. Add `OtterIR`.

Expected install path:

```text
/config/custom_components/zigbee2otterir
```

## Features

### Learn and save

- start IR learning mode from the panel or from the learn button entity
- save the last learned code into a shared library or a device-only library
- organize commands by library name instead of loose raw payloads

### Real Home Assistant entities

- every saved command becomes a Home Assistant `button` entity
- command entity IDs can be adjusted from the OtterIR panel
- shared commands can appear on every compatible IR blaster

### Imports

- CSV and TSV imports for simple command lists
- SmartIR JSON imports for Broadlink-based command sets
- `.ir` catalog imports for larger external databases

### Storage

OtterIR keeps its editable library data in:

```text
/config/zigbee2otterir/library.json
```

That file is designed to stay readable and manually editable when needed.

## Repository Layout

```text
custom_components/zigbee2otterir/
  brand/                      Branding assets
  frontend/                   Panel JavaScript and CSS
  __init__.py                 Integration setup and services
  button.py                   Learn button and saved-command button entities
  library.py                  Persistent library storage
  ws_api.py                   WebSocket API for the panel
```

## Public Repo Notes

- this repository intentionally excludes temporary files and local research notes
- no hostnames, passwords, MQTT broker addresses, or runtime library data are tracked
- live Home Assistant library data and entity registry changes stay on the Home Assistant system, not in this repository

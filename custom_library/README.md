# Custom OtterIR Library

This folder contains a snapshot of the editable OtterIR library file from:

```text
\\prx-haos\config\zigbee2otterir\library.json
```

OtterIR also writes this file on Home Assistant as:

```text
/config/zigbee2otterir/library.json
```

## Top-level layout

The JSON file has five top-level keys:

```json
{
  "version": 1,
  "catalogs": {},
  "devices": {},
  "shared_codes": {},
  "device_codes": {}
}
```

- `version`: storage format version for this editable file.
- `catalogs`: imported catalog source metadata and imported remote previews.
- `devices`: per-IR-blaster settings and the last learned signal.
- `shared_codes`: saved commands that can appear on every compatible IR blaster.
- `device_codes`: saved commands that belong to one specific IR blaster.

## Devices

`devices` is keyed by the Zigbee2MQTT friendly name of the IR blaster.

Example shape:

```json
{
  "devices": {
    "IR Blaster (2)": {
      "import_library": "ZUILVENTILATOR",
      "last_learned": {
        "code": "...",
        "encoding": "tuya_raw_base64",
        "learned_at": "2026-07-11T15:00:00+00:00",
        "source": "learned"
      }
    }
  }
}
```

Common device fields:

- `pending_name`: default command name used by the learn-and-save workflow.
- `csv_source`: CSV, TSV, or Markdown source path/URL for quick imports.
- `entity_id_base`: custom base used when generating HA entity IDs for that blaster.
- `import_library`: default target library for imports from the panel.
- `smartir_source`: SmartIR JSON source path/URL for quick imports.
- `last_learned`: most recent IR signal captured by that blaster.

## Saved Commands

Saved commands are stored in either `shared_codes` or `device_codes`.

`shared_codes` is keyed by library name:

```json
{
  "shared_codes": {
    "ZUILVENTILATOR": [
      {
        "code_id": "zuilventilator_power",
        "name": "Power",
        "code": "...",
        "device_type": "generic",
        "encoding": "tuya_raw_base64",
        "record_uid": "...",
        "source": "catalog_import",
        "tags": [],
        "created_at": "2026-07-11T15:51:48+00:00",
        "updated_at": "2026-07-11T15:51:48+00:00"
      }
    ]
  }
}
```

`device_codes` adds one level for the target IR blaster, then the library name:

```json
{
  "device_codes": {
    "IR Blaster (2)": {
      "ZUILVENTILATOR": []
    }
  }
}
```

Important saved-command fields:

- `code_id`: stable command identifier used by services and generated button entity IDs.
- `name`: display name for the command.
- `code`: the IR payload.
- `encoding`: payload format. For this setup it is usually `tuya_raw_base64`.
- `device_type`: loose category such as `generic`, `fan`, `climate`, or similar.
- `manufacturer` / `model`: optional source metadata.
- `record_uid`: stable opaque ID used to keep Home Assistant button entities attached even if `code_id` changes.
- `source`: where the command came from, such as learned, CSV import, SmartIR import, or catalog import.
- `tags`: optional labels.
- `learned_at`, `created_at`, `updated_at`: timestamps in ISO format.

## Catalogs

`catalogs.sources` stores where an external catalog import came from.

Source fields:

- `source_key`: stable key for the imported source.
- `source_name`: display name shown in the panel.
- `origin_kind`: kind of source, such as `github_file`.
- `source`: original source path or URL.
- `remote_count`: number of remotes found in that source.
- `truncated`: whether the import was capped before all remotes were loaded.
- `metadata`: extra source metadata.
- `updated_at`: last import/update time.

`catalogs.remotes` is grouped by `source_key`. Each remote contains preview metadata and, when available, importable commands.

Remote fields:

- `remote_id`: stable key for the catalog remote.
- `source_key` / `source_name`: link back to the catalog source.
- `origin_kind` / `origin_url`: source type and original URL/path.
- `relative_path`: path inside the external catalog.
- `category`, `brand`, `model`, `display_name`: remote identity fields.
- `manufacturer`, `device_type`, `library_hint`: defaults used when importing.
- `command_count`, `supported_command_count`, `unsupported_command_count`: import compatibility counts.
- `preview_commands`: short command-name list for the panel.
- `commands`: full command records available for import.
- `updated_at`: last import/update time.

Catalog command fields:

- `name`: command name.
- `entry_type`: source command type, often `raw`.
- `protocol`: decoded protocol when known, otherwise `null`.
- `encoding`: command encoding after conversion.
- `code`: command payload.
- `supported`: whether OtterIR can import/send this command.
- `frequency`: IR carrier frequency, usually `38000`.
- `duty_cycle`: IR duty cycle from the source when present.

## Editing notes

- Keep the file valid JSON. There are no comments inside `library.json`.
- Rename libraries through the OtterIR panel when possible, because Home Assistant entity IDs may need to follow the change.
- `record_uid` should not be edited by hand; it is what keeps saved-command entities stable.
- If hand-editing `code_id`, make sure it stays unique across all shared and device-only saved commands.
- After copying a changed `library.json` back to Home Assistant, restart Home Assistant Core so the integration reloads it.

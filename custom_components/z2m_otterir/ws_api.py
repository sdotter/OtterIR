"""WebSocket API for the OtterIR app panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import entity_registry as er

from .entity_ids import (
    command_button_unique_id,
    current_command_entity_id,
    current_entity_ids,
    desired_command_entity_id,
)
from .const import (
    ATTR_CODE_ID,
    ATTR_CSV_SOURCE,
    ATTR_ENTITY_ID_BASE,
    ATTR_FRIENDLY_NAME,
    ATTR_IMPORT_LIBRARY,
    ATTR_LIBRARY,
    ATTR_NAME,
    ATTR_PENDING_NAME,
    ATTR_RECORD_UID,
    ATTR_SMARTIR_SOURCE,
    DOMAIN,
    SIGNAL_LIBRARY_UPDATED,
    SIGNAL_IMPORT_FIELDS_UPDATED,
    SIGNAL_PENDING_NAME_UPDATED,
)
from .library import IRLibraryStore

WS_REGISTERED_KEY = f"{DOMAIN}_ws_registered"


def async_register_ws_api(hass: HomeAssistant) -> None:
    """Register the OtterIR WebSocket API once."""

    if hass.data.get(WS_REGISTERED_KEY):
        return

    websocket_api.async_register_command(hass, websocket_get_state)
    websocket_api.async_register_command(hass, websocket_set_device_settings)
    websocket_api.async_register_command(hass, websocket_update_code)
    websocket_api.async_register_command(hass, websocket_update_code_entity_id)
    websocket_api.async_register_command(hass, websocket_rename_library)
    hass.data[WS_REGISTERED_KEY] = True


@websocket_api.websocket_command({vol.Required("type"): "z2m_otterir/get_state"})
@websocket_api.async_response
async def websocket_get_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current OtterIR app state."""

    try:
        entry_id, entry_data = _default_entry_data(hass)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_configured", str(err))
        return

    # The panel refreshes from one compact state payload so the frontend can
    # stay mostly stateless between user actions and live updates.
    connection.send_result(
        msg["id"],
        _build_state(hass, entry_id, entry_data),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "z2m_otterir/set_device_settings",
        vol.Required(ATTR_FRIENDLY_NAME): str,
        vol.Optional(ATTR_PENDING_NAME): str,
        vol.Optional(ATTR_IMPORT_LIBRARY): str,
        vol.Optional(ATTR_CSV_SOURCE): str,
        vol.Optional(ATTR_ENTITY_ID_BASE): str,
        vol.Optional(ATTR_SMARTIR_SOURCE): str,
    }
)
@websocket_api.async_response
async def websocket_set_device_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist per-device app settings."""

    try:
        entry_id, entry_data = _default_entry_data(hass)
        friendly_name = msg[ATTR_FRIENDLY_NAME]
        if friendly_name not in entry_data["devices"]:
            raise HomeAssistantError(f"Unknown IR device '{friendly_name}'")

        store: IRLibraryStore = entry_data["store"]

        if ATTR_PENDING_NAME in msg:
            pending_name = msg[ATTR_PENDING_NAME].strip()
            entry_data["pending_names"][friendly_name] = pending_name
            await store.async_set_pending_name(friendly_name, pending_name)
            async_dispatcher_send(
                hass,
                SIGNAL_PENDING_NAME_UPDATED.format(entry_id),
                {
                    ATTR_FRIENDLY_NAME: friendly_name,
                    ATTR_PENDING_NAME: pending_name,
                },
            )

        import_payload: dict[str, Any] = {ATTR_FRIENDLY_NAME: friendly_name}

        if ATTR_IMPORT_LIBRARY in msg:
            import_library = msg[ATTR_IMPORT_LIBRARY].strip()
            entry_data["import_libraries"][friendly_name] = import_library
            await store.async_set_import_library(friendly_name, import_library)
            import_payload[ATTR_IMPORT_LIBRARY] = import_library

        if ATTR_CSV_SOURCE in msg:
            csv_source = msg[ATTR_CSV_SOURCE].strip()
            entry_data["csv_sources"][friendly_name] = csv_source
            await store.async_set_csv_source(friendly_name, csv_source)
            import_payload[ATTR_CSV_SOURCE] = csv_source

        if ATTR_ENTITY_ID_BASE in msg:
            from . import _async_set_entity_id_base

            await _async_set_entity_id_base(
                hass,
                entry_data,
                friendly_name,
                msg[ATTR_ENTITY_ID_BASE].strip(),
            )
            import_payload[ATTR_ENTITY_ID_BASE] = msg[ATTR_ENTITY_ID_BASE].strip()

        if ATTR_SMARTIR_SOURCE in msg:
            smartir_source = msg[ATTR_SMARTIR_SOURCE].strip()
            entry_data["smartir_sources"][friendly_name] = smartir_source
            await store.async_set_smartir_source(friendly_name, smartir_source)
            import_payload[ATTR_SMARTIR_SOURCE] = smartir_source

        if len(import_payload) > 1:
            async_dispatcher_send(
                hass,
                SIGNAL_IMPORT_FIELDS_UPDATED.format(entry_id),
                import_payload,
            )

    except HomeAssistantError as err:
        connection.send_error(msg["id"], "update_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        _build_state(hass, entry_id, entry_data),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "z2m_otterir/update_code",
        vol.Required("current_code_id"): str,
        vol.Optional(ATTR_NAME): str,
    }
)
@websocket_api.async_response
async def websocket_update_code(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename a saved code."""

    try:
        entry_id, entry_data = _default_entry_data(hass)
        store: IRLibraryStore = entry_data["store"]
        current_code_id = msg["current_code_id"]
        existing = store.get_code(current_code_id)
        if existing is None:
            raise HomeAssistantError(f"Unknown code id '{current_code_id}'")

        try:
            updated = await store.async_update_code_metadata(
                current_code_id,
                name=str(msg.get(ATTR_NAME) or existing[ATTR_NAME]).strip()
                or existing[ATTR_NAME],
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(entry_id),
            {
                "current_code_id": current_code_id,
                ATTR_CODE_ID: updated[ATTR_CODE_ID],
                ATTR_FRIENDLY_NAME: updated.get(ATTR_FRIENDLY_NAME),
            },
        )

    except HomeAssistantError as err:
        connection.send_error(msg["id"], "update_code_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        _build_state(hass, entry_id, entry_data),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "z2m_otterir/update_code_entity_id",
        vol.Required(ATTR_CODE_ID): str,
        vol.Required(ATTR_FRIENDLY_NAME): str,
        vol.Optional("custom_entity_id"): bool,
        vol.Optional("entity_id"): str,
    }
)
@websocket_api.async_response
async def websocket_update_code_entity_id(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update the real Home Assistant entity_id for one saved-command button."""

    try:
        entry_id, entry_data = _default_entry_data(hass)
        store: IRLibraryStore = entry_data["store"]
        record = store.get_code(msg[ATTR_CODE_ID])
        if record is None:
            raise HomeAssistantError(f"Unknown code id '{msg[ATTR_CODE_ID]}'")

        friendly_name = str(msg[ATTR_FRIENDLY_NAME]).strip()
        if friendly_name not in entry_data["devices"]:
            raise HomeAssistantError(f"Unknown IR device '{friendly_name}'")

        unique_id = command_button_unique_id(record[ATTR_RECORD_UID], friendly_name)
        registry = er.async_get(hass)
        current_entity_id = registry.async_get_entity_id("button", DOMAIN, unique_id)
        if current_entity_id is None:
            raise HomeAssistantError("The command entity is not registered yet")

        custom_entity_id = bool(msg.get("custom_entity_id"))
        if custom_entity_id:
            requested_entity_id = str(msg.get("entity_id") or "").strip()
            if not requested_entity_id:
                raise HomeAssistantError("entity_id is required when custom_entity_id is enabled")
            new_entity_id = requested_entity_id
        else:
            new_entity_id = desired_command_entity_id(
                entry_data,
                friendly_name,
                record[ATTR_CODE_ID],
            )

        registry.async_update_entity(current_entity_id, new_entity_id=new_entity_id)
        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(entry_id),
            {
                ATTR_CODE_ID: record[ATTR_CODE_ID],
                ATTR_FRIENDLY_NAME: friendly_name,
                "entity_id": new_entity_id,
            },
        )

    except HomeAssistantError as err:
        connection.send_error(msg["id"], "update_code_entity_id_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        _build_state(hass, entry_id, entry_data),
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "z2m_otterir/rename_library",
        vol.Required(ATTR_LIBRARY): str,
        vol.Required("new_library"): str,
        vol.Optional(ATTR_FRIENDLY_NAME): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def websocket_rename_library(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Rename one shared or device-specific library group."""

    try:
        entry_id, entry_data = _default_entry_data(hass)
        store: IRLibraryStore = entry_data["store"]
        library = str(msg[ATTR_LIBRARY]).strip()
        new_library = str(msg["new_library"]).strip()
        friendly_name = msg.get(ATTR_FRIENDLY_NAME)
        if friendly_name is not None:
            friendly_name = str(friendly_name).strip()

        try:
            renamed = await store.async_rename_library(
                library,
                new_library,
                friendly_name=friendly_name,
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

        if renamed == 0:
            scope_name = "shared library" if friendly_name is None else f"library for '{friendly_name}'"
            raise HomeAssistantError(f"No saved commands were found in {scope_name} '{library}'")

        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(entry_id),
            {
                ATTR_FRIENDLY_NAME: friendly_name,
                ATTR_LIBRARY: new_library,
            },
        )

    except HomeAssistantError as err:
        connection.send_error(msg["id"], "rename_library_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        _build_state(hass, entry_id, entry_data),
    )


def _build_state(
    hass: HomeAssistant,
    entry_id: str,
    entry_data: dict[str, Any],
) -> dict[str, Any]:
    """Build the panel state payload."""

    store: IRLibraryStore = entry_data["store"]
    return {
        "entry_id": entry_id,
        "devices": _serialize_devices(hass, entry_data),
        "codes": _serialize_codes(hass, entry_data, store),
        "catalog_sources": _serialize_catalog_sources(store),
        "catalog_remotes": _serialize_catalog_remotes(store),
    }


def _default_entry_data(hass: HomeAssistant) -> tuple[str, dict[str, Any]]:
    """Return the first configured OtterIR entry."""

    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        if isinstance(entry_data, dict) and "store" in entry_data:
            return entry_id, entry_data
    raise HomeAssistantError("OtterIR is not configured")


def _serialize_devices(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Serialize known devices for the panel."""

    store: IRLibraryStore = entry_data["store"]
    devices: list[dict[str, Any]] = []
    for friendly_name, device in sorted(entry_data["devices"].items()):
        learned = entry_data["learned"].get(friendly_name) or store.get_last_learned(
            friendly_name
        )
        devices.append(
            {
                "friendly_name": friendly_name,
                "manufacturer": device.get("manufacturer"),
                "model": (
                    device.get("model_id")
                    or device.get("model")
                    or device.get("definition", {}).get("model")
                ),
                "pending_name": entry_data["pending_names"].get(friendly_name, ""),
                "import_library": entry_data["import_libraries"].get(friendly_name, ""),
                "csv_source": entry_data["csv_sources"].get(friendly_name, ""),
                "entity_id_base": entry_data["entity_id_bases"].get(friendly_name, ""),
                "entity_ids": current_entity_ids(hass, friendly_name=friendly_name),
                "smartir_source": entry_data["smartir_sources"].get(friendly_name, ""),
                "last_learned": learned,
                "saved_count": len(store.list_codes(friendly_name)),
            }
        )
    return devices


def _serialize_codes(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    store: IRLibraryStore,
) -> list[dict[str, Any]]:
    """Serialize saved codes for the panel."""

    records: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str, str, str]] = set()
    for record in store.list_codes():
        dedupe_key = (
            record.get("friendly_name"),
            record["library"],
            record["name"],
            record["code_hash"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        target_devices = _code_target_devices(entry_data, record)
        command_entity_ids = {
            friendly_name: entity_id
            for friendly_name in target_devices
            if (
                entity_id := current_command_entity_id(
                    hass,
                    record_uid=record[ATTR_RECORD_UID],
                    friendly_name=friendly_name,
                )
            )
            is not None
        }
        records.append(
            {
                "code_id": record["code_id"],
                "name": record["name"],
                "default_entity_ids": {
                    friendly_name: desired_command_entity_id(
                        entry_data,
                        friendly_name,
                        record["code_id"],
                    )
                    for friendly_name in target_devices
                },
                "entity_ids": command_entity_ids,
                "library": record["library"],
                "friendly_name": record.get("friendly_name"),
                "shared": record.get("friendly_name") is None,
                "device_type": record.get("device_type"),
                "manufacturer": record.get("manufacturer"),
                "model": record.get("model"),
                "record_uid": record[ATTR_RECORD_UID],
                "source": record.get("source"),
                "updated_at": record.get("updated_at"),
            }
        )
    return records


def _code_target_devices(
    entry_data: dict[str, Any],
    record: dict[str, Any],
) -> list[str]:
    """Return the target device names that get a button entity for one record."""

    record_target = record.get(ATTR_FRIENDLY_NAME)
    if record_target:
        return [record_target] if record_target in entry_data["devices"] else []
    return sorted(entry_data["devices"])


def _serialize_catalog_sources(store: IRLibraryStore) -> list[dict[str, Any]]:
    """Serialize imported catalog sources for the panel."""

    return [
        {
            "source_key": record.get("source_key"),
            "source_name": record.get("source_name"),
            "origin_kind": record.get("origin_kind"),
            "source": record.get("source"),
            "remote_count": record.get("remote_count", 0),
            "truncated": bool(record.get("truncated", False)),
            "metadata": record.get("metadata", {}),
            "updated_at": record.get("updated_at"),
        }
        for record in store.list_catalog_sources()
    ]


def _serialize_catalog_remotes(store: IRLibraryStore) -> list[dict[str, Any]]:
    """Serialize imported catalog remotes for the panel."""

    return [
        {
            "remote_id": record.get("remote_id"),
            "source_key": record.get("source_key"),
            "source_name": record.get("source_name"),
            "origin_kind": record.get("origin_kind"),
            "origin_url": record.get("origin_url"),
            "relative_path": record.get("relative_path"),
            "category": record.get("category"),
            "brand": record.get("brand"),
            "model": record.get("model"),
            "display_name": record.get("display_name"),
            "manufacturer": record.get("manufacturer"),
            "device_type": record.get("device_type"),
            "library_hint": record.get("library_hint"),
            "command_count": record.get("command_count", 0),
            "supported_command_count": record.get("supported_command_count", 0),
            "unsupported_command_count": record.get("unsupported_command_count", 0),
            "preview_commands": list(record.get("preview_commands", [])),
            "updated_at": record.get("updated_at"),
        }
        for record in store.list_catalog_remotes()
    ]

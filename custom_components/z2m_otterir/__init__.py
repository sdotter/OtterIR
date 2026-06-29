"""OtterIR integration."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_CATALOG_NAME,
    ATTR_CODE,
    ATTR_CODE_ID,
    ATTR_COMMANDS_IMPORTED,
    ATTR_CSV_SOURCE,
    ATTR_DEVICE_TYPE,
    ATTR_ENTITY_ID_BASE,
    ATTR_ENCODING,
    ATTR_FILE_PATH,
    ATTR_FRIENDLY_NAME,
    ATTR_IMPORT_LIBRARY,
    ATTR_IMPORT_SOURCE,
    ATTR_LIBRARY,
    ATTR_MANUFACTURER,
    ATTR_MAX_FILES,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_OVERWRITE,
    ATTR_PENDING_NAME,
    ATTR_REPEAT,
    ATTR_REMOTE_ID,
    ATTR_TAGS,
    ATTR_SHARED,
    ATTR_SMARTIR_SOURCE,
    ATTR_SOURCE_KEY,
    ATTR_URL,
    CONF_BASE_TOPIC,
    CONF_DISCOVERY_PREFIX,
    CONF_ENABLE_AUTO,
    CONF_MANUAL_FRIENDLY_NAMES,
    DEFAULT_BASE_TOPIC,
    DEFAULT_DISCOVERY_PREFIX,
    DEFAULT_LIBRARY,
    DOMAIN,
    ENCODING_BROADLINK_BASE64,
    ENCODING_TUYA_RAW,
    PLATFORMS,
    SERVICE_DELETE_CODE,
    SERVICE_DELETE_CATALOG_SOURCE,
    SERVICE_IMPORT_CATALOG_REMOTE,
    SERVICE_IMPORT_CSV_COMMANDS,
    SERVICE_IMPORT_FLIPPER_SOURCE,
    SERVICE_IMPORT_BROADLINK_CODE,
    SERVICE_IMPORT_SMARTIR_JSON,
    SERVICE_SAVE_LEARNED_CODE,
    SERVICE_SEND_CODE,
    SERVICE_SEND_SAVED_CODE,
    SERVICE_SET_ENTITY_ID_BASE,
    SERVICE_START_LEARNING,
    SIGNAL_CATALOG_UPDATED,
    SIGNAL_IMPORT_FIELDS_UPDATED,
    SIGNAL_IR_CODE_LEARNED,
    SIGNAL_LIBRARY_UPDATED,
    SIGNAL_NEW_IR_DEVICE,
    SIGNAL_PENDING_NAME_UPDATED,
)
from .device_registry import is_ir_device, normalize_device
from .entity_ids import (
    async_update_device_entity_ids,
    command_button_unique_id,
    entity_id_base_for_device,
)
from .flipper_catalog import (
    async_import_flipper_source as async_import_flipper_catalog_source,
    iter_supported_catalog_commands,
)
from .frontend import async_register_panel
from .library import IRLibraryStore, build_learned_record, build_saved_record, parse_tags
from .list_import import nec_to_tuya, parse_command_list_text
from .mqtt_helpers import (
    build_learning_payload,
    build_payload,
    build_topic,
    convert_broadlink_to_tuya,
    extract_ir_code,
)
from .ws_api import async_register_ws_api

_LOGGER = logging.getLogger(__name__)


def _target_fields() -> dict[vol.Marker, object]:
    """Return reusable target service fields."""

    return {
        vol.Optional(ATTR_FRIENDLY_NAME): cv.string,
        vol.Optional(CONF_ENTITY_ID): cv.entity_id,
    }


SEND_CODE_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Required(ATTR_CODE): cv.string,
        vol.Optional(ATTR_REPEAT, default=1): vol.Coerce(int),
    }
)

START_LEARNING_SCHEMA = vol.Schema(_target_fields())

SAVE_LEARNED_CODE_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_CODE_ID): cv.string,
        vol.Optional(ATTR_LIBRARY, default=DEFAULT_LIBRARY): cv.string,
        vol.Optional(ATTR_DEVICE_TYPE, default="generic"): cv.string,
        vol.Optional(ATTR_MANUFACTURER): cv.string,
        vol.Optional(ATTR_MODEL): cv.string,
        vol.Optional(ATTR_TAGS, default=""): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_SHARED, default=True): bool,
        vol.Optional(ATTR_OVERWRITE, default=False): bool,
    }
)

SEND_SAVED_CODE_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Required(ATTR_CODE_ID): cv.string,
        vol.Optional(ATTR_REPEAT, default=1): vol.Coerce(int),
    }
)

DELETE_CODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CODE_ID): cv.string,
    }
)

IMPORT_BROADLINK_CODE_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Required(ATTR_NAME): cv.string,
        vol.Required(ATTR_CODE): cv.string,
        vol.Optional(ATTR_CODE_ID): cv.string,
        vol.Optional(ATTR_LIBRARY, default=DEFAULT_LIBRARY): cv.string,
        vol.Optional(ATTR_DEVICE_TYPE, default="generic"): cv.string,
        vol.Optional(ATTR_MANUFACTURER): cv.string,
        vol.Optional(ATTR_MODEL): cv.string,
        vol.Optional(ATTR_TAGS, default=""): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_SHARED, default=True): bool,
        vol.Optional(ATTR_OVERWRITE, default=False): bool,
    }
)

IMPORT_CSV_COMMANDS_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Optional(ATTR_IMPORT_SOURCE): cv.string,
        vol.Optional(ATTR_FILE_PATH): cv.string,
        vol.Optional(ATTR_URL): cv.string,
        vol.Optional(ATTR_LIBRARY): cv.string,
        vol.Optional(ATTR_DEVICE_TYPE, default="generic"): cv.string,
        vol.Optional(ATTR_MANUFACTURER): cv.string,
        vol.Optional(ATTR_MODEL): cv.string,
        vol.Optional(ATTR_TAGS, default=""): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_SHARED, default=True): bool,
        vol.Optional(ATTR_OVERWRITE, default=False): bool,
    }
)

IMPORT_SMARTIR_JSON_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Optional(ATTR_IMPORT_SOURCE): cv.string,
        vol.Optional(ATTR_FILE_PATH): cv.string,
        vol.Optional(ATTR_URL): cv.string,
        vol.Optional(ATTR_LIBRARY): cv.string,
        vol.Optional(ATTR_DEVICE_TYPE): cv.string,
        vol.Optional(ATTR_MANUFACTURER): cv.string,
        vol.Optional(ATTR_MODEL): cv.string,
        vol.Optional(ATTR_TAGS, default=""): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_SHARED, default=True): bool,
        vol.Optional(ATTR_OVERWRITE, default=False): bool,
    }
)

IMPORT_FLIPPER_SOURCE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_IMPORT_SOURCE): cv.string,
        vol.Optional(ATTR_FILE_PATH): cv.string,
        vol.Optional(ATTR_URL): cv.string,
        vol.Optional(ATTR_CATALOG_NAME): cv.string,
        vol.Optional(ATTR_MAX_FILES, default=200): vol.Coerce(int),
    }
)

IMPORT_CATALOG_REMOTE_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Required(ATTR_REMOTE_ID): cv.string,
        vol.Optional(ATTR_LIBRARY): cv.string,
        vol.Optional(ATTR_DEVICE_TYPE): cv.string,
        vol.Optional(ATTR_MANUFACTURER): cv.string,
        vol.Optional(ATTR_MODEL): cv.string,
        vol.Optional(ATTR_TAGS, default=""): vol.Any(cv.string, [cv.string]),
        vol.Optional(ATTR_SHARED, default=True): bool,
        vol.Optional(ATTR_OVERWRITE, default=False): bool,
    }
)

DELETE_CATALOG_SOURCE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SOURCE_KEY): cv.string,
    }
)

SET_ENTITY_ID_BASE_SCHEMA = vol.Schema(
    {
        **_target_fields(),
        vol.Optional(ATTR_ENTITY_ID_BASE, default=""): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OtterIR from a config entry."""

    entry_config = {**entry.data, **entry.options}
    base_topic = entry_config.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)
    discovery_prefix = entry_config.get(CONF_DISCOVERY_PREFIX, DEFAULT_DISCOVERY_PREFIX)
    enable_auto = entry_config.get(CONF_ENABLE_AUTO, True)
    manual_friendly_names = _manual_names(
        entry_config.get(CONF_MANUAL_FRIENDLY_NAMES, "")
    )

    store = IRLibraryStore(hass, entry.entry_id)
    await store.async_load()

    hass.data.setdefault(DOMAIN, {})

    old_data = hass.data[DOMAIN].get(entry.entry_id, {})
    for unsubscribe in old_data.get("unsub", []):
        unsubscribe()

    entry_data: dict[str, Any] = {
        "base_topic": base_topic,
        "csv_sources": dict(store.data["csv_sources"]),
        "devices": {},
        "entity_id_bases": dict(store.data["entity_id_bases"]),
        "import_libraries": dict(store.data["import_libraries"]),
        "learned": dict(store.last_learned),
        "pending_names": dict(store.data["pending_names"]),
        "smartir_sources": dict(store.data["smartir_sources"]),
        "store": store,
        "unsub": [],
    }
    hass.data[DOMAIN][entry.entry_id] = entry_data
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    @callback
    def maybe_add_device(device: dict[str, Any]) -> None:
        normalized = normalize_device(device)
        if normalized is None:
            return

        if not enable_auto and normalized["friendly_name"] not in manual_friendly_names:
            return

        if not is_ir_device(normalized, manual_friendly_names):
            return

        devices = entry_data["devices"]
        friendly_name = normalized["friendly_name"]
        is_new = friendly_name not in devices
        devices[friendly_name] = normalized

        if is_new:
            async_dispatcher_send(
                hass,
                SIGNAL_NEW_IR_DEVICE.format(entry.entry_id),
                normalized,
            )

    @callback
    def device_inventory_message(message) -> None:
        try:
            payload = json.loads(message.payload)
        except (TypeError, ValueError):
            _LOGGER.debug("Ignoring non-JSON Zigbee2MQTT device inventory payload")
            return

        if not isinstance(payload, list):
            return

        for device in payload:
            if isinstance(device, dict):
                maybe_add_device(device)

    @callback
    def discovery_message(message) -> None:
        try:
            payload = json.loads(message.payload)
        except (TypeError, ValueError):
            _LOGGER.debug("Ignoring non-JSON MQTT discovery payload")
            return

        if isinstance(payload, dict):
            maybe_add_device(payload)

    @callback
    def state_message(message) -> None:
        friendly_name = _friendly_name_from_topic(base_topic, message.topic)
        if friendly_name is None or friendly_name not in entry_data["devices"]:
            return

        try:
            payload = json.loads(message.payload)
        except (TypeError, ValueError):
            _LOGGER.debug("Ignoring non-JSON Zigbee2MQTT state payload")
            return

        if not isinstance(payload, dict):
            return

        learned_code = payload.get("learned_ir_code")
        if not isinstance(learned_code, str) or not learned_code:
            return

        learned_code = extract_ir_code(learned_code)
        current_record = entry_data["learned"].get(friendly_name)
        if current_record and current_record[ATTR_CODE] == learned_code:
            return

        record = build_learned_record(learned_code)
        entry_data["learned"][friendly_name] = record
        async_dispatcher_send(
            hass,
            SIGNAL_IR_CODE_LEARNED.format(entry.entry_id),
            {
                ATTR_FRIENDLY_NAME: friendly_name,
                "record": record,
            },
        )
        hass.async_create_task(store.async_set_last_learned(friendly_name, record))

    await mqtt.async_wait_for_mqtt_client(hass)

    # Zigbee2MQTT publishes the full device inventory on this topic, which lets
    # OtterIR discover IR-capable devices before state updates start arriving.
    unsub_device_inventory = await mqtt.async_subscribe(
        hass,
        f"{base_topic}/bridge/devices",
        device_inventory_message,
        0,
    )
    unsub_discovery = await mqtt.async_subscribe(
        hass,
        f"{discovery_prefix}/+/+/config",
        discovery_message,
        0,
    )
    unsub_discovery_with_node = await mqtt.async_subscribe(
        hass,
        f"{discovery_prefix}/+/+/+/config",
        discovery_message,
        0,
    )
    unsub_state = await mqtt.async_subscribe(
        hass,
        f"{base_topic}/+",
        state_message,
        0,
    )

    entry_data["unsub"].extend(
        [
            unsub_device_inventory,
            unsub_discovery,
            unsub_discovery_with_node,
            unsub_state,
        ]
    )

    _async_register_services(hass)
    async_register_ws_api(hass)
    await async_register_panel(hass)

    if _infrared_platform_available():
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    else:
        _LOGGER.warning(
            "Home Assistant infrared platform is not available; IR entities will "
            "not be created, but the %s services remain available",
            DOMAIN,
        )

    hass.async_create_task(_async_prune_stale_command_registry_entries(hass, entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = True
    if _infrared_platform_available():
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, {})
    for unsubscribe in data.get("unsub", []):
        unsubscribe()

    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)

    return unload_ok


def _infrared_platform_available() -> bool:
    """Return whether this Home Assistant build includes the infrared platform."""

    from importlib.util import find_spec

    return find_spec("homeassistant.components.infrared") is not None


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry after options change."""

    await hass.config_entries.async_reload(entry.entry_id)


async def _async_prune_stale_command_registry_entries(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Remove saved-command button registry rows that no longer map to stored codes."""

    await asyncio.sleep(10)

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return

    devices = entry_data.get("devices", {})
    if not devices:
        return

    valid_unique_ids: set[str] = set()
    for record in entry_data["store"].list_codes():
        target_name = record.get(ATTR_FRIENDLY_NAME)
        if target_name:
            target_names = [target_name] if target_name in devices else []
        else:
            target_names = sorted(devices)

        for friendly_name in target_names:
            valid_unique_ids.add(
                command_button_unique_id(record[ATTR_RECORD_UID], friendly_name)
            )

    registry = er.async_get(hass)
    removed_count = 0
    for registry_entry in list(registry.entities.values()):
        if registry_entry.platform != DOMAIN or registry_entry.domain != "button":
            continue
        if registry_entry.config_entry_id != entry.entry_id:
            continue

        unique_id = str(registry_entry.unique_id or "")
        if not unique_id.startswith(f"{DOMAIN}_saved_command_"):
            continue
        if unique_id in valid_unique_ids:
            continue

        registry.async_remove(registry_entry.entity_id)
        removed_count += 1

    if removed_count:
        _LOGGER.info("Removed %s stale OtterIR saved-command entities", removed_count)


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration services once."""

    async def async_send_code(call: ServiceCall) -> None:
        friendly_name, _, entry_data = _resolve_target_device(
            hass,
            friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
            entity_id=call.data.get(CONF_ENTITY_ID),
        )
        await _async_publish_code(
            hass,
            entry_data=entry_data,
            friendly_name=friendly_name,
            code=call.data[ATTR_CODE],
            repeat=max(1, call.data[ATTR_REPEAT]),
        )

    async def async_start_learning(call: ServiceCall) -> None:
        friendly_name, _, entry_data = _resolve_target_device(
            hass,
            friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
            entity_id=call.data.get(CONF_ENTITY_ID),
        )
        topic = build_topic(friendly_name, base_topic=entry_data["base_topic"])
        await hass.services.async_call(
            "mqtt",
            "publish",
            {
                "topic": topic,
                "payload": build_learning_payload(True),
            },
            blocking=True,
        )

    async def async_save_learned_code(call: ServiceCall) -> None:
        friendly_name, device, entry_data = _resolve_target_device(
            hass,
            friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
            entity_id=call.data.get(CONF_ENTITY_ID),
        )
        store: IRLibraryStore = entry_data["store"]
        learned = entry_data["learned"].get(friendly_name) or store.get_last_learned(
            friendly_name
        )
        if learned is None:
            raise HomeAssistantError(
                f"No learned code is available yet for '{friendly_name}'"
            )

        library = call.data[ATTR_LIBRARY]
        name = (
            call.data.get(ATTR_NAME)
            or entry_data["pending_names"].get(friendly_name, "")
        ).strip()
        if not name:
            raise HomeAssistantError(
                "No name was provided. Fill in 'Pending code name' on the device page or pass name in the service call."
            )
        overwrite = call.data[ATTR_OVERWRITE]
        code_id = call.data.get(ATTR_CODE_ID)
        if code_id is None and overwrite:
            code_id = _existing_code_id_for_name(store, library, name)
        if code_id is None:
            code_id = store.next_code_id(name, library)

        existing = store.get_code(code_id)
        if existing and not overwrite:
            raise HomeAssistantError(
                f"Code id '{code_id}' already exists; set overwrite to true or use a different id"
            )

        record = build_saved_record(
            code_id=code_id,
            name=name,
            code=learned[ATTR_CODE],
            source=learned["source"],
            encoding=learned[ATTR_ENCODING],
            library=library,
            friendly_name=_record_target_name(friendly_name, call.data[ATTR_SHARED]),
            device_type=call.data[ATTR_DEVICE_TYPE],
            manufacturer=call.data.get(ATTR_MANUFACTURER) or device.get("manufacturer"),
            model=call.data.get(ATTR_MODEL) or _device_model(device),
            tags=parse_tags(call.data.get(ATTR_TAGS)),
            learned_at=learned["learned_at"],
            created_at=existing["created_at"] if existing else None,
        )
        await store.async_upsert_code(record)
        await _async_set_pending_name(hass, entry_data, friendly_name, "")
        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(_entry_id_for_data(hass, entry_data)),
            {ATTR_FRIENDLY_NAME: record.get(ATTR_FRIENDLY_NAME)},
        )

    async def async_send_saved_code(call: ServiceCall) -> None:
        entry_id, store, record = _find_store_and_code(hass, call.data[ATTR_CODE_ID])
        if record is None:
            raise HomeAssistantError(f"Unknown code id '{call.data[ATTR_CODE_ID]}'")

        entry_data = hass.data[DOMAIN][entry_id]
        target_friendly_name = call.data.get(ATTR_FRIENDLY_NAME)
        entity_id = call.data.get(CONF_ENTITY_ID)
        if target_friendly_name is None and entity_id is None:
            target_friendly_name = record.get(ATTR_FRIENDLY_NAME)

        friendly_name, _, resolved_entry_data = _resolve_target_device(
            hass,
            friendly_name=target_friendly_name,
            entity_id=entity_id,
        )
        await _async_publish_code(
            hass,
            entry_data=resolved_entry_data if target_friendly_name or entity_id else entry_data,
            friendly_name=friendly_name,
            code=record[ATTR_CODE],
            repeat=max(1, call.data[ATTR_REPEAT]),
        )

    async def async_delete_code(call: ServiceCall) -> None:
        entry_id, store, record = _find_store_and_code(hass, call.data[ATTR_CODE_ID])
        if record is None:
            raise HomeAssistantError(f"Unknown code id '{call.data[ATTR_CODE_ID]}'")

        deleted = await store.async_delete_code(call.data[ATTR_CODE_ID])
        if not deleted:
            raise HomeAssistantError(f"Unable to delete code '{call.data[ATTR_CODE_ID]}'")

        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(entry_id),
            {ATTR_FRIENDLY_NAME: record.get(ATTR_FRIENDLY_NAME)},
        )

    async def async_import_broadlink_code(call: ServiceCall) -> None:
        friendly_name: str | None = None
        device: dict[str, Any] | None = None
        entry_data = _default_entry_data(hass)
        if call.data.get(ATTR_FRIENDLY_NAME) or call.data.get(CONF_ENTITY_ID):
            friendly_name, device, entry_data = _resolve_target_device(
                hass,
                friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
                entity_id=call.data.get(CONF_ENTITY_ID),
            )

        store: IRLibraryStore = entry_data["store"]
        library = call.data[ATTR_LIBRARY]
        name = call.data[ATTR_NAME]
        overwrite = call.data[ATTR_OVERWRITE]
        code_id = call.data.get(ATTR_CODE_ID)
        if code_id is None and overwrite:
            code_id = _existing_code_id_for_name(store, library, name)
        if code_id is None:
            code_id = store.next_code_id(name, library)

        existing = store.get_code(code_id)
        if existing and not overwrite:
            raise HomeAssistantError(
                f"Code id '{code_id}' already exists; set overwrite to true or use a different id"
            )

        converted_code = convert_broadlink_to_tuya(call.data[ATTR_CODE].strip())
        record = build_saved_record(
            code_id=code_id,
            name=name,
            code=converted_code,
            source="broadlink_import",
            encoding=ENCODING_TUYA_RAW,
            library=library,
            friendly_name=_record_target_name(friendly_name, call.data[ATTR_SHARED]),
            device_type=call.data[ATTR_DEVICE_TYPE],
            manufacturer=call.data.get(ATTR_MANUFACTURER) or (device or {}).get("manufacturer"),
            model=call.data.get(ATTR_MODEL) or _device_model(device or {}),
            tags=parse_tags(call.data.get(ATTR_TAGS)),
            created_at=existing["created_at"] if existing else None,
        )
        await store.async_upsert_code(record)
        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(_entry_id_for_data(hass, entry_data)),
            {ATTR_FRIENDLY_NAME: record.get(ATTR_FRIENDLY_NAME)},
        )

    async def async_import_csv_commands(call: ServiceCall) -> None:
        friendly_name: str | None = None
        device: dict[str, Any] | None = None
        entry_data = _default_entry_data(hass)
        if call.data.get(ATTR_FRIENDLY_NAME) or call.data.get(CONF_ENTITY_ID):
            friendly_name, device, entry_data = _resolve_target_device(
                hass,
                friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
                entity_id=call.data.get(CONF_ENTITY_ID),
            )

        store: IRLibraryStore = entry_data["store"]
        source = _resolve_import_source(call.data)
        _validate_csv_tsv_source(source)
        text = await _async_load_text_source(hass, source)
        commands = parse_command_list_text(text)

        library = call.data.get(ATTR_LIBRARY) or _library_from_source(source)
        overwrite = call.data[ATTR_OVERWRITE]
        record_friendly_name = _record_target_name(friendly_name, call.data[ATTR_SHARED])

        imported = 0
        for command_name, nec_code in commands:
            existing_id = (
                _existing_code_id_for_name(store, library, command_name)
                if overwrite
                else None
            )
            code_id = existing_id or store.next_code_id(command_name, library)
            existing = store.get_code(code_id)
            if existing and not overwrite:
                continue

            record = build_saved_record(
                code_id=code_id,
                name=command_name,
                code=nec_to_tuya(nec_code),
                source="csv_import",
                encoding=ENCODING_TUYA_RAW,
                library=library,
                friendly_name=record_friendly_name,
                device_type=call.data[ATTR_DEVICE_TYPE],
                manufacturer=call.data.get(ATTR_MANUFACTURER) or (device or {}).get("manufacturer"),
                model=call.data.get(ATTR_MODEL) or _device_model(device or {}),
                tags=parse_tags(call.data.get(ATTR_TAGS)),
                created_at=existing["created_at"] if existing else None,
            )
            await store.async_upsert_code(record)
            imported += 1

        if imported == 0:
            raise HomeAssistantError("No commands were imported from the provided list")

        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(_entry_id_for_data(hass, entry_data)),
            {
                ATTR_FRIENDLY_NAME: None if call.data[ATTR_SHARED] else friendly_name,
                ATTR_COMMANDS_IMPORTED: imported,
            },
        )

    async def async_import_smartir_json(call: ServiceCall) -> None:
        friendly_name: str | None = None
        device: dict[str, Any] | None = None
        entry_data = _default_entry_data(hass)
        if call.data.get(ATTR_FRIENDLY_NAME) or call.data.get(CONF_ENTITY_ID):
            friendly_name, device, entry_data = _resolve_target_device(
                hass,
                friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
                entity_id=call.data.get(CONF_ENTITY_ID),
            )

        store: IRLibraryStore = entry_data["store"]
        source = _resolve_import_source(call.data)
        payload = await _async_load_json_source(hass, source)
        commands = _flatten_command_tree(payload.get("commands", {}))
        if not commands:
            raise HomeAssistantError("No importable commands were found in the SmartIR JSON")

        library = call.data.get(ATTR_LIBRARY) or _library_from_source(source)
        overwrite = call.data[ATTR_OVERWRITE]
        manufacturer = call.data.get(ATTR_MANUFACTURER) or payload.get("manufacturer")
        models = payload.get("supportedModels") or []
        model = call.data.get(ATTR_MODEL) or (models[0] if models else _device_model(device or {}))
        device_type = call.data.get(ATTR_DEVICE_TYPE) or _device_type_from_source(source)
        supported_controller = str(payload.get("supportedController", "")).strip().lower()
        commands_encoding = str(payload.get("commandsEncoding", "")).strip().lower()

        imported = 0
        for command_name, raw_value in commands:
            existing_id = (
                _existing_code_id_for_name(store, library, command_name)
                if overwrite
                else None
            )
            code_id = existing_id or store.next_code_id(command_name, library)
            existing = store.get_code(code_id)
            if existing and not overwrite:
                continue

            normalized_code = _normalize_imported_code(
                raw_value,
                supported_controller=supported_controller,
                commands_encoding=commands_encoding,
            )
            record = build_saved_record(
                code_id=code_id,
                name=command_name,
                code=normalized_code,
                source="smartir_import",
                encoding=ENCODING_TUYA_RAW,
                library=library,
                friendly_name=_record_target_name(friendly_name, call.data[ATTR_SHARED]),
                device_type=device_type,
                manufacturer=manufacturer,
                model=model,
                tags=parse_tags(call.data.get(ATTR_TAGS)),
                created_at=existing["created_at"] if existing else None,
            )
            await store.async_upsert_code(record)
            imported += 1

        if imported == 0:
            raise HomeAssistantError("No commands were imported from the SmartIR JSON")

        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(_entry_id_for_data(hass, entry_data)),
            {
                ATTR_COMMANDS_IMPORTED: imported,
                ATTR_FRIENDLY_NAME: None if call.data[ATTR_SHARED] else friendly_name,
            },
        )

    async def async_import_flipper_source(call: ServiceCall) -> None:
        entry_id, entry_data = _default_entry(hass)
        store: IRLibraryStore = entry_data["store"]
        source = _resolve_import_source(call.data)
        source_record, remote_records = await async_import_flipper_catalog_source(
            hass,
            source,
            source_name=call.data.get(ATTR_CATALOG_NAME),
            max_files=call.data[ATTR_MAX_FILES],
        )
        await store.async_replace_catalog_source(source_record, remote_records)
        async_dispatcher_send(
            hass,
            SIGNAL_CATALOG_UPDATED.format(entry_id),
            {
                ATTR_SOURCE_KEY: source_record.get("source_key"),
                ATTR_COMMANDS_IMPORTED: sum(
                    remote.get("supported_command_count", 0) for remote in remote_records
                ),
            },
        )

    async def async_import_catalog_remote(call: ServiceCall) -> None:
        friendly_name: str | None = None
        device: dict[str, Any] | None = None
        entry_id, entry_data = _default_entry(hass)
        if call.data.get(ATTR_FRIENDLY_NAME) or call.data.get(CONF_ENTITY_ID):
            friendly_name, device, entry_data = _resolve_target_device(
                hass,
                friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
                entity_id=call.data.get(CONF_ENTITY_ID),
            )
            entry_id = _entry_id_for_data(hass, entry_data)

        store: IRLibraryStore = entry_data["store"]
        remote = store.get_catalog_remote(call.data[ATTR_REMOTE_ID])
        if remote is None:
            raise HomeAssistantError(f"Unknown catalog remote '{call.data[ATTR_REMOTE_ID]}'")

        commands = iter_supported_catalog_commands(remote)
        if not commands:
            raise HomeAssistantError("That catalog remote does not contain supported commands")

        library = (
            str(call.data.get(ATTR_LIBRARY) or remote.get("library_hint") or DEFAULT_LIBRARY)
            .strip()
            or DEFAULT_LIBRARY
        )
        overwrite = call.data[ATTR_OVERWRITE]
        record_friendly_name = _record_target_name(friendly_name, call.data[ATTR_SHARED])
        manufacturer = (
            call.data.get(ATTR_MANUFACTURER)
            or remote.get(ATTR_MANUFACTURER)
            or (device or {}).get("manufacturer")
        )
        model = call.data.get(ATTR_MODEL) or remote.get(ATTR_MODEL) or _device_model(device or {})
        device_type = call.data.get(ATTR_DEVICE_TYPE) or remote.get(ATTR_DEVICE_TYPE) or "generic"
        source_name = remote.get("source_name") or "catalog"
        remote_name = remote.get("display_name") or remote.get("model") or "remote"

        imported = 0
        for command in commands:
            command_name = str(command.get(ATTR_NAME) or "").strip()
            command_code = str(command.get(ATTR_CODE) or "").strip()
            if not command_name or not command_code:
                continue

            existing_id = (
                _existing_code_id_for_name(store, library, command_name)
                if overwrite
                else None
            )
            code_id = existing_id or store.next_code_id(command_name, library)
            existing = store.get_code(code_id)
            if existing and not overwrite:
                continue

            record = build_saved_record(
                code_id=code_id,
                name=command_name,
                code=command_code,
                source=f"catalog:{source_name}/{remote_name}",
                encoding=str(command.get(ATTR_ENCODING) or ENCODING_TUYA_RAW),
                library=library,
                friendly_name=record_friendly_name,
                device_type=str(device_type),
                manufacturer=manufacturer,
                model=model,
                tags=parse_tags(call.data.get(ATTR_TAGS)),
                created_at=existing["created_at"] if existing else None,
            )
            await store.async_upsert_code(record)
            imported += 1

        if imported == 0:
            raise HomeAssistantError("No commands were imported from that catalog remote")

        async_dispatcher_send(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(entry_id),
            {
                ATTR_COMMANDS_IMPORTED: imported,
                ATTR_FRIENDLY_NAME: None if call.data[ATTR_SHARED] else friendly_name,
                ATTR_REMOTE_ID: call.data[ATTR_REMOTE_ID],
            },
        )

    async def async_delete_catalog_source(call: ServiceCall) -> None:
        entry_id, entry_data = _default_entry(hass)
        store: IRLibraryStore = entry_data["store"]
        deleted = await store.async_delete_catalog_source(call.data[ATTR_SOURCE_KEY])
        if not deleted:
            raise HomeAssistantError(
                f"Unknown catalog source '{call.data[ATTR_SOURCE_KEY]}'"
            )
        async_dispatcher_send(
            hass,
            SIGNAL_CATALOG_UPDATED.format(entry_id),
            {ATTR_SOURCE_KEY: call.data[ATTR_SOURCE_KEY]},
        )

    async def async_set_entity_id_base(call: ServiceCall) -> None:
        friendly_name, _, entry_data = _resolve_target_device(
            hass,
            friendly_name=call.data.get(ATTR_FRIENDLY_NAME),
            entity_id=call.data.get(CONF_ENTITY_ID),
        )
        await _async_set_entity_id_base(
            hass,
            entry_data,
            friendly_name,
            call.data[ATTR_ENTITY_ID_BASE],
        )

    def register_service(name: str, handler, schema) -> None:
        if hass.services.has_service(DOMAIN, name):
            return
        hass.services.async_register(DOMAIN, name, handler, schema=schema)

    register_service(SERVICE_SEND_CODE, async_send_code, SEND_CODE_SCHEMA)
    register_service(SERVICE_START_LEARNING, async_start_learning, START_LEARNING_SCHEMA)
    register_service(
        SERVICE_SAVE_LEARNED_CODE,
        async_save_learned_code,
        SAVE_LEARNED_CODE_SCHEMA,
    )
    register_service(
        SERVICE_SEND_SAVED_CODE,
        async_send_saved_code,
        SEND_SAVED_CODE_SCHEMA,
    )
    register_service(SERVICE_DELETE_CODE, async_delete_code, DELETE_CODE_SCHEMA)
    register_service(
        SERVICE_IMPORT_BROADLINK_CODE,
        async_import_broadlink_code,
        IMPORT_BROADLINK_CODE_SCHEMA,
    )
    register_service(
        SERVICE_IMPORT_CSV_COMMANDS,
        async_import_csv_commands,
        IMPORT_CSV_COMMANDS_SCHEMA,
    )
    register_service(
        SERVICE_IMPORT_SMARTIR_JSON,
        async_import_smartir_json,
        IMPORT_SMARTIR_JSON_SCHEMA,
    )
    register_service(
        SERVICE_IMPORT_FLIPPER_SOURCE,
        async_import_flipper_source,
        IMPORT_FLIPPER_SOURCE_SCHEMA,
    )
    register_service(
        SERVICE_IMPORT_CATALOG_REMOTE,
        async_import_catalog_remote,
        IMPORT_CATALOG_REMOTE_SCHEMA,
    )
    register_service(
        SERVICE_DELETE_CATALOG_SOURCE,
        async_delete_catalog_source,
        DELETE_CATALOG_SOURCE_SCHEMA,
    )
    register_service(
        SERVICE_SET_ENTITY_ID_BASE,
        async_set_entity_id_base,
        SET_ENTITY_ID_BASE_SCHEMA,
    )


async def _async_publish_code(
    hass: HomeAssistant,
    *,
    entry_data: dict[str, Any],
    friendly_name: str,
    code: str,
    repeat: int,
) -> None:
    """Send a code to a Zigbee2MQTT IR emitter."""

    topic = build_topic(friendly_name, base_topic=entry_data["base_topic"])
    payload = build_payload(code)
    for _ in range(max(1, repeat)):
        await hass.services.async_call(
            "mqtt",
            "publish",
            {
                "topic": topic,
                "payload": payload,
            },
            blocking=True,
        )


async def _async_set_pending_name(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    friendly_name: str,
    value: str,
) -> None:
    """Update the pending name for an emitter."""

    cleaned = value.strip()
    entry_data["pending_names"][friendly_name] = cleaned
    store: IRLibraryStore = entry_data["store"]
    await store.async_set_pending_name(friendly_name, cleaned)
    async_dispatcher_send(
        hass,
        SIGNAL_PENDING_NAME_UPDATED.format(_entry_id_for_data(hass, entry_data)),
        {
            ATTR_FRIENDLY_NAME: friendly_name,
            ATTR_PENDING_NAME: cleaned,
        },
    )


async def _async_set_csv_source(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    friendly_name: str,
    value: str,
) -> None:
    """Update the CSV/TSV import source for an emitter."""

    cleaned = value.strip()
    entry_data["csv_sources"][friendly_name] = cleaned
    store: IRLibraryStore = entry_data["store"]
    await store.async_set_csv_source(friendly_name, cleaned)
    async_dispatcher_send(
        hass,
        SIGNAL_IMPORT_FIELDS_UPDATED.format(_entry_id_for_data(hass, entry_data)),
        {
            ATTR_FRIENDLY_NAME: friendly_name,
            ATTR_CSV_SOURCE: cleaned,
        },
    )


async def _async_set_import_library(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    friendly_name: str,
    value: str,
) -> None:
    """Update the import library for an emitter."""

    cleaned = value.strip()
    entry_data["import_libraries"][friendly_name] = cleaned
    store: IRLibraryStore = entry_data["store"]
    await store.async_set_import_library(friendly_name, cleaned)
    async_dispatcher_send(
        hass,
        SIGNAL_IMPORT_FIELDS_UPDATED.format(_entry_id_for_data(hass, entry_data)),
        {
            ATTR_FRIENDLY_NAME: friendly_name,
            ATTR_IMPORT_LIBRARY: cleaned,
        },
    )


async def _async_set_entity_id_base(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    friendly_name: str,
    value: str,
) -> None:
    """Update the entity-id base for an emitter and rename its entities."""

    cleaned = value.strip()
    store: IRLibraryStore = entry_data["store"]
    entry_data["entity_id_bases"][friendly_name] = cleaned
    await store.async_set_entity_id_base(friendly_name, cleaned)

    try:
        await async_update_device_entity_ids(
            hass,
            friendly_name=friendly_name,
            entity_id_base=cleaned or friendly_name,
        )
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err

    async_dispatcher_send(
        hass,
        SIGNAL_IMPORT_FIELDS_UPDATED.format(_entry_id_for_data(hass, entry_data)),
        {
            ATTR_FRIENDLY_NAME: friendly_name,
            ATTR_ENTITY_ID_BASE: cleaned,
        },
    )


async def _async_set_smartir_source(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    friendly_name: str,
    value: str,
) -> None:
    """Update the SmartIR import source for an emitter."""

    cleaned = value.strip()
    entry_data["smartir_sources"][friendly_name] = cleaned
    store: IRLibraryStore = entry_data["store"]
    await store.async_set_smartir_source(friendly_name, cleaned)
    async_dispatcher_send(
        hass,
        SIGNAL_IMPORT_FIELDS_UPDATED.format(_entry_id_for_data(hass, entry_data)),
        {
            ATTR_FRIENDLY_NAME: friendly_name,
            ATTR_SMARTIR_SOURCE: cleaned,
        },
    )


def pending_name_for_device(entry_data: dict[str, Any], friendly_name: str) -> str:
    """Return the pending name for a device."""

    return entry_data.get("pending_names", {}).get(friendly_name, "")


def csv_source_for_device(entry_data: dict[str, Any], friendly_name: str) -> str:
    """Return the configured CSV/TSV source for a device."""

    return entry_data.get("csv_sources", {}).get(friendly_name, "")


def import_library_for_device(entry_data: dict[str, Any], friendly_name: str) -> str:
    """Return the configured import library for a device."""

    return entry_data.get("import_libraries", {}).get(friendly_name, "")


def entity_id_base_for_entry_device(entry_data: dict[str, Any], friendly_name: str) -> str:
    """Return the configured entity-id base for a device."""

    return entity_id_base_for_device(entry_data, friendly_name)


def smartir_source_for_device(entry_data: dict[str, Any], friendly_name: str) -> str:
    """Return the configured SmartIR source for a device."""

    return entry_data.get("smartir_sources", {}).get(friendly_name, "")


def _resolve_target_device(
    hass: HomeAssistant,
    *,
    friendly_name: str | None = None,
    entity_id: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Resolve a service target to a known Zigbee2MQTT IR device."""

    if friendly_name is None and entity_id is not None:
        friendly_name = _friendly_name_from_entity_id(hass, entity_id)

    if friendly_name is not None:
        for entry_data in hass.data.get(DOMAIN, {}).values():
            device = entry_data.get("devices", {}).get(friendly_name)
            if device is not None:
                return friendly_name, device, entry_data
        raise HomeAssistantError(f"Unknown IR device '{friendly_name}'")

    candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for entry_data in hass.data.get(DOMAIN, {}).values():
        for candidate_name, device in entry_data.get("devices", {}).items():
            candidates.append((candidate_name, device, entry_data))

    if not candidates:
        raise HomeAssistantError("No Zigbee2MQTT IR devices are available")
    if len(candidates) > 1:
        raise HomeAssistantError(
            "friendly_name or entity_id is required because multiple IR devices are available"
        )

    return candidates[0]


def _find_store_and_code(
    hass: HomeAssistant,
    code_id: str,
) -> tuple[str, IRLibraryStore, dict[str, Any] | None]:
    """Find the store and record that own a saved code id."""

    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        store: IRLibraryStore = entry_data["store"]
        record = store.get_code(code_id)
        if record is not None:
            return entry_id, store, record
    return "", _default_entry_data(hass)["store"], None


def _default_entry_data(hass: HomeAssistant) -> dict[str, Any]:
    """Return the only configured entry data."""

    entries = list(hass.data.get(DOMAIN, {}).values())
    if not entries:
        raise HomeAssistantError("OtterIR is not configured")
    return entries[0]


def _default_entry(hass: HomeAssistant) -> tuple[str, dict[str, Any]]:
    """Return the first configured entry id and data."""

    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        return entry_id, entry_data
    raise HomeAssistantError("OtterIR is not configured")


def _entry_id_for_data(hass: HomeAssistant, entry_data: dict[str, Any]) -> str:
    """Return the config entry id for a data block."""

    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if data is entry_data:
            return entry_id
    raise HomeAssistantError("Unable to resolve config entry for IR data")


def _existing_code_id_for_name(
    store: IRLibraryStore,
    library: str,
    name: str,
) -> str | None:
    """Return an existing code id for a library/name pair."""

    for record in store.list_codes():
        if record[ATTR_LIBRARY] == library and record[ATTR_NAME] == name:
            return record[ATTR_CODE_ID]
    return None


def _record_target_name(
    friendly_name: str | None,
    shared: bool,
) -> str | None:
    """Return the record target name for shared or device-local storage."""

    return None if shared else friendly_name


def _friendly_name_from_entity_id(
    hass: HomeAssistant,
    entity_id: str,
) -> str | None:
    """Resolve a Home Assistant entity id to a friendly name."""

    entity_state = hass.states.get(entity_id)
    entity_name = entity_state.name if entity_state is not None else None

    for entry_data in hass.data.get(DOMAIN, {}).values():
        for friendly_name in entry_data.get("devices", {}):
            slug = friendly_name.lower().replace(" ", "_")
            if slug in entity_id:
                return friendly_name
            if entity_name and entity_name.startswith(friendly_name):
                return friendly_name

    return None


def _friendly_name_from_topic(base_topic: str, topic: str) -> str | None:
    """Extract a Zigbee2MQTT friendly name from a state topic."""

    prefix = f"{base_topic}/"
    if not topic.startswith(prefix):
        return None

    suffix = topic[len(prefix) :]
    if "/" in suffix:
        return None

    return suffix or None


def _manual_names(value: str | list[str] | tuple[str, ...]) -> set[str]:
    """Parse manual friendly names from config flow input."""

    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}

    return {str(item).strip() for item in value if str(item).strip()}


def _resolve_config_path(file_path: str) -> Path:
    """Resolve an import path and keep it inside /config."""

    config_root = Path("/config").resolve()
    path = Path(file_path)
    if not path.is_absolute():
        path = config_root / path

    resolved = path.resolve()
    if resolved != config_root and config_root not in resolved.parents:
        raise HomeAssistantError("file_path must point inside /config")
    if not resolved.is_file():
        raise HomeAssistantError(f"File '{resolved}' does not exist")
    return resolved


def _resolve_import_source(data: dict[str, Any]) -> str:
    """Resolve a single import source from service data."""

    values = [
        str(value).strip()
        for value in (
            data.get(ATTR_IMPORT_SOURCE),
            data.get(ATTR_FILE_PATH),
            data.get(ATTR_URL),
        )
        if value and str(value).strip()
    ]
    unique_values = list(dict.fromkeys(values))
    if not unique_values:
        raise HomeAssistantError("import_source is required")
    if len(unique_values) > 1:
        raise HomeAssistantError("Use only one import source")
    return unique_values[0]


def _is_remote_source(source: str) -> bool:
    """Return whether the source points to an HTTP(S) resource."""

    lowered = source.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _normalize_remote_source_url(source: str) -> str:
    """Normalize known GitHub URLs to raw download endpoints."""

    parsed = urlparse(source.strip())
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host == "github.com":
        parts = path.split("/")
        if len(parts) >= 5 and parts[2] == "blob":
            return (
                f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/"
                f"{parts[3]}/{'/'.join(parts[4:])}"
            )

    if host == "gist.github.com":
        if "/raw" in parsed.path:
            return f"https://gist.githubusercontent.com/{path}"
        return f"https://gist.githubusercontent.com/{path}/raw"

    return source.strip()


async def _async_load_text_source(hass: HomeAssistant, source: str) -> str:
    """Load plain text from a local file or remote URL."""

    if _is_remote_source(source):
        session = async_get_clientsession(hass)
        normalized_url = _normalize_remote_source_url(source)
        async with session.get(normalized_url) as response:
            if response.status >= 400:
                raise HomeAssistantError(
                    f"Unable to download import source ({response.status})"
                )
            return await response.text()

    resolved = _resolve_config_path(source)
    return await hass.async_add_executor_job(_load_text_file, resolved)


async def _async_load_json_source(
    hass: HomeAssistant,
    source: str,
) -> dict[str, Any]:
    """Load a JSON object from a local file or remote URL."""

    text = await _async_load_text_source(hass, source)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as err:
        raise HomeAssistantError("The SmartIR source does not contain valid JSON") from err

    if not isinstance(payload, dict):
        raise HomeAssistantError("The SmartIR source must contain a JSON object")
    return payload


def _load_text_file(path: Path) -> str:
    """Load a plain-text file from disk."""

    with path.open("r", encoding="utf-8") as handle:
        return handle.read()


def _flatten_command_tree(
    commands: dict[str, Any],
    prefix: str = "",
) -> list[tuple[str, str]]:
    """Flatten nested SmartIR command trees to name/value pairs."""

    flattened: list[tuple[str, str]] = []
    for key, value in commands.items():
        command_name = key if not prefix else f"{prefix}.{key}"
        if isinstance(value, str):
            flattened.append((command_name, value))
            continue
        if isinstance(value, dict):
            flattened.extend(_flatten_command_tree(value, command_name))
    return flattened


def _normalize_imported_code(
    raw_value: str,
    *,
    supported_controller: str,
    commands_encoding: str,
) -> str:
    """Normalize an imported command to the internal Tuya raw format."""

    if commands_encoding == "raw":
        return extract_ir_code(raw_value)

    if (
        commands_encoding == "base64"
        and supported_controller in {"broadlink", "", ENCODING_BROADLINK_BASE64}
    ):
        try:
            return convert_broadlink_to_tuya(raw_value)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    raise HomeAssistantError(
        "Unsupported SmartIR command format; expected MQTT Raw or Broadlink Base64"
    )


def _device_model(device: dict[str, Any]) -> str | None:
    """Return the best available model value."""

    return (
        device.get("model_id")
        or device.get("model")
        or device.get("definition", {}).get("model")
        or device.get("device", {}).get("model")
        or device.get("dev", {}).get("mdl")
        or device.get("dev", {}).get("model")
    )


def _path_from_source(source: str) -> Path:
    """Return a best-effort path-like view of a local or remote source."""

    if _is_remote_source(source):
        return Path(urlparse(source).path)
    return Path(source)


def _library_from_source(source: str) -> str:
    """Infer a library name from an import source."""

    stem = _path_from_source(source).stem.strip()
    return stem or DEFAULT_LIBRARY


def _device_type_from_source(source: str) -> str:
    """Infer a device type from a SmartIR source path."""

    parent_name = _path_from_source(source).parent.name.lower()
    if parent_name in {"climate", "fan", "media_player", "light"}:
        return parent_name
    return "generic"


def _validate_csv_tsv_source(source: str) -> None:
    """Require a real CSV or TSV source path/URL."""

    normalized_source = _normalize_remote_source_url(source) if _is_remote_source(source) else source
    suffix = _path_from_source(normalized_source).suffix.lower()
    if suffix not in {".csv", ".tsv"}:
        raise HomeAssistantError(
            "CSV import only accepts real .csv or .tsv sources"
        )

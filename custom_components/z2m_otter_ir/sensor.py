"""Sensor platform for OtterIR."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CODE,
    ATTR_CODE_HASH,
    ATTR_CODE_ID,
    ATTR_CODE_IDS,
    ATTR_CODE_LENGTH,
    ATTR_CSV_SOURCE,
    ATTR_ENTITY_ID_BASE,
    ATTR_ENCODING,
    ATTR_FRIENDLY_NAME,
    ATTR_IMPORT_LIBRARY,
    ATTR_LEARNED_AT,
    ATTR_PENDING_NAME,
    ATTR_SAVED_COUNT,
    ATTR_SAVED_NAMES,
    ATTR_SMARTIR_SOURCE,
    ATTR_SOURCE,
    DOMAIN,
    SIGNAL_IMPORT_FIELDS_UPDATED,
    SIGNAL_IR_CODE_LEARNED,
    SIGNAL_LIBRARY_UPDATED,
    SIGNAL_NEW_IR_DEVICE,
    SIGNAL_PENDING_NAME_UPDATED,
)
from .device_registry import build_device_info
from .entity_ids import desired_entity_id, entity_id_base_for_device
from .library import IRLibraryStore


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for discovered IR devices."""

    data = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    @callback
    def add_device(device: dict) -> None:
        friendly_name = device["friendly_name"]
        if friendly_name in added:
            return

        added.add(friendly_name)
        entity_id = desired_entity_id("sensor", entity_id_base_for_device(data, friendly_name))
        async_add_entities(
            [Z2MIRLastLearnedSensor(hass, entry.entry_id, friendly_name, device, entity_id)]
        )

    for device in data["devices"].values():
        add_device(device)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_IR_DEVICE.format(entry.entry_id),
            add_device,
        )
    )


class Z2MIRLastLearnedSensor(SensorEntity):
    """Sensor that exposes the most recent learned IR code."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        friendly_name: str,
        device: dict,
        entity_id: str | None = None,
    ) -> None:
        """Initialize the sensor."""

        self.hass = hass
        self._entry_id = entry_id
        self._friendly_name = friendly_name
        self._attr_name = "Last learned code"
        self._attr_unique_id = f"{DOMAIN}_{friendly_name}_last_learned_code"
        self._attr_device_info = build_device_info(DOMAIN, friendly_name, device)
        self._attr_native_value = "none"
        self._attr_extra_state_attributes = {}
        if entity_id:
            self.entity_id = entity_id
        self._refresh_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime updates."""

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_IR_CODE_LEARNED.format(self._entry_id),
                self._handle_learned_code,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_LIBRARY_UPDATED.format(self._entry_id),
                self._handle_library_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PENDING_NAME_UPDATED.format(self._entry_id),
                self._handle_pending_name_update,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_IMPORT_FIELDS_UPDATED.format(self._entry_id),
                self._handle_import_fields_update,
            )
        )

    @callback
    def _handle_learned_code(self, payload: dict) -> None:
        """Refresh the sensor when a code is learned."""

        if payload.get(ATTR_FRIENDLY_NAME) != self._friendly_name:
            return
        self._refresh_state()
        self.async_write_ha_state()

    @callback
    def _handle_library_update(self, payload: dict) -> None:
        """Refresh the sensor when the library changes."""

        target = payload.get(ATTR_FRIENDLY_NAME)
        if target not in {None, self._friendly_name}:
            return
        self._refresh_state()
        self.async_write_ha_state()

    @callback
    def _handle_pending_name_update(self, payload: dict) -> None:
        """Refresh the sensor when the pending name changes."""

        if payload.get(ATTR_FRIENDLY_NAME) != self._friendly_name:
            return
        self._refresh_state()
        self.async_write_ha_state()

    @callback
    def _handle_import_fields_update(self, payload: dict) -> None:
        """Refresh the sensor when import fields change."""

        if payload.get(ATTR_FRIENDLY_NAME) != self._friendly_name:
            return
        self._refresh_state()
        self.async_write_ha_state()

    def _refresh_state(self) -> None:
        """Update the sensor state from runtime and persistent storage."""

        entry_data = self.hass.data[DOMAIN][self._entry_id]
        store: IRLibraryStore = entry_data["store"]
        learned = entry_data["learned"].get(self._friendly_name) or store.get_last_learned(
            self._friendly_name
        )
        saved_codes = store.list_codes(self._friendly_name)

        if learned is None:
            self._attr_native_value = "none"
            self._attr_extra_state_attributes = {
                ATTR_CSV_SOURCE: entry_data["csv_sources"].get(self._friendly_name, ""),
                ATTR_ENTITY_ID_BASE: entry_data["entity_id_bases"].get(self._friendly_name, ""),
                ATTR_IMPORT_LIBRARY: entry_data["import_libraries"].get(self._friendly_name, ""),
                ATTR_PENDING_NAME: entry_data["pending_names"].get(self._friendly_name, ""),
                ATTR_SAVED_COUNT: len(saved_codes),
                ATTR_CODE_IDS: [record[ATTR_CODE_ID] for record in saved_codes],
                ATTR_SAVED_NAMES: [record["name"] for record in saved_codes],
                ATTR_SMARTIR_SOURCE: entry_data["smartir_sources"].get(self._friendly_name, ""),
            }
            return

        self._attr_native_value = learned[ATTR_CODE_HASH]
        self._attr_extra_state_attributes = {
            ATTR_CODE: learned[ATTR_CODE],
            ATTR_CODE_HASH: learned[ATTR_CODE_HASH],
            ATTR_CODE_LENGTH: learned[ATTR_CODE_LENGTH],
            ATTR_CSV_SOURCE: entry_data["csv_sources"].get(self._friendly_name, ""),
            ATTR_ENTITY_ID_BASE: entry_data["entity_id_bases"].get(self._friendly_name, ""),
            ATTR_ENCODING: learned[ATTR_ENCODING],
            ATTR_IMPORT_LIBRARY: entry_data["import_libraries"].get(self._friendly_name, ""),
            ATTR_LEARNED_AT: learned[ATTR_LEARNED_AT],
            ATTR_PENDING_NAME: entry_data["pending_names"].get(self._friendly_name, ""),
            ATTR_SAVED_COUNT: len(saved_codes),
            ATTR_CODE_IDS: [record[ATTR_CODE_ID] for record in saved_codes],
            ATTR_SAVED_NAMES: [record["name"] for record in saved_codes],
            ATTR_SMARTIR_SOURCE: entry_data["smartir_sources"].get(self._friendly_name, ""),
            ATTR_SOURCE: learned[ATTR_SOURCE],
        }

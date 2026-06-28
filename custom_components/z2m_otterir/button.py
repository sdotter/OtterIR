"""Button platform for OtterIR."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CODE_ID,
    ATTR_FRIENDLY_NAME,
    ATTR_LIBRARY,
    ATTR_NAME,
    ATTR_RECORD_UID,
    ATTR_SOURCE,
    DOMAIN,
    SERVICE_SEND_SAVED_CODE,
    SERVICE_START_LEARNING,
    SIGNAL_LIBRARY_UPDATED,
    SIGNAL_NEW_IR_DEVICE,
)
from .device_registry import build_device_info
from .entity_ids import (
    command_button_unique_id,
    desired_command_entity_id,
    desired_entity_id,
    entity_id_base_for_device,
)
from .library import SavedCodeRecord


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons for discovered IR devices and saved commands."""

    data = hass.data[DOMAIN][entry.entry_id]
    learn_added: set[str] = set()
    command_entities: dict[str, Z2MIRSavedCodeButton] = {}

    @callback
    def add_learn_button(device: dict[str, Any]) -> None:
        friendly_name = device["friendly_name"]
        if friendly_name in learn_added:
            return

        learn_added.add(friendly_name)
        entity_id = desired_entity_id(
            "button",
            entity_id_base_for_device(data, friendly_name),
        )
        async_add_entities(
            [
                Z2MIRLearnButton(hass, friendly_name, device, entity_id),
            ]
        )

    @callback
    def _command_entity_key(record_uid: str, friendly_name: str) -> str:
        return f"{record_uid}::{friendly_name}"

    @callback
    def _target_names_for_record(record: SavedCodeRecord) -> list[str]:
        record_target = record.get(ATTR_FRIENDLY_NAME)
        if record_target:
            return [record_target] if record_target in data["devices"] else []
        return sorted(data["devices"])

    @callback
    def refresh_command_buttons(_: dict[str, Any] | None = None) -> None:
        desired_keys: set[str] = set()
        new_entities: list[Z2MIRSavedCodeButton] = []

        # Shared commands are materialized once per compatible IR device, while
        # device-specific commands stay attached to a single target blaster.
        for record in data["store"].list_codes():
            for friendly_name in _target_names_for_record(record):
                device = data["devices"].get(friendly_name)
                if device is None:
                    continue

                key = _command_entity_key(record[ATTR_RECORD_UID], friendly_name)
                desired_keys.add(key)
                entity = command_entities.get(key)
                if entity is None:
                    entity = Z2MIRSavedCodeButton(
                        hass=hass,
                        entry_id=entry.entry_id,
                        entry_data=data,
                        record=record,
                        target_friendly_name=friendly_name,
                        device=device,
                    )
                    command_entities[key] = entity
                    new_entities.append(entity)
                    continue

                entity.async_update_record(record=record, entry_data=data, device=device)

        stale_keys = [key for key in command_entities if key not in desired_keys]
        for key in stale_keys:
            entity = command_entities.pop(key)
            hass.async_create_task(entity.async_remove(force_remove=True))

        if new_entities:
            async_add_entities(new_entities)

    @callback
    def handle_new_device(device: dict[str, Any]) -> None:
        add_learn_button(device)
        refresh_command_buttons()

    for device in data["devices"].values():
        add_learn_button(device)

    refresh_command_buttons()

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_NEW_IR_DEVICE.format(entry.entry_id),
            handle_new_device,
        )
    )
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_LIBRARY_UPDATED.format(entry.entry_id),
            refresh_command_buttons,
        )
    )


class Z2MIRLearnButton(ButtonEntity):
    """Button that puts the IR blaster in learning mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        friendly_name: str,
        device: dict[str, Any],
        entity_id: str | None = None,
    ) -> None:
        """Initialize the button."""

        self.hass = hass
        self._friendly_name = friendly_name
        self._attr_name = "Learn IR code"
        self._attr_icon = "mdi:remote"
        self._attr_unique_id = f"{DOMAIN}_{friendly_name}_learn_ir_code"
        self._attr_device_info = build_device_info(DOMAIN, friendly_name, device)
        if entity_id:
            self.entity_id = entity_id

    async def async_press(self) -> None:
        """Start learning mode on the configured blaster."""

        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_START_LEARNING,
            {
                ATTR_FRIENDLY_NAME: self._friendly_name,
            },
            blocking=True,
        )


class Z2MIRSavedCodeButton(ButtonEntity):
    """Button entity for one saved IR command on one target device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry_id: str,
        entry_data: dict[str, Any],
        record: SavedCodeRecord,
        target_friendly_name: str,
        device: dict[str, Any],
    ) -> None:
        """Initialize a saved-command button."""

        self.hass = hass
        self._entry_id = entry_id
        self._entry_data = entry_data
        self._target_friendly_name = target_friendly_name
        self._record: SavedCodeRecord = record
        self._attr_icon = "mdi:play"
        self._apply_record(record, entry_data, device)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose library metadata for the saved command."""

        return {
            ATTR_CODE_ID: self._record[ATTR_CODE_ID],
            ATTR_LIBRARY: self._record[ATTR_LIBRARY],
            ATTR_RECORD_UID: self._record[ATTR_RECORD_UID],
            ATTR_SOURCE: self._record.get(ATTR_SOURCE),
            "shared": self._record.get(ATTR_FRIENDLY_NAME) is None,
        }

    @callback
    def async_update_record(
        self,
        *,
        record: SavedCodeRecord,
        entry_data: dict[str, Any],
        device: dict[str, Any],
    ) -> None:
        """Refresh this entity after library changes."""

        self._apply_record(record, entry_data, device)
        if self.hass is not None and self.platform is not None:
            self.async_write_ha_state()

    def _apply_record(
        self,
        record: SavedCodeRecord,
        entry_data: dict[str, Any],
        device: dict[str, Any],
    ) -> None:
        """Apply record data to entity attributes."""

        self._record = record
        self._entry_data = entry_data
        self._attr_name = record[ATTR_NAME]
        self._attr_unique_id = command_button_unique_id(
            record[ATTR_RECORD_UID],
            self._target_friendly_name,
        )
        self._attr_device_info = build_device_info(
            DOMAIN,
            self._target_friendly_name,
            device,
        )
        self.entity_id = desired_command_entity_id(
            entry_data,
            self._target_friendly_name,
            record[ATTR_CODE_ID],
        )

    async def async_press(self) -> None:
        """Send the saved code through the assigned IR blaster."""

        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_SEND_SAVED_CODE,
            {
                ATTR_CODE_ID: self._record[ATTR_CODE_ID],
                ATTR_FRIENDLY_NAME: self._target_friendly_name,
            },
            blocking=True,
        )

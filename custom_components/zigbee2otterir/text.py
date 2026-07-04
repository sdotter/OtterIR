"""Text platform for OtterIR."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import (
    _async_set_pending_name,
    pending_name_for_device,
)
from .const import (
    ATTR_FRIENDLY_NAME,
    ATTR_PENDING_NAME,
    DOMAIN,
    SIGNAL_NEW_IR_DEVICE,
    SIGNAL_PENDING_NAME_UPDATED,
)
from .device_registry import build_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the editable text fields for discovered IR devices."""

    data = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    @callback
    def add_device(device: dict) -> None:
        friendly_name = device["friendly_name"]
        if friendly_name in added:
            return

        added.add(friendly_name)
        async_add_entities(
            [
                Z2MIRPendingNameText(hass, entry.entry_id, friendly_name, device),
            ]
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


class Z2MIRPendingNameText(TextEntity):
    """Editable field for the next saved code name."""

    _attr_has_entity_name = True
    _attr_native_max = 80

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        friendly_name: str,
        device: dict,
    ) -> None:
        """Initialize the text entity."""

        self.hass = hass
        self._entry_id = entry_id
        self._friendly_name = friendly_name
        self._attr_name = "Pending code name"
        self._attr_icon = "mdi:form-textbox"
        self._attr_unique_id = f"{DOMAIN}_{friendly_name}_pending_code_name"
        self._attr_device_info = build_device_info(DOMAIN, friendly_name, device)
        self._attr_native_value = pending_name_for_device(
            hass.data[DOMAIN][entry_id],
            friendly_name,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to state updates."""

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PENDING_NAME_UPDATED.format(self._entry_id),
                self._handle_pending_name_update,
            )
        )

    @callback
    def _handle_pending_name_update(self, payload: dict) -> None:
        """Handle pending-name updates from runtime or services."""

        if payload.get(ATTR_FRIENDLY_NAME) != self._friendly_name:
            return
        self._attr_native_value = payload.get(ATTR_PENDING_NAME, "")
        self.async_write_ha_state()

    async def async_set_value(self, value: str) -> None:
        """Set the pending code name."""

        entry_data = self.hass.data[DOMAIN][self._entry_id]
        await _async_set_pending_name(
            self.hass,
            entry_data,
            self._friendly_name,
            value,
        )

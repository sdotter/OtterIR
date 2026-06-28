"""Event platform for OtterIR."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CODE,
    ATTR_CODE_HASH,
    ATTR_CODE_LENGTH,
    ATTR_FRIENDLY_NAME,
    ATTR_LEARNED_AT,
    DOMAIN,
    EVENT_LEARNED,
    SIGNAL_IR_CODE_LEARNED,
    SIGNAL_NEW_IR_DEVICE,
)
from .device_registry import build_device_info
from .entity_ids import desired_entity_id, entity_id_base_for_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event entities for discovered IR devices."""

    data = hass.data[DOMAIN][entry.entry_id]
    added: set[str] = set()

    @callback
    def add_device(device: dict) -> None:
        friendly_name = device["friendly_name"]
        if friendly_name in added:
            return

        added.add(friendly_name)
        entity_id = desired_entity_id("event", entity_id_base_for_device(data, friendly_name))
        async_add_entities(
            [Z2MIRLearnedEvent(hass, entry.entry_id, friendly_name, device, entity_id)]
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


class Z2MIRLearnedEvent(EventEntity):
    """Event entity that fires when the blaster learns a code."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [EVENT_LEARNED]
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        friendly_name: str,
        device: dict,
        entity_id: str | None = None,
    ) -> None:
        """Initialize the event entity."""

        self.hass = hass
        self._entry_id = entry_id
        self._friendly_name = friendly_name
        self._attr_name = "Learned signal"
        self._attr_unique_id = f"{DOMAIN}_{friendly_name}_learned_signal"
        self._attr_device_info = build_device_info(DOMAIN, friendly_name, device)
        if entity_id:
            self.entity_id = entity_id

    async def async_added_to_hass(self) -> None:
        """Subscribe to learned-code updates."""

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_IR_CODE_LEARNED.format(self._entry_id),
                self._handle_learned_code,
            )
        )

    @callback
    def _handle_learned_code(self, payload: dict) -> None:
        """Emit the event when a matching code is learned."""

        if payload.get(ATTR_FRIENDLY_NAME) != self._friendly_name:
            return

        record = payload["record"]
        self._trigger_event(
            EVENT_LEARNED,
            {
                ATTR_CODE: record[ATTR_CODE],
                ATTR_CODE_HASH: record[ATTR_CODE_HASH],
                ATTR_CODE_LENGTH: record[ATTR_CODE_LENGTH],
                ATTR_LEARNED_AT: record[ATTR_LEARNED_AT],
            },
        )

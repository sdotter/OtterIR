"""Helpers for OtterIR entity ID generation and migration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import entity_registry as er

from .const import ATTR_ENTITY_ID_BASE, DOMAIN
from .library import slugify

ENTITY_ID_SUFFIXES: dict[str, str] = {
    "infrared": "",
    "button": "_learn_ir_code",
    "sensor": "_last_learned_code",
    "event": "_learned_signal",
    "text": "_pending_code_name",
}


def default_entity_id_base(friendly_name: str) -> str:
    """Return the default entity-id base for a device."""

    return slugify(friendly_name)


def entity_id_base_for_device(entry_data: dict[str, Any], friendly_name: str) -> str:
    """Return the configured or default entity-id base for a device."""

    configured = str(
        entry_data.get("entity_id_bases", {}).get(friendly_name, "")
    ).strip()
    return slugify(configured or friendly_name)


def desired_entity_id(domain: str, base: str) -> str:
    """Return the desired entity ID for one OtterIR entity domain."""

    suffix = ENTITY_ID_SUFFIXES[domain]
    return f"{domain}.{base}{suffix}"


def command_button_unique_id(record_uid: str, friendly_name: str) -> str:
    """Return the unique id for a saved-command button entity."""

    return f"{DOMAIN}_saved_command_{slugify(friendly_name)}_{record_uid}"


def command_entity_id_base(
    entry_data: dict[str, Any],
    friendly_name: str,
    code_id: str,
) -> str:
    """Return the desired base for a saved-command button entity."""

    device_base = entity_id_base_for_device(entry_data, friendly_name)
    return slugify(f"{device_base}_{code_id}")


def desired_command_entity_id(
    entry_data: dict[str, Any],
    friendly_name: str,
    code_id: str,
) -> str:
    """Return the desired button entity id for a saved command on one device."""

    return f"button.{command_entity_id_base(entry_data, friendly_name, code_id)}"


async def async_update_device_entity_ids(
    hass,
    *,
    friendly_name: str,
    entity_id_base: str,
) -> dict[str, str]:
    """Rename all known OtterIR entity IDs for a device."""

    registry = er.async_get(hass)
    cleaned_base = slugify(entity_id_base or friendly_name)
    updated: dict[str, str] = {}

    for domain, suffix in ENTITY_ID_SUFFIXES.items():
        unique_id = (
            f"{DOMAIN}_{friendly_name}" if not suffix else f"{DOMAIN}_{friendly_name}{suffix}"
        )
        current_entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if current_entity_id is None:
            continue

        new_entity_id = desired_entity_id(domain, cleaned_base)
        if current_entity_id == new_entity_id:
            updated[domain] = current_entity_id
            continue

        registry.async_update_entity(current_entity_id, new_entity_id=new_entity_id)
        updated[domain] = new_entity_id

    return updated


def current_entity_ids(hass, *, friendly_name: str) -> dict[str, str]:
    """Return current entity IDs for a device, keyed by domain."""

    registry = er.async_get(hass)
    found: dict[str, str] = {}
    for domain, suffix in ENTITY_ID_SUFFIXES.items():
        unique_id = (
            f"{DOMAIN}_{friendly_name}" if not suffix else f"{DOMAIN}_{friendly_name}{suffix}"
        )
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id is not None:
            found[domain] = entity_id
    return found


def current_command_entity_id(
    hass,
    *,
    record_uid: str,
    friendly_name: str,
) -> str | None:
    """Return the current button entity id for one saved command target."""

    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "button",
        DOMAIN,
        command_button_unique_id(record_uid, friendly_name),
    )

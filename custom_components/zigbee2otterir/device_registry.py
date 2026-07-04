"""Device detection helpers for Zigbee2MQTT IR devices."""

from __future__ import annotations

from typing import Any

from .const import IR_KEYS, IR_MODELS


def is_ir_device(device: dict[str, Any], manual_friendly_names: set[str] | None = None) -> bool:
    """Return true when a Zigbee2MQTT device looks like an IR emitter."""

    friendly_name = str(device.get("friendly_name") or device.get("name") or "")
    if manual_friendly_names and friendly_name in manual_friendly_names:
        return True

    model = (
        device.get("model_id")
        or device.get("model")
        or device.get("definition", {}).get("model")
        or device.get("device", {}).get("model")
        or device.get("dev", {}).get("mdl")
        or device.get("dev", {}).get("model")
    )
    if model in IR_MODELS:
        return True

    exposes = device.get("definition", {}).get("exposes") or device.get("exposes") or []
    exposes_text = str(exposes)
    return any(key in exposes_text for key in IR_KEYS)


def is_ir_entity(entity_id: str, state: Any = None) -> bool:
    """Return true when an entity id/state points at a known IR expose."""

    if any(key in entity_id for key in IR_KEYS):
        return True

    attributes = getattr(state, "attributes", {}) or {}
    return any(key in str(attributes) for key in IR_KEYS)


def normalize_device(device: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize discovery payloads to the fields this integration needs."""

    friendly_name = device.get("friendly_name") or device.get("name")
    if not friendly_name:
        for topic_key in ("command_topic", "cmd_t", "state_topic", "stat_t"):
            topic = device.get(topic_key)
            if not topic:
                continue

            parts = str(topic).split("/")
            if len(parts) >= 3 and parts[-2] == "set":
                friendly_name = parts[-3]
                break
            if len(parts) >= 2:
                friendly_name = parts[-1]
                break

    if not friendly_name:
        return None

    normalized = dict(device)
    normalized["friendly_name"] = str(friendly_name)
    return normalized


def device_model(device: dict[str, Any]) -> str | None:
    """Return the best available model value."""

    return (
        device.get("model_id")
        or device.get("model")
        or device.get("definition", {}).get("model")
        or device.get("device", {}).get("model")
        or device.get("dev", {}).get("mdl")
        or device.get("dev", {}).get("model")
    )


def build_device_info(
    domain: str,
    friendly_name: str,
    device: dict[str, Any],
) -> dict[str, Any]:
    """Build consistent device info for OtterIR entities."""

    manufacturer = (
        device.get("manufacturer")
        or device.get("definition", {}).get("vendor")
        or "Zigbee2MQTT"
    )
    return {
        "identifiers": {(domain, friendly_name)},
        "name": friendly_name,
        "manufacturer": manufacturer,
        "model": device_model(device),
    }

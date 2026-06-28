"""Config flow for OtterIR."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries

from .const import (
    CONF_BASE_TOPIC,
    CONF_DISCOVERY_PREFIX,
    CONF_ENABLE_AUTO,
    CONF_MANUAL_FRIENDLY_NAMES,
    DEFAULT_BASE_TOPIC,
    DEFAULT_DISCOVERY_PREFIX,
    DOMAIN,
)


class Z2MIRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OtterIR."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow."""

        # HA 2024.11+: OptionsFlow no longer receives config_entry in __init__
        return Z2MIROptionsFlow()

    async def async_step_user(self, user_input=None):
        """Create the integration entry."""

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="OtterIR",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ENABLE_AUTO, default=True): bool,
                    vol.Optional(CONF_BASE_TOPIC, default=DEFAULT_BASE_TOPIC): str,
                    vol.Optional(
                        CONF_DISCOVERY_PREFIX,
                        default=DEFAULT_DISCOVERY_PREFIX,
                    ): str,
                    vol.Optional(
                        CONF_MANUAL_FRIENDLY_NAMES,
                        default="",
                    ): str,
                }
            ),
        )


class Z2MIROptionsFlow(config_entries.OptionsFlow):
    """Handle options for OtterIR."""

    # No __init__ needed - config_entry is available via self.config_entry in HA 2024.11+

    async def async_step_init(self, user_input=None):
        """Update integration options."""

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_AUTO,
                        default=data.get(CONF_ENABLE_AUTO, True),
                    ): bool,
                    vol.Optional(
                        CONF_BASE_TOPIC,
                        default=data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC),
                    ): str,
                    vol.Optional(
                        CONF_DISCOVERY_PREFIX,
                        default=data.get(
                            CONF_DISCOVERY_PREFIX,
                            DEFAULT_DISCOVERY_PREFIX,
                        ),
                    ): str,
                    vol.Optional(
                        CONF_MANUAL_FRIENDLY_NAMES,
                        default=data.get(CONF_MANUAL_FRIENDLY_NAMES, ""),
                    ): str,
                }
            ),
        )

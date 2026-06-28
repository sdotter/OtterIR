"""Frontend panel registration for OtterIR."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PANEL_COMPONENT = "otter-ir-panel"
PANEL_TITLE = "OtterIR"
PANEL_ICON = "mdi:remote"
PANEL_URL_PATH = DOMAIN
STATIC_URL_BASE = f"/{DOMAIN}_static"
STATIC_ENTRYPOINT = "otter-ir-panel.js"
STATIC_DATA_KEY = f"{DOMAIN}_frontend_registered"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the OtterIR sidebar panel once."""

    if hass.data.get(STATIC_DATA_KEY):
        return

    # Serve the panel assets from the integration directory so the JS entrypoint
    # can load its companion CSS file without external hosting.
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_URL_BASE,
                str(frontend_dir),
                cache_headers=False,
            )
        ]
    )

    if DOMAIN not in hass.data.get("frontend_panels", {}):
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            frontend_url_path=PANEL_URL_PATH,
            config={
                "_panel_custom": {
                    "name": PANEL_COMPONENT,
                    "embed_iframe": False,
                    "trust_external": False,
                    "js_url": f"{STATIC_URL_BASE}/{STATIC_ENTRYPOINT}?v=1.3.27",
                }
            },
            require_admin=True,
        )

    hass.data[STATIC_DATA_KEY] = True

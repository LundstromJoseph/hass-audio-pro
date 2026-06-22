"""Audio Pro integration."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import AudioProClient
from .cert import create_ssl_context
from .const import DOMAIN
from .coordinator import AudioProCoordinator
from .upnp import UPnPClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data["host"]
    ssl_context = create_ssl_context()

    # One shared session per entry (HA manages lifetime via config entry unload)
    session = aiohttp.ClientSession()
    api = AudioProClient(host, session, ssl_context)
    upnp = UPnPClient(host, session)

    coordinator = AudioProCoordinator(hass, api, upnp, entry.entry_id)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: AudioProCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.api._session.close()
    return unloaded

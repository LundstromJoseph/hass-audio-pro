"""Config flow for Audio Pro integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.ssdp import SsdpServiceInfo
from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant.data_entry_flow import FlowResult

from .api import AudioProClient
from .cert import create_ssl_context
from .const import CONF_HOST, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
})


class AudioProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._device_name: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            name, err = await self._try_connect(host)
            if err:
                errors["base"] = err
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name or host, data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo) -> FlowResult:
        # ssdp_location is the UPnP description URL, e.g. http://10.0.0.130:49152/description.xml
        from urllib.parse import urlparse
        location = str(discovery_info.ssdp_location or "")
        if not location:
            return self.async_abort(reason="no_host")
        parsed = urlparse(location)
        host = parsed.hostname
        if not host:
            return self.async_abort(reason="no_host")
        return await self._handle_discovery(host)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> FlowResult:
        host = str(discovery_info.host)
        return await self._handle_discovery(host)

    async def _handle_discovery(self, host: str) -> FlowResult:
        name, err = await self._try_connect(host)
        if err:
            # Not reachable on :4443 with mTLS — not an Audio Pro device
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()

        self._host = host
        self._device_name = name
        self.context["title_placeholders"] = {"name": name or host}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._device_name or self._host,
                data={CONF_HOST: self._host},
            )
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._device_name or self._host},
        )

    async def _try_connect(self, host: str) -> tuple[str | None, str | None]:
        """Return (device_name, error_key). error_key is None on success."""
        try:
            ssl_ctx = create_ssl_context()
            async with aiohttp.ClientSession() as session:
                client = AudioProClient(host, session, ssl_ctx)
                status = await client.get_status()
            return status.device_name, None
        except aiohttp.ClientConnectorError:
            return None, "cannot_connect"
        except Exception as err:
            _LOGGER.debug("Unexpected error connecting to %s: %s", host, err)
            return None, "unknown"

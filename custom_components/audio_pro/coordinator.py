"""DataUpdateCoordinator — polls api + upnp and merges state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AudioProClient, DeviceStatus
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, GROUP_SLAVE, ROLE_MASTER, ROLE_SLAVE, ROLE_SOLO
from .upnp import TrackInfo, UPnPClient

_LOGGER = logging.getLogger(__name__)


@dataclass
class AudioProState:
    # From api
    device_name: str = ""
    uuid: str = ""
    group: str = "0"
    master_ip: str | None = None
    slave_ips: list[str] = field(default_factory=list)
    # From upnp
    transport_state: str = "STOPPED"
    track: TrackInfo = field(default_factory=TrackInfo)
    volume: int = 0
    muted: bool = False

    @property
    def role(self) -> str:
        """Multiroom role: solo, master, or slave."""
        if self.group == GROUP_SLAVE:
            return ROLE_SLAVE
        if self.slave_ips:
            return ROLE_MASTER
        return ROLE_SOLO


class AudioProCoordinator(DataUpdateCoordinator[AudioProState]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: AudioProClient,
        upnp: UPnPClient,
        entry_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="audio_pro",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.upnp = upnp
        self._store: Store = Store(hass, 1, f"{DOMAIN}.device_name.{entry_id}")
        self._store_loaded = False
        self._original_name: str | None = None

    async def save_original_name(self, name: str) -> None:
        self._original_name = name
        await self._store.async_save(name)

    async def restore_original_name(self) -> str | None:
        name = self._original_name
        self._original_name = None
        await self._store.async_remove()
        return name

    async def _async_update_data(self) -> AudioProState:
        if not self._store_loaded:
            self._store_loaded = True
            self._original_name = await self._store.async_load()

        try:
            status, transport, track, volume, muted = await asyncio.gather(
                self.api.get_status(),
                self.upnp.get_transport_state(),
                self.upnp.get_position_info(),
                self.upnp.get_volume(),
                self.upnp.get_mute(),
            )
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Audio Pro device: {err}") from err

        slave_ips: list[str] = []
        if status.group != "1":  # not a slave — fetch slave list (empty if solo)
            try:
                slave_ips = await self.api.get_slave_list()
            except Exception:
                pass

        state = AudioProState(
            device_name=status.device_name,
            uuid=status.uuid,
            group=status.group,
            master_ip=status.master_ip,
            slave_ips=slave_ips,
            transport_state=transport,
            track=track,
            volume=volume,
            muted=muted,
        )

        # Recovery: restore the original name if the device is solo but was renamed for a group
        if self._original_name and state.role == ROLE_SOLO:
            try:
                await self.api.set_device_name(self._original_name)
                state.device_name = self._original_name
            except Exception:
                _LOGGER.warning("audio_pro: failed to restore device name to %r", self._original_name)
            else:
                self._original_name = None
                await self._store.async_remove()

        return state

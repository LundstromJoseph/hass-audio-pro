"""DataUpdateCoordinator — polls api + upnp and merges state."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AudioProClient, DeviceStatus
from .const import DEFAULT_SCAN_INTERVAL, GROUP_SLAVE, ROLE_MASTER, ROLE_SLAVE, ROLE_SOLO
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
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="audio_pro",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.upnp = upnp

    async def _async_update_data(self) -> AudioProState:
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

        return AudioProState(
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

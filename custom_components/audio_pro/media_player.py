"""MediaPlayerEntity for Audio Pro C5 MkII."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    GROUP_RETRY_ATTEMPTS,
    GROUP_RETRY_DELAY,
    GROUP_SLAVE,
    ROLE_MASTER,
    ROLE_SLAVE,
    ROLE_SOLO,
)
from .coordinator import AudioProCoordinator

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.GROUPING
)

_TRANSPORT_TO_STATE = {
    "PLAYING": MediaPlayerState.PLAYING,
    "PAUSED_PLAYBACK": MediaPlayerState.PAUSED,
    "STOPPED": MediaPlayerState.IDLE,
    "NO_MEDIA_PRESENT": MediaPlayerState.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AudioProCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AudioProMediaPlayer(coordinator, entry)])


class AudioProMediaPlayer(CoordinatorEntity[AudioProCoordinator], MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, coordinator: AudioProCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Audio Pro",
            model="C5 MkII",
        )

    @property
    def state(self) -> MediaPlayerState:
        data = self.coordinator.data
        if data is None:
            return MediaPlayerState.UNAVAILABLE
        if data.group == GROUP_SLAVE:
            return MediaPlayerState.PLAYING
        return _TRANSPORT_TO_STATE.get(data.transport_state, MediaPlayerState.IDLE)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "multiroom_role": data.role,
            "group_master": self._group_master_entity_id(),
        }

    @property
    def volume_level(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.volume / 100

    @property
    def is_volume_muted(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.muted

    @property
    def media_title(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.track.title

    @property
    def media_artist(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.track.artist

    @property
    def media_album_name(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.track.album

    @property
    def media_image_url(self) -> str | None:
        data = self.coordinator.data
        if data is None or data.group == GROUP_SLAVE:
            return None
        return data.track.art_url

    @property
    def media_duration(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return _parse_upnp_time(self.coordinator.data.track.duration)

    @property
    def media_position(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return _parse_upnp_time(self.coordinator.data.track.position)

    @property
    def group_members(self) -> list[str]:
        """All entities in this device's group, master first; empty when solo.

        Reported identically by the master and its slaves so the standard HA
        grouping model works for any consumer (cards, automations, the join UI).
        """
        data = self.coordinator.data
        if data is None:
            return []
        if data.role == ROLE_MASTER:
            return [self.entity_id] + self._slave_entity_ids()
        if data.role == ROLE_SLAVE:
            return self._slave_view_of_group()
        return []  # solo

    def _slave_entity_ids(self) -> list[str]:
        """Entity ids of this (master) device's slaves."""
        data = self.coordinator.data
        if not data:
            return []
        return _entity_ids_for_hosts(self.hass, data.slave_ips)

    def _slave_view_of_group(self) -> list[str]:
        """Full member list as seen from this slave's master (master first)."""
        data = self.coordinator.data
        if not data or not data.master_ip:
            return []
        master_coord, master_entity_id = _coord_and_entity_for_host(self.hass, data.master_ip)
        if not master_coord or not master_entity_id:
            return []
        master_data = master_coord.data
        slave_hosts = master_data.slave_ips if master_data else []
        return [master_entity_id] + _entity_ids_for_hosts(self.hass, slave_hosts)

    def _group_master_entity_id(self) -> str | None:
        """Entity id of this group's master, or None when solo."""
        data = self.coordinator.data
        if data is None:
            return None
        if data.role == ROLE_MASTER:
            return self.entity_id
        if data.role == ROLE_SLAVE and data.master_ip:
            _, master_entity_id = _coord_and_entity_for_host(self.hass, data.master_ip)
            return master_entity_id
        return None

    async def async_media_play(self) -> None:
        await self.coordinator.api.set_player_cmd("play")
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        await self.coordinator.api.set_player_cmd("pause")
        await self.coordinator.async_request_refresh()

    async def async_media_stop(self) -> None:
        await self.coordinator.api.set_player_cmd("stop")
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        await self.coordinator.api.set_player_cmd("next")
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        await self.coordinator.api.set_player_cmd("prev")
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        vol_int = round(volume * 100)
        await self.coordinator.upnp.set_volume(vol_int)
        data = self.coordinator.data
        if data and data.group != GROUP_SLAVE and data.slave_ips:
            for entry_id, coord in self.hass.data.get(DOMAIN, {}).items():
                if entry_id == self._entry.entry_id:
                    continue
                if hasattr(coord, "api") and coord.api._host in data.slave_ips:
                    try:
                        await coord.upnp.set_volume(vol_int)
                    except Exception:
                        pass
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.upnp.set_mute(mute)
        await self.coordinator.async_request_refresh()

    async def async_join_players(self, group_members: list[str]) -> None:
        """Make this device the master; join listed entities as slaves.

        Arylic join is unreliable, so re-issue and verify until every requested
        member has joined (or the attempts run out).
        """
        targets = [e for e in group_members if e != self.entity_id]
        if not targets:
            return
        for _ in range(GROUP_RETRY_ATTEMPTS):
            for entity_id in targets:
                slave_coord = _coord_for_entity(self.hass, entity_id)
                if slave_coord is not None:
                    try:
                        await slave_coord.api.join_group(self.coordinator.api._host)
                    except Exception as err:
                        _LOGGER.debug("join_group failed for %s: %s", entity_id, err)
            await asyncio.sleep(GROUP_RETRY_DELAY)
            await self.coordinator.async_request_refresh()
            if set(targets).issubset(self._slave_entity_ids()):
                return
        _LOGGER.warning(
            "Audio Pro: group around %s did not fully form after %d attempts",
            self.entity_id,
            GROUP_RETRY_ATTEMPTS,
        )

    async def async_unjoin_player(self) -> None:
        """Leave (slave) or dissolve (master) the group, verifying until settled."""
        data = self.coordinator.data
        slave_coords: list[AudioProCoordinator] = []
        if data and data.role == ROLE_MASTER:
            for host in data.slave_ips:
                coord, _ = _coord_and_entity_for_host(self.hass, host)
                if coord is not None:
                    slave_coords.append(coord)
        for _ in range(GROUP_RETRY_ATTEMPTS):
            for coord in (self.coordinator, *slave_coords):
                try:
                    await coord.api.unjoin()
                except Exception as err:
                    _LOGGER.debug("unjoin failed for %s: %s", coord.api._host, err)
            await asyncio.sleep(GROUP_RETRY_DELAY)
            await self.coordinator.async_request_refresh()
            for coord in slave_coords:
                await coord.async_request_refresh()
            if self.coordinator.data and self.coordinator.data.role == ROLE_SOLO:
                return
        _LOGGER.warning(
            "Audio Pro: %s did not leave its group after %d attempts",
            self.entity_id,
            GROUP_RETRY_ATTEMPTS,
        )


def _coord_for_entity(hass: HomeAssistant, entity_id: str) -> AudioProCoordinator | None:
    """Find the Audio Pro coordinator backing a given entity_id."""
    registry = er.async_get(hass)
    reg_entry = registry.async_get(entity_id)
    if reg_entry is None or reg_entry.config_entry_id is None:
        return None
    coord = hass.data.get(DOMAIN, {}).get(reg_entry.config_entry_id)
    return coord if isinstance(coord, AudioProCoordinator) else None


def _coord_and_entity_for_host(
    hass: HomeAssistant, host: str
) -> tuple[AudioProCoordinator | None, str | None]:
    """Return the (coordinator, media_player entity_id) for the device at `host`."""
    registry = er.async_get(hass)
    for entry_id, coord in hass.data.get(DOMAIN, {}).items():
        if not isinstance(coord, AudioProCoordinator) or coord.api._host != host:
            continue
        for reg_entry in er.async_entries_for_config_entry(registry, entry_id):
            if reg_entry.entity_id.startswith("media_player."):
                return coord, reg_entry.entity_id
    return None, None


def _entity_ids_for_hosts(hass: HomeAssistant, hosts: list[str]) -> list[str]:
    """Map device hosts/IPs to their media_player entity ids."""
    result: list[str] = []
    for host in hosts or []:
        _, entity_id = _coord_and_entity_for_host(hass, host)
        if entity_id:
            result.append(entity_id)
    return result


def _parse_upnp_time(time_str: str | None) -> float | None:
    """Convert H:MM:SS to seconds."""
    if not time_str or time_str in ("NOT_IMPLEMENTED", "0:00:00"):
        return None
    try:
        parts = time_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        pass
    return None

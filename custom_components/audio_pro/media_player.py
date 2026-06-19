"""MediaPlayerEntity for Audio Pro C5 MkII."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, GROUP_SLAVE
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
        return {"raw_group": data.group, "master_ip": data.master_ip, "slave_ips": data.slave_ips}

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
    def group_members(self) -> list[str] | None:
        data = self.coordinator.data
        if data is None or data.group == GROUP_SLAVE:
            return None
        slave_ids = self._slave_entity_ids()
        if not slave_ids:
            return None  # solo
        return [self.entity_id] + slave_ids

    def _slave_entity_ids(self) -> list[str]:
        data = self.coordinator.data
        if not data or not data.slave_ips:
            return []
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(self.hass)
        result = []
        for entry_id, coord in self.hass.data.get(DOMAIN, {}).items():
            if entry_id == self._entry.entry_id:
                continue
            if not (hasattr(coord, "api") and coord.api._host in data.slave_ips):
                continue
            entries = er.async_entries_for_config_entry(registry, entry_id)
            for reg_entry in entries:
                result.append(reg_entry.entity_id)
        return result

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
        """Make this device the master; join listed entities as slaves."""
        # group_members is a list of entity_ids that should follow this master
        for entity_id in group_members:
            slave_coord = _coord_for_entity(self.hass, entity_id)
            if slave_coord is not None:
                await slave_coord.api.join_group(self.coordinator.api._host)
        await self.coordinator.async_request_refresh()

    async def async_unjoin_player(self) -> None:
        await self.coordinator.api.unjoin()
        await self.coordinator.async_request_refresh()


def _coord_for_entity(hass: HomeAssistant, entity_id: str) -> AudioProCoordinator | None:
    """Find the coordinator for a given entity_id in the DOMAIN."""
    for coord in hass.data.get(DOMAIN, {}).values():
        if not isinstance(coord, AudioProCoordinator):
            continue
        # Look through entity registry / platform entities to match
        entity_registry = hass.data.get("entity_registry")
        if entity_registry:
            entry = entity_registry.async_get(entity_id)
            if entry and entry.config_entry_id in hass.data.get(DOMAIN, {}):
                candidate = hass.data[DOMAIN][entry.config_entry_id]
                if isinstance(candidate, AudioProCoordinator):
                    return candidate
    return None


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

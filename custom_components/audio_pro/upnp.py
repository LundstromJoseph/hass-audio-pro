"""UPnP SOAP client for AVTransport and RenderingControl (HTTP port 49152)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import aiohttp

from .const import UPNP_AVT_SERVICE, UPNP_CONTROL_URL, UPNP_PORT, UPNP_RC_SERVICE, UPNP_RENDERING_URL

_LOGGER = logging.getLogger(__name__)

SOAP_ENVELOPE = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="{service}">
      {args}
    </u:{action}>
  </s:Body>
</s:Envelope>"""


@dataclass
class TrackInfo:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    art_url: str | None = None
    duration: str | None = None
    position: str | None = None


class UPnPClient:
    def __init__(self, host: str, session: aiohttp.ClientSession, port: int = UPNP_PORT) -> None:
        self._host = host
        self._session = session
        self._port = port

    async def _soap(self, control_url: str, service: str, action: str, args: str = "") -> ET.Element:
        url = f"http://{self._host}:{self._port}{control_url}"
        body = SOAP_ENVELOPE.format(action=action, service=service, args=args)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{service}#{action}"',
        }
        async with self._session.post(
            url,
            data=body.encode(),
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            resp.raise_for_status()
            text = await resp.text()
        return ET.fromstring(text)

    def _find(self, root: ET.Element, tag: str) -> str | None:
        for el in root.iter():
            if el.tag.endswith(f"}}{tag}") or el.tag == tag:
                return el.text
        return None

    async def get_transport_state(self) -> str:
        """Returns PLAYING, PAUSED_PLAYBACK, STOPPED, or NO_MEDIA_PRESENT."""
        try:
            root = await self._soap(
                UPNP_CONTROL_URL,
                UPNP_AVT_SERVICE,
                "GetTransportInfo",
                "<InstanceID>0</InstanceID>",
            )
            return self._find(root, "CurrentTransportState") or "STOPPED"
        except Exception as err:
            _LOGGER.debug("get_transport_state failed on %s: %s", self._host, err)
            return "STOPPED"

    async def get_position_info(self) -> TrackInfo:
        try:
            root = await self._soap(
                UPNP_CONTROL_URL,
                UPNP_AVT_SERVICE,
                "GetPositionInfo",
                "<InstanceID>0</InstanceID>",
            )
        except Exception as err:
            _LOGGER.debug("get_position_info failed on %s: %s", self._host, err)
            return TrackInfo()

        info = TrackInfo(
            duration=self._find(root, "TrackDuration"),
            position=self._find(root, "RelTime"),
        )

        didl = self._find(root, "TrackMetaData")
        if didl:
            try:
                info = _parse_didl(didl, info)
            except Exception as err:
                _LOGGER.debug("DIDL parse error on %s: %s", self._host, err)

        return info

    async def get_volume(self) -> int:
        try:
            root = await self._soap(
                UPNP_RENDERING_URL,
                UPNP_RC_SERVICE,
                "GetVolume",
                "<InstanceID>0</InstanceID><Channel>Master</Channel>",
            )
            val = self._find(root, "CurrentVolume")
            return int(val) if val is not None else 0
        except Exception as err:
            _LOGGER.debug("get_volume failed on %s: %s", self._host, err)
            return 0

    async def set_volume(self, level: int) -> None:
        level = max(0, min(100, level))
        await self._soap(
            UPNP_RENDERING_URL,
            UPNP_RC_SERVICE,
            "SetVolume",
            f"<InstanceID>0</InstanceID><Channel>Master</Channel><DesiredVolume>{level}</DesiredVolume>",
        )

    async def get_mute(self) -> bool:
        try:
            root = await self._soap(
                UPNP_RENDERING_URL,
                UPNP_RC_SERVICE,
                "GetMute",
                "<InstanceID>0</InstanceID><Channel>Master</Channel>",
            )
            val = self._find(root, "CurrentMute")
            return val in ("1", "true", "True")
        except Exception as err:
            _LOGGER.debug("get_mute failed on %s: %s", self._host, err)
            return False

    async def set_mute(self, muted: bool) -> None:
        await self._soap(
            UPNP_RENDERING_URL,
            UPNP_RC_SERVICE,
            "SetMute",
            f"<InstanceID>0</InstanceID><Channel>Master</Channel><DesiredMute>{'1' if muted else '0'}</DesiredMute>",
        )


def _parse_didl(didl_xml: str, info: TrackInfo) -> TrackInfo:
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
        "r": "urn:schemas-rinconnetworks-com:metadata-1-0/",
    }
    root = ET.fromstring(didl_xml)
    item = root.find(".//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}item")
    if item is None:
        # Try without namespace
        item = root.find(".//item")
    if item is None:
        return info

    def _text(tag: str, namespace: str | None = None) -> str | None:
        if namespace:
            el = item.find(f"{{{namespace}}}{tag}")
        else:
            el = item.find(tag)
            if el is None:
                for child in item:
                    if child.tag.endswith(f"}}{tag}"):
                        el = child
                        break
        return el.text if el is not None else None

    info.title = _text("title", "http://purl.org/dc/elements/1.1/") or _text("title")
    info.artist = _text("artist", "http://purl.org/dc/elements/1.1/") or _text("artist")
    info.album = _text("album", "http://purl.org/dc/elements/1.1/") or _text("album")

    # albumArtURI is in upnp namespace
    art = item.find("{urn:schemas-upnp-org:metadata-1-0/upnp/}albumArtURI")
    if art is not None and art.text and art.text not in ("un_known", "unknown", ""):
        info.art_url = art.text

    return info

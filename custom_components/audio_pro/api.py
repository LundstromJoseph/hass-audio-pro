"""HTTPS httpapi client for Audio Pro devices (port 4443, mTLS)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


@dataclass
class DeviceStatus:
    device_name: str
    uuid: str
    project: str
    # "0"=solo, "1"=master, "2"=slave
    group: str
    master_uuid: str | None
    master_ip: str | None


class AudioProClient:
    def __init__(self, host: str, session: aiohttp.ClientSession, ssl_context: Any) -> None:
        self._host = host
        self._session = session
        self._ssl = ssl_context
        self._base = f"https://{host}:4443"

    async def _get(self, command: str) -> dict[str, Any]:
        url = f"{self._base}/httpapi.asp?command={command}"
        async with self._session.get(url, ssl=self._ssl, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            resp.raise_for_status()
            text = await resp.text()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.debug("Non-JSON response from %s command=%s: %r", self._host, command, text)
            return {"raw": text}

    async def get_status(self) -> DeviceStatus:
        data = await self._get("getStatusEx")
        return DeviceStatus(
            device_name=data.get("DeviceName", self._host),
            uuid=data.get("uuid", ""),
            project=data.get("project", ""),
            group=str(data.get("group", "0")),
            master_uuid=data.get("master_uuid") or data.get("MasterUUID"),
            master_ip=data.get("master_ip") or data.get("MasterIP"),
        )

    async def get_slave_list(self) -> list[str]:
        """Return list of slave IP addresses (master only)."""
        try:
            data = await self._get("multiroom:getSlaveList")
        except Exception:
            return []
        slave_list = data.get("slave_list", [])
        if isinstance(slave_list, list):
            return [str(s.get("ip", "")) for s in slave_list if isinstance(s, dict) and s.get("ip")]
        return []

    async def join_group(self, master_ip: str) -> None:
        """Make *this* device join master_ip's group (called on the slave)."""
        command = f"ConnectMasterAp:JoinGroupMaster:eth{master_ip}:wifi0.0.0.0"
        await self._get(command)

    async def unjoin(self) -> None:
        """Leave current group (works for both master and slave)."""
        await self._get("multiroom:Ungroup")

    async def kick_slave(self, slave_ip: str) -> None:
        """Remove a specific slave from this master's group."""
        await self._get(f"multiroom:SlaveKickout:{slave_ip}")

    async def set_player_cmd(self, cmd: str) -> None:
        await self._get(f"setPlayerCmd:{cmd}")

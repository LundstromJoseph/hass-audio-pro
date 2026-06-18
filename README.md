# Audio Pro for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Home Assistant integration for Audio Pro C5 MkII (and other Arylic-firmware LinkPlay speakers).

## Features

- Play/pause/stop, next/previous track
- Volume and mute control
- Track metadata (title, artist, album, cover art) via UPnP
- Multiroom grouping via the HA media player grouping UI

## Installation via HACS

1. In HACS, go to **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/josephgodwinkimani/hass-audio-pro` as an **Integration**
3. Install **Audio Pro** from HACS
4. Restart Home Assistant
5. Go to **Settings → Integrations → Add integration → Audio Pro**

## Manual setup

Enter the IP address of your speaker. Devices are also auto-discovered via SSDP/UPnP.

## Notes

- Requires port **4443** (HTTPS/mTLS) and **49152** (UPnP) to be reachable from HA
- Remove devices from the WiiM integration before adding them here


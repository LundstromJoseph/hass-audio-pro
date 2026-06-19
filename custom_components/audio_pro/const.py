DOMAIN = "audio_pro"

HTTPS_PORT = 4443
UPNP_PORT = 49152
DEFAULT_SCAN_INTERVAL = 5

UPNP_CONTROL_URL = "/upnp/control/rendertransport1"
UPNP_RENDERING_URL = "/upnp/control/rendercontrol1"
UPNP_AVT_SERVICE = "urn:schemas-upnp-org:service:AVTransport:1"
UPNP_RC_SERVICE = "urn:schemas-upnp-org:service:RenderingControl:1"

CONF_HOST = "host"

# getStatusEx group field values (Arylic firmware: 0=master/solo, 1=slave)
GROUP_SLAVE = "1"

# Multiroom roles, exposed as the `multiroom_role` attribute
ROLE_SOLO = "solo"
ROLE_MASTER = "master"
ROLE_SLAVE = "slave"

# Arylic join/unjoin is flaky — re-issue and verify until the group settles
GROUP_RETRY_ATTEMPTS = 5
GROUP_RETRY_DELAY = 2  # seconds between attempts

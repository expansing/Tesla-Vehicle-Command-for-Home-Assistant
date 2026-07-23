"""Constants for Tesla Vehicle Command integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "tesla_vehicle_command"

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.CLIMATE,
    Platform.LOCK,
    Platform.COVER,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SELECT,
]

# Configuration keys
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_FLEET_API_BASE_URL = "fleet_api_base_url"
CONF_VEHICLES = "vehicles"
CONF_VIN = "vin"
CONF_NAME = "name"
CONF_PRIVATE_KEY_PATH = "private_key_path"
CONF_TELEMETRY_HOSTNAME = "telemetry_hostname"
CONF_TELEMETRY_PORT = "telemetry_port"
CONF_UPDATE_INTERVAL = "update_interval"

# OAuth2
OAUTH2_AUTHORIZE = "https://auth.tesla.com/oauth2/v3/authorize"
OAUTH2_TOKEN = "https://auth.tesla.com/oauth2/v3/token"
OAUTH2_SCOPES = [
    "openid",
    "offline_access",
    "vehicle_device_data",
    "vehicle_cmds",
    "vehicle_charging_cmds",
    "vehicle_location",
]

# Fleet API regions
FLEET_API_BASE_URL_NA = "https://fleet-api.prd.na.vn.cloud.tesla.com"
FLEET_API_BASE_URL_EU = "https://fleet-api.prd.eu.vn.cloud.tesla.com"

# Proxy settings
PROXY_PORT = 4443
PROXY_HOST = "local-tesla-vehicle-command-proxy"
PROXY_TIMEOUT = 30

# API endpoints (proxied through tesla-http-proxy)
API_VEHICLES = "/api/1/vehicles"
API_VEHICLE_DATA = "/api/1/vehicles/{vin}/vehicle_data"
API_WAKE_UP = "/api/1/vehicles/{vin}/wake_up"
API_COMMAND = "/api/1/vehicles/{vin}/command/{command}"
API_FLEET_TELEMETRY_CONFIG = "/api/1/vehicles/fleet_telemetry_config"

# Vehicle commands
COMMANDS = {
    "lock": "door_lock",
    "unlock": "door_unlock",
    "honk": "honk_horn",
    "flash": "flash_lights",
    "climate_on": "auto_conditioning_start",
    "climate_off": "auto_conditioning_stop",
    "charge_start": "charge_start",
    "charge_stop": "charge_stop",
    "charge_port_open": "charge_port_door_open",
    "charge_port_close": "charge_port_door_close",
    "trunk_rear": "actuate_trunk",
    "trunk_front": "actuate_trunk",
    "sentry_on": "set_sentry_mode",
    "sentry_off": "set_sentry_mode",
    "seat_heater": "remote_seat_heater_request",
    "steering_heater": "remote_steering_wheel_heater_request",
    "window_vent": "window_control",
    "window_close": "window_control",
    "sunroof": "sunroof_control",
    "set_temps": "set_temps",
    "set_charge_limit": "set_charge_limit",
    "fart": "remote_boombox",
    "wake_up": "wake_up",
}

# Command bodies
COMMAND_BODIES = {
    "trunk_rear": {"which_trunk": "rear"},
    "trunk_front": {"which_trunk": "front"},
    "sentry_on": {"on": True},
    "sentry_off": {"on": False},
    "window_vent": {"command": "vent", "lat": 0, "lon": 0},
    "window_close": {"command": "close", "lat": 0, "lon": 0},
    "fart": {"action": "fart"},
}

# Temperature limits (Celsius)
MIN_TEMP = 15.0
MAX_TEMP = 28.0
TEMP_STEP = 0.5

# Charge limit
CHARGE_LIMIT_MIN = 50
CHARGE_LIMIT_MAX = 100
CHARGE_LIMIT_STEP = 5

# Seat heater levels
SEAT_HEATER_OFF = 0
SEAT_HEATER_LOW = 1
SEAT_HEATER_MEDIUM = 2
SEAT_HEATER_HIGH = 3

# Update intervals
DEFAULT_UPDATE_INTERVAL = 30
MIN_UPDATE_INTERVAL = 30
MAX_UPDATE_INTERVAL = 900

# Fleet Telemetry settings
DEFAULT_TELEMETRY_PORT = 4443
MIN_TELEMETRY_PORT = 1
MAX_TELEMETRY_PORT = 65535

# Proxy binary names by platform
PROXY_BINARIES = {
    "linux_x86_64": "tesla-http-proxy-linux-amd64",
    "linux_aarch64": "tesla-http-proxy-linux-arm64",
    "darwin_x86_64": "tesla-http-proxy-darwin-amd64",
    "darwin_arm64": "tesla-http-proxy-darwin-arm64",
    "win32": "tesla-http-proxy-windows-amd64.exe",
}

# GitHub releases
GITHUB_REPO = "teslamotors/vehicle-command"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"